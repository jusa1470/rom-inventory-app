

from fastapi import APIRouter, Depends, HTTPException, Query

from app import config, db, jobs
from app.auth import get_creds, require_session


router = APIRouter(
    prefix="/api/sync", tags=["sync"], dependencies=[Depends(require_session)]
)

def _launch(creds, need, name, fn, *args, also=()):
    if not all(creds.get(k) for k in need):
        raise HTTPException(400, "Credentials not configured")
    if any(j["name"] in (name, *also) for j in jobs.get_running()):
        raise HTTPException(409, f"{name} job already running")
    return {"job_id": jobs.start(name, fn, *args)}

_WM = ("webami_username", "webami_password")

# Shopify

@router.post("/shopify")
def start_shopify_sync(full: bool = False, creds: dict = Depends(get_creds)):
    return _launch(creds, ("shopify_store", "shopify_token"), "Shopify Sync",
               jobs.run_shopify_sync, creds["shopify_store"], creds["shopify_token"], full)


# WebAMI

@router.post("/webami")
def start_webami_sync(creds: dict = Depends(get_creds)):
    return _launch(creds, _WM, "WebAMI Sync", jobs.run_webami_sync,
               config.WEBAMI_BASE_URL, creds["webami_username"], creds["webami_password"])


@router.get("/webami-stats")
def webami_stats():
    return db.get_webami_stats()


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


# Webami

@router.post("/webami-products")
def start_webami_resolve(refetch: bool = False, creds: dict = Depends(get_creds)):
    return _launch(creds, _WM, "WebAMI Products", jobs.run_webami_resolve,
               config.WEBAMI_BASE_URL, creds["webami_username"], creds["webami_password"],
               refetch, also=("WebAMI Sync",))


@router.post("/prices")
def start_price_check(creds: dict = Depends(get_creds)):
    return _launch(creds, _WM, "Price Check", jobs.run_price_check,
               config.WEBAMI_BASE_URL, creds["webami_username"], creds["webami_password"])