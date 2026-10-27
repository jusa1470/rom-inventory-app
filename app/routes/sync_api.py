

from fastapi import APIRouter, Depends
from flask import jsonify

from app import db, db, jobs
from app.auth import require_session


router = APIRouter(
    prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_session)]
)


@router.post("/shopify")
def start_shopify_sync(full: bool = False):
    cfg = jobs.get_config()
    creds = jobs.get_creds()
    store = cfg.get("shopify_store")
    token = creds.get("shopify_token_enc")
    if not store or not token:
        return jsonify({"error": "Shopify credentials not configured"}), 400
    if any(job["name"] == "Shopify Sync" for job in jobs.get_running()):
        return jsonify({"error": "Shopify Sync job already running"}), 409
    job_id = jobs.start("Shopify Sync", jobs.run_shopify_sync, store, token, full)
    return jsonify({"job_id": job_id})


@router.get("/status/{job_id}")
def sync_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    return jsonify({"ok": jobs.cancel(job_id)})


@router.get("/running")
def running_jobs():
    return jsonify({"jobs": jobs.get_running()})


@router.get("/log")
def get_sync_log(limit: int = 15):
    if limit < 1 or limit > 200:
        return jsonify({"error": "Limit must be between 1 and 200"}), 400
    return jsonify({"items": db.get_sync_log(limit)})