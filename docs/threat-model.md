# Prototype threat model

## Assets and trust boundaries

The assets are the original PDF, content-encryption key, recipient signing and decapsulation seeds, signed decryption records, validator chains, watermark secret and forensic reports. The browser talks to a loopback FastAPI service. Application metadata, private-key seals, master key and all validator databases reside on one workstation. This host is the trust boundary. Local accounts and cookie sessions are checked by the API.

## Tested protections

| Threat | Prototype control | Evidence |
|---|---|---|
| Wrong recipient tries another envelope | ML-KEM shared secret differs; AES-GCM CEK unwrap fails | Automated wrong-recipient test |
| Ciphertext or document ID altered | AES-GCM associated data and SHA3 hashes reject it | Automated AES integrity test |
| Decryption event altered | Canonical bytes fail ML-DSA signature and event hash checks | Automated signature/ledger tests |
| One validator row corrupted | Independent hash/signature checks mark node `DIVERGED`; 2/3 chain remains | Automated tamper and restore test |
| PDF metadata stripped | Watermark remains in rendered page content | Automated metadata removal test |
| Unknown or ambiguous visual signal | Detector returns `INCONCLUSIVE` | Negative original-PDF test |
| One demo account attempts another role's operation | API role and recipient ownership checks deny access; mutations require CSRF token | API authorization test |
| Repeated login or compute requests | Five-failure account window, per-source login window, per-user expensive-action limits | Auth and API throttle tests |
| Unattended authenticated browser | Eight-hour absolute and fifteen-minute inactivity expiry, enforced by the server | Expired-session API test |
| Small digital shift or rotation | Bounded feature-based registration before rechecking the visual signal | Three-document deterministic benchmark |
| One verifier path compromised or misleading | Separate read-only public-key process recomputes hashes, signatures and quorum | Healthy / one-divergent / restored verifier tests |

## Limitations and assumptions

An attacker with host administrator access can read the master key, recipient seeds and all validator keys. The three validators are logical replicas under one coordinator. They demonstrate replicated tamper evidence but offer no protection against coordinated host compromise. Demo account passwords are intentionally published; local login is role enforcement for a video workflow, not a production identity system. The API must remain on a trusted local machine. Generated private keys are not in frontend APIs, but this does not replace hardware-backed storage. No formal authorization to handle classified documents exists.

The watermark relies on an authenticated original and the issued-session list. A small synthetic benchmark now covers exact copies, PDF re-render, 90% resize, JPEG quality 65, 2-pixel shift and 1-degree rotation; these results do not establish general robustness. New issued copies are image-only, preventing direct text selection, but OCR, screenshots, retyping, collusion, heavy crop/rotation, hostile editing, physical print/scan and watermark transplantation remain unproven or outside attribution. A text-only re-creation must return `INCONCLUSIVE`, not a person. A larger blind false-positive/false-negative study is required. The `confidence` number is correlation, not a calibrated probability. The forensic result identifies the marked decryption session; it does not establish who disclosed the file.

Availability and replay are simplified: the prototype does not support key rotation, disaster recovery, recipient certificate chains, time-stamping authorities, multi-site consensus, secure clock attestation or retained chain snapshots outside this workstation. A sophisticated attacker can remove or destroy local storage. The PDF parser still runs in the API process and body limits are incomplete for requests without a trustworthy `Content-Length`. No FIPS validation, accreditation or independent security audit is claimed.

## Safe demo handling

Use the generated synthetic PDF and fictional identities. Run the API on `127.0.0.1`. Store `data/` only on the demo machine and never commit it to a repository. Stop the API before reset. Do not put actual secrets or classified data into this prototype. The demonstration-only tamper button intentionally corrupts one local validator database; restore it through the adjacent action.
