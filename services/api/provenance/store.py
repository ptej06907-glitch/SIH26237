from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .crypto import canonical, utc_now


class Store:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.files_dir = data_dir / "files"
        self.files_dir.mkdir(parents=True, exist_ok=True)
        self.path = data_dir / "app.sqlite"
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS recipients (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, designation TEXT NOT NULL,
              status TEXT NOT NULL, kem_public TEXT NOT NULL, kem_private_sealed TEXT NOT NULL,
              sign_public TEXT NOT NULL, sign_private_sealed TEXT NOT NULL,
              kem_fingerprint TEXT NOT NULL, sign_fingerprint TEXT NOT NULL,
              created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, filename TEXT NOT NULL, classification TEXT NOT NULL,
              uploaded_by TEXT NOT NULL, created_at TEXT NOT NULL,
              original_hash TEXT NOT NULL, ciphertext_hash TEXT NOT NULL,
              nonce TEXT NOT NULL, ciphertext_path TEXT NOT NULL,
              authority_cek_sealed TEXT NOT NULL, page_count INTEGER NOT NULL,
              status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS envelopes (
              document_id TEXT NOT NULL, recipient_id TEXT NOT NULL,
              kem_ciphertext TEXT NOT NULL, wrap_nonce TEXT NOT NULL,
              wrapped_cek TEXT NOT NULL,
              PRIMARY KEY (document_id, recipient_id)
            );
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, document_id TEXT NOT NULL, recipient_id TEXT NOT NULL,
              event_id TEXT NOT NULL, created_at TEXT NOT NULL,
              marked_path TEXT NOT NULL, marked_hash TEXT NOT NULL,
              watermark_commitment TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY, payload_json TEXT NOT NULL, signature TEXT NOT NULL,
              sign_public TEXT NOT NULL, block_height INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS investigations (
              id TEXT PRIMARY KEY, suspect_hash TEXT NOT NULL,
              result_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS audit_records (
              id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT NOT NULL,
              detail_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS users (
              id TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL,
              recipient_id TEXT, password_hash TEXT NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS auth_sessions (
              token_hash TEXT PRIMARY KEY, user_id TEXT NOT NULL,
              csrf_token TEXT NOT NULL, expires_at TEXT NOT NULL,
              created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
              FOREIGN KEY(user_id) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS login_failures (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL, source TEXT NOT NULL, attempted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS login_failures_user_time ON login_failures(user_id,attempted_at);
            CREATE INDEX IF NOT EXISTS login_failures_source_time ON login_failures(source,attempted_at);
            CREATE TABLE IF NOT EXISTS action_attempts (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user_id TEXT NOT NULL, action TEXT NOT NULL, attempted_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS action_attempts_user_action_time ON action_attempts(user_id,action,attempted_at);
            """)
            columns = {row[1] for row in db.execute("PRAGMA table_info(auth_sessions)")}
            if "last_seen_at" not in columns:
                db.execute("ALTER TABLE auth_sessions ADD COLUMN last_seen_at TEXT")
                db.execute("UPDATE auth_sessions SET last_seen_at=created_at WHERE last_seen_at IS NULL")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA journal_mode=WAL")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _one(row: sqlite3.Row | None) -> dict[str, Any] | None:
        return dict(row) if row is not None else None

    def audit(self, action: str, detail: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO audit_records(action,detail_json,created_at) VALUES(?,?,?)",
                       (action, canonical(detail).decode(), utc_now()))

    def add_recipient(self, value: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO recipients
              (id,name,designation,status,kem_public,kem_private_sealed,sign_public,
               sign_private_sealed,kem_fingerprint,sign_fingerprint,created_at)
              VALUES (:id,:name,:designation,:status,:kem_public,:kem_private_sealed,:sign_public,
                      :sign_private_sealed,:kem_fingerprint,:sign_fingerprint,:created_at)""", value)

    def recipients(self, public_only: bool = True) -> list[dict[str, Any]]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM recipients ORDER BY id").fetchall()
        result = [dict(row) for row in rows]
        if public_only:
            for item in result:
                item.pop("kem_private_sealed", None)
                item.pop("sign_private_sealed", None)
                item["decryptions"] = self.count_sessions(item["id"])
        return result

    def recipient(self, recipient_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._one(db.execute("SELECT * FROM recipients WHERE id=?", (recipient_id,)).fetchone())

    def revoke_recipient(self, recipient_id: str) -> bool:
        with self.connect() as db:
            changed = db.execute("UPDATE recipients SET status='REVOKED' WHERE id=? AND status='ACTIVE'", (recipient_id,)).rowcount
        return bool(changed)

    def count_sessions(self, recipient_id: str) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM sessions WHERE recipient_id=?", (recipient_id,)).fetchone()[0]

    def add_document(self, value: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO documents
              (id,filename,classification,uploaded_by,created_at,original_hash,ciphertext_hash,
               nonce,ciphertext_path,authority_cek_sealed,page_count,status)
              VALUES (:id,:filename,:classification,:uploaded_by,:created_at,:original_hash,:ciphertext_hash,
                      :nonce,:ciphertext_path,:authority_cek_sealed,:page_count,:status)""", value)

    def document(self, document_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._one(db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())

    def documents(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            docs = [dict(row) for row in db.execute("SELECT * FROM documents ORDER BY created_at DESC").fetchall()]
            for item in docs:
                item["recipients"] = db.execute("SELECT COUNT(*) FROM envelopes WHERE document_id=?", (item["id"],)).fetchone()[0]
                item["decryptions"] = db.execute("SELECT COUNT(*) FROM sessions WHERE document_id=?", (item["id"],)).fetchone()[0]
                for field in ("authority_cek_sealed", "ciphertext_path", "nonce"):
                    item.pop(field, None)
        return docs

    def add_envelopes(self, document_id: str, envelopes: list[dict[str, str]]) -> None:
        with self.connect() as db:
            for envelope in envelopes:
                db.execute("""INSERT INTO envelopes(document_id,recipient_id,kem_ciphertext,wrap_nonce,wrapped_cek)
                    VALUES(?,?,?,?,?)""", (document_id, envelope["recipient_id"], envelope["kem_ciphertext"],
                                      envelope["wrap_nonce"], envelope["wrapped_cek"]))
            db.execute("UPDATE documents SET status='DISTRIBUTED' WHERE id=?", (document_id,))

    def envelope(self, document_id: str, recipient_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._one(db.execute("SELECT * FROM envelopes WHERE document_id=? AND recipient_id=?",
                                        (document_id, recipient_id)).fetchone())

    def add_session(self, session: dict[str, Any], event: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO sessions(id,document_id,recipient_id,event_id,created_at,
                 marked_path,marked_hash,watermark_commitment)
                 VALUES (:id,:document_id,:recipient_id,:event_id,:created_at,:marked_path,
                         :marked_hash,:watermark_commitment)""", session)
            db.execute("INSERT INTO events(id,payload_json,signature,sign_public,block_height) VALUES(?,?,?,?,?)",
                       (event["id"], canonical(event["payload"]).decode(), event["signature"],
                        event["sign_public"], event["block_height"]))

    def sessions(self, document_id: str | None = None) -> list[dict[str, Any]]:
        with self.connect() as db:
            if document_id:
                rows = db.execute("SELECT * FROM sessions WHERE document_id=? ORDER BY created_at DESC", (document_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(row) for row in rows]

    def session(self, session_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._one(db.execute("SELECT * FROM sessions WHERE id=?", (session_id,)).fetchone())

    def event(self, event_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = self._one(db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone())
        if row:
            row["payload"] = json.loads(row.pop("payload_json"))
        return row

    def events(self) -> list[dict[str, Any]]:
        with self.connect() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM events ORDER BY block_height DESC").fetchall()]
        return [self.event(event_id) for event_id in ids]

    def add_investigation(self, investigation_id: str, suspect_hash: str, result: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO investigations(id,suspect_hash,result_json,created_at) VALUES(?,?,?,?)",
                       (investigation_id, suspect_hash, json.dumps(result, sort_keys=True), utc_now()))

    def investigation(self, investigation_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = self._one(db.execute("SELECT * FROM investigations WHERE id=?", (investigation_id,)).fetchone())
        if row:
            row["result"] = json.loads(row.pop("result_json"))
        return row

    def count_investigations(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM investigations").fetchone()[0]

    def add_user(self, value: dict[str, Any]) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO users(id,display_name,role,recipient_id,password_hash,status,created_at)
                VALUES(:id,:display_name,:role,:recipient_id,:password_hash,:status,:created_at)""", value)

    def user(self, user_id: str) -> dict[str, Any] | None:
        with self.connect() as db:
            return self._one(db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone())

    def user_count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def add_auth_session(self, value: dict[str, str]) -> None:
        with self.connect() as db:
            db.execute("""INSERT INTO auth_sessions(token_hash,user_id,csrf_token,expires_at,created_at,last_seen_at)
                VALUES(:token_hash,:user_id,:csrf_token,:expires_at,:created_at,:created_at)""", value)

    def auth_session(self, token_hash: str) -> dict[str, Any] | None:
        with self.connect() as db:
            row = db.execute("""SELECT s.token_hash,s.csrf_token,s.expires_at,s.last_seen_at,u.id,u.display_name,u.role,
                u.recipient_id,u.status FROM auth_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=?""", (token_hash,)).fetchone()
            return self._one(row)

    def touch_auth_session(self, token_hash: str, now: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE auth_sessions SET last_seen_at=? WHERE token_hash=?", (now, token_hash))

    def login_failure_counts(self, user_id: str, source: str, account_since: str, source_since: str) -> tuple[int, int]:
        with self.connect() as db:
            account = db.execute("SELECT COUNT(*) FROM login_failures WHERE user_id=? AND attempted_at>=?",
                                 (user_id, account_since)).fetchone()[0]
            origin = db.execute("SELECT COUNT(*) FROM login_failures WHERE source=? AND attempted_at>=?",
                                (source, source_since)).fetchone()[0]
        return account, origin

    def add_login_failure(self, user_id: str, source: str, now: str, prune_before: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM login_failures WHERE attempted_at<?", (prune_before,))
            db.execute("INSERT INTO login_failures(user_id,source,attempted_at) VALUES(?,?,?)",
                       (user_id, source, now))

    def clear_login_failures(self, user_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM login_failures WHERE user_id=?", (user_id,))

    def allow_action(self, user_id: str, action: str, now: str, since: str, maximum: int) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM action_attempts WHERE attempted_at<?", (since,))
            count = db.execute("SELECT COUNT(*) FROM action_attempts WHERE user_id=? AND action=? AND attempted_at>=?",
                               (user_id, action, since)).fetchone()[0]
            if count >= maximum:
                return False
            db.execute("INSERT INTO action_attempts(user_id,action,attempted_at) VALUES(?,?,?)",
                       (user_id, action, now))
            return True

    def remove_auth_session(self, token_hash: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (token_hash,))

    def revoke_user_by_recipient(self, recipient_id: str) -> None:
        with self.connect() as db:
            db.execute("UPDATE users SET status='REVOKED' WHERE recipient_id=?", (recipient_id,))
            db.execute("DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM users WHERE recipient_id=?)",
                       (recipient_id,))
