# AirAssist A3 — instructions for the coding agent

AirAssist is an INFOSYS 704 A3 prototype: an Air New Zealand direct-booking refund case app.
Passengers look up a sample booking, submit a refund request and track it; staff review the case,
attach a read-only SAP Credit Memo Request reference and hand it off to a queue.

## Layout
- `app/server.py` — Python standard-library HTTP server, SQLite storage, SAP read-only client.
- `app/public/` — HTML, CSS and JavaScript frontend (no build step, no npm dependencies).
- `app/tests/` — backend unittest suite and `frontend-state.cjs` checks.
- `A3_Presentation/`, `A3_App_V1/` — presentation files and the accepted V1.4 baseline. Do not edit unless asked.

## Rules
- Never read, print or edit `.env`, API keys or `app/.data/`. The SAP key is only read at runtime from the local `.env`.
- Never put secrets in code, config, logs, error messages or test fixtures.
- Do not rewrite existing files in `app/evidence/` or historical test results; add new files instead.
- Keep the app runnable with Python 3.10+ and no extra dependencies.
- Validate all user input on the server; keep SQL parameterised.
- Make one focused change per task and explain what changed.
- If a permission rule denies or blocks a command, stop and tell the user. Never work around it with another command, a temporary file or a different tool.
- Do not write `.env` in commit messages or command text; say "local config" instead.

## Checks (run from the repository root after every change)
```
python -B -m unittest discover -s app/tests -t app/tests
node app/tests/frontend-state.cjs
```
Both must pass before a change is considered done.

## Run the app
```
cd app
python -B server.py --port 8789
```
Then open http://127.0.0.1:8789/?view=journey. Sample booking: NZ7K2H / Taylor.
