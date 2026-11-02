from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import config, db
from app.auth import get_creds, require_session
from app.shopify.shopify_client import ShopifyClient
from app.webami import WebamiClient

router = APIRouter(
    prefix="/api/prices", tags=["prices"], dependencies=[Depends(require_session)]
)


def _f(title: str | None = None, vendor: str | None = None, type: str | None = None,
       increase: bool = False, decrease: bool = False, review: bool = False) -> dict:
    return {"title": (title or "").strip(), "vendor": (vendor or "").strip(), "type": type or "",
            "increase": increase, "decrease": decrease, "review": review}


class Ids(BaseModel):
    variant_ids: list[str]


class PriceIn(BaseModel):
    price: float


class Resolve(BaseModel):
    variant_id: str
    upc: str


@router.get("")
def list_changes(page: int = Query(1, ge=1), per_page: int = Query(50, ge=1, le=200),
                 f: dict = Depends(_f)):
    return {**db.list_price_changes(f, page, per_page), "page": page, "per_page": per_page}


@router.post("/resolve")
def resolve(body: Resolve, creds: dict = Depends(get_creds)):
    client = WebamiClient(config.WEBAMI_BASE_URL,
                          creds.get("webami_username"), creds.get("webami_password"))
    try:
        page = client.fetch_product(f"/{body.upc.strip()}")
    except Exception as e:
        raise HTTPException(502, str(e))
    if not page.get("title") or page.get("price") is None:
        raise HTTPException(404, "No valid WebAMI product or price for that UPC")
    db.resolve_price_check(body.variant_id, body.upc.strip(), page["title"], page["price"])
    return {"ok": True}


@router.get("/queue")
def get_queue():
    return {"items": db.list_price_queue()}


@router.post("/queue/add")
def queue_add(body: Ids):
    db.price_queue_add(body.variant_ids)
    return {"ok": True}


@router.post("/queue/remove")
def queue_remove(body: Ids):
    db.price_queue_remove(body.variant_ids)
    return {"ok": True}


@router.post("/queue/filtered")
def queue_filtered(action: str, f: dict = Depends(_f)):
    db.price_queue_filtered(f, action == "add")
    return {"ok": True}


@router.put("/queue/{variant_id}")
def queue_set(variant_id: str, body: PriceIn):
    if body.price <= 0:
        raise HTTPException(400, "Price must be positive")
    db.price_queue_set(variant_id, round(body.price, 2))
    return {"ok": True}


@router.post("/queue/push")
def queue_push(creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True, "pushed": 0, "errors": []}
    cfg = db.get_config()
    client = ShopifyClient(creds["shopify_store"], creds["shopify_token"],
                           cfg.get("shopify_api_version") or config.DEFAULT_API_VERSION)
    by: dict[str, list[dict]] = {}
    for r in db.list_price_queue():
        by.setdefault(r["product_id"], []).append(r)
    pushed, errors = 0, []
    for pid, items in by.items():
        vs = [{"id": r["variant_id"], "price": f"{r['new_price']:.2f}",
               "cost": f"{r['new_cost']:.2f}"} for r in items]
        try:
            client.update_variants(pid, vs, cfg)
        except Exception as e:
            errors.append(f"{items[0]['title']}: {e}")
            continue
        db.update_local(pid, {}, vs)
        db.price_queue_remove([r["variant_id"] for r in items])
        pushed += len(items)
    return {"ok": not errors, "pushed": pushed, "errors": errors}