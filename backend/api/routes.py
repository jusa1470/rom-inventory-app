import logging
import secrets
from typing import Optional

import requests
from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

import db.database as db
from credentials import CredentialStore, CredentialError

from shopify.shopify_service import ShopifySyncService
from webami.webami_service import WebamiSyncService
from sync.services.pricing import PriceSyncService
from sync.services.gap_fill import GapFillService

from shopify.client import ShopifyClient

logger = logging.getLogger(__name__)
router = APIRouter()

_creds = CredentialStore()

# ── service instances ────────────────────────────────────────────────

_webami = WebamiSyncService()
_shopify = ShopifySyncService()
_price_sync = PriceSyncService()
_gap_fill = GapFillService()

_shopify_client = ShopifyClient()

# ── request models ───────────────────────────────────────────────────

class AuthRequest(BaseModel):
    password: str

class PriceSyncRequest(BaseModel):
    upcs: Optional[list[str]] = None

class BulkDeleteRequest(BaseModel):
    product_ids: list[str]

class BulkUpdateRequest(BaseModel):
    products: list[dict]

class GapFillRequest(BaseModel):
    product_ids: Optional[list[str]] = None

class CreateProductRequest(BaseModel):
    products: list[dict]


# ── AUTH ─────────────────────────────────────────────────────────────

@router.post("/auth/verify")
async def verify_password(body: AuthRequest):
    try:
        _creds.verify_app_password(body.password)
        return {"authenticated": True}
    except CredentialError:
        raise HTTPException(status_code=401, detail="Incorrect password")


@router.get("/auth")
def auth(shop: str):
    state = secrets.token_urlsafe(16)

    install_url = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id=change_me"
        f"&scope=write_inventory,read_inventory,read_products,write_products"
        f"&redirect_uri=http://localhost:8000/api/auth/callback"
        f"&state={state}"
    )

    return RedirectResponse(install_url)


@router.get("/auth/callback")
def callback(shop: str, code: str):
    token_url = f"https://{shop}/admin/oauth/access_token"

    resp = requests.post(token_url, json={
        "client_id": "change_me",
        "client_secret": "change_me",
        "code": code,
    })

    resp.raise_for_status()
    return {"status": "installed"}


# ── WEBAMI SYNC ─────────────────────────────────────────────────────

@router.post("/sync/webami/orders/full")
async def webami_orders_full():
    return await run_in_threadpool(_webami.run_full)

@router.post("/sync/webami/orders/incremental")
async def webami_orders_incremental():
    return await run_in_threadpool(_webami.run_incremental)

@router.post("/sync/webami/products/full")
async def webami_products_full():
    return await run_in_threadpool(_webami.run_products_full)

@router.post("/sync/webami/prices")
async def webami_prices(body: PriceSyncRequest):
    return await run_in_threadpool(_price_sync.run_full)


# ── SHOPIFY SYNC ────────────────────────────────────────────────────

@router.post("/sync/shopify/full")
async def shopify_full():
    return await run_in_threadpool(_shopify.run_full)

@router.post("/sync/shopify/incremental")
async def shopify_incremental():
    return await run_in_threadpool(_shopify.run_incremental)


# ── GAP FILL + PRICE SYNC (NO MORE BRIDGE LAYER) ────────────────────

@router.post("/sync/prices")
async def sync_prices():
    return await run_in_threadpool(_price_sync.run_full)


@router.post("/sync/gap-fill")
async def gap_fill(body: GapFillRequest):
    return await run_in_threadpool(_gap_fill.run_full)


# ── CRUD (unchanged but CLEANED) ────────────────────────────────────

@router.post("/shopify/products")
async def create_products(body: CreateProductRequest):
    results = []
    for product in body.products:
        try:
            new_id = await run_in_threadpool(
                _shopify_client.create_product, product
            )
            results.append({"id": new_id, "status": "created"})
        except Exception as e:
            results.append({"input": product, "status": "error", "detail": str(e)})
    return results


@router.put("/shopify/products/{product_id}")
async def update_product(product_id: str, body: dict):
    body["id"] = product_id
    return await run_in_threadpool(_shopify_client.update_product, body)


@router.delete("/shopify/products/{product_id}")
async def delete_product(product_id: str):
    deleted = await run_in_threadpool(
        _shopify_client.delete_product, product_id
    )
    db.delete_shopify_product_local(product_id)
    return {"deleted": deleted}


# ── SEARCH ──────────────────────────────────────────────────────────

@router.get("/webami/products")
async def search_webami(q: str = ""):
    return db.search_webami_products(q)


@router.get("/shopify/products")
async def search_shopify(q: str = ""):
    return db.search_shopify_products(q)


# ── SYNC STATUS ─────────────────────────────────────────────────────

@router.get("/sync/status")
async def sync_status():
    keys = [
        "webami_orders",
        "webami_products",
        "webami_prices",
        "shopify_products",
    ]

    return {
        key: db.get_sync_state(key)
        for key in keys
    }


# ── CANCEL SYSTEM (UNCHANGED) ───────────────────────────────────────

@router.post("/sync/cancel")
async def cancel_sync():
    import sync.cancel as cancel
    cancel.request_cancel()
    return {"cancelled": True}


@router.get("/sync/running")
async def sync_running():
    import sync.cancel as cancel
    return {
        "running": cancel.running_label() or None,
        "last_result": cancel.last_result(),
    }


@router.post("/sync/ack-result")
async def ack_result():
    import sync.cancel as cancel
    cancel.clear_result()
    return {"ok": True}