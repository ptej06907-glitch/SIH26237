from __future__ import annotations

import html
import hmac
import json
import os
import re
import subprocess
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator

from .crypto import sha3
from .auth import LoginThrottled
from .service import Prototype

ROOT = Path(__file__).resolve().parents[3]
system = Prototype(ROOT)
if system.crypto and system.ledger and (not system.store.recipients() or not system.store.user_count()):
    system.seed_demo()

app = FastAPI(title="SIH26237 Secure Document Provenance", version="0.1.0",
              description="Offline standards-based research prototype. Not an official Ministry of Defence deployment.")
PUBLIC_ORIGIN = (os.getenv("SOURCEX_PUBLIC_ORIGIN") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")
ALLOWED_ORIGINS = {"http://127.0.0.1:3000", "http://localhost:3000"}
if PUBLIC_ORIGIN:
    ALLOWED_ORIGINS.add(PUBLIC_ORIGIN)
app.add_middleware(CORSMiddleware, allow_origins=sorted(ALLOWED_ORIGINS),
                   allow_credentials=True, allow_methods=["GET", "POST"],
                   allow_headers=["Content-Type", "X-CSRF-Token"])

COOKIE_NAME = "sih26237_session"


@app.middleware("http")
async def local_security_headers(request: Request, call_next):
    origin = request.headers.get("origin")
    if origin and origin not in ALLOWED_ORIGINS:
        return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
    if request.url.path in {"/documents", "/forensics/analyze"} and request.method == "POST":
        declared = request.headers.get("content-length")
        if declared and (not declared.isdecimal() or int(declared) > 16 * 1024 * 1024):
            return JSONResponse(status_code=413, content={"detail": "PDF request exceeds 16 MiB"})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.endswith("/report.html"):
        response.headers["Content-Security-Policy"] = "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'"
    if request.url.path not in {"/health"}:
        response.headers["Cache-Control"] = "no-store"
    return response


def current_user(request: Request) -> dict[str, Any]:
    session = system.auth.resolve(request.cookies.get(COOKIE_NAME))
    if not session:
        raise HTTPException(status_code=401, detail="Sign in to continue")
    return session


def permit(*roles: str):
    def dependency(request: Request, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if user["role"] not in roles:
            raise HTTPException(status_code=403, detail="This account cannot perform that action")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            provided = request.headers.get("X-CSRF-Token", "")
            if not hmac.compare_digest(provided, user["csrf_token"]):
                raise HTTPException(status_code=403, detail="Request token missing or invalid")
        return user
    return dependency


def limit_action(user: dict[str, Any], action: str, maximum: int) -> None:
    now = datetime.now(timezone.utc)
    timestamp = now.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    since = (now - timedelta(minutes=1)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    if not system.store.allow_action(user["id"], action, timestamp, since, maximum):
        system.store.audit("ACTION_THROTTLED", {"user_id": user["id"], "action": action})
        raise HTTPException(status_code=429, detail="Action limit reached. Try again shortly.",
                            headers={"Retry-After": "60"})


@app.exception_handler(ValueError)
async def value_error_handler(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"status": "INVALID", "detail": str(exc)})


@app.exception_handler(RuntimeError)
async def runtime_error_handler(_, exc: RuntimeError):
    return JSONResponse(status_code=503, content={"status": "UNAVAILABLE", "detail": str(exc)})


class RecipientInput(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    designation: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=10, max_length=200)

    @field_validator("name", "designation")
    @classmethod
    def readable_text(cls, value: str) -> str:
        value = unicodedata.normalize("NFC", value).strip()
        if any(unicodedata.category(char).startswith("C") for char in value):
            raise ValueError("Control characters are not allowed")
        return value


class DistributionInput(BaseModel):
    recipient_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("recipient_ids")
    @classmethod
    def unique_recipient_ids(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not re.fullmatch(r"REC-[0-9]{3,6}", item) for item in value):
            raise ValueError("Recipient IDs must be unique and well formed")
        return value


class DecryptInput(BaseModel):
    document_id: str
    recipient_id: str


class ValidatorInput(BaseModel):
    validator_id: str


class LoginInput(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)


@app.post("/auth/login")
def login(payload: LoginInput, response: Response, request: Request):
    try:
        result = system.auth.login(payload.user_id, payload.password,
                                   request.client.host if request.client else "local")
    except LoginThrottled as exc:
        raise HTTPException(status_code=429, detail="Too many sign-in attempts. Try again shortly.",
                            headers={"Retry-After": str(exc.retry_after)}) from exc
    if result is None:
        raise HTTPException(status_code=401, detail="Invalid account or password")
    token, session = result
    response.set_cookie(COOKIE_NAME, token, max_age=8 * 3600, httponly=True,
                        secure=os.getenv("SOURCEX_HOSTED") == "1", samesite="strict", path="/")
    return system.auth.public_session(session)


@app.get("/auth/me")
def me(request: Request):
    user = system.auth.resolve(request.cookies.get(COOKIE_NAME))
    return system.auth.public_session(user) if user else None


@app.post("/auth/logout")
def logout(request: Request, response: Response,
           user: dict[str, Any] = Depends(permit("SENDER", "RECIPIENT", "INVESTIGATOR", "AUDITOR"))):
    system.auth.logout(request.cookies.get(COOKIE_NAME))
    system.store.audit("LOGOUT", {"user_id": user["id"]})
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"status": "SIGNED_OUT"}


@app.get("/health")
def health():
    status = system.status()
    return {"status": "READY" if status["pqc_engine"] == "READY" and
            status["watermark_engine"] == "READY" and status["ledger"]["status"] == "VALID" else "ERROR",
            "version": status["app_version"], "prototype": True}


@app.get("/system/status")
def system_status(_: dict[str, Any] = Depends(current_user)):
    return system.status()


@app.get("/dashboard")
def dashboard(user: dict[str, Any] = Depends(current_user)):
    result = system.dashboard()
    if user["role"] == "RECIPIENT":
        recipient_id = user["recipient_id"]
        result["recent_documents"] = [d for d in result["recent_documents"]
                                      if system.store.envelope(d["id"], recipient_id)]
        result["recent_sessions"] = [s for s in result["recent_sessions"] if s["recipient_id"] == recipient_id]
        result["counts"]["documents"] = len([d for d in system.store.documents()
                                                if system.store.envelope(d["id"], recipient_id)])
        result["counts"]["decryptions"] = system.store.count_sessions(recipient_id)
    elif user["role"] == "INVESTIGATOR":
        result["recent_documents"] = []
        result["recent_sessions"] = []
    return result


@app.get("/recipients")
def recipients(user: dict[str, Any] = Depends(current_user)):
    rows = system.store.recipients()
    if user["role"] == "RECIPIENT":
        return [row for row in rows if row["id"] == user["recipient_id"]]
    if user["role"] == "INVESTIGATOR":
        return []
    return rows


@app.get("/recipients/{recipient_id}")
def recipient(recipient_id: str, user: dict[str, Any] = Depends(current_user)):
    if user["role"] == "INVESTIGATOR" or (user["role"] == "RECIPIENT" and user["recipient_id"] != recipient_id):
        raise HTTPException(status_code=403, detail="Recipient record unavailable")
    item = next((row for row in system.store.recipients() if row["id"] == recipient_id), None)
    if item is None:
        raise ValueError("Recipient not found")
    return item


@app.post("/recipients")
def create_recipient(payload: RecipientInput, _: dict[str, Any] = Depends(permit("SENDER"))):
    return system.create_recipient(payload.name, payload.designation, payload.password)


@app.post("/recipients/{recipient_id}/revoke")
def revoke_recipient(recipient_id: str, _: dict[str, Any] = Depends(permit("SENDER"))):
    if not system.store.revoke_recipient(recipient_id):
        raise ValueError("Active recipient not found")
    system.store.revoke_user_by_recipient(recipient_id)
    system.store.audit("RECIPIENT_REVOKED", {"recipient_id": recipient_id})
    return {"recipient_id": recipient_id, "status": "REVOKED"}


@app.get("/documents")
def documents(user: dict[str, Any] = Depends(current_user)):
    rows = system.store.documents()
    if user["role"] == "RECIPIENT":
        return [row for row in rows if system.store.envelope(row["id"], user["recipient_id"])]
    if user["role"] == "INVESTIGATOR":
        return []
    return rows


@app.get("/documents/{document_id}")
def document(document_id: str, user: dict[str, Any] = Depends(current_user)):
    item = next((row for row in documents(user) if row["id"] == document_id), None)
    if item is None:
        raise ValueError("Document not found")
    item["authorized_recipients"] = [person["id"] for person in system.store.recipients()
                                     if system.store.envelope(document_id, person["id"])]
    item["sessions"] = system.store.sessions(document_id)
    if user["role"] == "RECIPIENT":
        item["sessions"] = [s for s in item["sessions"] if s["recipient_id"] == user["recipient_id"]]
    for session in item["sessions"]:
        session.pop("marked_path", None)
    return item


@app.post("/documents")
async def upload_document(file: UploadFile = File(...), classification: str = Form("DEMO RESTRICTED"),
                          _: dict[str, Any] = Depends(permit("SENDER"))):
    if classification not in {"OFFICIAL", "DEMO RESTRICTED", "CONFIDENTIAL — DEMO ONLY"}:
        raise ValueError("Invalid demo classification")
    payload = await file.read(15 * 1024 * 1024 + 1)
    return system.create_document(file.filename or "document.pdf", classification, payload, "Document Authority")


@app.post("/documents/{document_id}/distribute")
def distribute(document_id: str, payload: DistributionInput,
               _: dict[str, Any] = Depends(permit("SENDER"))):
    return system.distribute(document_id, payload.recipient_ids)


@app.get("/demo/sample-pdf")
def sample_pdf(_: dict[str, Any] = Depends(current_user)):
    return Response(content=system._sample_pdf(), media_type="application/pdf",
                    headers={"Content-Disposition": 'inline; filename="Strategic_Exercise_Brief.pdf"'})


@app.post("/decrypt")
def decrypt(payload: DecryptInput, user: dict[str, Any] = Depends(permit("RECIPIENT"))):
    if payload.recipient_id != user["recipient_id"]:
        raise HTTPException(status_code=403, detail="Recipient identity does not match signed-in account")
    limit_action(user, "decrypt", 10)
    return system.decrypt(payload.document_id, payload.recipient_id)


@app.get("/sessions/{session_id}/download")
def download(session_id: str, user: dict[str, Any] = Depends(permit("RECIPIENT"))):
    session = system.store.session(session_id)
    if session is None:
        raise ValueError("Session not found")
    if session["recipient_id"] != user["recipient_id"]:
        raise HTTPException(status_code=403, detail="This copy belongs to another recipient")
    verification = system.verify_event(session["event_id"])
    if verification["status"] != "VALID":
        raise RuntimeError("Signed event or ledger verification failed")
    path = Path(session["marked_path"])
    if not path.is_file() or sha3(path.read_bytes()) != session["marked_hash"]:
        raise RuntimeError("Marked PDF hash invalid")
    return FileResponse(path, media_type="application/pdf", filename=f"marked-{session_id[:8]}.pdf")


@app.get("/events")
def events(_: dict[str, Any] = Depends(permit("SENDER", "AUDITOR"))):
    result = system.store.events()
    for event in result:
        event.pop("sign_public", None)
    return result


@app.get("/events/{event_id}")
def event(event_id: str, _: dict[str, Any] = Depends(permit("SENDER", "AUDITOR", "INVESTIGATOR"))):
    item = system.store.event(event_id)
    if item is None:
        raise ValueError("Event not found")
    return item


@app.post("/events/{event_id}/verify")
def verify_event(event_id: str, _: dict[str, Any] = Depends(permit("SENDER", "AUDITOR", "INVESTIGATOR"))):
    return system.verify_event(event_id)


@app.get("/ledger/blocks")
def blocks(_: dict[str, Any] = Depends(permit("SENDER", "AUDITOR", "INVESTIGATOR"))):
    return system.ready()[1].authoritative_blocks()


@app.get("/ledger/validators")
def validators(_: dict[str, Any] = Depends(current_user)):
    return system.ready()[1].verify()


@app.post("/ledger/verify")
def verify_ledger(_: dict[str, Any] = Depends(permit("SENDER", "AUDITOR", "INVESTIGATOR"))):
    return system.ready()[1].verify()


@app.post("/ledger/independent-verify")
def independent_verify(user: dict[str, Any] = Depends(permit("SENDER", "AUDITOR", "INVESTIGATOR"))):
    limit_action(user, "independent_verify", 5)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "services" / "api") + os.pathsep + env.get("PYTHONPATH", "")
    try:
        run = subprocess.run([sys.executable, "-m", "provenance.independent_verify",
                              "--data-dir", str(system.data_dir)], capture_output=True,
                             text=True, timeout=25, env=env, check=True)
        return json.loads(run.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise RuntimeError("INDEPENDENT VERIFIER UNAVAILABLE") from exc


@app.post("/forensics/analyze")
async def analyze(file: UploadFile = File(...), user: dict[str, Any] = Depends(permit("INVESTIGATOR"))):
    limit_action(user, "forensic_analyze", 5)
    payload = await file.read(15 * 1024 * 1024 + 1)
    return system.analyze(payload)


@app.get("/forensics/{investigation_id}")
def investigation(investigation_id: str, _: dict[str, Any] = Depends(permit("INVESTIGATOR", "AUDITOR"))):
    item = system.store.investigation(investigation_id)
    if item is None:
        raise ValueError("Investigation not found")
    return item["result"]


@app.get("/forensics/{investigation_id}/report.json")
def report_json(investigation_id: str, _: dict[str, Any] = Depends(permit("INVESTIGATOR", "AUDITOR"))):
    item = system.store.investigation(investigation_id)
    if item is None:
        raise ValueError("Investigation not found")
    return JSONResponse(content=item["result"], headers={"Content-Disposition":
                        f'attachment; filename="evidence-{investigation_id[:8]}.json"'})


@app.get("/forensics/{investigation_id}/report.html")
def report_html(investigation_id: str, _: dict[str, Any] = Depends(permit("INVESTIGATOR", "AUDITOR"))):
    item = system.store.investigation(investigation_id)
    if item is None:
        raise ValueError("Investigation not found")
    result = item["result"]
    fields = [("Status", result.get("status")), ("Suspect SHA3-256", result.get("suspect_sha3_256")),
              ("Document", result.get("document_name")), ("Recipient", result.get("recipient_name")),
              ("Session", result.get("session_id")), ("Watermark score", result.get("watermark_score")),
              ("ML-DSA signature", result.get("ml_dsa_signature")),
              ("Ledger", result.get("ledger_chain")), ("Validator quorum", result.get("validator_quorum")),
              ("Block hash", result.get("block_hash"))]
    rows = "".join(f"<tr><th>{html.escape(str(label))}</th><td>{html.escape(str(value or '—'))}</td></tr>"
                   for label, value in fields)
    markup = f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>Evidence report {html.escape(investigation_id)}</title>
    <style>body{{font:16px system-ui;max-width:850px;margin:48px auto;color:#17253c}}h1{{color:#102846}}table{{width:100%;border-collapse:collapse}}th,td{{padding:13px;border-bottom:1px solid #ccd5dd;text-align:left}}th{{width:35%}}.note{{margin-top:30px;color:#536477}}</style>
    <h1>Forensic attribution evidence</h1><p>Investigation {html.escape(investigation_id)}</p><table>{rows}</table>
    <p class="note">SIH 2026 Prototype — Not an official Ministry of Defence deployment. This report identifies a marked decryption session; it makes no legal determination. The score is a detector correlation, not a probability.</p></html>"""
    return HTMLResponse(markup)


@app.get("/sessions/{session_id}/robustness")
def robustness(session_id: str, user: dict[str, Any] = Depends(permit("INVESTIGATOR", "AUDITOR"))):
    limit_action(user, "robustness", 3)
    return system.robustness(session_id)


@app.post("/demo/tamper-validator")
def tamper(payload: ValidatorInput, _: dict[str, Any] = Depends(permit("AUDITOR"))):
    ledger = system.ready()[1]
    ledger.tamper(payload.validator_id)
    system.store.audit("DEMO_TAMPER", {"validator_id": payload.validator_id})
    return ledger.verify()


@app.post("/demo/restore-validator")
def restore(payload: ValidatorInput, _: dict[str, Any] = Depends(permit("AUDITOR"))):
    ledger = system.ready()[1]
    ledger.restore(payload.validator_id)
    system.store.audit("DEMO_RESTORE", {"validator_id": payload.validator_id})
    return ledger.verify()


@app.post("/demo/seed")
def seed(_: dict[str, Any] = Depends(permit("AUDITOR"))):
    return system.seed_demo()
