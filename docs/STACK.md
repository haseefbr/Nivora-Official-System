# Stack

Confirmed by the human in GigaLab on 2026-10-22.

| Layer | Choice | Why |
|---|---|---|
| Frontend | Plain HTML, CSS and JavaScript | No build step and nothing to install, as GigaLab itself; fine for forms, lists and dashboards |
| Backend | Python: FastAPI | GigaLab's own stack: small, fast and typed; you add sign-in and an admin with libraries |
| Database | SQLite | One file on the server; enough for a few thousand tasks a month on one server with a lasting disk |
| Hosting | A hosting platform (PaaS) | Push code and it runs, with a managed database; pay more, look after less |
| Extras | none | |

## Commands
- Install: `pip install -r requirements.txt`
- Run the tests: `pytest -q`
- Run the app: `uvicorn app.main:app --reload`

## Who looks after it
- Reads best: JavaScript or TypeScript. Team: Just me, with a coding agent. Runs a Linux server: No. Live updates: Yes: live chat, a live inbox or notifications.

## Checks from GigaLab
- warn: Many hosting platforms wipe the disk on each deploy: check that yours keeps one for the SQLite file, or use its managed PostgreSQL.
- warn: You read JavaScript best, but the backend is Python: you must still review every change the agent makes.
