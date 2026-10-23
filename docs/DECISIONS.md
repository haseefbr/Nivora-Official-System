# Decisions

Each decision, what GigaLab suggested from the inputs, what was chosen and why.

## 2. Requirements

### Version 1
- Chosen: **The must-haves only**
- Suggested: The must-haves only. 7 must-have features first: the smallest product a customer will pay for. The should-haves come after real use.
- Options: The must-haves only; Must and should
- Why it matters: Version 1 should be the smallest product a customer will pay for. Every extra feature is more to build, test and support before anyone pays.

## 3. Tech stack

### Frontend
- Chosen: **Plain HTML, CSS and JavaScript**
- Suggested: React (with Vite). You read JavaScript best: React components, with the most examples online.
- Why not the suggestion: (not written)
- Options: Plain HTML, CSS and JavaScript; Server pages with htmx; React (with Vite); Vue (with Vite); Next.js (React)
- Why it matters: The pages your customers see. Choose what you can read: the agent writes it, you approve every change.

### Backend
- Chosen: **Python: FastAPI**
- Suggested: Node.js: Express. You read JavaScript best: review what you can read.
- Why not the suggestion: (not written)
- Options: Python: FastAPI; Python: Django; Node.js: Express; Node.js: Next.js route handlers
- Why it matters: Where the rules live: sign-in, permissions, the data and the model calls. Keys and checks belong here, never in the browser (Module 1).

### Hosting
- Chosen: **A hosting platform (PaaS)**
- Suggested: A hosting platform (PaaS). A hosting platform runs it for you; you pay a little more and look after less.
- Options: One server (VPS) with Docker; A hosting platform (PaaS); Vercel or another serverless host
- Why it matters: Pick what you can keep running at 3 a.m. Backups and monitoring matter more than the vendor.

### Database
- Chosen: **SQLite**
- Suggested: PostgreSQL. A hosting platform can wipe its disk on every deploy, so a file database would be lost: use its managed PostgreSQL.
- Why not the suggestion: (not written)
- Options: SQLite; PostgreSQL; MySQL or MariaDB
- Why it matters: Pick the smallest database that fits your volume and your hosting. You can move up later, but moving data is work.

## 5. Core modules

### Tenancy
- Chosen: **One database, tenant id on every row and key**
- Suggested: One database, tenant id on every row and key. One database with the tenant id on every row and key is cheap and enough; your tests prove the isolation.
- Options: One database, tenant id on every row and key; A database per customer
- Why it matters: Every query and every key must say which customer it belongs to, or one customer will see another's data.

### Whose API key pays
- Chosen: **Your key (you bill the customer)**
- Suggested: Your key (you bill the customer). Small-business owners will not get an API key: use yours, and price the tokens in.
- Options: Your key (you bill the customer); The customer's own key
- Why it matters: With your key you pay the provider and bill the customer, so your price must cover tokens. With the customer's own key they pay the provider directly.

### Where the model is called from
- Chosen: **Your server, keys in .env**
- Suggested: Your server, keys in .env. The browser talks only to your server; the key stays in .env (Module 1).
- Options: Your server, keys in .env; The browser, key in the page
- Why it matters: A key in the browser can be read by anyone who opens the page (Module 1).

## 6. AI features (Module 2)

### Output format
- Chosen: **JSON fields, checked by code**
- Suggested: JSON fields, checked by code. Code can check the answer, so give it fields to check (Module 2). List them on each AI feature’s card.
- Options: Plain text; JSON fields, checked by code; JSON with the provider's structured output
- Why it matters: Code can only check what it can parse. Free text is fine for a person to read, not for a system to act on.

### Failure policy
- Chosen: **Repair once, then a safe reply**
- Suggested: Repair once, then a safe reply. Mistakes are cheap: one repair, then a safe fallback reply.
- Options: Repair once, then a safe reply; Repair once, then human review; Always human review; Stop and alert
- Why it matters: Every reply that fails a check needs a planned next step. Module 4 showed repair once, human review and stop-and-alert.

### Few-shot examples
- Chosen: **Two or three**
- Suggested: Two or three. Customers write in two languages: give one example in each, plus an edge case.
- Options: None; Two or three; Five or more
- Why it matters: Examples show the model the exact shape and tone. They cost tokens on every call, so add only what the tests show you need.

## 7. Tools and agent (Modules 3 and 11)

### Shape
- Chosen: **One model call**
- Suggested: One model call. No tools: it needs no facts from your data and takes no actions, so one call, checked by code, is enough.
- Options: One model call; A fixed workflow; An agent loop with tools
- Why it matters: Every extra model call adds cost, time and a place to fail. Start with the simplest shape that does the job (Module 3).

### Know-how
- Chosen: **Everything in one prompt**
- Suggested: Everything in one prompt. It does one kind of task, so its steps fit in the prompt contract (Module 2). Add skills when it takes on a second kind of task.
- Options: Everything in one prompt; One skill per task, loaded on demand
- Why it matters: A skill packages the steps and files for one task. The agent sees only each skill's name and description until a request needs it, so many skills do not crowd the context, and each can be tested alone (Module 11).

## 8. State (Module 6)

### Cache
- Chosen: **No cache**
- Suggested: No cache. Requests rarely repeat, so a cache would seldom hit.
- Options: No cache; Cache with a full key; Cache by the question only
- Why it matters: A cache hit costs nothing and takes milliseconds. A cache key without the tenant gives one customer another customer's answer (Module 6).

### Rate limits
- Chosen: **Per customer and per person**
- Suggested: Per customer and per person. Your customers’ own customers reach it through a public channel: limit each customer and each end user.
- Options: Per customer (tenant); Per customer and per person; No limit
- Why it matters: Without a limit one customer, or one bug, can spend your whole budget in minutes. Use an atomic counter (Module 6).

## 9. Context (Module 7)

### Knowledge
- Chosen: **None**
- Suggested: None. No reference material.
- Options: None; Everything in the prompt, cached; Keyword retrieval (BM25); Retrieval with embeddings
- Why it matters: Small material can simply go in every call (and be cached). Large material must be selected per question, or the cost and the noise grow (Module 7).

### Memory
- Chosen: **None**
- Suggested: None. One request, one answer: nothing to remember.
- Options: None; Full history; Last N turns; Summary + last N turns; Structured state + last 2 turns
- Why it matters: A long chat costs more on every turn. Keep the facts, not the whole transcript (Module 7).

### Prompt caching
- Chosen: **No caching**
- Suggested: No caching. Your stable start is about 640 tokens: below most providers’ cache minimum (1,024 tokens).
- Options: No caching; Cache the stable start
- Why it matters: A long, unchanging start is read from the provider's cache at a fraction of the price, but only if nothing changes before it (Module 7).

## 10. Reliability (Module 4)

### Eval set
- Chosen: **Your cases and the failure tests**
- Suggested: Your cases, one per rule and never-rule, and the failure tests. One case for each rule and never-rule, so every rule has a test that would catch it breaking (Module 4).
- Why not the suggestion: (not written)
- Options: Your cases and the failure tests; Your cases, one per rule and never-rule, and the failure tests; All that, plus twenty or more real requests
- Why it matters: Each rule and each never-rule needs at least one case that would catch it breaking (Module 4).

### Release gate
- Chosen: **All critical cases pass, 90% overall**
- Suggested: All critical cases pass, 90% overall. Mistakes are cheap: the Module 4 default is enough.
- Options: All critical cases pass, 90% overall; All critical and never cases pass, 95% overall; Every case passes
- Why it matters: The gate decides, not your mood on release day. Failures are ranked by severity (Module 4).

### Fallback model
- Chosen: **A second provider on timeout or 429**
- Suggested: A second provider on timeout or 429. Paying customers expect it to work when one provider is down: same contract and checks, a second provider.
- Options: None; A second provider on timeout or 429
- Why it matters: Providers time out and rate-limit. A second provider keeps you up; your checks keep its replies safe (Module 4).

### What you log
- Chosen: **A safe log line**
- Suggested: A safe log line. Enough to debug and to bill, without keeping what customers wrote (Module 4).
- Options: A safe log line; Full prompts and replies
- Why it matters: You need logs to debug and to bill. What users write is personal data (Module 4's safe log line).

## 11. Cost (Module 1)

### Model
- Chosen: **ollama · gigalab-local**
- Suggested: ollama · gigalab-local. The cheapest for all your AI features at your estimate: $0 per customer a month. Move up only if the release gate fails (Module 2’s model matrix).
- Why it matters: Start with the cheapest model that passes your release gate; move up only when the eval set says so (Module 2's model matrix).

### Models per feature
- Chosen: **One model for every AI feature**
- Suggested: One model for every AI feature. Your AI features are alike: one model is simpler to test, to price and to switch.
- Options: One model for every AI feature; A small model for simple features, the chosen model for the rest
- Why it matters: Simple jobs such as classifying or extracting fields rarely need the strongest model. A small model for them cuts the bill; the eval set shows whether it is good enough (Module 2's model matrix).

## 12. SaaS business

### Billing
- Chosen: **Stripe**
- Suggested: Stripe. Cards and online banking: compare Stripe with a Malaysian FPX gateway for the methods and fees you need.
- Options: Manual invoices at first; A Malaysian gateway with FPX; Stripe
- Why it matters: Let a payment provider hold card and bank details; you only keep its customer id. Compare the fees and recurring-billing support yourself.

### How long you keep personal data
- Chosen: **One year**
- Suggested: One year. No personal data: keep a year of records for your own reports.
- Options: 30 days; 90 days; One year; Until the customer deletes it
- Why it matters: Malaysia's PDPA: collect only what you need, say why, keep it no longer than needed, protect it, and let people ask for their data.

## 13. Build pack (Module 5)

### Coding agent
- Chosen: **Another agent**
- Suggested: Claude Code. The course used Claude Code (Module 5); the pack works with any agent that reads AGENTS.md.
- Why not the suggestion: Hermes
- Options: Claude Code; OpenAI Codex; Cursor; GitHub Copilot; Gemini CLI; Another agent
- Why it matters: AGENTS.md works for most coding agents; CLAUDE.md and GEMINI.md import it, and Copilot gets a pointer to it. All are in the pack.
