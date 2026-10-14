<h1 align="center">AirAssist</h1>

<p align="center">
 <strong>One-tap refunds for disrupted Air New Zealand flights.</strong><br/>
 Passengers request a full refund in seconds. Staff approve it with every detail in front of them.
</p>

<p align="center">
 <img src="https://img.shields.io/badge/INFOSYS%20704-A3%20prototype-00838A" alt="INFOSYS 704 A3 prototype" />
 <img src="https://img.shields.io/badge/SAP-Credit%20Memo%20Request%20API-0A6ED1" alt="SAP Credit Memo Request API" />
 <img src="https://img.shields.io/badge/built%20with-OpenCode-111111" alt="Built with OpenCode" />
 <img src="https://img.shields.io/badge/python-3.10%2B-3776AB" alt="Python 3.10+" />
 <img src="https://img.shields.io/badge/tests-84%20backend%20%C2%B7%2053%20frontend-brightgreen" alt="84 backend and 53 frontend checks passing" />
</p>

<p align="center">
 <a href="https://infosys704-a3-airassist.vercel.app/">Live demo</a> ·
 <a href="#demo-accounts">Demo accounts</a> ·
 <a href="#run-it-locally">Run locally</a> ·
 <a href="#how-sap-is-used">How SAP is used</a> ·
 <a href="#deploy-to-vercel">Deploy</a> ·
 <a href="#team">Team</a>
</p>

<p align="center">
 <img src="./docs/demo.gif" alt="Walkthrough: a passenger requests a full refund, staff approve it, and the passenger sees the result" width="375" />
</p>

> [!NOTE]
> Coursework prototype for INFOSYS 704 (IT Consultancy), Assignment 3. It uses **synthetic data only**. It does not cancel real tickets, make payments or write anything to SAP.

---

## What it does

When a flight is cancelled, passengers usually have to find a form, choose a reason and wait. AirAssist removes those steps:

1. **Passenger** signs in and opens **My trips**. Every booking shows its status: refund available, awaiting approval, refunded, declined or on time.
2. For a cancelled flight, the **full refund amount is read live from SAP**. The passenger adds a mobile number or email, ticks one box and taps **Request full refund**. There is no reason to choose: the app already knows the flight was cancelled.
3. **Staff** sign in and see every request in one list: reason, amount, SAP credit memo, contact details, refund destination and a suggested route (**Fast track** or **Specialist**).
4. Staff **approve** (with a confirmation step) or **decline** (a reason is required). If a request is declined, customer service contacts the passenger.
5. The passenger's **My trips** updates straight away. Refunds always go back to the original payment method.

Staff can use **Reset demo data** to restore the starting state, so the demo can be repeated.

## Demo accounts

| Role | Username | Password | Lands on |
| --- | --- | --- | --- |
| Passenger | `Mark.don` | `password123!` | My trips and refund requests |
| Staff | `admin` | `admin123!` | Refund requests to approve or decline |

These are **public demo credentials for synthetic data only**. Locally they come from `AIRASSIST_PASSENGER_PASSWORD` and `AIRASSIST_STAFF_PASSWORD` in the local config file; the deployed demo uses the same values as Vercel environment variables. Never reuse them anywhere else, and never enter real personal or payment details.

### Two-minute demo script

1. Sign in as **Mark.don**. My trips shows four bookings with different statuses.
2. Open **NZ7K2H** (AKL → LAX, cancelled). Check the amount (USD 175.50 from SAP) and the refund destination (Visa •••• 4242).
3. Enter a mobile number, tick the confirmation and tap **Request full refund**.
4. Sign out and sign in as **admin**. Open Mark Don's new request and **Approve** it, or **Decline** it with a reason.
5. Sign back in as **Mark.don**. My trips shows the result.
6. As **admin**, tap **Reset demo data** before the next run.

Refreshing the page signs you out by design: the sign-in token is kept only in memory.

## How SAP is used

AirAssist reads the **SAP S/4HANA Cloud Credit Memo Request (A2X)** API from the SAP Business Accelerator Hub sandbox. In SAP, money owed back to a customer is a credit memo request, so AirAssist treats it as the source of truth for the refund:

- **Refund amount.** The amount the passenger sees is read live from SAP. NZ7K2H is linked to credit memo request **60000073** (USD 175.50). If SAP cannot be reached, the app says so and blocks the request; it never invents an amount.
- **Routing.** An open SAP document (status A) of USD 300 or less goes to **Fast track**; anything else goes to **Specialist**.
- **Audit trail.** Each request stores the SAP document number, amount, status and the time it was read. Seeded demo requests use recorded SAP snapshots.

The connection is **read-only**. Nothing is written to SAP and no payment is made. The SAP sandbox holds generic sample data, so the link between each demo booking and its credit memo is preset.

## Run it locally

You need **Python 3.10 or newer**. There are no npm packages to install.

```sh
cd app
python -B server.py --port 8789
```

On macOS you can also run `sh start.command`; on Windows, `powershell -File start.ps1`. Then open **http://127.0.0.1:8789/** and keep the terminal running. Press `Ctrl+C` to stop.

- If no passwords are set in the local config, the terminal prints random demo passwords at startup.
- **Restart the server after backend changes.** Front-end changes only need a page refresh.
- Local data is stored in `app/.data/` (SQLite) and is separate from the online demo.

### Connect to SAP

Without an SAP key the app still runs, but refund amounts show as unavailable. To connect:

```sh
cd app
cp .env.example .env
```

In the local `.env`, set `AIRASSIST_SAP_MODE=live` and add **your own personal SAP API Hub key**, then restart the server. The service URL is already in the template. Never commit `.env`, keys or `app/.data/`.

### Checks

Run from the repository root:

```sh
python -B -m unittest discover -s app/tests -t app/tests
node app/tests/frontend-state.cjs
```

Current results: **84 backend tests and 53 frontend checks pass**. See `app/evidence/TEST_RESULTS_V1_5.txt` and `app/evidence/FRONTEND_TEST_RESULTS_V1_5.txt`. Older V1.x files in `app/evidence/` are the historical V1.4 baseline.

## Deploy to Vercel

The Vercel entry point is [`api/index.py`](api/index.py). It reuses the same HTTP rules as `app/server.py`. [`vercel.json`](vercel.json) routes every request to the Python function, and [`.vercelignore`](.vercelignore) keeps secrets, local databases, tests, evidence and slides out of the deployment. Online records are stored as SQLite snapshots in **private Vercel Blob** storage (region `syd1`).

Set these environment variables in the Vercel project (names only; never commit the values):

| Variable | Purpose |
| --- | --- |
| `AIRASSIST_PASSENGER_PASSWORD`, `AIRASSIST_STAFF_PASSWORD` | Demo account passwords |
| `AIRASSIST_SESSION_SECRET` | Signs the sign-in tokens |
| `AIRASSIST_SAP_MODE`, `AIRASSIST_SAP_BASE_URL`, `AIRASSIST_SAP_API_KEY` | Live SAP refund amounts |
| `AIRASSIST_ALLOWED_HOSTS` | Allowed host name, e.g. `infosys704-a3-airassist.vercel.app` |
| `BLOB_READ_WRITE_TOKEN` | Added by Vercel when private Blob storage is connected |

Deploy from the repository root with an account that has access to the project:

```sh
vercel link --yes --project infosys704-a3-airassist --scope harryhaber606-7483s-projects
vercel deploy --yes --target preview
vercel alias set <new-deployment-url> infosys704-a3-airassist.vercel.app
```

GitHub automatic deployment is not connected, so pushing to GitHub does not update the live demo.

## How it was built

AirAssist was developed with **OpenCode** as the agentic coding tool, in small reviewed tasks: each change was planned, implemented, tested and checked in a real browser before it was committed. OpenCode session exports from the original build are kept in `app/evidence/`.

- **Backend:** Python standard library (`http.server`, `sqlite3`), signed stateless sign-in tokens, rate-limited sign-in, parameterised SQL and a strict Content Security Policy.
- **Frontend:** plain HTML, CSS and JavaScript. Mobile first, because passengers use it at the airport.

## Project layout

```text
app/
  server.py          Local server, business rules, SQLite storage, SAP client
  cloud_handler.py   Vercel adapter (with cloud_access.py and cloud_store.py)
  public/            index.html, app.js, styles.css
  tests/             Backend unit tests and frontend checks
  evidence/          Test results (V1_5 = current) and OpenCode records
  .env.example       Configuration template without secrets
api/index.py         Vercel function entry point
docs/demo.gif        Walkthrough shown above
A3_Presentation/     Slides, speaking script and group checklist
A3_App_V1/           Historical V1.4 baseline (ZIP, QA records, screenshots)
```

## Team

INFOSYS 704 A3 group. Course usernames are listed (not GitHub handles). Contribution was agreed by the group: **25% each**.

| Member | Course username | Contribution |
| --- | --- | ---: |
| Zihang Zhang | zahz503 | 25% |
| Yi Han | yhan606 | 25% |
| Xiao Lin | xlin031 | 25% |
| Zhuyi Xia | zxia461 | 25% |

How the group works on this repository is described in [`CONTRIBUTING.md`](CONTRIBUTING.md).
