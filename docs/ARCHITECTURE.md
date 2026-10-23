# Architecture

## One request
```mermaid
flowchart LR
  S0["Message in: A web app"]
  S1["Sign-in, role: Email magic link, Google sign-in, Phone number with a one-time code, Email and password, from a proven library"]
  S2["Rate limit: customer + user"]
  S3["Build context: role and rules"]
  S4["Model call: gigalab-local"]
  S5["Check reply: schema + rules"]
  S6["Save: SQLite"]
  S7["Reply: to the customer"]
  S0 --> S1
  S1 --> S2
  S2 --> S3
  S3 --> S4
  S4 --> S5
  S5 --> S6
  S6 --> S7
```

- **Message in**: The request arrives from a web app or web chat.
- **Sign-in, role**: People sign in (email magic link, google sign-in, phone number with a one-time code, email and password, from a proven library); every step below knows the tenant and the role, and the role’s permission is checked first (docs/AUTH.md).
- **Rate limit**: An atomic counter refuses calls over the plan (Module 6).
- **Build context**: Stable parts first, then knowledge, memory and the request (Module 7).
- **Model call**: 2 AI features on gigalab-local, from your server with the key in .env, a second provider on timeout (Modules 1 and 4).
- **Check reply**: Code checks what goes in (a length limit on what users send, screen for prompt injection) and every reply (the business rules, no banned words or promises); on failure: repair once, then a safe reply (Modules 2 and 4).
- **Save**: Records with the tenant id, and a safe log line.
- **Reply**: The checked reply goes back.

## Parts
- Code: Plain HTML, CSS and JavaScript · Python 3.12, FastAPI · SQLite. Details in docs/STACK.md.
- Data: SQLite; tenancy: one database, tenant id on every row and key. Tables in docs/DATA_MODEL.md.
- Model: ollama · gigalab-local; your key (you bill the customer); called from the server. Settings in docs/AI_SETTINGS.md.
- Sign-in: Email magic link, Google sign-in, Phone number with a one-time code, Email and password, from a proven library. Roles and permissions in docs/AUTH.md.
- Integrations: Google Sheets or Excel, Calendar, Online payment. Platforms: A web app.
- Billing: Stripe. Keep only the provider’s customer id; verify every webhook.
- Hosting: A hosting platform (PaaS), over HTTPS, with daily backups and an uptime check.

## Personal data (PDPA)
- Personal data: no. Kept for: one year.
- Collect only what the features need; say why in a privacy notice.
- Logs hold no message text. Customers can ask for their data and for deletion.
- Plan what you do if data leaks: who you tell, and how fast.

## Ready before the first customer
- [ ] A privacy notice (PDPA) (not planned yet)
- [x] Terms of service
- [x] Sign-up and a guided first task
- [x] A support channel: email or WhatsApp
- [x] Daily backups, restored once
- [x] Uptime monitoring with an alert to your phone
- [ ] Product analytics, without personal data (not planned yet)

## Environment variables (.env, never committed)
- `APP_SECRET`
- `DATABASE_PATH`
- `ANTHROPIC_API_KEY`
- `EMAIL_API_KEY`
- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `SMS_API_KEY`
- `PAYMENT_API_KEY`
- `PAYMENT_WEBHOOK_SECRET`
