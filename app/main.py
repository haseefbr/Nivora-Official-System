"""NIVORA: FastAPI app, middleware, pages and the billing webhook.

Run: uvicorn app.main:app --reload
"""
from __future__ import annotations

import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import billing, db, models, permissions
from .auth import default_google_verifier, router as auth_router, get_db
from .permissions import has_permission
from .routes.api import router as api_router
from .routes.shop_api import router as shop_router
from .routes.bot_api import router as bot_router
from .safelog import request_line
from .security import apply_security_headers, compare, load_session
from .settings import ROOT, Settings

STATIC = ROOT / "static"
MAX_BODY = 1_000_000


class PermissionMiddleware(BaseHTTPMiddleware):
    """Deny by default: an /api route with no rule is refused, signed in or not."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api") or permissions.is_public(path):
            return await call_next(request)
        if request.method == "OPTIONS":
            return await call_next(request)
        app = request.app
        rule = permissions.rule_for(request.method, path)
        if rule is None:
            return JSONResponse(
                {"ok": False, "code": "no_permission_rule",
                 "message": "This route has no permission rule, so it is refused."},
                status_code=403,
            )
        conn = app.state.connect()
        try:
            session = load_session(conn, request.cookies.get(app.state.settings.cookie_name))
        finally:
            conn.close()
        if session is None:
            return JSONResponse(
                {"ok": False, "code": "not_signed_in", "message": "Please sign in to continue."},
                status_code=401,
            )
        if not session["email_verified"] and not session["phone_verified"]:
            return JSONResponse(
                {"ok": False, "code": "email_unverified",
                 "message": "Verify your email address first: open the link we sent you."},
                status_code=403,
            )
        if session["require_2fa"] and session["role"] == "OWNER" and not session["totp_secret"]:
            if not path.startswith("/api/auth/") and path != "/api/me":
                return JSONResponse(
                    {"ok": False, "code": "2fa_enrollment_required",
                     "message": "Set up two-factor sign-in before using the app."},
                    status_code=403,
                )
        if not has_permission(session["role"], rule):
            return JSONResponse(
                {"ok": False, "code": "forbidden",
                 "message": f"Your role cannot use this: {rule}."},
                status_code=403,
            )
        request.state.session = session
        return await call_next(request)


class HardeningMiddleware(BaseHTTPMiddleware):
    """HTTPS, security headers, CSRF, body limit and one safe log line per request."""

    async def dispatch(self, request: Request, call_next):
        settings: Settings = request.app.state.settings
        request_id = uuid.uuid4().hex[:12]
        request.state.request_id = request_id

        forwarded = request.headers.get("x-forwarded-proto", "").lower()
        scheme = forwarded or request.url.scheme
        if settings.force_https and scheme != "https":
            url = request.url.replace(scheme="https")
            return RedirectResponse(str(url), status_code=307)

        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > MAX_BODY:
            return JSONResponse(
                {"ok": False, "code": "too_large", "message": "That request is too large."},
                status_code=413,
            )

        path = request.url.path
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and path.startswith("/api") \
                and not permissions.is_public(path):
            header = request.headers.get("x-csrf-token", "")
            conn = request.app.state.connect()
            try:
                session = load_session(conn, request.cookies.get(settings.cookie_name))
            finally:
                conn.close()
            if session is None:
                return JSONResponse(
                    {"ok": False, "code": "not_signed_in", "message": "Please sign in to continue."},
                    status_code=401,
                )
            if not compare(header, session["csrf_token"]):
                return JSONResponse(
                    {"ok": False, "code": "csrf",
                     "message": "That form expired. Reload the page and try again."},
                    status_code=403,
                )

        started = time.monotonic()
        response = await call_next(request)
        duration = int((time.monotonic() - started) * 1000)
        response.headers["X-Request-Id"] = request_id
        apply_security_headers(response, settings)
        session = getattr(request.state, "session", None)
        if path.startswith("/api") or path == "/":
            request_line(
                settings, request_id=request_id, method=request.method, path=path,
                status=response.status_code, duration_ms=duration,
                tenant_id=session["tenant_id"] if session else None,
                user_id=session["user_id"] if session else None,
            )
        return response


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    db.init_db(settings.database_path)

    app = FastAPI(
        title="NIVORA",
        description="AI order and profit assistant for Malaysian food sellers",
        version="1.0.0",
        docs_url="/api/docs" if settings.dev_mode else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.dev_mode else None,
    )
    app.state.settings = settings
    app.state.connect = lambda: db.connect(settings.database_path)
    app.state.google_verifier = default_google_verifier

    @app.middleware("http")
    async def no_store(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(PermissionMiddleware)
    app.add_middleware(HardeningMiddleware)

    app.include_router(auth_router)
    app.include_router(api_router)
    app.include_router(shop_router)
    app.include_router(bot_router)

    # ---------------------------------------------------------- webhook
    @app.post("/api/billing/webhook")
    async def billing_webhook(request: Request):
        raw = await request.body()
        try:
            event = billing.verify_webhook(
                settings, raw, request.headers.get("stripe-signature")
                or request.headers.get("x-webhook-signature"))
        except billing.BillingError as exc:
            return JSONResponse({"ok": False, "code": exc.code, "message": str(exc)},
                                status_code=exc.status)
        conn = app.state.connect()
        try:
            with db.tx(conn):
                outcome = billing.apply_webhook(conn, event)
        except billing.BillingError as exc:
            return JSONResponse({"ok": False, "code": exc.code, "message": str(exc)},
                                status_code=exc.status)
        finally:
            conn.close()
        return JSONResponse(outcome)

    # ------------------------------------------------------------ pages
    def page(name: str) -> FileResponse:
        return FileResponse(STATIC / name, media_type="text/html",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/", include_in_schema=False)
    def index():
        return page("index.html")

    @app.get("/login", include_in_schema=False)
    def login_page():
        return page("login.html")

    @app.get("/reset", include_in_schema=False)
    def reset_page():
        return page("reset.html")

    @app.get("/chat.html", include_in_schema=False)
    def chat_page():
        return page("chat.html")

    @app.get("/shop", include_in_schema=False)
    def shop_page():
        return page("shop.html")

    @app.get("/shop/", include_in_schema=False)
    def shop_page_slash():
        return page("shop.html")

    @app.get("/support", include_in_schema=False)
    def support():
        return {"ok": True, **billing.SUPPORT}

    # --------------------------------------------------------- handlers
    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            body = {"ok": False, **detail}
        else:
            body = {"ok": False, "code": "error", "message": str(detail)}
        response = JSONResponse(body, status_code=exc.status_code)
        retry = getattr(exc, "retry_after", None)
        if retry:
            response.headers["Retry-After"] = str(retry)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = []
        for error in exc.errors()[:5]:
            field = ".".join(str(part) for part in error.get("loc", [])[1:])
            errors.append({"field": field, "message": error.get("msg", "is not valid")})
        return JSONResponse(
            {"ok": False, "code": "invalid_input",
             "message": "Check the highlighted fields and try again.", "errors": errors},
            status_code=422,
        )

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        # No message from the customer, no key: just the error type.
        import logging
        request_id = getattr(request.state, "request_id", "-")
        logging.getLogger("nivora.error").error(
            "unhandled request_id=%s type=%s path=%s", request_id, type(exc).__name__,
            request.url.path)
        try:
            from .safelog import logger_for
            logger_for(settings).error(
                "error request_id=%s type=%s path=%s", request_id, type(exc).__name__,
                request.url.path)
        except Exception:
            pass
        return JSONResponse(
            {"ok": False, "code": "server_error",
             "message": "Something went wrong and nothing was saved. Try again."},
            status_code=500,
        )

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    return app


app = create_app()
