"""Single-origin hosted demo: static web export, API, and a shared access gate."""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .app import app as api

ACCESS_CODE = os.environ.get("SOURCEX_DEMO_GATE", "")
if len(ACCESS_CODE) < 16:
    raise RuntimeError("SOURCEX_DEMO_GATE must contain at least 16 characters")

WEB_DIR = Path(os.environ.get("SOURCEX_WEB_DIR", "/app/apps/web/out"))
if not WEB_DIR.is_dir():
    raise RuntimeError(f"Static web export missing: {WEB_DIR}")

COOKIE = "sourcex_demo_access"
TOKEN = hmac.new(ACCESS_CODE.encode(), b"sourcex-gate-v1", hashlib.sha256).hexdigest()
FAILURES: dict[str, list[float]] = {}
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


def access_page(error: str = "") -> HTMLResponse:
    message = '<p class="error" role="alert">Incorrect code. Please try again.</p>' if error else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SourceX | Demo access</title><style>
:root{{color-scheme:dark}}*{{box-sizing:border-box}}body{{min-height:100vh;margin:0;display:grid;
place-items:center;background:radial-gradient(circle at 20% 15%,#193e51,#07151f 55%);color:#f3f8fa;
font:16px system-ui,sans-serif;padding:24px}}main{{width:min(100%,440px);border:1px solid #54717b;
border-radius:20px;background:#102936;padding:36px;box-shadow:0 25px 80px #0005}}
.mark{{font-size:44px;font-weight:800;letter-spacing:-.08em}}.mark span{{color:#e9a864}}
h1{{font-size:24px;margin:20px 0 8px}}p{{line-height:1.5;color:#bdd0d7}}label{{display:block;margin:24px 0 8px}}
input,button{{width:100%;font:inherit;border-radius:10px;padding:13px 15px}}input{{border:1px solid #8299a0;
background:#f8fbfc;color:#102936}}button{{margin-top:16px;border:0;background:#e9a864;color:#17252d;
font-weight:750;cursor:pointer}}button:hover{{background:#f5be82}}button:focus-visible,input:focus-visible{{outline:3px solid #73d9e7;outline-offset:3px}}
.error{{color:#ffb4ad}}small{{display:block;margin-top:25px;color:#a7bdc4;line-height:1.5}}
</style></head><body><main><div class="mark">Source<span>X</span></div>
<h1>Enter the demonstration</h1><p>Use the access code supplied by the SourceX team.
The four fictional role accounts are available inside.</p>{message}
<form action="/access" method="post"><label for="code">Demo access code</label>
<input id="code" name="code" type="password" autocomplete="off" required autofocus>
<button type="submit">Open SourceX</button></form>
<small>SIH 2026 research prototype. Hosted demo uses temporary cloud storage.
Use synthetic documents only. Not an official Ministry of Defence deployment.</small>
</main></body></html>"""
    return HTMLResponse(page, status_code=401 if error else 200)


@app.middleware("http")
async def protect_demo(request: Request, call_next):
    path = request.url.path
    if path != "/health" and path != "/access":
        valid = hmac.compare_digest(request.cookies.get(COOKIE, ""), TOKEN)
        if not valid:
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Demo access expired. Reload and enter the access code."}, status_code=401)
            return RedirectResponse("/access", status_code=303)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; connect-src 'self'; object-src 'none'; "
        "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
    )
    return response


@app.get("/health")
def health():
    from .app import health as api_health
    result = api_health()
    return JSONResponse(result, status_code=200 if result["status"] == "READY" else 503)


@app.get("/access", response_class=HTMLResponse)
def access(request: Request):
    if hmac.compare_digest(request.cookies.get(COOKIE, ""), TOKEN):
        return RedirectResponse("/", status_code=303)
    return access_page()


@app.post("/access")
def unlock(request: Request, code: str = Form(...)):
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    recent = [stamp for stamp in FAILURES.get(address, []) if now - stamp < 300]
    if len(recent) >= 10:
        return HTMLResponse("Too many attempts. Try again in five minutes.", status_code=429)
    if not hmac.compare_digest(code, ACCESS_CODE):
        recent.append(now)
        FAILURES[address] = recent
        return access_page("incorrect")
    FAILURES.pop(address, None)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(COOKIE, TOKEN, max_age=12 * 3600, httponly=True,
                        secure=os.getenv("SOURCEX_HOSTED") == "1", samesite="lax", path="/")
    return response


app.mount("/api", api)
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
