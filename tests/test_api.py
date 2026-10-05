from __future__ import annotations

import importlib
from pathlib import Path

from fastapi.testclient import TestClient


def test_http_role_bound_demo_journey(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIH_DATA_DIR", str(tmp_path / "http-data"))
    module = importlib.import_module("provenance.app")
    module = importlib.reload(module)

    def login(client: TestClient, user_id: str, password: str) -> dict:
        response = client.post("/auth/login", json={"user_id": user_id, "password": password})
        assert response.status_code == 200, response.text
        assert "httponly" in response.headers["set-cookie"].lower()
        return {"X-CSRF-Token": response.json()["csrf_token"]}

    def logout(client: TestClient, headers: dict) -> None:
        assert client.post("/auth/logout", headers=headers).status_code == 200

    with TestClient(module.app) as client:
        assert client.get("/health").json()["status"] == "READY"
        assert client.get("/documents").status_code == 401
        assert client.get("/auth/me").json() is None
        assert client.post("/auth/login", json={"user_id": "sender", "password": "wrong"}).status_code == 401

        sender = login(client, "sender", "Sender-2026!")
        assert client.get("/auth/me").json()["role"] == "SENDER"
        people = client.get("/recipients").json()
        assert len(people) == 3
        assert all("kem_private_sealed" not in person and "sign_private_sealed" not in person for person in people)
        document = client.get("/documents").json()[0]
        assert client.post(f"/documents/{document['id']}/distribute",
                           json={"recipient_ids": ["REC-001"]}).status_code == 403
        sent = client.post(f"/documents/{document['id']}/distribute", headers=sender,
                           json={"recipient_ids": ["REC-001", "REC-002", "REC-003"]})
        assert sent.status_code == 200 and sent.json()["content_encryption_count"] == 1
        assert client.post("/decrypt", headers=sender,
                           json={"document_id": document["id"], "recipient_id": "REC-002"}).status_code == 403
        logout(client, sender)

        alice = login(client, "REC-001", "Arjun-2026!")
        assert len(client.get("/documents").json()) == 1
        assert len(client.get("/recipients").json()) == 1
        assert client.post("/decrypt", headers=alice,
                           json={"document_id": document["id"], "recipient_id": "REC-002"}).status_code == 403
        first = client.post("/decrypt", headers=alice,
                            json={"document_id": document["id"], "recipient_id": "REC-001"})
        assert first.status_code == 200, first.text
        assert client.get(first.json()["download_url"]).status_code == 200
        assert client.post("/forensics/analyze", headers=alice,
                           files={"file": ("copy.pdf", b"not a pdf", "application/pdf")}).status_code == 403
        logout(client, alice)

        meera = login(client, "REC-002", "Meera-2026!")
        assert client.get(first.json()["download_url"]).status_code == 403
        decrypted = client.post("/decrypt", headers=meera,
                                json={"document_id": document["id"], "recipient_id": "REC-002"})
        assert decrypted.status_code == 200, decrypted.text
        session = decrypted.json()
        pdf = client.get(session["download_url"])
        assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
        logout(client, meera)

        investigator = login(client, "investigator", "Investigator-2026!")
        assert client.get("/documents").json() == []
        assert client.get("/recipients").json() == []
        assert client.get(session["download_url"]).status_code == 403
        assert client.post("/demo/tamper-validator", headers=investigator,
                           json={"validator_id": "validator-2"}).status_code == 403
        investigation = client.post("/forensics/analyze", headers=investigator,
                                    files={"file": ("found.pdf", pdf.content, "application/pdf")})
        assert investigation.status_code == 200, investigation.text
        evidence = investigation.json()
        assert evidence["status"] == "VERIFIED MATCH" and evidence["recipient_id"] == "REC-002"
        assert client.post(f"/events/{session['event_id']}/verify", headers=investigator).json()["signature"] == "VALID"
        assert client.get(f"/forensics/{evidence['investigation_id']}/report.json").status_code == 200
        assert client.get(f"/forensics/{evidence['investigation_id']}/report.html").status_code == 200
        logout(client, investigator)

        auditor = login(client, "auditor", "Auditor-2026!")
        assert client.post("/ledger/verify", headers=auditor).json()["quorum"] == 3
        separate = client.post("/ledger/independent-verify", headers=auditor)
        assert separate.status_code == 200 and separate.json()["quorum"] == 3
        assert separate.json()["verifier"] == "separate-read-only-process"
        tampered = client.post("/demo/tamper-validator", headers=auditor,
                               json={"validator_id": "validator-2"}).json()
        assert tampered["quorum"] == 2 and tampered["validators"][1]["status"] == "DIVERGED"
        separate = client.post("/ledger/independent-verify", headers=auditor).json()
        assert separate["quorum"] == 2 and separate["validators"][1]["status"] == "DIVERGED"
        assert client.post("/demo/restore-validator", headers=auditor,
                           json={"validator_id": "validator-2"}).json()["quorum"] == 3


def test_auth_throttle_idle_expiry_and_request_limits(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SIH_DATA_DIR", str(tmp_path / "security-data"))
    module = importlib.import_module("provenance.app")
    module = importlib.reload(module)
    with TestClient(module.app) as client:
        for _ in range(5):
            assert client.post("/auth/login", json={"user_id": "sender", "password": "wrong"}).status_code == 401
        throttled = client.post("/auth/login", json={"user_id": "sender", "password": "Sender-2026!"})
        assert throttled.status_code == 429 and "Retry-After" in throttled.headers
        assert client.post("/auth/login", headers={"Origin": "https://untrusted.example"},
                           json={"user_id": "REC-002", "password": "Meera-2026!"}).status_code == 403
        login = client.post("/auth/login", json={"user_id": "REC-002", "password": "Meera-2026!"})
        assert login.status_code == 200
        assert login.headers["cache-control"] == "no-store"
        assert login.headers["x-content-type-options"] == "nosniff"
        with module.system.store.connect() as db:
            db.execute("UPDATE auth_sessions SET last_seen_at='2020-01-01T00:00:00.000Z' WHERE user_id='REC-002'")
        assert client.get("/documents").status_code == 401
        assert client.post("/documents", headers={"Content-Length": str(17 * 1024 * 1024)},
                           files={"file": ("test.pdf", b"%PDF-", "application/pdf")}).status_code == 413
        investigator = client.post("/auth/login", json={"user_id": "investigator",
                                                         "password": "Investigator-2026!"})
        assert investigator.status_code == 200
        csrf = {"X-CSRF-Token": investigator.json()["csrf_token"]}
        for _ in range(5):
            assert client.post("/forensics/analyze", headers=csrf,
                               files={"file": ("bad.pdf", b"not-a-pdf", "application/pdf")}).status_code == 400
        assert client.post("/forensics/analyze", headers=csrf,
                           files={"file": ("bad.pdf", b"not-a-pdf", "application/pdf")}).status_code == 429
        auditor = client.post("/auth/login", json={"user_id": "auditor", "password": "Auditor-2026!"})
        assert auditor.status_code == 200
        with module.system.store.connect() as db:
            db.execute("UPDATE auth_sessions SET expires_at='2020-01-01T00:00:00.000Z' WHERE user_id='auditor'")
        assert client.get("/system/status").status_code == 401
