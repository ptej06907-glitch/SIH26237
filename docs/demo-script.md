# Three-minute video script

**0:00–0:25 — Establish the claim.** Sign in as `sender`. Open Dashboard. Point to `PQC READY`, `WATERMARK READY`, air-gapped configuration and three healthy validators. Explain that this is an SIH 2026 research prototype using synthetic content, not an official Ministry of Defence deployment.

**0:25–0:55 — Encrypt once.** Open Documents. Select `Strategic_Exercise_Brief.pdf`, tick all three fictional recipients and create envelopes. Call out: one AES-256-GCM ciphertext, three ML-KEM-768 recipient envelopes wrapping the same content key.

**0:55–1:25 — Recipient access.** Sign out and sign in as REC-002 (Lt. Commander Meera Singh). Open Decrypt; submit. Show the ML-KEM, AES, watermark, ML-DSA and ledger steps, plus the 3/3 quorum. Download and open the PDF. It looks like the original; the issued copy has image-only pages and an invisible rendered-content carrier. Mention that OCR/retyping can still recreate content without the mark.

**1:25–2:10 — Investigate.** Sign out and sign in as `investigator`. Upload the downloaded PDF. Read the result: REC-002, specific session, measured visual correlation, valid ML-DSA signature, valid ledger chain, block hash and 3/3 quorum. Say clearly that this attributes a *decryption copy*, not legal responsibility for a leak. Export JSON or print the HTML report.

**2:10–2:45 — Demonstrate tamper evidence.** Open Ledger, load the blocks and verify the recipient signature. Sign in as `auditor`; run the demonstration-only validator-2 tamper action. Point to validator-2 `DIVERGED`, other replicas `HEALTHY`, and authoritative quorum 2/3. Run the separate read-only public-key check, then restore validator-2; quorum returns to 3/3.

**2:45–3:00 — Robustness and boundary.** Run the optional digital transformation lab. State that exact PDF, re-render, 90% resize and selected JPEG levels were tested. Physical print/scan and hostile edits require further evaluation.

Keep the upload/download files together in a local demo folder. Stop and reset the API before each clean recording.
