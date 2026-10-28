import html
import logging
import secrets
import threading
import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app import auth, config, vault
from app.shopify import oauth

logger: logging.Logger = logging.getLogger(__name__)

# Session-protected: start a token refresh and poll its result.
router = APIRouter(
    prefix="/api/shopify/oauth",
    tags=["shopify-oauth"],
    dependencies=[Depends(auth.require_session)],
)
# Shopify redirects the browser here. The session cookie is SameSite=Strict, so it is
# not sent on this cross-site redirect; the one-time `state` authenticates the request.
callback_router = APIRouter(tags=["shopify-oauth"])

STATE_TTL_SECONDS: int = 300
_pending: dict[str, dict] = {}
_lock: threading.Lock = threading.Lock()


class StartIn(BaseModel):
    store: Literal["main", "test"]
    scopes: str
    password: str


def _purge_expired(now: float) -> None:
    for state in [s for s, e in _pending.items() if e["expires"] < now]:
        del _pending[state]


def _page(message: str) -> HTMLResponse:
    body = (
        "<!doctype html><meta charset='utf-8'><title>Shopify authorization</title>"
        "<body style=\"font-family:system-ui,sans-serif;background:#0f1117;color:#e8ecf0;"
        "display:grid;place-items:center;height:100vh;margin:0\">"
        f"<div><h2>{html.escape(message)}</h2><p>You can close this tab.</p></div>"
    )
    return HTMLResponse(body)


@router.post("/start")
def start(body: StartIn):
    creds = auth.check_password(body.password, wrong_status=403)
    keys = oauth.STORES[body.store]
    shop = creds.get(keys["store"])
    client_id = creds.get("shopify_client_id")
    client_secret = creds.get("shopify_client_secret")
    if not shop or not client_id or not client_secret:
        raise HTTPException(
            400, f"Vault is missing {keys['store']}, shopify_client_id or shopify_client_secret"
        )
    if not oauth.SHOP_RE.match(shop):
        raise HTTPException(400, f"Invalid store domain: {shop}")
    try:
        scopes = oauth.normalize_scopes(body.scopes)
    except ValueError as e:
        raise HTTPException(400, str(e))

    state = secrets.token_urlsafe(24)
    now = time.time()
    with _lock:
        _purge_expired(now)
        _pending[state] = {
            "store": body.store,
            "password": body.password,  # needed to re-seal the vault; dropped when done
            "status": "pending",
            "message": "",
            "scope": "",
            "expires": now + STATE_TTL_SECONDS,
        }
    return {
        "state": state,
        "url": oauth.authorize_url(shop, client_id, scopes, config.OAUTH_REDIRECT_URI, state),
    }


@router.get("/status/{state}")
def status(state: str):
    with _lock:
        entry = _pending.get(state)
        if not entry or entry["expires"] < time.time():
            _pending.pop(state, None)
            return {"status": "expired", "message": "Authorization expired. Start again.", "scope": ""}
        result = {k: entry[k] for k in ("status", "message", "scope")}
        if entry["status"] in ("done", "error"):
            del _pending[state]
    return result


@callback_router.get("/api/auth/callback", response_class=HTMLResponse)
def callback(request: Request):
    params = dict(request.query_params)
    with _lock:
        entry = _pending.get(params.get("state", ""))
        if not entry or entry["expires"] < time.time() or entry["status"] != "pending":
            return _page("This authorization link is invalid or expired. Start again from Settings.")
        entry["status"] = "working"  # single use
        password = entry["password"]

    outcome = ("error", "Unknown error", "")
    try:
        creds = vault.open_vault(password)
        keys = oauth.STORES[entry["store"]]
        shop = creds[keys["store"]]
        if params.get("shop") != shop:
            raise ValueError("Shop in callback does not match the configured store")
        if not oauth.verify_hmac(params, creds["shopify_client_secret"]):
            raise ValueError("Invalid callback signature")
        code = params.get("code")
        if not code:
            raise ValueError("No authorization code received")
        data = oauth.exchange_code(
            shop, creds["shopify_client_id"], creds["shopify_client_secret"], code
        )
        merged = vault.update_vault(password, {
            keys["token"]: data["access_token"],
            keys["scope"]: data.get("scope", ""),
        })
        auth.set_creds(merged)
        outcome = ("done", f"Token refreshed for {shop}", data.get("scope", ""))
    except Exception as exc:
        logger.exception("Shopify token refresh failed")
        outcome = ("error", str(exc), "")
    finally:
        with _lock:
            entry.update(status=outcome[0], message=outcome[1], scope=outcome[2])
            entry.pop("password", None)
    return _page(outcome[1])