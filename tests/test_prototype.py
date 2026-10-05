from __future__ import annotations

import copy
import os
from pathlib import Path

import pymupdf
import pytest
from cryptography.exceptions import InvalidTag

from provenance.crypto import CryptoEngine, canonical, sha3, unb64
from provenance.service import Prototype
from provenance.watermark import Candidate, detect_pdf, mark_pdf, rerender_pdf
from provenance.independent_verify import verify_public
from scripts.benchmark_watermark import raster_transform, text_only_copy


@pytest.fixture
def prototype(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Prototype:
    monkeypatch.setenv("SIH_DATA_DIR", str(tmp_path / "data"))
    result = Prototype(tmp_path)
    assert result.status()["pqc_engine"] == "READY"
    assert result.status()["watermark_engine"] == "READY"
    result.seed_demo()
    return result


def test_real_post_quantum_keys_envelope_and_wrong_recipient(prototype: Prototype) -> None:
    crypto = prototype.crypto
    alice = prototype.store.recipient("REC-001")
    bob = prototype.store.recipient("REC-002")
    cek = os.urandom(32)
    envelope = crypto.make_envelope(cek, "document-test", alice["id"], alice["kem_public"])
    assert crypto.open_envelope(envelope, "document-test", alice["id"], alice["kem_private_sealed"]) == cek
    with pytest.raises((InvalidTag, ValueError)):
        crypto.open_envelope(envelope, "document-test", alice["id"], bob["kem_private_sealed"])
    assert len(unb64(alice["kem_public"])) > 1000
    assert len(unb64(alice["sign_public"])) > 1000


def test_aes_integrity_and_canonical_signature(prototype: Prototype) -> None:
    crypto = prototype.crypto
    recipient = prototype.store.recipient("REC-002")
    data = b"sensitive synthetic PDF bytes"
    cek, nonce, ciphertext = crypto.encrypt_document(data, "doc-1")
    assert crypto.decrypt_document(cek, nonce, ciphertext, "doc-1") == data
    with pytest.raises(InvalidTag):
        crypto.decrypt_document(cek, nonce, ciphertext[:-1] + bytes([ciphertext[-1] ^ 1]), "doc-1")
    with pytest.raises(InvalidTag):
        crypto.decrypt_document(cek, nonce, ciphertext, "doc-2")
    payload = {"schema_version": 1, "recipient_id": recipient["id"], "event_id": "x"}
    signature = crypto.sign_event(payload, recipient["id"], recipient["sign_private_sealed"])
    assert crypto.verify_event(payload, signature, recipient["sign_public"])
    assert not crypto.verify_event({**payload, "recipient_id": "REC-001"}, signature, recipient["sign_public"])
    assert not crypto.verify_event(payload, signature, prototype.store.recipient("REC-001")["sign_public"])
    assert canonical({"b": 2, "a": 1}) == canonical({"a": 1, "b": 2})


def test_watermark_is_rendered_not_metadata_and_unique(prototype: Prototype) -> None:
    original = prototype._sample_pdf()
    secret = prototype.watermark_secret
    one = Candidate("session-1", "doc-1", "nonce-1")
    two = Candidate("session-2", "doc-1", "nonce-2")
    marked_one, commitment_one = mark_pdf(original, one, secret)
    marked_two, commitment_two = mark_pdf(original, two, secret)
    assert marked_one != marked_two
    assert commitment_one != commitment_two
    assert detect_pdf(marked_one, original, [one, two], secret)["matched_session_id"] == one.session_id
    assert detect_pdf(marked_two, original, [one, two], secret)["matched_session_id"] == two.session_id
    document = pymupdf.open(stream=marked_one, filetype="pdf")
    document.set_metadata({})
    metadata_stripped = document.tobytes(garbage=4, deflate=True)
    document.close()
    assert detect_pdf(metadata_stripped, original, [one, two], secret)["status"] == "VALID"
    assert detect_pdf(original, original, [one, two], secret)["status"] == "INCONCLUSIVE"


def test_selected_digital_transformations(prototype: Prototype) -> None:
    original = prototype._sample_pdf()
    candidate = Candidate("session-jpeg", "doc-1", "nonce-jpeg")
    marked, _ = mark_pdf(original, candidate, prototype.watermark_secret)
    for transformed in (rerender_pdf(marked), rerender_pdf(marked, scale=0.9),
                        rerender_pdf(marked, 85), rerender_pdf(marked, 65),
                        raster_transform(marked, shift=2), raster_transform(marked, rotation=1)):
        detected = detect_pdf(transformed, original, [candidate], prototype.watermark_secret)
        assert detected["status"] == "VALID", detected
    assert detect_pdf(text_only_copy(marked), original, [candidate],
                      prototype.watermark_secret)["status"] == "INCONCLUSIVE"


def test_end_to_end_attribution_tamper_and_restore(prototype: Prototype) -> None:
    document = prototype.store.documents()[0]
    distributed = prototype.distribute(document["id"], ["REC-001", "REC-002", "REC-003"])
    assert distributed["content_encryption_count"] == 1
    assert distributed["envelope_count"] == 3
    assert len({prototype.store.envelope(document["id"], r)["kem_ciphertext"] for r in distributed["recipient_ids"]}) == 3
    first = prototype.decrypt(document["id"], "REC-002")
    second = prototype.decrypt(document["id"], "REC-002")
    assert first["session_id"] != second["session_id"]
    assert first["marked_pdf_sha3_256"] != second["marked_pdf_sha3_256"]
    assert prototype.verify_event(first["event_id"])["status"] == "VALID"
    assert prototype.ledger.verify()["quorum"] == 3
    assert prototype.ledger.authoritative_blocks()[2]["core"]["previous_block_hash"] == first["ledger"]["block_hash"]
    marked = Path(prototype.store.session(first["session_id"])["marked_path"]).read_bytes()
    issued_pdf = pymupdf.open(stream=marked, filetype="pdf")
    assert not any(page.get_text().strip() for page in issued_pdf)
    issued_pdf.close()
    forensic = prototype.analyze(marked)
    assert forensic["status"] == "VERIFIED MATCH"
    assert forensic["recipient_id"] == "REC-002"
    assert forensic["ml_dsa_signature"] == "VALID"
    assert forensic["ledger_chain"] == "VALID"
    assert forensic["validator_quorum"] == 3
    assert prototype.analyze(prototype.original_pdf(prototype.store.document(document["id"])))["status"] == "INCONCLUSIVE"
    prototype.ledger.tamper("validator-2")
    tampered = prototype.ledger.verify()
    assert tampered["status"] == "VALID"
    assert tampered["quorum"] == 2
    assert [v["status"] for v in tampered["validators"]] == ["HEALTHY", "DIVERGED", "HEALTHY"]
    separately_checked = verify_public(prototype.data_dir)
    assert separately_checked["quorum"] == 2
    assert separately_checked["validators"][1]["status"] == "DIVERGED"
    assert prototype.analyze(marked)["status"] == "VERIFIED MATCH"
    prototype.ledger.restore("validator-2")
    assert prototype.ledger.verify()["quorum"] == 3
    independent = verify_public(prototype.data_dir)
    assert independent["status"] == "VALID" and independent["quorum"] == 3


def test_ledger_rejects_event_and_block_corruption(prototype: Prototype) -> None:
    document = prototype.store.documents()[0]
    prototype.distribute(document["id"], ["REC-002"])
    result = prototype.decrypt(document["id"], "REC-002")
    event, _ = prototype.ledger.find_event(result["event_id"])
    changed = copy.deepcopy(event)
    changed["payload"]["recipient_id"] = "REC-001"
    assert sha3(canonical(changed)) != sha3(canonical(event))
    assert not prototype.crypto.verify_event(changed["payload"], changed["signature"], changed["sign_public"])
    prototype.ledger.tamper("validator-1")
    prototype.ledger.tamper("validator-2")
    state = prototype.ledger.verify()
    assert state["status"] == "INVALID"
    assert state["quorum"] == 1
    with pytest.raises(RuntimeError, match="QUORUM"):
        prototype.ledger.authoritative_blocks()
