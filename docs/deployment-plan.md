# Vercel deployment plan · 2026-10-14

Deploy the existing coursework prototype as a Vercel preview. Preserve the
local Python/SQLite workflow and the accepted V1.4 evidence and ZIP archives.

1. Extract the HTTP handler factory without changing local behavior. Verify
   the existing backend and frontend checks, then commit independently.
2. Add private Blob snapshot storage for the small demo database. Each
   operation uses a fresh temporary SQLite copy; conditional ETag writes
   prevent lost updates across serverless instances. Test cold starts,
   duplicate submissions, ownership checks and concurrent writes.
3. Add the Vercel handler with exact host/origin checks and signed browser
   sessions for API requests. Keep SAP unconfigured unless the owner supplies
   environment variables. Test security boundaries and the complete workflow.
4. Deploy only application files. Confirm Vercel reports Ready. Update the
   README with the deployment link, storage/authentication boundaries and
   redeployment instructions; push each independently verified change.
5. Attempt to update repository About/homepage. If GitHub rejects the current
   collaborator permissions, report the limitation and provide the exact text.

The online app remains a public coursework demo using synthetic bookings.
It has no staff identity provider and must not receive real traveller data.
Private Blob snapshots suit a small classroom demo, not a production database.
The Vercel GitHub integration currently cannot access the owner's repository;
CLI deployment remains available from the authenticated Vercel account.
