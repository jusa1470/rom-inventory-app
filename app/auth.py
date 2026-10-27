import secrets
import time

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from pydantic import BaseModel

from app import vault


router = APIRouter(prefix="/api", tags=["auth"])

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


@router.post("/api/login")
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


@router.post("/api/logout")
def logout(response: Response, rs_session: str | None = Cookie(default=None)):
    _sessions.discard(rs_session or "")
    if not _sessions:
        global _creds
        _creds = None
    response.delete_cookie("rs_session")
    return {"ok": True}


@router.get("/api/me", dependencies=[Depends(require_session)])
def me():
    return {"ok": True}