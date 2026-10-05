from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from .crypto import utc_now
from .store import Store

SESSION_HOURS = 8
IDLE_MINUTES = 15
ACCOUNT_FAILURES = 5
SOURCE_FAILURES = 20


class LoginThrottled(Exception):
    """A short local cooldown, not a permanent account lock."""

    retry_after = 300
DEMO_ACCOUNTS = (
    ("sender", "Document Authority", "SENDER", None, "Sender-2026!"),
    ("REC-001", "Major Arjun Rao", "RECIPIENT", "REC-001", "Arjun-2026!"),
    ("REC-002", "Lt. Commander Meera Singh", "RECIPIENT", "REC-002", "Meera-2026!"),
    ("REC-003", "Analyst Vikram Sharma", "RECIPIENT", "REC-003", "Vikram-2026!"),
    ("investigator", "Forensic Investigator", "INVESTIGATOR", None, "Investigator-2026!"),
    ("auditor", "Auditor / Administrator", "AUDITOR", None, "Auditor-2026!"),
)


def password_hash(password: str, salt: bytes | None = None) -> str:
    salt = salt or os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt-v1${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        version, salt, digest = encoded.split("$")
        if version != "scrypt-v1":
            return False
        actual = password_hash(password, bytes.fromhex(salt)).split("$")[2]
        return hmac.compare_digest(actual, digest)
    except (ValueError, TypeError):
        return False


DUMMY_HASH = password_hash("not-a-valid-demo-password", b"\x00" * 16)


class AuthManager:
    def __init__(self, store: Store):
        self.store = store

    def seed_demo_accounts(self) -> list[str]:
        created = []
        for user_id, name, role, recipient_id, password in DEMO_ACCOUNTS:
            if self.store.user(user_id):
                continue
            self.store.add_user({"id": user_id, "display_name": name, "role": role,
                                 "recipient_id": recipient_id, "password_hash": password_hash(password),
                                 "status": "ACTIVE", "created_at": utc_now()})
            created.append(user_id)
        return created

    def create_recipient_account(self, recipient_id: str, name: str, password: str) -> None:
        if len(password) < 10:
            raise ValueError("Recipient password must have at least 10 characters")
        self.store.add_user({"id": recipient_id, "display_name": name, "role": "RECIPIENT",
                             "recipient_id": recipient_id, "password_hash": password_hash(password),
                             "status": "ACTIVE", "created_at": utc_now()})

    def login(self, user_id: str, password: str, source: str = "local") -> tuple[str, dict[str, Any]] | None:
        now = datetime.now(timezone.utc)
        iso = lambda value: value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        account_since = iso(now - timedelta(minutes=5))
        source_since = iso(now - timedelta(minutes=1))
        account_count, source_count = self.store.login_failure_counts(user_id, source, account_since, source_since)
        if account_count >= ACCOUNT_FAILURES or source_count >= SOURCE_FAILURES:
            self.store.audit("LOGIN_THROTTLED", {"user_id": user_id, "source": source})
            raise LoginThrottled()
        user = self.store.user(user_id)
        password_valid = verify_password(password, user["password_hash"] if user else DUMMY_HASH)
        if not user or user["status"] != "ACTIVE" or not password_valid:
            self.store.add_login_failure(user_id, source, iso(now), account_since)
            self.store.audit("LOGIN_FAILED", {"user_id": user_id, "source": source})
            return None
        if user["recipient_id"]:
            recipient = self.store.recipient(user["recipient_id"])
            if not recipient or recipient["status"] != "ACTIVE":
                self.store.add_login_failure(user_id, source, iso(now), account_since)
                return None
        self.store.clear_login_failures(user_id)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(32)
        expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        self.store.add_auth_session({"token_hash": hashlib.sha256(token.encode()).hexdigest(),
                                     "user_id": user_id, "csrf_token": csrf,
                                     "expires_at": expires, "created_at": utc_now()})
        self.store.audit("LOGIN", {"user_id": user_id})
        return token, self.resolve(token)

    def resolve(self, token: str | None) -> dict[str, Any] | None:
        if not token:
            return None
        session = self.store.auth_session(hashlib.sha256(token.encode()).hexdigest())
        now = datetime.now(timezone.utc)
        if not session:
            return None
        last_seen = datetime.fromisoformat(session["last_seen_at"].replace("Z", "+00:00"))
        if (session["expires_at"] <= utc_now() or session["status"] != "ACTIVE"
                or now - last_seen > timedelta(minutes=IDLE_MINUTES)):
            self.store.remove_auth_session(session["token_hash"])
            return None
        if session["recipient_id"]:
            recipient = self.store.recipient(session["recipient_id"])
            if not recipient or recipient["status"] != "ACTIVE":
                return None
        self.store.touch_auth_session(session["token_hash"], utc_now())
        return session

    def logout(self, token: str | None) -> None:
        if token:
            self.store.remove_auth_session(hashlib.sha256(token.encode()).hexdigest())

    @staticmethod
    def public_session(session: dict[str, Any]) -> dict[str, Any]:
        return {key: session[key] for key in ("id", "display_name", "role", "recipient_id", "csrf_token", "expires_at")}
