import secrets
import time
from pathlib import Path

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import vault

STATIC = Path(__file__).resolve().parent.parent / "static"
app = FastAPI()

# In-memory state: decrypted credentials live only while the app runs.
_creds: dict | None = None
_sessions: set[str] = set()
_fails: list[float] = []


class Login(BaseModel):
    password: str


def require_session(rs_session: str | None = Cookie(default=None)) -> None:
    if not rs_session or rs_session not in _sessions:
        raise HTTPException(401, "Locked")


def get_creds() -> dict:
    if _creds is None:
        raise HTTPException(401, "Locked")
    return _creds


@app.post("/api/login")
def login(body: Login, response: Response):
    global _creds
    now = time.time()
    _fails[:] = [t for t in _fails if now - t < 60]
    if len(_fails) >= 5:
        raise HTTPException(429, "Too many attempts, wait a minute")
    try:
        _creds = vault.open_vault(body.password)
    except vault.VaultError as e:
        _fails.append(now)
        raise HTTPException(401, str(e))
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    response.set_cookie("rs_session", token, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, rs_session: str | None = Cookie(default=None)):
    _sessions.discard(rs_session or "")
    response.delete_cookie("rs_session")
    return {"ok": True}


@app.get("/api/me", dependencies=[Depends(require_session)])
def me():
    return {"ok": True}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{path:path}")
def spa(path: str):
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
