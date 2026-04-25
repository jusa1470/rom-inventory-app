from fastapi import HTTPException
import time

from main import APP_STATE

# -------------------------
# Session State (in-memory)
# -------------------------
SESSION = {
    "unlocked": False,
    "creds": None,
    "last_used": None
}

SESSION_TIMEOUT = 60 * 60 * 2  # 2 hours

def require_auth():
    if not APP_STATE["ready"]:
        raise HTTPException(
            status_code=503,
            detail=APP_STATE["error"] or "App not ready"
        )
    
    if not SESSION["unlocked"]:
        raise HTTPException(401, "Locked")

    if SESSION["last_used"] and (time.time() - SESSION["last_used"] > SESSION_TIMEOUT):
        SESSION["unlocked"] = False
        SESSION["creds"] = None
        raise HTTPException(401, "Session expired")

    SESSION["last_used"] = time.time()


def get_creds():
    if not SESSION["creds"]:
        raise HTTPException(401, "No credentials loaded")
    return SESSION["creds"]