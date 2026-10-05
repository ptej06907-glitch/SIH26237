"""Read-only ledger verifier using public keys only.

It does not import Ledger, Store, CryptoEngine, or the local master secret. The API
invokes this module in a separate Python process for an independent code path.
All inputs remain on one host, so this is not independent organizational custody.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.mldsa import MLDSA65PublicKey

from .crypto import EVENT_CONTEXT, VOTE_CONTEXT, canonical, sha3, unb64

VALIDATORS = ("validator-1", "validator-2", "validator-3")
GENESIS_TIME = "2026-01-01T00:00:00.000Z"


def _read_db(path: Path, query: str) -> list[tuple]:
    if not path.is_file():
        raise ValueError(f"Missing database: {path.name}")
    with sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=5) as db:
        return db.execute(query).fetchall()


def _signature(public: str, signature: str, message: dict, context: bytes) -> bool:
    try:
        MLDSA65PublicKey.from_public_bytes(unb64(public)).verify(
            unb64(signature), canonical(message), context)
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


def verify_public(data_dir: Path) -> dict:
    """Recompute chains and approvals without reading any private key material."""
    validators_dir = data_dir / "validators"
    try:
        public = json.loads((validators_dir / "validator_public.json").read_text(encoding="utf-8"))
        if set(public) != set(VALIDATORS):
            raise ValueError("Validator public registry incomplete")
        recipients = {row[0]: row[1] for row in _read_db(
            data_dir / "app.sqlite", "SELECT id,sign_public FROM recipients")}
    except (OSError, ValueError, sqlite3.Error) as exc:
        return {"status": "INVALID", "quorum": 0, "validators": [], "reason": str(exc),
                "verifier": "separate-read-only-process"}

    genesis_core = {"version": 1, "height": 0, "previous_block_hash": "0" * 64,
                    "created_at_utc": GENESIS_TIME, "event_hashes": [],
                    "event_root": sha3(canonical({"event_hashes": []})), "proposer_id": "GENESIS"}
    nodes = []
    for validator in VALIDATORS:
        try:
            rows = _read_db(validators_dir / validator / "ledger.sqlite",
                            "SELECT height,body_json FROM blocks ORDER BY height")
            if not rows:
                raise ValueError("Missing genesis")
            previous = "0" * 64
            for index, (stored_height, encoded) in enumerate(rows):
                block = json.loads(encoded)
                core = block["core"]
                if stored_height != index or core["height"] != index or core["previous_block_hash"] != previous:
                    raise ValueError(f"Broken link at height {index}")
                if index == 0 and (core != genesis_core or block["events"]):
                    raise ValueError("Invalid genesis")
                block_hash = sha3(canonical(core))
                if block["block_hash"] != block_hash:
                    raise ValueError(f"Block hash mismatch at height {index}")
                event_hashes = [sha3(canonical(event)) for event in block["events"]]
                if core["event_hashes"] != event_hashes or core["event_root"] != sha3(canonical({"event_hashes": event_hashes})):
                    raise ValueError(f"Event root mismatch at height {index}")
                for event in block["events"]:
                    payload = event["payload"]
                    sign_public = event["sign_public"]
                    if (sha3(unb64(sign_public)) != payload["recipient_signing_key_fingerprint"]
                            or recipients.get(payload["recipient_id"]) != sign_public
                            or not _signature(sign_public, event["signature"], payload, EVENT_CONTEXT)):
                        raise ValueError(f"Recipient signature invalid at height {index}")
                approved = set()
                for approval in block["validator_approvals"]:
                    vote = approval["payload"]
                    voter = vote["validator_id"]
                    if voter not in public or voter in approved or vote != {
                        "version": 1, "validator_id": voter, "height": index,
                        "block_hash": block_hash, "decision": "APPROVE"
                    } or not _signature(public[voter], approval["signature"], vote, VOTE_CONTEXT):
                        raise ValueError(f"Validator approval invalid at height {index}")
                    approved.add(voter)
                if len(approved) < 2:
                    raise ValueError(f"Quorum missing at height {index}")
                previous = block_hash
            nodes.append({"validator_id": validator, "status": "HEALTHY",
                          "height": len(rows) - 1, "head_hash": previous})
        except (OSError, ValueError, KeyError, IndexError, TypeError, sqlite3.Error) as exc:
            nodes.append({"validator_id": validator, "status": "DIVERGED",
                          "height": None, "head_hash": None, "reason": str(exc)})
    groups = Counter((node["height"], node["head_hash"]) for node in nodes
                     if node["status"] == "HEALTHY")
    (height, head_hash), quorum = max(groups.items(), key=lambda item: (item[1], item[0][0])) if groups else ((None, None), 0)
    for node in nodes:
        if node["status"] == "HEALTHY" and (node["height"], node["head_hash"]) != (height, head_hash):
            node["status"] = "DIVERGED"
            node["reason"] = "Non-authoritative chain head"
    return {"status": "VALID" if quorum >= 2 else "INVALID", "quorum": quorum,
            "height": height, "head_hash": head_hash, "validators": nodes,
            "verifier": "separate-read-only-process",
            "validator_public_registry_sha3_256": sha3(canonical(public))}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify_public(args.data_dir.resolve()), sort_keys=True))


if __name__ == "__main__":
    main()
