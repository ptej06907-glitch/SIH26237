from __future__ import annotations

import base64
import hashlib
import json
import os
import unicodedata
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.mlkem import (
    MLKEM768PrivateKey,
    MLKEM768PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.mldsa import (
    MLDSA65PrivateKey,
    MLDSA65PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

SUITE = "ML-KEM-768+ML-DSA-65+AES-256-GCM+SHA3-256/v1"
EVENT_CONTEXT = b"SIH26237-DECRYPT-EVENT-v1"
VOTE_CONTEXT = b"SIH26237-VALIDATOR-VOTE-v1"


def b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def unb64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def sha3(value: bytes) -> str:
    return hashlib.sha3_256(value).hexdigest()


def _normalized(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalized(item) for item in value]
    if isinstance(value, dict):
        return {_normalized(str(key)): _normalized(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int)):
        return value
    raise TypeError(f"Unsupported canonical value: {type(value).__name__}")


def canonical(value: dict[str, Any]) -> bytes:
    return json.dumps(
        _normalized(value), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")


def utc_now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class CryptoEngine:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        master_path = data_dir / "master.key"
        if not master_path.exists():
            try:
                fd = os.open(master_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "wb") as handle:
                    handle.write(os.urandom(32))
            except FileExistsError:
                pass
        self.master = master_path.read_bytes()
        if len(self.master) != 32:
            raise RuntimeError("PQC ENGINE UNAVAILABLE: invalid local key store")
        self.self_test()

    @staticmethod
    def self_test() -> None:
        try:
            kem = MLKEM768PrivateKey.generate()
            secret, ciphertext = kem.public_key().encapsulate()
            if kem.decapsulate(ciphertext) != secret:
                raise RuntimeError("ML-KEM round trip failed")
            signer = MLDSA65PrivateKey.generate()
            signature = signer.sign(b"SIH26237 startup test", EVENT_CONTEXT)
            signer.public_key().verify(signature, b"SIH26237 startup test", EVENT_CONTEXT)
            key = AESGCM.generate_key(bit_length=256)
            nonce = os.urandom(12)
            if AESGCM(key).decrypt(nonce, AESGCM(key).encrypt(nonce, b"test", b"aad"), b"aad") != b"test":
                raise RuntimeError("AES-GCM round trip failed")
        except Exception as exc:
            raise RuntimeError(f"PQC ENGINE UNAVAILABLE: {exc}") from exc

    def seal(self, plaintext: bytes, purpose: str) -> str:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self.master).encrypt(nonce, plaintext, purpose.encode())
        return b64(nonce + ciphertext)

    def unseal(self, encoded: str, purpose: str) -> bytes:
        value = unb64(encoded)
        return AESGCM(self.master).decrypt(value[:12], value[12:], purpose.encode())

    def make_identity(self, identity_id: str) -> dict[str, str]:
        kem = MLKEM768PrivateKey.generate()
        signer = MLDSA65PrivateKey.generate()
        kem_public = kem.public_key().public_bytes_raw()
        sign_public = signer.public_key().public_bytes_raw()
        return {
            "kem_public": b64(kem_public),
            "kem_private_sealed": self.seal(kem.private_bytes_raw(), f"kem:{identity_id}"),
            "sign_public": b64(sign_public),
            "sign_private_sealed": self.seal(signer.private_bytes_raw(), f"sign:{identity_id}"),
            "kem_fingerprint": sha3(kem_public),
            "sign_fingerprint": sha3(sign_public),
        }

    @staticmethod
    def encrypt_document(pdf: bytes, document_id: str) -> tuple[bytes, bytes, bytes]:
        cek = AESGCM.generate_key(bit_length=256)
        nonce = os.urandom(12)
        ciphertext = AESGCM(cek).encrypt(nonce, pdf, f"document:{document_id}:v1".encode())
        return cek, nonce, ciphertext

    @staticmethod
    def decrypt_document(cek: bytes, nonce: bytes, ciphertext: bytes, document_id: str) -> bytes:
        return AESGCM(cek).decrypt(nonce, ciphertext, f"document:{document_id}:v1".encode())

    @staticmethod
    def _wrap_key(shared: bytes, document_id: str, recipient_id: str) -> bytes:
        return HKDF(
            algorithm=hashes.SHA3_256(), length=32,
            salt=bytes.fromhex(sha3(document_id.encode())),
            info=f"SIH26237-CEK-wrap-v1:{document_id}:{recipient_id}".encode(),
        ).derive(shared)

    def make_envelope(self, cek: bytes, document_id: str, recipient_id: str, kem_public_b64: str) -> dict[str, str]:
        public = MLKEM768PublicKey.from_public_bytes(unb64(kem_public_b64))
        shared, kem_ciphertext = public.encapsulate()
        wrap_key = self._wrap_key(shared, document_id, recipient_id)
        nonce = os.urandom(12)
        aad = f"envelope:{document_id}:{recipient_id}:v1".encode()
        wrapped = AESGCM(wrap_key).encrypt(nonce, cek, aad)
        return {"kem_ciphertext": b64(kem_ciphertext), "wrap_nonce": b64(nonce), "wrapped_cek": b64(wrapped)}

    def open_envelope(self, envelope: dict[str, str], document_id: str, recipient_id: str, sealed_private: str) -> bytes:
        seed = self.unseal(sealed_private, f"kem:{recipient_id}")
        private = MLKEM768PrivateKey.from_seed_bytes(seed)
        shared = private.decapsulate(unb64(envelope["kem_ciphertext"]))
        wrap_key = self._wrap_key(shared, document_id, recipient_id)
        aad = f"envelope:{document_id}:{recipient_id}:v1".encode()
        return AESGCM(wrap_key).decrypt(unb64(envelope["wrap_nonce"]), unb64(envelope["wrapped_cek"]), aad)

    def sign_event(self, payload: dict[str, Any], identity_id: str, sealed_private: str) -> str:
        seed = self.unseal(sealed_private, f"sign:{identity_id}")
        return b64(MLDSA65PrivateKey.from_seed_bytes(seed).sign(canonical(payload), EVENT_CONTEXT))

    @staticmethod
    def verify_event(payload: dict[str, Any], signature_b64: str, public_b64: str) -> bool:
        try:
            MLDSA65PublicKey.from_public_bytes(unb64(public_b64)).verify(
                unb64(signature_b64), canonical(payload), EVENT_CONTEXT,
            )
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False

    def sign_vote(self, vote: dict[str, Any], validator_id: str, sealed_private: str) -> str:
        seed = self.unseal(sealed_private, f"sign:{validator_id}")
        return b64(MLDSA65PrivateKey.from_seed_bytes(seed).sign(canonical(vote), VOTE_CONTEXT))

    @staticmethod
    def verify_vote(vote: dict[str, Any], signature_b64: str, public_b64: str) -> bool:
        try:
            MLDSA65PublicKey.from_public_bytes(unb64(public_b64)).verify(
                unb64(signature_b64), canonical(vote), VOTE_CONTEXT,
            )
            return True
        except (InvalidSignature, ValueError, TypeError):
            return False
