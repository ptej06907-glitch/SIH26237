# Public SIH26237 repository comparison

Checked 3 October 2026. This compares publicly visible repository documentation, not independently executed peer code. The two directly relevant public repositories reviewed were [bala9387/encryption](https://github.com/bala9387/encryption) and [ashebbar-dev/SIH (NISHAN-PQ)](https://github.com/ashebbar-dev/SIH). Our measured upgrades are recorded in [UPGRADE_EVIDENCE.md](UPGRADE_EVIDENCE.md).

| Area | This prototype, tested locally | Public peer documentation | Assessment |
|---|---|---|---|
| Video demo usability | Original Next.js interface with dashboard, document register, persona flow, forensic evidence panel, ledger explorer, bilingual nav and responsive layout; Chrome journey tested | `bala9387/encryption` describes a CLI and a local web UI with inline CSS; NISHAN also documents an interactive browser demo | Our interface is a clear presentation strength; visual quality is subjective |
| Setup on this Windows PC | `cryptography` wheels installed and real ML-KEM/ML-DSA self-tests passed; no custom PQC C build needed | `bala9387/encryption` documents building liboqs from source on Windows | Our tested setup is simpler on this PC |
| Issued-PDF text path | New issued copies are image-only before visual marking; text-only re-creation returns inconclusive. Source ciphertext retains the original PDF. | `bala9387/encryption` also flattens issued PDF pages; NISHAN describes an editable-PDF path and additional corroboration. | We have closed simple selectable-text copying but this is not a unique advantage; OCR/retyping remain outside attribution. |
| Ledger verification | Three local SQLite replicas, signed votes, 2/3 quorum and one-node tamper detection; a separate read-only public-key verifier process. | `bala9387/encryption` documents a real Hyperledger Fabric mode with four peers and 3-of-4 endorsement. | A second verifier improves auditability, but Fabric remains architecturally stronger on process and organizational separation. |
| Watermark attack evaluation | Three synthetic PDFs: 18/18 marked digital variants including 2-pixel shift and 1-degree rotation; 6/6 negative controls inconclusive. | Both peers document broader transformations; NISHAN reports dual carriers, collusion fixtures and JPEG-Q55 trials. | Our regression evidence improved, but peer evaluation is broader and no common blind benchmark exists. |
| End-to-end verification | Eight local automated tests, offline backend workflow check, full Chrome video journey and zero external browser requests in that prior run. | Both peers report their own test suites and demo runs. | These results are not directly comparable without a common independent test corpus. |

**Honest conclusion:** SourceX is more credible after measured registration, an image-only issued-copy policy, a separate public-key verifier and basic web hardening. It is not established as technically superior overall. In particular, the peers' documented Fabric endorsement and NISHAN's broader watermark evaluation exceed this prototype's current scope. Lead with reproducible working evidence, accessibility and clear threat boundaries.

## Highest-value future upgrades

1. Add a common blind benchmark corpus and run this detector and peer detectors under the same transformations, measuring false attribution and `INCONCLUSIVE` rates.
2. Put validators in separately controlled processes or machines, with enrollment-bound public-key registry and authenticated inter-node messages.
3. Add a second independent watermark carrier, transformation registration and anti-transplant checks; only claim print/scan after real captures are tested.

These upgrades are beyond the current three-minute prototype and should not be implied by the UI.
