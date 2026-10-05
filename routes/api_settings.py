from flask import Blueprint, jsonify, request, session

import config
import db.database as db
from services.auth_utils import encrypt, decrypt, verify_password

bp = Blueprint("settings", __name__)


def _require_auth():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    return None


@bp.get("/api/settings")
def get_settings():
    err = _require_auth()
    if err:
        return err
    cfg = db.get_config() or {}
    return jsonify({
        "shopify_store":       cfg.get("shopify_store") or "",
        "shopify_api_version": cfg.get("shopify_api_version") or config.SHOPIFY_API_VERSION,
        "shopify_location_id": cfg.get("shopify_location_id") or "",
        "shopify_upc_ns":      cfg.get("shopify_upc_ns") or "custom",
        "shopify_upc_key":     cfg.get("shopify_upc_key") or "upc",
        "shopify_genres_ns":    cfg.get("shopify_genres_ns") or "custom",
        "shopify_genres_key":   cfg.get("shopify_genres_key") or "genres",
        "webami_base_url":     cfg.get("webami_base_url") or config.WEBAMI_BASE_URL,
        "target_margin":       cfg.get("target_margin") or config.TARGET_MARGIN,
        "last_shopify_sync":   cfg.get("last_shopify_sync") or "",
        "last_matcher_run":    cfg.get("last_matcher_run") or "",
        "dry_run":             1 if bool(cfg.get("dry_run")) else 0,
        # Never send encrypted values - just indicate if set
        "shopify_token_set":   bool(cfg.get("shopify_token_enc")),
        "webami_creds_set":    bool(cfg.get("webami_username_enc")),
    })


@bp.post("/api/settings")
def save_settings():
    err = _require_auth()
    if err:
        return err

    data = request.get_json(silent=True) or {}

    updates: dict = {}

    # Non-sensitive fields
    for field in ("shopify_store", "shopify_api_version", "shopify_upc_ns",
                  "shopify_upc_key", "shopify_genres_ns", "shopify_genres_key",
                  "webami_base_url", "target_margin"):
        if field in data:
            updates[field] = data[field]

    if "dry_run" in data:
        updates["dry_run"] = 1 if data["dry_run"] else 0

    # Sensitive fields need current password to re-encrypt
    password = (data.get("password") or "").strip()
    cfg = db.get_config() or {}

    has_sensitive = any(k in data for k in ("shopify_token", "webami_username", "webami_password"))
    if has_sensitive:
        if not password:
            return jsonify({"error": "Password required to update credentials"}), 400
        if not verify_password(password, cfg.get("password_hash") or ""):
            return jsonify({"error": "Incorrect password"}), 401

        if "shopify_token" in data and data["shopify_token"]:
            updates["shopify_token_enc"] = encrypt(password, data["shopify_token"])
            session["shopify_token"]     = data["shopify_token"]

        if "webami_username" in data and data["webami_username"]:
            updates["webami_username_enc"] = encrypt(password, data["webami_username"])
            session["webami_username"]     = data["webami_username"]

        if "webami_password" in data and data["webami_password"]:
            updates["webami_password_enc"] = encrypt(password, data["webami_password"])
            session["webami_password"]     = data["webami_password"]

    if "webami_base_url" in updates:
        base = updates["webami_base_url"].rstrip("/")
        updates["webami_base_url"] = base
        config.WEBAMI_BASE_URL     = base
        session["webami_base_url"] = base

    if "target_margin" in updates:
        m = float(updates["target_margin"])
        if not (0 < m < 1):
            return jsonify({"error": "Margin must be between 0 and 1"}), 400
        config.TARGET_MARGIN       = m
        session["target_margin"]   = m
        updates["target_margin"]   = m

    if "shopify_store" in updates:
        session["shopify_store"] = updates["shopify_store"]

    if updates:
        db.upsert_config(**updates)

    # Reconfigure Webami session if creds changed
    from webami.session import configure as configure_webami
    wu = session.get("webami_username") or ""
    wp = session.get("webami_password") or ""
    wb = session.get("webami_base_url") or config.WEBAMI_BASE_URL
    if wu and wp:
        configure_webami(wb, wu, wp)

    return jsonify({"ok": True})


# ── Stats ──────────────────────────────────────────────────────────

@bp.get("/api/stats")
def get_stats():
    err = _require_auth()
    if err:
        return err
    return jsonify(db.get_stats())


# ── Sync log ───────────────────────────────────────────────────────

@bp.get("/api/log")
def get_log():
    err = _require_auth()
    if err:
        return err
    limit = min(int(request.args.get("limit", 50)), 200)
    return jsonify({"items": db.get_sync_log(limit)})


# ── Artist aliases ─────────────────────────────────────────────────

@bp.get("/api/aliases")
def list_aliases():
    err = _require_auth()
    if err:
        return err
    return jsonify({"items": db.get_artist_aliases()})


@bp.post("/api/aliases")
def create_alias():
    err = _require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    alias     = (data.get("alias_name") or "").strip()
    canonical = (data.get("canonical_name") or "").strip()
    if not alias or not canonical:
        return jsonify({"error": "Both alias and canonical name required"}), 400
    try:
        alias_id = db.create_artist_alias(alias, canonical)
        return jsonify({"ok": True, "id": alias_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@bp.delete("/api/aliases/<int:alias_id>")
def delete_alias(alias_id: int):
    err = _require_auth()
    if err:
        return err
    db.delete_artist_alias(alias_id)
    return jsonify({"ok": True})


# ── UPC aliases ────────────────────────────────────────────────────

@bp.get("/api/upc-aliases")
def list_upc_aliases():
    err = _require_auth()
    if err:
        return err
    return jsonify({"items": db.get_all_aliases()})


@bp.post("/api/upc-aliases")
def create_upc_alias():
    err = _require_auth()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    retired = (data.get("retired_upc") or "").strip()
    active  = (data.get("active_upc") or "").strip()
    notes   = (data.get("notes") or "").strip() or None
    if not retired or not active:
        return jsonify({"error": "Both retired and active UPC required"}), 400
    db.upsert_product_alias(retired, active, notes)
    return jsonify({"ok": True})


@bp.delete("/api/upc-aliases/<retired_upc>")
def delete_upc_alias(retired_upc: str):
    err = _require_auth()
    if err:
        return err
    db.delete_alias(retired_upc)
    return jsonify({"ok": True})
