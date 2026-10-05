from pathlib import Path
import socket
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
from provenance.service import Prototype  # noqa: E402


def main() -> None:
    # Fail any accidental non-loopback socket connection during this workflow.
    real_connect = socket.socket.connect

    def loopback_only(sock, address):
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"Outbound network blocked by demo check: {address[0]}")
        return real_connect(sock, address)

    socket.socket.connect = loopback_only
    try:
        with tempfile.TemporaryDirectory(prefix="sih26237-check-") as temp:
            import os
            os.environ["SIH_DATA_DIR"] = str(Path(temp) / "data")
            system = Prototype(ROOT)
            assert system.status()["pqc_engine"] == "READY"
            assert system.status()["watermark_engine"] == "READY"
            system.seed_demo()
            document = system.store.documents()[0]
            distributed = system.distribute(document["id"], ["REC-001", "REC-002", "REC-003"])
            assert distributed["content_encryption_count"] == 1
            session = system.decrypt(document["id"], "REC-002")
            pdf = Path(system.store.session(session["session_id"])["marked_path"]).read_bytes()
            result = system.analyze(pdf)
            assert result["status"] == "VERIFIED MATCH" and result["recipient_id"] == "REC-002"
            assert result["ml_dsa_signature"] == "VALID" and result["validator_quorum"] == 3
            system.ledger.tamper("validator-2")
            state = system.ledger.verify()
            assert state["status"] == "VALID" and state["quorum"] == 2
            system.ledger.restore("validator-2")
            assert system.ledger.verify()["quorum"] == 3
            print("PASS: encrypt once -> ML-KEM envelope -> decrypt -> watermark -> ML-DSA -> 3/3 ledger -> forensic attribution")
            print("PASS: single-validator corruption rejected; authoritative quorum remains 2/3; restoration returns 3/3")
            print("PASS: no non-loopback socket connection attempted by this backend workflow")
    finally:
        socket.socket.connect = real_connect


if __name__ == "__main__":
    main()
