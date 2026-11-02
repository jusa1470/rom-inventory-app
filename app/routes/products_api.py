from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import config, db
from app.auth import get_creds, require_session
from app.db.connection import strip_gid
from app.shopify.shopify_client import ShopifyClient
from app.webami.webami_client import WebamiClient

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


@router.get("/{product_id}/webami-suggestions")
def webami_suggestions(product_id: str, search: bool = False, variant_id: str | None = None, creds: dict = Depends(get_creds)):
    p = db.get_product_detail(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    tags = [t.strip().lower() for t in (p.get("tags") or "").split(",")]
    if p["title"].strip().endswith("- U") or "used" in tags:
        return {"items": []}
    v = next((x for x in p["variants"] if x["variant_id"] == variant_id), None)
    p["variant_title"] = v["title"] if v else None
    cands = db.suggest_local(p)
    if search or not any(c["tier"] == 1 for c in cands):
        stype = p.get("type") or p.get("product_type") or ""
        fmt = {"Vinyl": "LP", "CD": "CD", "Cassette": "Cassette"}.get(stype, "")
        try:
            client = WebamiClient(config.WEBAMI_BASE_URL,
                                  creds.get("webami_username"), creds.get("webami_password"))
            seen = {c["upc"] for c in cands}
            found = []
            kw = " ".join(sorted(db.variant_kws(p["variant_title"]))) if v else ""
            results = client.search_site(p["title"], p["vendor"] or "", fmt, kw) if kw else []
            got = {x["upc"] for x in results}
            results += [x for x in client.search_site(p["title"], p["vendor"] or "", fmt)
                        if x["upc"] not in got]
            for r in results[:8]:
                if r["upc"] in seen or not db.format_ok(stype, r["format"]):
                    continue
                try:
                    page = client.get_product(f"/{r['upc']}")
                except Exception:
                    continue
                if not page.get("title"):
                    continue
                if not db.good_match(p["title"], p["vendor"],
                        page["title"], page.get("artist") or r["artist"]):
                    continue
                missing, extra = db.kw_eval(p, {"title": page["title"], "features": page.get("features"),
                                                "description": page.get("description")})
                if missing:
                    continue
                found.append({"id": None, "title": page["title"],
                              "artist": page.get("artist") or r["artist"],
                              "features": page.get("features"),
                              "description": page.get("description"),
                              "product_type": page.get("product_type") or r["format"],
                              "upc": r["upc"], "price": page.get("price"),
                              "tier": 2, "source": "search (page verified)",
                              "kw_extra": extra,
                              "artist_match": (page.get("artist") or r["artist"]).lower()
                                              == (p["vendor"] or "").lower()})
            cands += found
        except Exception as e:
            raise HTTPException(502, str(e))
    cands.sort(key=lambda c: c["tier"])
    for c in cands:
        c["suggested"] = db.suggest_parts(c)
    return {"items": cands[:15]}


@router.get("/{product_id}")
def get_shopify_product_route(product_id: str):
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
    for v in vs:
        if v.get("upc"):
            db.drop_from_match_cache(v["id"])
    return {"ok": True}