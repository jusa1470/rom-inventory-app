from flask import Blueprint, jsonify, request, session

import db.database as db
from services import jobs
from services.shopify_sync import run_shopify_sync
from services.matcher import run_matcher

bp = Blueprint("shopify", __name__)


def _require_auth():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    return None


def _shopify_creds():
    return session.get("shopify_store"), session.get("shopify_token")


@bp.post("/api/sync/shopify")
def start_shopify_sync():
    err = _require_auth()
    if err:
        return err
    store, token = _shopify_creds()
    if not store or not token:
        return jsonify({"error": "Shopify credentials not configured"}), 400
    job_id = jobs.start("Shopify Sync", run_shopify_sync, store, token)
    return jsonify({"job_id": job_id})


@bp.post("/api/sync/matcher")
def start_matcher():
    err = _require_auth()
    if err:
        return err
    if db.count_shopify_products() == 0:
        return jsonify({"error": "Sync Shopify products first"}), 400
    job_id = jobs.start("Batch Matcher", run_matcher)
    return jsonify({"job_id": job_id})


@bp.post("/api/sync/duplicates")
def start_duplicate_check():
    err = _require_auth()
    if err:
        return err
    from services.matcher import detect_shopify_duplicates
    job_id = jobs.start("Duplicate Check", lambda job_id: {"duplicates": detect_shopify_duplicates()})
    return jsonify({"job_id": job_id})


@bp.get("/api/sync/status/<job_id>")
def sync_status(job_id: str):
    err = _require_auth()
    if err:
        return err
    return jsonify(jobs.get(job_id))


@bp.post("/api/sync/cancel/<job_id>")
def cancel_job(job_id: str):
    err = _require_auth()
    if err: return err
    return jsonify({"ok": jobs.cancel(job_id)})


@bp.get("/api/sync/running")
def running_jobs():
    err = _require_auth()
    if err: return err
    return jsonify({"jobs": jobs.get_running()})