# NIVORA

Order &amp; profit system for Malaysian food sellers — with a shop page buyers
order from. One message or one checkout becomes a structured order, a production
plan, a grocery list and a profit number — with every AI reply checked in code
before anyone sees it.

## Start it

**Windows:** double-click **`RUN NIVORA.bat`**. It creates the Python environment
on first run, seeds the demo shop, opens the browser and serves
<http://localhost:8000>. Keep the window open; Ctrl+C stops it.

**macOS / Linux:** `./run.sh`

| | |
|---|---|
| Seller | `demo@nivora.my` / `nivora-demo-2026` |
| Buyer shop | <http://localhost:8000/shop?b=dapur-aminah> |

Everything the shop does lives in `data/nivora.db` — delete it and run again for
a clean start; it is re-seeded with the demo business.

Two sides, one app:

- **Seller** — menu, orders, production, grocery list, profit, costing, messages.
- **Buyer** — opens the shop link, picks dishes, checks out; the order lands on
  the seller's dashboard as a notification and a message thread.

Built from this pack (GigaLab Module 8, 2026-10-22). The stack is the confirmed
one: **plain HTML/CSS/JS · Python 3.12 + FastAPI · SQLite**.

`blueprint.json` is the source of truth for every requirement, choice and target.
`docs/` explains it. `tests/acceptance/` proves it.

## Run it

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt      # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

cp .env.example .env        # then put a long random APP_SECRET in it
.venv/Scripts/python -m scripts.seed_demo                   # optional demo business
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Open <http://localhost:8000>. The first screen asks **how you are using NIVORA**:

| Role | What happens |
|---|---|
| Seller | Sign in (password, email link, or phone code) and run the business. |
| Buyer | Opens the shop linked in Settings — no account needed. |

The demo business (if seeded) signs in with `demo@nivora.my` /
`nivora-demo-2026`; two-factor is off for that one seeded owner only. Its shop is
<http://localhost:8000/shop?b=dapur-aminah>. Sign-up creates a real account:
verify by email link, then sign in with the printed authenticator secret and a
6-digit code.

In development there is no email or SMS provider, so one-time links and codes are
shown on the sign-in page itself (and written to `data/outbox.log`). A remote
caller never sees them, and `DEV_SHOW_LINKS=false` turns it off.

## What the seller sets up

- **Settings → Shop profile**: shop name, tagline, phone, address — what buyers
  see on the shop page.
- **Settings → Menu**: the dishes the shop sells, their price, category, photo
  and optional link to a recipe so orders cost themselves.
- **Settings → Shop link**: send it to customers. Every order arrives with a
  notification and a message thread they can reply to.
- **Language**: English or Bahasa Melayu, one switch, remembered per browser.

## The chatbot

A floating **Ask / Tanya** button opens a chat panel on the seller app and on
every shop page. It is a Flowise agent flow, called from the server with a
context block built from the shop's own row and menu — so prices, delivery and
the order link are the shop's, not the model's. Replies take 5–10 s.

Set it in `.env` (`FLOWISE_URL`, optional `FLOWISE_API_KEY`, `BOT_ENABLED`).
`docs/CHATBOT.md` covers the grounding rules, limits and why the proxy exists.

When a buyer orders a dish that has no recipe yet, the AI researches one in the
background (ingredients and a sensible batch size), files it under *Recipe ideas*
and notifies the seller. Approving it turns the idea into costed ingredients —
matched to the shop's own ingredient prices — and links it to the dish. Nothing
is invented: prices come from the seller's ingredient list, and an idea the
checks reject never reaches the screen.

## Commands

| What | Command |
|---|---|
| Install | `pip install -r requirements.txt` |
| Tests | `pytest -q` |
| AI release gate | `python -m evals.run_evals` |
| Run | `uvicorn app.main:app --reload` |
| Backup | `python -m scripts.backup` |
| Restore | `python -m scripts.backup --restore data/backups/<file>.db` |

## What is built

| Feature | Where |
|---|---|
| AI MESSAGE PARSER (F1) | `app/ai/`, `POST /api/ai/parse`, approve → order |
| Order Management Dashboard (F2) | `GET /api/orders`, `GET /api/dashboard` |
| Recipe & Ingredient Costing (F3) | `app/models.py`, `POST /api/ai/costing` |
| Production Planning (F4) | `GET /api/production` |
| Automatic Grocery List (F5) | `GET /api/grocery` |
| Profit & Loss Calculator (F6) | `GET /api/profit`, `/api/orders/{id}/profit` |
| Message Box (F9) | `/api/threads`, public `/chat.html?t=…` |
| Sign-in, roles, tenants (M1–M2) | `app/auth.py`, `app/permissions.py` |
| AI settings, budget, usage (M4) | `/api/ai/settings`, `/api/usage` |
| Contract checks, failure policy (M5) | `app/ai/contracts.py`, `app/ai/runner.py` |
| Quality targets (M6) | `tests/acceptance/test_quality.py` |
| Billing, plans, retention (M7) | `app/billing.py` |

## The AI, and what it may not do

- One model call, no tools (`docs/TOOLS.md`). The server calls **ollama ·
  gigalab-local**; on a timeout or 429 it moves to the second provider. If no
  model answers and `AI_LOCAL_FALLBACK=true` (development default), a
  deterministic reader answers and the log says `provider=local-rules` — it is
  never presented as the model.
- Every reply is checked three ways: JSON syntax, field schema, then business
  rules (no invented price, date or name; no banned word or promise). A failure
  is repaired once, then replaced by a safe reply that waits for a person.
- Limits: 10 calls a minute per person, 56 a day per customer (plan), a monthly
  budget per customer with an alert at 80%.
- One safe log line per call: request id, tenant, model, tokens, cost, time,
  outcome, checks. Never message text.

## Before the first customer

See `docs/ARCHITECTURE.md`. Still open by the pack's own record: a PDPA privacy
notice and product analytics. Terms, support channel, backups and monitoring are
in place (`/support`, `scripts/backup.py`, `.github/workflows/ci.yml`).

## Changing a requirement

Change it in GigaLab and download the pack again; then copy the new
`blueprint.json` and `docs/` over these. Do not edit requirements in code.
