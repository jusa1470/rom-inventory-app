

from fastapi import APIRouter, Depends, HTTPException, Query

from app import db, jobs
from app.auth import get_creds, require_session


router = APIRouter(
    prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_session)]
)


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