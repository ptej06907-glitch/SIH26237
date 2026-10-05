from __future__ import annotations

import hashlib
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pymupdf

from .crypto import CryptoEngine, SUITE, b64, canonical, sha3, unb64, utc_now
from .auth import AuthManager
from .ledger import Ledger
from .store import Store
from .watermark import Candidate, detect_pdf, mark_pdf, render_locked_pdf, rerender_pdf, text_reconstruction_pdf, CARRIER_VERSION, CONTENT_MODE

MAX_PDF_BYTES = 15 * 1024 * 1024
DEMO_RECIPIENTS = (
    ("REC-001", "Major Arjun Rao", "Operations Officer"),
    ("REC-002", "Lt. Commander Meera Singh", "Naval Intelligence Officer"),
    ("REC-003", "Analyst Vikram Sharma", "Security Analyst"),
)


class Prototype:
    def __init__(self, root: Path):
        self.root = root
        self.data_dir = Path(os.environ.get("SIH_DATA_DIR", str(root / "data"))).resolve()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.data_dir)
        self.auth = AuthManager(self.store)
        self.crypto: CryptoEngine | None = None
        self.ledger: Ledger | None = None
        self.pqc_error: str | None = None
        self.watermark_error: str | None = None
        try:
            self.crypto = CryptoEngine(self.data_dir)
            self.ledger = Ledger(self.data_dir, self.crypto, self.store)
        except Exception as exc:
            self.pqc_error = str(exc)
        if self.crypto:
            try:
                test_pdf = self._sample_pdf()
                candidate = Candidate("startup-self-test", "startup", "self-test")
                marked, _ = mark_pdf(test_pdf, candidate, self.watermark_secret)
                if detect_pdf(marked, test_pdf, [candidate], self.watermark_secret)["status"] != "VALID":
                    raise RuntimeError("rendered-content extraction failed")
            except Exception as exc:
                self.watermark_error = str(exc)

    @property
    def watermark_secret(self) -> bytes:
        if self.crypto is None:
            raise RuntimeError("PQC ENGINE UNAVAILABLE")
        return hashlib.sha3_256(self.crypto.master + b"SIH26237-watermark-v1").digest()

    def ready(self, watermark: bool = False) -> tuple[CryptoEngine, Ledger]:
        if self.crypto is None or self.ledger is None:
            raise RuntimeError(f"PQC ENGINE UNAVAILABLE: {self.pqc_error}")
        if watermark and self.watermark_error:
            raise RuntimeError(f"WATERMARK ENGINE UNAVAILABLE: {self.watermark_error}")
        return self.crypto, self.ledger

    @staticmethod
    def _sample_pdf() -> bytes:
        pdf = pymupdf.open()
        page = pdf.new_page(width=595, height=842)
        page.insert_text((55, 70), "STRATEGIC EXERCISE BRIEF", fontsize=19, color=(0.08, 0.18, 0.30))
        page.insert_text((55, 101), "FICTIONAL SIH 2026 DEMONSTRATION DOCUMENT", fontsize=10)
        page.draw_line((55, 118), (540, 118), color=(0.2, 0.37, 0.5), width=1)
        lines = [
            "Purpose: demonstrate secure multi-recipient document distribution.",
            "This file contains synthetic data. It is not a defence document.",
            "Recipients: Major Arjun Rao, Lt. Commander Meera Singh, Analyst Vikram Sharma.",
            "Each authorized decryption creates a separately traceable rendered copy.",
            "The forensic result identifies a decryption session, not legal responsibility.",
        ]
        for index, line in enumerate(lines):
            page.insert_text((55, 160 + index * 32), line, fontsize=10)
        page.insert_text((55, 755), "SIH26237 | DEMO RESTRICTED | Synthetic content only", fontsize=9)
        result = pdf.tobytes()
        pdf.close()
        return result

    @staticmethod
    def validate_pdf(payload: bytes) -> int:
        if not payload.startswith(b"%PDF-") or len(payload) > MAX_PDF_BYTES:
            raise ValueError("Upload a PDF of at most 15 MB")
        try:
            doc = pymupdf.open(stream=payload, filetype="pdf")
            pages = doc.page_count
            if doc.is_encrypted or pages < 1 or pages > 12:
                raise ValueError("PDF must be unencrypted and have 1 to 12 pages")
            for page in doc:
                if page.rect.width > 2000 or page.rect.height > 2000:
                    raise ValueError("PDF page dimensions exceed prototype limit")
                if (page.rect.width * 140 / 72) * (page.rect.height * 140 / 72) > 5_000_000:
                    raise ValueError("PDF rendered page exceeds 5 megapixels")
            doc.close()
            return pages
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError(f"Invalid PDF: {exc}") from exc

    def seed_demo(self) -> dict[str, Any]:
        crypto, _ = self.ready(watermark=True)
        created = []
        for recipient_id, name, designation in DEMO_RECIPIENTS:
            if self.store.recipient(recipient_id):
                continue
            identity = crypto.make_identity(recipient_id)
            self.store.add_recipient({"id": recipient_id, "name": name, "designation": designation,
                                      "status": "ACTIVE", "created_at": utc_now(), **identity})
            created.append(recipient_id)
        if not self.store.documents():
            doc = self.create_document("Strategic_Exercise_Brief.pdf", "DEMO RESTRICTED",
                                       self._sample_pdf(), "Document Authority")
            sample_id = doc["id"]
        else:
            sample_id = self.store.documents()[0]["id"]
        users = self.auth.seed_demo_accounts()
        self.store.audit("DEMO_SEEDED", {"recipients_created": created, "users_created": users,
                                         "sample_document_id": sample_id})
        return {"recipients_created": created, "users_created": users, "sample_document_id": sample_id}

    def create_recipient(self, name: str, designation: str, password: str) -> dict[str, Any]:
        crypto, _ = self.ready()
        if len(password) < 10:
            raise ValueError("Recipient password must have at least 10 characters")
        next_id = f"REC-{len(self.store.recipients()) + 1:03d}"
        if self.store.recipient(next_id):
            next_id = f"REC-{uuid.uuid4().hex[:8].upper()}"
        identity = crypto.make_identity(next_id)
        self.store.add_recipient({"id": next_id, "name": name.strip(), "designation": designation.strip(),
                                  "status": "ACTIVE", "created_at": utc_now(), **identity})
        self.auth.create_recipient_account(next_id, name.strip(), password)
        self.store.audit("RECIPIENT_CREATED", {"recipient_id": next_id})
        return next(item for item in self.store.recipients() if item["id"] == next_id)

    def create_document(self, filename: str, classification: str, pdf: bytes, uploaded_by: str) -> dict[str, Any]:
        crypto, _ = self.ready()
        pages = self.validate_pdf(pdf)
        document_id = str(uuid.uuid4())
        cek, nonce, ciphertext = crypto.encrypt_document(pdf, document_id)
        path = self.store.files_dir / f"{document_id}.encrypted"
        path.write_bytes(ciphertext)
        value = {"id": document_id, "filename": Path(filename).name, "classification": classification,
                 "uploaded_by": uploaded_by, "created_at": utc_now(), "original_hash": sha3(pdf),
                 "ciphertext_hash": sha3(ciphertext), "nonce": b64(nonce),
                 "ciphertext_path": str(path), "authority_cek_sealed": crypto.seal(cek, f"authority:{document_id}"),
                 "page_count": pages, "status": "UPLOADED"}
        self.store.add_document(value)
        self.store.audit("DOCUMENT_ENCRYPTED_ONCE", {"document_id": document_id, "ciphertext_hash": value["ciphertext_hash"]})
        return next(item for item in self.store.documents() if item["id"] == document_id)

    def distribute(self, document_id: str, recipient_ids: list[str]) -> dict[str, Any]:
        crypto, _ = self.ready()
        document = self.store.document(document_id)
        if document is None:
            raise ValueError("Document not found")
        if not recipient_ids:
            raise ValueError("Select at least one recipient")
        cek = crypto.unseal(document["authority_cek_sealed"], f"authority:{document_id}")
        envelopes = []
        for recipient_id in dict.fromkeys(recipient_ids):
            recipient = self.store.recipient(recipient_id)
            if recipient is None or recipient["status"] != "ACTIVE":
                raise ValueError(f"Recipient unavailable: {recipient_id}")
            if self.store.envelope(document_id, recipient_id):
                raise ValueError(f"Recipient already has an envelope: {recipient_id}")
            envelope = crypto.make_envelope(cek, document_id, recipient_id, recipient["kem_public"])
            envelopes.append({"recipient_id": recipient_id, **envelope})
        self.store.add_envelopes(document_id, envelopes)
        self.store.audit("DOCUMENT_DISTRIBUTED", {"document_id": document_id, "recipients": recipient_ids})
        return {"document_id": document_id, "ciphertext_hash": document["ciphertext_hash"],
                "envelope_count": len(envelopes), "recipient_ids": recipient_ids,
                "content_encryption_count": 1}

    def original_pdf(self, document: dict[str, Any]) -> bytes:
        crypto, _ = self.ready()
        cek = crypto.unseal(document["authority_cek_sealed"], f"authority:{document['id']}")
        ciphertext = Path(document["ciphertext_path"]).read_bytes()
        if sha3(ciphertext) != document["ciphertext_hash"]:
            raise RuntimeError("Encrypted document hash invalid")
        pdf = crypto.decrypt_document(cek, unb64(document["nonce"]), ciphertext, document["id"])
        if sha3(pdf) != document["original_hash"]:
            raise RuntimeError("Original document hash invalid")
        return pdf

    def decrypt(self, document_id: str, recipient_id: str) -> dict[str, Any]:
        crypto, ledger = self.ready(watermark=True)
        document = self.store.document(document_id)
        recipient = self.store.recipient(recipient_id)
        envelope = self.store.envelope(document_id, recipient_id)
        if document is None or recipient is None or envelope is None:
            raise ValueError("Document or recipient envelope not found")
        if recipient["status"] != "ACTIVE":
            raise ValueError("Recipient is revoked")
        cek = crypto.open_envelope(envelope, document_id, recipient_id, recipient["kem_private_sealed"])
        ciphertext = Path(document["ciphertext_path"]).read_bytes()
        if sha3(ciphertext) != document["ciphertext_hash"]:
            raise RuntimeError("Encrypted document hash invalid")
        original = crypto.decrypt_document(cek, unb64(document["nonce"]), ciphertext, document_id)
        if sha3(original) != document["original_hash"]:
            raise RuntimeError("Original document hash invalid")
        session_id = str(uuid.uuid4())
        event_id = str(uuid.uuid4())
        random_nonce = os.urandom(16).hex()
        candidate = Candidate(session_id, document_id, random_nonce)
        marked, commitment = mark_pdf(render_locked_pdf(original), candidate, self.watermark_secret)
        marked_hash = sha3(marked)
        created_at = utc_now()
        payload = {"schema_version": 1, "algorithm_suite": SUITE, "content_mode": CONTENT_MODE, "event_id": event_id,
                   "session_id": session_id, "document_id": document_id,
                   "original_document_sha3_256": document["original_hash"],
                   "recipient_id": recipient_id, "recipient_signing_key_fingerprint": recipient["sign_fingerprint"],
                   "created_at_utc": created_at, "random_nonce": random_nonce,
                   "watermark_carrier_version": CARRIER_VERSION, "watermark_commitment": commitment,
                   "marked_pdf_sha3_256": marked_hash}
        signature = crypto.sign_event(payload, recipient_id, recipient["sign_private_sealed"])
        event = {"payload": payload, "signature": signature, "sign_public": recipient["sign_public"]}
        # Stage output locally. It is unavailable to any download route until quorum succeeds.
        fd, staged_path = tempfile.mkstemp(prefix="pending-", suffix=".pdf", dir=self.store.files_dir)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(marked)
            receipt = ledger.append(event)
            final_path = self.store.files_dir / f"{session_id}.pdf"
            os.replace(staged_path, final_path)
        except Exception:
            Path(staged_path).unlink(missing_ok=True)
            raise
        self.store.add_session({"id": session_id, "document_id": document_id, "recipient_id": recipient_id,
                                "event_id": event_id, "created_at": created_at, "marked_path": str(final_path),
                                "marked_hash": marked_hash, "watermark_commitment": commitment},
                               {"id": event_id, "payload": payload, "signature": signature,
                                "sign_public": recipient["sign_public"], "block_height": receipt["height"]})
        self.store.audit("DECRYPTION_COMMITTED", {"event_id": event_id, "session_id": session_id,
                                                  "recipient_id": recipient_id, "block_height": receipt["height"]})
        return {"session_id": session_id, "event_id": event_id, "recipient_id": recipient_id,
                "document_id": document_id, "created_at": created_at, "marked_pdf_sha3_256": marked_hash,
                "watermark_commitment": commitment, "signature_valid": True,
                "ledger": receipt, "download_url": f"/sessions/{session_id}/download",
                "steps": ["ML-KEM-768 DECAPSULATED", "AES-256-GCM VERIFIED", "UNIQUE VISUAL WATERMARK EMBEDDED",
                          "ML-DSA-65 EVENT SIGNED", "LEDGER QUORUM COMMITTED"]}

    def verify_event(self, event_id: str) -> dict[str, Any]:
        crypto, ledger = self.ready()
        found = ledger.find_event(event_id)
        if found is None:
            return {"status": "INVALID", "reason": "Event absent from authoritative ledger"}
        event, block = found
        signature_ok = crypto.verify_event(event["payload"], event["signature"], event["sign_public"])
        ledger_state = ledger.verify()
        return {"status": "VALID" if signature_ok and ledger_state["status"] == "VALID" else "INVALID",
                "signature": "VALID" if signature_ok else "INVALID",
                "ledger": ledger_state["status"], "quorum": ledger_state["quorum"],
                "block_height": block["core"]["height"], "block_hash": block["block_hash"]}

    def analyze(self, suspect: bytes) -> dict[str, Any]:
        self.ready(watermark=True)
        self.validate_pdf(suspect)
        if len(self.store.documents()) > 100 or len(self.store.sessions()) > 1000:
            raise RuntimeError("FORENSIC CAPACITY LIMIT: reduce demo corpus before analysis")
        investigation_id = str(uuid.uuid4())
        suspect_hash = sha3(suspect)
        matches = []
        searched = 0
        for document_summary in self.store.documents():
            document = self.store.document(document_summary["id"])
            sessions = self.store.sessions(document["id"])
            if not sessions:
                continue
            candidates_by_mode: dict[str, list[Candidate]] = {}
            for session in sessions:
                event = self.store.event(session["event_id"])
                if event:
                    mode = event["payload"].get("content_mode", "SEARCHABLE_V1")
                    candidates_by_mode.setdefault(mode, []).append(
                        Candidate(session["id"], document["id"], event["payload"]["random_nonce"]))
            original = self.original_pdf(document)
            searched += 1
            for mode, candidates in candidates_by_mode.items():
                reference = render_locked_pdf(original) if mode == CONTENT_MODE else original
                result = detect_pdf(suspect, reference, candidates, self.watermark_secret)
                if result["status"] == "VALID":
                    matches.append((document, result))
        pipeline = ["FILE RECEIVED", "SHA3-256 CALCULATED", "PAGES RENDERED", "VISUAL CARRIER TESTED"]
        if len(matches) != 1:
            result = {"investigation_id": investigation_id, "status": "INCONCLUSIVE",
                      "reason": "No unique visual watermark match" if not matches else "Multiple document matches",
                      "suspect_sha3_256": suspect_hash, "documents_searched": searched,
                      "pipeline": pipeline, "created_at_utc": utc_now()}
            self.store.add_investigation(investigation_id, suspect_hash, result)
            return result
        document, detection = matches[0]
        session = self.store.session(detection["matched_session_id"])
        found = self.ledger.find_event(session["event_id"])
        if found is None:
            result = {"investigation_id": investigation_id, "status": "INVALID",
                      "reason": "Watermark matched but signed ledger event is missing",
                      "suspect_sha3_256": suspect_hash, "pipeline": pipeline, "created_at_utc": utc_now()}
            self.store.add_investigation(investigation_id, suspect_hash, result)
            return result
        event, block = found
        payload = event["payload"]
        recipient = self.store.recipient(payload["recipient_id"])
        signature_valid = self.crypto.verify_event(payload, event["signature"], event["sign_public"])
        ledger_state = self.ledger.verify()
        expected_commitment = sha3(canonical({"carrier_version": CARRIER_VERSION,
                                              "session_id": payload["session_id"],
                                              "document_id": payload["document_id"],
                                              "nonce": payload["random_nonce"]}))
        commitment_valid = expected_commitment == payload["watermark_commitment"] == session["watermark_commitment"]
        all_valid = signature_valid and commitment_valid and ledger_state["status"] == "VALID"
        result = {"investigation_id": investigation_id,
                  "status": "VERIFIED MATCH" if all_valid else "INVALID",
                  "reason": "Visual carrier and cryptographic evidence agree" if all_valid else "Evidence verification failed",
                  "suspect_sha3_256": suspect_hash, "document_id": document["id"],
                  "document_name": document["filename"], "session_id": session["id"],
                  "event_id": session["event_id"], "recipient_id": recipient["id"],
                  "recipient_name": recipient["name"], "recipient_designation": recipient["designation"],
                  "recipient_key_fingerprint": recipient["sign_fingerprint"],
                  "decrypted_at_utc": payload["created_at_utc"],
                  "watermark": "VALID" if commitment_valid else "INVALID",
                  "watermark_score": detection["confidence"],
                  "watermark_score_label": "Correlation score; not a probability",
                  "ml_dsa_signature": "VALID" if signature_valid else "INVALID",
                  "ledger_chain": ledger_state["status"], "validator_quorum": ledger_state["quorum"],
                  "validator_total": 3, "ledger_block": block["core"]["height"],
                  "block_hash": block["block_hash"], "event_payload": payload,
                  "event_signature": event["signature"], "created_at_utc": utc_now(),
                  "pipeline": pipeline + ["SESSION LOCATED", "ML-DSA-65 VERIFIED", "LEDGER VERIFIED",
                                          "VALIDATOR QUORUM CHECKED", "REPORT CREATED"]}
        self.store.add_investigation(investigation_id, suspect_hash, result)
        self.store.audit("FORENSIC_ANALYSIS", {"investigation_id": investigation_id, "status": result["status"]})
        return result

    def robustness(self, session_id: str) -> list[dict[str, Any]]:
        self.ready(watermark=True)
        session = self.store.session(session_id)
        if session is None:
            raise ValueError("Session not found")
        document = self.store.document(session["document_id"])
        original = self.original_pdf(document)
        source_pdf = original
        event = self.store.event(session["event_id"])
        if event["payload"].get("content_mode") == CONTENT_MODE:
            original = render_locked_pdf(original)
        candidate = Candidate(session_id, document["id"], event["payload"]["random_nonce"])
        marked = Path(session["marked_path"]).read_bytes()
        variants = [("Exact marked PDF", marked), ("PDF re-render", rerender_pdf(marked)),
                    ("Scaled 90% and re-rendered", rerender_pdf(marked, scale=0.9)),
                    ("JPEG quality 85", rerender_pdf(marked, 85)),
                    ("JPEG quality 65", rerender_pdf(marked, 65)),
                    ("Text-only reconstruction (negative control)", text_reconstruction_pdf(source_pdf))]
        results = []
        for name, data in variants:
            result = detect_pdf(data, original, [candidate], self.watermark_secret)
            results.append({"transformation": name, "status": result["status"],
                            "score": result.get("confidence"), "matched_session_id": result.get("matched_session_id")})
        return results

    def status(self) -> dict[str, Any]:
        ledger = self.ledger.verify() if self.ledger else {"status": "UNAVAILABLE", "quorum": 0,
                                                            "total_validators": 3, "height": None,
                                                            "validators": []}
        hosted = os.getenv("SOURCEX_HOSTED") == "1"
        return {"air_gapped_mode": "NOT APPLICABLE" if hosted else "CONFIGURED", "deployment_mode": "HOSTED DEMO" if hosted else "LOCAL OFFLINE",
                "runtime_external_dependencies": 0,
                "egress_test": "UNVERIFIED", "pqc_engine": "READY" if self.crypto else "ERROR",
                "pqc_error": self.pqc_error, "watermark_engine": "READY" if self.crypto and not self.watermark_error else "ERROR",
                "watermark_error": self.watermark_error, "ledger": ledger,
                "database": "READY", "app_version": "0.1.0", "algorithm_suite": SUITE}

    def dashboard(self) -> dict[str, Any]:
        documents = self.store.documents()
        recipients = self.store.recipients()
        sessions = self.store.sessions()
        state = self.status()
        for session in sessions:
            session.pop("marked_path", None)
        return {"counts": {"documents": len(documents), "recipients": len(recipients),
                           "decryptions": len(sessions), "ledger_blocks": (state["ledger"]["height"] or 0) + 1,
                           "investigations": self.store.count_investigations()},
                "recent_documents": documents[:5], "recent_sessions": sessions[:5], "system": state}
