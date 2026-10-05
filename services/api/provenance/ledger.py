from __future__ import annotations

import json
import sqlite3
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .crypto import CryptoEngine, b64, canonical, sha3, unb64, utc_now
from .store import Store

VALIDATORS = ("validator-1", "validator-2", "validator-3")
GENESIS_TIME = "2026-01-01T00:00:00.000Z"


class Ledger:
    """Three signed logical validators with physically separate SQLite stores.

    A single host still controls all keys; this is explicitly a demo trust model.
    """

    def __init__(self, data_dir: Path, crypto: CryptoEngine, store: Store):
        self.path = data_dir / "validators"
        self.path.mkdir(parents=True, exist_ok=True)
        self.crypto = crypto
        self.store = store
        trust_path = self.path / "validator_trust.json"
        if trust_path.exists():
            self.identities = json.loads(trust_path.read_text(encoding="utf-8"))
        else:
            self.identities = {validator: crypto.make_identity(validator) for validator in VALIDATORS}
            trust_path.write_bytes(canonical(self.identities))
        public_path = self.path / "validator_public.json"
        if not public_path.exists():
            public_path.write_bytes(canonical({validator: self.identities[validator]["sign_public"]
                                               for validator in VALIDATORS}))
        for validator in VALIDATORS:
            with self._connect(validator) as db:
                db.execute("CREATE TABLE IF NOT EXISTS blocks(height INTEGER PRIMARY KEY, body_json TEXT NOT NULL)")
                count = db.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]
                if count == 0:
                    genesis = self._genesis()
                    db.execute("INSERT INTO blocks(height,body_json) VALUES(0,?)", (canonical(genesis).decode(),))

    @contextmanager
    def _connect(self, validator: str) -> Iterator[sqlite3.Connection]:
        if validator not in VALIDATORS:
            raise ValueError("Unknown validator")
        db = sqlite3.connect(self.path / validator / "ledger.sqlite", timeout=10) if (self.path / validator).exists() else None
        if db is None:
            (self.path / validator).mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(self.path / validator / "ledger.sqlite", timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _vote(self, validator: str, height: int, block_hash: str) -> dict[str, Any]:
        vote = {"version": 1, "validator_id": validator, "height": height,
                "block_hash": block_hash, "decision": "APPROVE"}
        signature = self.crypto.sign_vote(vote, validator, self.identities[validator]["sign_private_sealed"])
        return {"payload": vote, "signature": signature}

    def _genesis(self) -> dict[str, Any]:
        core = {"version": 1, "height": 0, "previous_block_hash": "0" * 64,
                "created_at_utc": GENESIS_TIME, "event_hashes": [],
                "event_root": sha3(canonical({"event_hashes": []})), "proposer_id": "GENESIS"}
        block_hash = sha3(canonical(core))
        return {"core": core, "block_hash": block_hash, "events": [],
                "validator_approvals": [self._vote(v, 0, block_hash) for v in VALIDATORS]}

    def _read(self, validator: str) -> list[dict[str, Any]]:
        with self._connect(validator) as db:
            return [json.loads(row[0]) for row in db.execute("SELECT body_json FROM blocks ORDER BY height")]

    def _verify_chain(self, validator: str) -> dict[str, Any]:
        try:
            blocks = self._read(validator)
            if not blocks:
                raise ValueError("Missing genesis")
            previous = "0" * 64
            for index, block in enumerate(blocks):
                core = block["core"]
                if core["height"] != index or core["previous_block_hash"] != previous:
                    raise ValueError(f"Broken previous hash at block {index}")
                expected_hash = sha3(canonical(core))
                if block["block_hash"] != expected_hash:
                    raise ValueError(f"Block hash mismatch at block {index}")
                event_hashes = [sha3(canonical(event)) for event in block["events"]]
                if event_hashes != core["event_hashes"]:
                    raise ValueError(f"Event hash mismatch at block {index}")
                if sha3(canonical({"event_hashes": event_hashes})) != core["event_root"]:
                    raise ValueError(f"Event root mismatch at block {index}")
                if index == 0 and core != self._genesis()["core"]:
                    raise ValueError("Invalid genesis")
                for event in block["events"]:
                    payload = event["payload"]
                    public = event["sign_public"]
                    if sha3(unb64(public)) != payload["recipient_signing_key_fingerprint"]:
                        raise ValueError(f"Recipient key fingerprint mismatch at block {index}")
                    recipient = self.store.recipient(payload["recipient_id"])
                    if recipient is None or recipient["sign_public"] != public:
                        raise ValueError(f"Unknown recipient signing key at block {index}")
                    if not self.crypto.verify_event(payload, event["signature"], public):
                        raise ValueError(f"Invalid recipient signature at block {index}")
                approvals = block["validator_approvals"]
                approved = set()
                for approval in approvals:
                    vote = approval["payload"]
                    validator_id = vote["validator_id"]
                    if validator_id not in VALIDATORS or validator_id in approved:
                        raise ValueError(f"Invalid validator set at block {index}")
                    if vote["block_hash"] != expected_hash or vote["height"] != index or vote["decision"] != "APPROVE":
                        raise ValueError(f"Invalid validator vote at block {index}")
                    public_key = self.identities[validator_id]["sign_public"]
                    if not self.crypto.verify_vote(vote, approval["signature"], public_key):
                        raise ValueError(f"Invalid validator signature at block {index}")
                    approved.add(validator_id)
                if len(approved) < 2:
                    raise ValueError(f"Quorum missing at block {index}")
                previous = expected_hash
            return {"validator_id": validator, "status": "HEALTHY", "height": len(blocks) - 1,
                    "head_hash": previous, "reason": None}
        except Exception as exc:
            return {"validator_id": validator, "status": "DIVERGED", "height": None,
                    "head_hash": None, "reason": str(exc)}

    def verify(self) -> dict[str, Any]:
        nodes = [self._verify_chain(v) for v in VALIDATORS]
        groups = Counter((node["height"], node["head_hash"]) for node in nodes if node["status"] == "HEALTHY")
        if groups:
            (height, head_hash), quorum = max(groups.items(), key=lambda item: (item[1], item[0][0]))
        else:
            height, head_hash, quorum = None, None, 0
        for node in nodes:
            if node["status"] == "HEALTHY" and (node["height"], node["head_hash"]) != (height, head_hash):
                node["status"] = "DIVERGED"
                node["reason"] = "Valid but non-authoritative chain head"
        return {"status": "VALID" if quorum >= 2 else "INVALID",
                "quorum": quorum, "total_validators": 3, "height": height,
                "head_hash": head_hash, "replicas_agree": quorum == 3, "validators": nodes,
                "genesis_valid": all(node["status"] == "HEALTHY" for node in nodes if node["height"] == 0) if quorum else False}

    def authoritative_blocks(self) -> list[dict[str, Any]]:
        status = self.verify()
        if status["status"] != "VALID":
            raise RuntimeError("QUORUM NOT ESTABLISHED")
        chosen = next(node["validator_id"] for node in status["validators"]
                      if node["status"] == "HEALTHY" and node["head_hash"] == status["head_hash"])
        return self._read(chosen)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        status = self.verify()
        if status["status"] != "VALID":
            raise RuntimeError("QUORUM NOT ESTABLISHED")
        height = status["height"] + 1
        event_hash = sha3(canonical(event))
        core = {"version": 1, "height": height, "previous_block_hash": status["head_hash"],
                "created_at_utc": utc_now(), "event_hashes": [event_hash],
                "event_root": sha3(canonical({"event_hashes": [event_hash]})),
                "proposer_id": "local-coordinator"}
        block_hash = sha3(canonical(core))
        eligible = [node["validator_id"] for node in status["validators"]
                    if node["status"] == "HEALTHY" and node["head_hash"] == status["head_hash"]]
        votes = [self._vote(validator, height, block_hash) for validator in eligible]
        if len(votes) < 2:
            raise RuntimeError("QUORUM NOT ESTABLISHED")
        block = {"core": core, "block_hash": block_hash, "events": [event], "validator_approvals": votes}
        encoded = canonical(block).decode()
        committed = []
        for validator in eligible:
            with self._connect(validator) as db:
                head = db.execute("SELECT height,body_json FROM blocks ORDER BY height DESC LIMIT 1").fetchone()
                if head["height"] != height - 1 or json.loads(head["body_json"])["block_hash"] != status["head_hash"]:
                    continue
                db.execute("INSERT INTO blocks(height,body_json) VALUES(?,?)", (height, encoded))
                committed.append(validator)
        if len(committed) < 2:
            raise RuntimeError("QUORUM NOT ESTABLISHED: block not persisted")
        return {"height": height, "block_hash": block_hash, "quorum": len(committed),
                "validators": committed}

    def find_event(self, event_id: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        for block in self.authoritative_blocks():
            for event in block["events"]:
                if event["payload"]["event_id"] == event_id:
                    return event, block
        return None

    def tamper(self, validator: str) -> None:
        if validator not in VALIDATORS:
            raise ValueError("Unknown validator")
        with self._connect(validator) as db:
            row = db.execute("SELECT height,body_json FROM blocks WHERE height>0 ORDER BY height DESC LIMIT 1").fetchone()
            if row is None:
                raise ValueError("No decryption block exists to tamper")
            block = json.loads(row["body_json"])
            block["events"][0]["payload"]["recipient_id"] = "REC-TAMPERED"
            db.execute("UPDATE blocks SET body_json=? WHERE height=?", (canonical(block).decode(), row["height"]))

    def restore(self, validator: str) -> None:
        if validator not in VALIDATORS:
            raise ValueError("Unknown validator")
        blocks = self.authoritative_blocks()
        with self._connect(validator) as db:
            db.execute("DELETE FROM blocks")
            db.executemany("INSERT INTO blocks(height,body_json) VALUES(?,?)",
                           [(block["core"]["height"], canonical(block).decode()) for block in blocks])
