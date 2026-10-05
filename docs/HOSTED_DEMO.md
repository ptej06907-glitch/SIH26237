# SourceX hosted demonstration

The primary SourceX run mode remains local and offline. The root `Dockerfile` and
`render.yaml` add a separate online demonstration mode for judges. The hosted
copy is **not air-gapped** and must receive only synthetic, unclassified PDFs.

## Deploy on Render

1. In the Render dashboard, create a Blueprint from the public `SIH26237`
   GitHub repository. The Blueprint defines one free Docker web service.
2. When prompted for `SOURCEX_DEMO_GATE`, enter a unique access code of at
   least 16 characters. Keep it out of Git. Share it with judges separately.
3. Wait for the build and the `/health` check to pass. Open the assigned
   `https://...onrender.com` URL.
4. Enter the access code, then use the fictional role credentials shown on
   the sign-in screen. Run the sender → recipient → investigator → auditor
   workflow with the seeded sample PDF.

The deployment exports Next.js to static files, serves those files and the
FastAPI backend from one origin, and keeps the same real cryptographic and
ledger operations. HTTPS session cookies and a separate demo access gate
protect the shared example credentials. The gate is for demonstration access,
not production authentication. Three validators remain logical stores within
one container, not independently operated nodes.

## Free-hosting limitations

Render free web services spin down after 15 minutes without traffic; the first
visit after that can take about a minute. Their local filesystem is ephemeral:
uploads, newly created recipients, ledger events and investigations disappear
on restart, redeploy or spin-down. Startup recreates the seed accounts and
sample PDF. Finish a live demonstration in one active session, and open the
link shortly before presenting. For durable data or independent validators,
use a different production architecture.

Never submit classified or real sensitive material. Public demo credentials
are intentionally published in the repository. The shared access code reduces
drive-by use but is not a substitute for production identity controls,
independent key custody, durable storage or a security audit.
