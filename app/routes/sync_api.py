

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config, db, jobs
from app.auth import get_creds, require_session


router = APIRouter(
    prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_session)]
)

# Shopify

@router.post("/shopify")
def start_shopify_sync(full: bool = False, creds: dict = Depends(get_creds)):
    store = creds.get("shopify_store")
    token = creds.get("shopify_token")
    if not store or not token:
        raise HTTPException(400, "Shopify credentials not configured")
    if any(job["name"] == "Shopify Sync" for job in jobs.get_running()):
        raise HTTPException(409, "Shopify Sync job already running")
    job_id = jobs.start("Shopify Sync", jobs.run_shopify_sync, store, token, full)
    return {"job_id": job_id}


# WebAMI

@router.post("/webami")
def start_webami_sync(creds: dict = Depends(get_creds)):
    user, pw = creds.get("webami_username"), creds.get("webami_password")
    if not user or not pw:
        raise HTTPException(400, "WebAMI credentials not configured")
    if any(job["name"] == "WebAMI Sync" for job in jobs.get_running()):
        raise HTTPException(409, "WebAMI Sync job already running")
    job_id = jobs.start("WebAMI Sync", jobs.run_webami_sync, config.WEBAMI_BASE_URL, user, pw)
    return {"job_id": job_id}


# Jobs

@router.get("/status/{job_id}")
def sync_status(job_id: str):
    job = jobs.get(job_id)
    if not job or job["status"] == "not_found":
       raise HTTPException(404, "Job not found")
    return job


@router.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    return {"ok": jobs.cancel(job_id)}


@router.get("/running")
def running_jobs():
    return {"jobs": jobs.get_running()}


@router.get("/log")
def get_sync_log(limit: int = Query(15, ge=1, le=200)):
    return {"items": db.get_sync_log(limit)}