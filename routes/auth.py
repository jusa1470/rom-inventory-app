from flask import Blueprint, jsonify, request, session

import db.database as db
import config
from services.auth_utils import hash_password, verify_password, encrypt, decrypt
from webami.session import configure as configure_webami

bp = Blueprint("auth", __name__)


def _load_webami_session(password: str, cfg: dict) -> None:
    """Decrypt Webami credentials and configure the scraper session."""
    try:
        username = decrypt(password, cfg.get("webami_username_enc") or "")
        pw       = decrypt(password, cfg.get("webami_password_enc") or "")
        base_url = cfg.get("webami_base_url") or config.WEBAMI_BASE_URL
        if username and pw:
            configure_webami(base_url, username, pw)
    except Exception:
        pass


@bp.get("/api/auth/status")
def status():
    setup_done = db.has_setup()
    return jsonify({
        "authenticated": bool(session.get("authenticated")),
        "setup_required": not setup_done,
    })


@bp.post("/api/auth/login")
def login():
    data     = request.get_json(silent=True) or {}
    password = (data.get("password") or "").strip()
    if not password:
        return jsonify({"error": "Password required"}), 400

    cfg = db.get_config()
    if not cfg or not cfg.get("password_hash"):
        return jsonify({"error": "App not configured yet"}), 400

    if not verify_password(password, cfg["password_hash"]):
        return jsonify({"error": "Incorrect password"}), 401

    # Decrypt stored creds and stash in server-side session
    shopify_token = decrypt(password, cfg.get("shopify_token_enc") or "")
    webami_user   = decrypt(password, cfg.get("webami_username_enc") or "")
    webami_pw     = decrypt(password, cfg.get("webami_password_enc") or "")

    session.clear()
    session["authenticated"]  = True
    session["shopify_store"]  = cfg.get("shopify_store") or ""
    session["shopify_token"]  = shopify_token
    session["webami_base_url"]= cfg.get("webami_base_url") or config.WEBAMI_BASE_URL
    session["webami_username"]= webami_user
    session["webami_password"]= webami_pw
    session["target_margin"]  = cfg.get("target_margin") or config.TARGET_MARGIN

    _load_webami_session(password, cfg)
    return jsonify({"ok": True})


@bp.post("/api/auth/logout")
def logout():
    session.clear()
    return jsonify({"ok": True})


@bp.post("/api/auth/setup")
def setup():
    """First-time setup - create password and save credentials."""
    if db.has_setup():
        return jsonify({"error": "Already configured"}), 400

    data = request.get_json(silent=True) or {}
    password        = (data.get("password") or "").strip()
    shopify_store   = (data.get("shopify_store") or "").strip()
    shopify_token   = (data.get("shopify_token") or "").strip()
    webami_base_url = (data.get("webami_base_url") or config.WEBAMI_BASE_URL).strip()
    webami_username = (data.get("webami_username") or "").strip()
    webami_password = (data.get("webami_password") or "").strip()

    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if not shopify_store or not shopify_token:
        return jsonify({"error": "Shopify store and token are required"}), 400

    db.upsert_config(
        password_hash       = hash_password(password),
        shopify_store       = shopify_store,
        shopify_token_enc   = encrypt(password, shopify_token),
        webami_base_url     = webami_base_url,
        webami_username_enc = encrypt(password, webami_username),
        webami_password_enc = encrypt(password, webami_password),
    )

    config.WEBAMI_BASE_URL = webami_base_url
    return jsonify({"ok": True})


@bp.post("/api/auth/change-password")
def change_password():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401

    data         = request.get_json(silent=True) or {}
    old_password = (data.get("old_password") or "").strip()
    new_password = (data.get("new_password") or "").strip()

    if len(new_password) < 6:
        return jsonify({"error": "New password must be at least 6 characters"}), 400

    cfg = db.get_config()
    if not verify_password(old_password, cfg.get("password_hash") or ""):
        return jsonify({"error": "Incorrect current password"}), 401

    # Re-encrypt all credentials with new password
    shopify_token   = session.get("shopify_token") or ""
    webami_username = session.get("webami_username") or ""
    webami_password = session.get("webami_password") or ""

    db.upsert_config(
        password_hash       = hash_password(new_password),
        shopify_token_enc   = encrypt(new_password, shopify_token),
        webami_username_enc = encrypt(new_password, webami_username),
        webami_password_enc = encrypt(new_password, webami_password),
    )
    return jsonify({"ok": True})
