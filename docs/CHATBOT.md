# Chatbot

A Flowise agent flow answers customers on the shop page and the seller in the app.
It is **proxied** through the backend, never called from the browser.

```
browser ──POST /api/bot/chat ─────────────► FastAPI ──POST FLOWISE_URL──► Flowise
        └─POST /api/public/shops/{slug}/bot─┘         (context + rules)
```

## Configure

`.env`:

```ini
BOT_ENABLED=true
FLOWISE_URL=https://flowise.bdctraining.cloud/api/v1/prediction/<flow-id>
FLOWISE_API_KEY=            # only when the flow requires a bearer token
FLOWISE_TIMEOUT_SECONDS=35
```

Empty `FLOWISE_URL` switches the assistant off; both endpoints then answer
`503 bot_not_configured`. `BOT_ENABLED=false` turns the UI dark as well.

## Why the proxy

- **Grounding.** The flow has its own training knowledge and will invent prices
  if asked cold (measured: it once quoted "Kuih Lapis RM4.90 for 3 pieces" while
  this shop sells a box of ten for RM12). Every call therefore prepends a context
  block built from the database — name, address, phone, every active dish with
  its price and category, the delivery fee, payment and the order link — plus
  rules: answer only from that context, say "not sure, call the shop" otherwise,
  never mention documents/knowledge base/AI, max three sentences, never take an
  order in chat.
- **No key or URL in the page.** The browser sees only `/api/bot/chat`.
- **Limits.** 25 questions per 10 minutes per seller; 20 per 10 minutes per
  device on a shop page.
- **Audit.** Each call writes one row to `ai_calls` (`feature = CHATBOT`,
  `provider = flowise`, duration, outcome) so a broken flow is visible in logs.

## Conversation memory

The flow's `sessionId` is stored per browser, but the agent does not replay its
own memory, so the browser sends the last three turns and they are inlined into
the question as `PERBUALAN SEBELUM INI`. History is capped at 300 characters a
turn and six turns server-side.

## Files

| File | Role |
|---|---|
| `app/bot.py` | `BotFacts` (context), `build_question`, `tidy`, `BotClient` |
| `app/routes/bot_api.py` | `POST /api/bot/chat`, `POST /api/public/shops/{slug}/bot` |
| `static/bot.js` | floating panel, history in `localStorage`, CSRF |
| `static/bot.css` | panel styling (root class `nivora-bot`) |
| `tests/test_bot.py` | grounding, tidying, payload, errors, limits |

## Replies are tidied

Flowise returns chatty preambles ("Berikut adalah ringkasan yang lebih natural…:").
`tidy()` strips those openers, markdown emphasis and heading marks, collapses
blank lines and trims a runaway answer to ~1200 characters at a sentence break.

## Trade-offs

- Latency is 5–10 s on the current flow (it runs a router agent plus retrieval);
  the panel shows `Thinking…` and prints the elapsed seconds when a reply takes
  more than four.
- The flow cannot see stock, orders or the seller's costs. It only knows what is
  in the context block. Adding "today's remaining stock" means adding it to
  `BotFacts` — do not let the model guess.
- One flow serves every tenant; the context is what makes each shop's answers
  different. A per-tenant flow id would only matter for different *tone*.
