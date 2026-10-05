# Four-area upgrade evidence · 3 October 2026

This note records measured changes to SourceX. It is a research-prototype result, not a security certification or a claim of superiority over another team on a common benchmark.

## 1. Watermark resilience

The detector first checks the original reference-assisted visual correlation. When that check is inconclusive, it estimates a small Euclidean alignment from document features with OpenCV ECC, then repeats the same correlation and winner-margin checks. Alignment is capped at about 2.9 degrees and 12 low-resolution pixels; a missing or ambiguous carrier remains inconclusive. Existing exact/JPEG/re-render/scale detection is unchanged.

`scripts/benchmark_watermark.py` makes three synthetic documents with different page content, marks one of three candidate sessions per document, and challenges the detector with six marked-copy variants and two negative controls. It writes `artifacts/watermark-benchmark.json` and exits unsuccessfully if any case fails.

| Transformation | Before alignment | After alignment |
|---|---:|---:|
| Exact marked PDF | 3/3 | 3/3 |
| PDF re-render | 3/3 | 3/3 |
| JPEG quality 65 | 3/3 | 3/3 |
| 90% scaling | 3/3 | 3/3 |
| Two-pixel shift | 0/3 | 3/3 |
| One-degree rotation | 0/3 | 3/3 |
| Unmarked original correctly inconclusive | 3/3 | 3/3 |
| Text-only reconstruction correctly inconclusive | 3/3 | 3/3 |

The after-alignment result is **18/18 positive variants and 6/6 negative controls** on this small deterministic corpus. It does not establish a population false-positive rate, physical print/scan robustness, resistance to adversarial removal, or results on unseen real-world documents. A broader blind corpus is still needed.

## 2. Text-copy leakage boundary

New decryption sessions now render the authenticated source into an image-only PDF *before* embedding the visual carrier. The encrypted source remains intact. The signed event records `content_mode=RENDER_LOCKED_V1`; forensic detection chooses the matching reference for new and legacy sessions. An issued PDF has no selectable text layer. This removes the easiest PDF copy-and-paste route, at the cost of accessibility, searchability and file size. Existing older marked copies remain analyzable through the legacy reference path.

No PDF watermark can prevent someone from photographing the screen, using OCR, manually transcribing, or retyping content. The robustness lab includes a text-only reconstruction as a **negative control** and should report `INCONCLUSIVE`. The product must never imply that inconclusive reconstructed content proves no disclosure occurred.

## 3. Ledger verification independence

`provenance.independent_verify` is a separate read-only implementation. It runs in its own Python process, opens each validator SQLite database in read-only mode, uses a public-only validator registry and recipient public keys, and recomputes genesis, links, event/root/block hashes, recipient ML-DSA signatures, validator vote signatures, 2/3 quorum and matching chain heads. Its result is available in the Ledger UI and through `POST /ledger/independent-verify`. Tests verify 3/3 healthy, 2/3 with one corrupted node, and 3/3 after restore.

This is **independent verification code and process**, not independently governed validators. Signing keys, public registry and three databases still share one computer and host administrator. A privileged host compromise can rewrite them together. It does not exceed a real separately controlled Hyperledger Fabric deployment on organizational independence.

## 4. Web application security

The backend now enforces a 15-minute inactivity timeout in addition to its existing eight-hour absolute expiry. Login has per-account and per-source failure windows, generic failed-credential responses, and `429` cooldowns. Decrypt, forensic analysis, robustness and independent verification actions have per-user limits. The frontend clears its session state and returns to sign-in when the API returns 401.

The API rejects disallowed browser Origins, checks declared PDF request length before endpoint parsing, adds no-store/nosniff/frame/referrer response headers, limits PDF render size to 5 megapixels per page, caps forensic corpus size, and validates recipient lists and control characters in names. The Next.js app adds a restrictive local-resource CSP and related browser headers. Tests cover throttle, expiry, origin rejection, upload-length rejection and the role journey.

Remaining security work: published demo passwords, local master key and all validator keys on one host, no HSM or MFA, incomplete isolation of the PDF parser, incomplete streaming body limits when `Content-Length` is absent, limited concurrency/CPU quotas, no independent penetration test and no networked deployment approval. Keep the API on loopback and use synthetic documents.

## Verification commands

```powershell
& .\.venv\Scripts\python.exe -m pytest -q --basetemp=.pytest_tmp
& .\.venv\Scripts\python.exe scripts\benchmark_watermark.py
& .\.venv\Scripts\python.exe scripts\run_demo_checks.py
cd apps\web
npm run build
npm run smoke
```

The benchmark is a *regression gate* for the specific generated corpus. Broader comparative claims require the same blind test set run against SourceX and peer systems by an independent evaluator.
