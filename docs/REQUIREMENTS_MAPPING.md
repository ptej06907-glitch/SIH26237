# SIH26237 requirements mapping

The scope below maps the provided problem brief to working source. `EXTRA FEATURE — NOT EXPLICITLY REQUIRED BY SIH26237` marks useful video-demo additions. See test status in README. The live Chrome test found no external requests; a firewall-level isolation test and Docker run remain unverified on this machine.

| Requirement | Implementation / source | Video demonstration |
|---|---|---|
| One encrypted PDF for many recipients | `services/api/provenance/crypto.py`, `service.py` | Documents → distribute; response says encryption count 1 |
| ML-KEM-768 recipient identities and envelopes | `crypto.py`, `store.py` | Recipients fingerprints; distribute to three |
| ML-DSA-65 recipient decryption signature | `crypto.py`, `service.py`, `ledger.py` | Ledger → select event → Verify signature |
| Unique marked PDF for every decryption | `watermark.py`, `service.py` | Decrypt same document twice; sessions and hashes differ |
| Real rendered-content invisible/near-invisible mark | `watermark.py`; new issued copy is image-only | Download marked PDF; metadata removal test still detects |
| Watermark extraction and technical attribution | `watermark.py`, `service.py` | Forensics → upload marked PDF |
| Offline hash-linked replicated ledger | `ledger.py` | Ledger → Load blocks → Verify entire chain |
| Three validators and 2/3 quorum | `ledger.py`, separate `data/validators/validator-*` | System status and Ledger validator panels |
| Independent hash/signature/quorum verification | `ledger.py`, `independent_verify.py`, `service.py` | Ledger verifier, separate read-only public-key check and forensic evidence panel |
| Fail-closed PQC and no classical fallback | `crypto.py`, `service.py` | System status; startup self-test and automated tests |
| Local runtime without cloud services | Next.js bundled assets, FastAPI local stores, `scripts/run_demo_checks.py` | System page and offline backend check |
| Role-based local authentication and ownership | `services/api/provenance/auth.py`, `app.py`, `store.py`; `apps/web/src/components/AppShell.tsx` | Sign in as sender, REC-002, investigator and auditor; unauthorized API actions are rejected |
| Session and request hardening | `auth.py`, `app.py`, `store.py`, Next config | Show expiry and throttle tests, browser headers, and request rejection |
| Seed and rapid reset | `scripts/seed_demo.py`, `scripts/reset_demo.py` | Run reset before recording |
| Evidence report | `services/api/provenance/app.py` | Forensics → JSON / printable HTML |
| `EXTRA FEATURE — NOT EXPLICITLY REQUIRED BY SIH26237`: tamper demonstration | `ledger.py`, `app.py`, Ledger UI | Corrupt validator-2, observe 2/3, restore |
| `EXTRA FEATURE — NOT EXPLICITLY REQUIRED BY SIH26237`: digital robustness lab | `watermark.py`, `service.py`, Forensics UI | Run PDF re-render and JPEG 85/65 trials |
| Measured small shift/rotation and negative control | `scripts/benchmark_watermark.py`, `artifacts/watermark-benchmark.json` | Show 18/18 marked and 6/6 negative cases; explicitly state the small synthetic scope |
| Government-quality navigation and accessibility basics | `apps/web/src/components/AppShell.tsx`, `globals.css` | Show bilingual nav, breadcrumbs, keyboard/contrast controls |

## Deliberate exclusions

No production IAM, HSM, classified-document use, public blockchain, token functionality, cloud API, mobile app, arbitrary document formats, nationwide PKI, OCR, smart contracts, perfect print/scan robustness or collusion-resistant tracing. These would expand implementation risk without improving the core video story. The current three validator stores are coordinated by one process, so they are not independent network peers.
