# Security review — NIVORA before launch

Reviewed against the OWASP Top 10 (2021). Every line names where the control
lives and the test that proves it. Run `pytest -q` and
`python -m evals.run_evals` before release.

## A01 Broken access control
- Deny by default: `app/permissions.py` holds the permission matrix and the route
  rules. `PermissionMiddleware` refuses any `/api` route with no rule.
- Tenancy is enforced in every query in `app/models.py` (`WHERE tenant_id = ?`)
  and on every rate-limit and cache key (`nivora:{tenant}:...`).
- Tests: `tests/test_permissions.py` (cross-tenant reads and writes on every
  table, no-rule route, role change), `tests/acceptance/test_f9_message_box.py`.

## A02 Cryptographic failures
- Passwords: argon2id via `argon2-cffi` (`app/security.py:hash_password`). No
  password is ever stored, logged or returned.
- Sessions: 32-byte random tokens, stored as SHA-256 hashes; HttpOnly, SameSite=Lax,
  Secure cookies; server-side revocation on sign-out and password reset.
- HTTPS: `FORCE_HTTPS` redirects and HSTS is sent outside development.
- Tests: `tests/test_auth.py`, `tests/acceptance/test_quality.py::test_security_https`.

## A03 Injection
- SQL: every statement is parameterised; no string-built SQL with user input.
- XSS: the pages render with `textContent`/escaped templates; CSP allows only
  same-origin scripts (`script-src 'self'`, plus accounts.google.com for Google
  sign-in) and blocks inline handlers.
- Prompt injection: input is screened (`app/ai/text.py:injection_flags`), the
  prompt marks the message as data, and the reply is checked.
- Tests: `tests/test_ai.py`, `tests/acceptance/test_f1_ai_message_parser.py`,
  `evals/cases.json` X1–X3.

## A04 Insecure design
- One model call, no tools, no outbound actions: `docs/TOOLS.md`. Nothing is sent
  outside without a person's approval.
- The failure policy is explicit: repair once, then a safe reply for a human.
- Money is `Decimal`, rounded to 2 places (`app/money.py`).

## A05 Security misconfiguration
- Security headers on every response (`app/security.py:apply_security_headers`):
  CSP, nosniff, frame-deny, referrer policy, permissions policy.
- Secrets only from the environment (`app/settings.py`); `.env` is gitignored and
  never read by the browser. `/api/meta` returns public configuration only.
- Tests: `test_security_secrets`, `test_security_https`.

## A06 Vulnerable and outdated components
- Versions are pinned in `requirements.txt`.
- `pip-audit -r requirements.txt` runs in CI on every push
  (`.github/workflows/ci.yml`) and is part of the release checklist.
- Test: `test_security_deps`.

## A07 Identification and authentication failures
- Four methods: email magic link, Google, phone one-time code, email and password
  from a proven library. One-time tokens are hashed, single-use and expire.
- Failed sign-ins slow down and then lock; owners must pass TOTP two-factor.
- Tests: `tests/test_auth.py`.

## A08 Software and data integrity failures
- Payment webhooks are verified with an HMAC over the timestamp and body, with a
  300-second replay window, before any plan changes; event ids are unique so a
  retry never runs twice (`app/billing.py`).
- Tests: `tests/test_billing.py`.

## A09 Security logging and monitoring failures
- One safe line per request and per model call: request id, tenant, model,
  tokens, cost, time, outcome. Never message text, never a key or a token
  (`app/safelog.py`).
- Alerts: budget at 80%, over-budget pause, failed-check rate (`app/ai/runner.py`).
- Tests: `test_the_safe_log_line_has_no_message_text`, `test_an_alert_goes_out_at_eighty_percent`.

## A10 Server-side request forgery
- The server calls only the configured model and payment providers; base URLs come
  from the environment, never from a request. No user-supplied URL is fetched.
- `app/ai/provider.py`, `app/billing.py`.
