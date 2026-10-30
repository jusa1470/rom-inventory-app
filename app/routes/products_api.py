from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import config, db
from app.auth import get_creds, require_session
from app.db.connection import strip_gid
from app.shopify.shopify_client import ShopifyClient

router = APIRouter(
    prefix="/api/products", tags=["products"], dependencies=[Depends(require_session)]
)


class ProductIn(BaseModel):
    title: str | None = None
    vendor: str | None = None
    status: Literal["ACTIVE", "DRAFT", "ARCHIVED"] | None = None
    product_type: str | None = None
    tags: list[str] | None = None
    handle: str | None = None
    category: str | None = None
    genres: list[str] | None = None
    type: str | None = None
    upc: str | None = None


class VariantIn(BaseModel):
    id: str
    inventory_item_id: str | None = None
    title: str | None = None
    upc: str | None = None
    description: str | None = None
    release_date: str | None = None
    variant_tags: str | None = None
    price: str | None = None
    cost: str | None = None
    inventory_quantity: int | None = None
    weight: float | None = None


class ProductUpdate(BaseModel):
    product: ProductIn = ProductIn()
    variants: list[VariantIn] = []


@router.get("")
def list_products(
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=200),
    sort: str = "title",
    direction: Literal["asc", "desc"] = Query("asc", alias="dir"),
    title: str | None = None,
    vendor: str | None = None,
    status: list[str] | None = Query(None),
    category: list[str] | None = Query(None),
    product_type: list[str] | None = Query(None, alias="type"),
    genres: list[str] | None = Query(None),
    tags: list[str] | None = Query(None),
):
    per_page = per_page or db.get_config().get("page_size", 100)
    candidates = {
        "title": [title.strip()] if title and title.strip() else None,
        "vendor": [vendor.strip()] if vendor and vendor.strip() else None,
        "status": status,
        "category": category,
        "type": product_type,
        "genres": genres,
        "tags": tags,
    }
    filters = {k: v for k, v in candidates.items() if v}
    result = db.list_products(
        q.strip() if q else "", page, per_page, sort, direction, filters
    )
    return {
        "items": result["items"],
        "total": result["total"],
        "page": page,
        "per_page": per_page,
    }


@router.get("/filter-options")
def filter_options():
    return db.get_filter_options()


@router.get("/{product_id}")
def get_product_detail(product_id: str):
    product = db.get_product_detail(product_id)
    if not product:
        raise HTTPException(404, "Product not found")
    return product


@router.put("/{product_id}")
def update_product_fields(product_id: str, body: ProductUpdate, creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    p = body.product.model_dump(exclude_unset=True)
    vs = [v.model_dump(exclude_unset=True) for v in body.variants]
    cfg = db.get_config()
    client = ShopifyClient(
        creds["shopify_store"], creds["shopify_token"],
        cfg.get("shopify_api_version") or config.DEFAULT_API_VERSION,
    )
    try:
        if "category" in p:
            cat = client.find_category(p.pop("category"))
            p["category_id"] = strip_gid(cat["id"])
            p["category_name"] = cat["name"]
        if p:
            client.update_product(product_id, p, cfg)
        if vs:
            client.update_variants(product_id, vs, cfg)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    db.update_local(product_id, p, vs)
    return {"ok": True}