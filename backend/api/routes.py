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
from sync.bridge import BridgeService

from shopify.client import ShopifyClient

logger: logging.Logger = logging.getLogger(__name__)
router = APIRouter()

_creds = CredentialStore()

# ── service instances ────────────────────────────────────────────────

_webami = WebamiSyncService()
_shopify = ShopifySyncService()
_bridge = BridgeService()

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

class AliasRequest(BaseModel):
    alias_upc: str
    canonical_upc: str

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
    state: str = secrets.token_urlsafe(16)

    install_url: str = (
        f"https://{shop}/admin/oauth/authorize"
        f"?client_id=changeme"
        f"&scope=write_inventory,read_inventory,read_products,write_products"
        f"&redirect_uri=http://localhost:8000/api/auth/callback"
        f"&state={state}"
    )

    return RedirectResponse(install_url)

@router.get("/auth/callback")
def callback(shop: str, code: str):
    token_url: str = f"https://{shop}/admin/oauth/access_token"

    resp: requests.Response = requests.post(token_url, json={
        "client_id": "changeme",
        "client_secret": "changeme",
        "code": code,
    })

    resp.raise_for_status()
    data = resp.json()
    print("Token: ", data["access_token"])
    return {"status": "installed"}

# ── WEBAMI SYNC ─────────────────────────────────────────────────────

@router.post("/sync/webami/orders/full")
async def webami_orders_full():
    return await run_in_threadpool(_webami.sync_orders_full)

@router.post("/sync/webami/orders/recent")
async def webami_orders_recent():
    return await run_in_threadpool(_webami.sync_orders_recent)

@router.post("/sync/webami/products/full")
async def webami_products_full():
    return await run_in_threadpool(_webami.sync_products_full)

@router.patch("/webami/orders/{guid}/items/{item_id}")
async def update_order_item(guid: str, item_id: int, body: dict):
    qty: int = body.get("quantity_received", 0)
    db.mark_item_received(item_id, qty)
    return {"ok": True}

@router.post("/sync/webami/prices")
async def webami_prices():
    return await run_in_threadpool(_webami.sync_prices)

@router.post("/webami/products/alias")
async def create_alias(body: AliasRequest):
    db.upsert_product_alias(body.alias_upc, body.canonical_upc)
    return {"ok": True}

# ── SHOPIFY SYNC ────────────────────────────────────────────────────

@router.post("/sync/shopify/full")
async def shopify_full():
    return await run_in_threadpool(_shopify.run_full)

@router.post("/sync/shopify/recent")
async def shopify_recent():
    return await run_in_threadpool(_shopify.run_recent)

# ── GAP FILL + PRICE SYNC ───────────────────────────────────────────

@router.post("/sync/prices")
async def sync_prices():
    return await run_in_threadpool(_bridge.push_prices)

@router.post("/sync/gap-fill")
async def gap_fill(body: GapFillRequest):
    ids: list[str] | None = body.product_ids or None
    return await run_in_threadpool(lambda: _bridge.fill_gaps(ids))

# ── CRUD ────────────────────────────────────────────────────────────

@router.post("/shopify/products")
async def create_products(body: CreateProductRequest):
    results = []
    for product in body.products:
        try:
            new_id: str = await run_in_threadpool(
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
    deleted: str = await run_in_threadpool(
        _shopify_client.delete_product, product_id
    )
    db.delete_shopify_product_local(product_id)
    return {"deleted": deleted}

# ── SEARCH ──────────────────────────────────────────────────────────

@router.get("/webami/orders")
async def search_webami_orders(q: str = ""):
    return db.search_webami_orders(q)

@router.get("/webami/orders/count")
async def count_webami_orders():
    return db.count_webami_orders()

@router.get("/webami/products")
async def search_webami_products(q: str = ""):
    return db.search_webami_products(q)

@router.get("/webami/products/count")
async def count_webami_products():
    return db.count_webami_products()

@router.get("/shopify/products")
async def search_shopify_products(q: str = ""):
    return db.search_shopify_products(q)

@router.get("/shopify/products/count")
async def count_shopify_products():
    return db.count_shopify_products()

# ── SYNC STATUS ─────────────────────────────────────────────────────

@router.get("/sync/status")
async def sync_status():
    keys: list[str] = [
        "webami_orders",
        "webami_products",
        "shopify_products",
        "webami_prices",
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