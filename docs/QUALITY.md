# Quality

The three qualities that matter most for this product. Each target becomes a test, or a scripted check, in M6. Every other quality still meets its baseline.

## 1. Security
Accounts and data stay safe from people who should not see them.

- Every input is validated on the server
- Secrets live only in environment variables, never in code, logs or the browser
- HTTPS only, secure cookies and CSRF protection
- Rate limits on sign-in and on every public route
- A dependency audit runs on every build (pip-audit or npm audit)
- Reviewed against the OWASP Top 10 before launch
- Prompt-injection tests: text from customers never changes the rules

## 2. Reliability
It keeps working, and when something fails, it fails safely.

- Every error gives a clear message, and nothing is left half-saved
- Calls to outside services time out and retry with back-off
- Daily backups, restored once to prove they work
- Payments and actions are idempotent: a retry never runs them twice
- The AI release gate passes before every release

## 3. Performance
It feels fast, on a phone, on a slow connection.

- p95 page load under 2 seconds on a phone over 4G
- p95 API response under 500 ms, not counting AI calls
- A database index for every list and search
- An AI reply starts within 5 seconds, streamed or with progress shown

## Baseline for the rest
- Availability: An uptime check with an alert
- Scalability: No state kept in the app server's memory
- Privacy and PDPA: A privacy notice, and no personal data in logs
- Usability and accessibility: Works on a phone; error messages say what to do
- Maintainability: Every feature has acceptance tests
- Observability: One safe log line per request
- Cost efficiency: Know the monthly bill before it arrives
