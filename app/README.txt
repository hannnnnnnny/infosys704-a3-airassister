AirAssist — A3 functional prototype (V1.5, 2026-10-15)

What it does
Passengers sign in, open My trips and request a full refund for a cancelled flight in one step.
Staff sign in, see every request and approve or decline it. The passenger's My trips shows the result.
Refund amounts are read live from the SAP Credit Memo Request API (NZ7K2H is linked to document 60000073).
Seeded demo requests use recorded SAP snapshots. Refunds always go back to the original payment method.
This is not an airline system. Trips, fares and contacts are synthetic. It does not cancel tickets,
make payments or write anything to SAP.

Start the app
1. You need Python 3.10 or newer (check with: python3 --version). No npm packages are needed.
2. Open a terminal in this folder (app) and run one of:
   macOS:   sh start.command
   Windows: powershell -File start.ps1
   Any OS:  python -B server.py --port 8789
3. Open http://127.0.0.1:8789/ in a browser. Keep the terminal running; press Ctrl+C to stop.
Do not open index.html directly — it needs the local server.
Restart the server after backend changes. Front-end changes only need a page refresh.

Demo accounts
Passenger: Mark.don / password123! — requests a full refund.
Staff:     admin / admin123!     — approves or declines refunds.
Public demo credentials for synthetic data only. Locally they come from AIRASSIST_PASSENGER_PASSWORD and
AIRASSIST_STAFF_PASSWORD in the local config file; if they are not set, the terminal prints random passwords
at startup. The deployed demo uses the same values as Vercel environment variables.

Demo script
1. Sign in as Mark.don. My trips lists four bookings with their status.
2. Open NZ7K2H (AKL to LAX, cancelled). Check the amount from SAP and "Refund to Visa •••• 4242".
3. Enter a mobile number (email is optional), tick the confirmation and tap Request full refund.
4. Sign in as admin. Expand Mark Don's request to see the flight, SAP credit memo, contact and refund
   destination. Approve it (with a confirmation step) or Decline it with a reason.
5. Sign in as Mark.don again. My trips shows the result; the status screen offers a receipt download.
6. As admin, tap Reset demo data to restore the starting state.
Refreshing the page signs you out by design. Submitting the same booking twice returns the original request.

SAP connection
The refund amount is read from SAP each time a refundable trip is opened. The connection is read-only.
This is the real SAP sandbox API with generic sample financial data, not Air New Zealand production data.
If SAP cannot be reached, the app shows an error with a retry button and never invents an amount.
To connect on another computer: copy .env.example to .env, set AIRASSIST_SAP_MODE=live, add your own
personal SAP API Hub key, then restart. The service URL is already in .env.example.
Never put .env, API keys, .data/ or real personal details in a ZIP, repository, screenshot or AI prompt.

Checks and evidence
Run from the repository root:
  python -B -m unittest discover -s app/tests -t app/tests     (84 backend tests pass)
  node app/tests/frontend-state.cjs                            (53 frontend checks pass; needs Node.js)
Current results: evidence/TEST_RESULTS_V1_5.txt and evidence/FRONTEND_TEST_RESULTS_V1_5.txt.
Older V1.x files in evidence/ are the historical V1.4 baseline. OpenCode session exports from the
original build are kept in evidence/ (OPENCODE_*).

Vercel environment variables (names only; never commit values)
AIRASSIST_PASSENGER_PASSWORD, AIRASSIST_STAFF_PASSWORD, AIRASSIST_SESSION_SECRET,
AIRASSIST_SAP_MODE, AIRASSIST_SAP_BASE_URL, AIRASSIST_SAP_API_KEY.

Local data is stored in .data/airassist.sqlite3 (created on first start). The local server only listens on
127.0.0.1. A production version would need real airline booking and payment systems, staff identity
management and approval permissions.

Official references
SAP: https://api.sap.com/api/sap-s4-CE_CREDITMEMOREQUEST_0001-v1/overview
OpenCode: https://opencode.ai/docs/cli/
