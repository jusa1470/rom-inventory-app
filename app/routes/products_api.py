import re as _re
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

_FMT = {"lp": "Vinyl", "cd": "CD", "cassette": "Cassette"}


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
    release_date: str | None = None


class VariantIn(BaseModel):
    id: str | None = None
    inventory_item_id: str | None = None
    title: str | None = None
    upc: str | None = None
    description: str | None = None
    release_date: str | None = None
    variant_tags: str | None = None
    media_id: str | None = None
    price: str | None = None
    cost: str | None = None
    inventory_quantity: int | None = None
    weight: float | None = None
    barcode: str | None = None
    image_url: str | None = None
    channels: list[str] | None = None


class ProductUpdate(BaseModel):
    product: ProductIn = ProductIn()
    variants: list[VariantIn] = []


def _inch(fmt: str | None) -> str | None:
    m = _re.search(r'\b(7|10)\s*(?:"|”|in\b|-?inch)', fmt or "", _re.I)
    return f"{m.group(1)}-inch" if m and "single" in (fmt or "").lower() else None


def _defaults(typ: str) -> dict:
    if not typ:
        return {}
    c = db.get_conn()

    def top(col):
        r = c.execute(
            f"SELECT {col} FROM shopify_products WHERE type=? AND {col} IS NOT NULL "
            f"AND {col}!='' GROUP BY {col} ORDER BY COUNT(*) DESC LIMIT 1", (typ,)).fetchone()
        return r[0] if r else None
    d = {"type": typ, "product_type": top("product_type") or typ,
         "category": top("category_name"), "tags": f"New, {typ}"}
    return {k: v for k, v in d.items() if v}


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


def _client(creds: dict) -> ShopifyClient:
    cfg = db.get_config()
    return ShopifyClient(creds["shopify_store"], creds["shopify_token"],
                         cfg.get("shopify_api_version") or config.DEFAULT_API_VERSION)


@router.get("/channels")
def channels(creds: dict = Depends(get_creds)):
    try:
        return {"items": _client(creds).list_channels()}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.get("/{product_id}/variant-channels")
def variant_channels(product_id: str, creds: dict = Depends(get_creds)):
    p = db.get_product_detail(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    cfg = db.get_config()
    client = ShopifyClient(
        creds["shopify_store"], creds["shopify_token"],
        cfg.get("shopify_api_version") or config.DEFAULT_API_VERSION,
    )
    try:
        return {"items": {v["variant_id"]: client.variant_channels(v["variant_id"])
                          for v in p["variants"]}}
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.post("")
def create_product(body: ProductUpdate, creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    p = body.product.model_dump(exclude_unset=True)
    vs = [v.model_dump(exclude_unset=True) for v in body.variants]
    client = _client(creds)
    cfg = db.get_config()
    try:
        cat = p.pop("category", "")
        if cat:
            c = client.find_category(cat)
            p["category_id"] = strip_gid(c["id"])
            p["category_name"] = c["name"]
        img = p.pop("image_url", None)
        pid = client.create_product(p, cfg)
        created = client.create_variants(pid, vs, cfg) if vs else []
        all_ids = [c["id"] for c in client.list_channels()]
        for v, c in zip(vs, created):
            client.set_variant_channels(
                c["id"], v["channels"] if v.get("channels") is not None else all_ids)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    db.add_local_product(pid, p)
    if vs:
        db.add_local_variants(pid, vs, created)
    return {"ok": True, "product_id": pid}


@router.delete("/{product_id}")
def delete_product(product_id: str, creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    client = _client(creds)
    cfg = db.get_config()
    try:
        client.delete_product(product_id)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    db.delete_local_product(product_id)
    return {"ok": True}


@router.delete("/{product_id}/variants/{variant_id}")
def delete_variant(product_id: str, variant_id: str, creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    cfg = db.get_config()
    client = _client(creds)
    try:
        client.delete_variant(product_id, variant_id)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    db.delete_local_variant(variant_id)
    return {"ok": True}


@router.get("/by-upc/{upc}")
def by_upc(upc: str, creds: dict = Depends(get_creds)):
    upc = upc.strip()
    try:
        client = WebamiClient(config.WEBAMI_BASE_URL,
                              creds.get("webami_username"), creds.get("webami_password"))
        w = client.fetch_product(f"/{upc}")
    except Exception as e:
        raise HTTPException(502, str(e))
    if not w.get("title"):
        raise HTTPException(404, "UPC not found in WebAMI")
    s = db.suggest_parts(w)
    vendor = db.canon(w.get("artist") or w.get("vendor"))
    inch = _inch(w.get("product_type"))
    typ = "Vinyl" if inch else _FMT.get((w.get("product_type") or "").strip().lower(), "")
    lbs = {"lb": 1, "lbs": 1, "oz": 1 / 16, "kg": 2.20462, "g": 1 / 453.592}
    cost = w.get("price")
    color = s["color"]
    if inch:
        c = _re.sub(r"(?i)\s*vinyl$", "", color or "").strip()
        words = [x for x in c.split() if x.lower() not in ("and", "&", "none")]
        c = " ".join(words) if words and c.lower() != "none" else ""
        color = f"{c} {inch}".strip().title().replace("-Inch", "-inch")
    var = {
        "edition": s["edition"], "color": color, "attributes": s["attributes"],
        "upc": upc, "description": w.get("description"),
        "release_date": w.get("release_date"),
        "cost": f"{cost:.2f}" if cost is not None else None,
        "price": f"{cost / 0.66:.2f}" if cost is not None else None,
        "weight": (round(w["weight"] * lbs.get(w.get("weight_unit"), 1), 4)
                   if w.get("weight") is not None else None),
        "image_url": w.get("image_url"),
    }
    var = {k: str(v) for k, v in var.items() if v not in (None, "", "None")}
    prod = {"title": s["title"], "vendor": vendor, **_defaults(typ),
            "genres": ", ".join(g for g in (w.get("genres") or "").split(",") if g)}
    prod = {k: v for k, v in prod.items() if v}
    conn = db.get_conn()
    ve = conn.execute(
        "SELECT v.variant_id, v.title, p.product_id, p.title AS product_title "
        "FROM shopify_variants v JOIN shopify_products p ON p.product_id=v.product_id "
        "WHERE v.upc=? LIMIT 1", (upc,)).fetchone()
    if ve:
        pe = {"product_id": ve["product_id"], "title": ve["product_title"]}
    else:
        r = conn.execute(
            "SELECT product_id, title FROM shopify_products "
            "WHERE title=? COLLATE NOCASE AND vendor=? COLLATE NOCASE LIMIT 1",
            (prod["title"], vendor)).fetchone()
        pe = dict(r) if r else None
    return {"image_url": w.get("image_url"), "webami_title": w["title"],
            "prefill": {"product": prod, "variant": var},
            "variant_exists": dict(ve) if ve else None, "product_exists": pe}


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
                              "release_date": page.get("release_date"),
                              "image_url": page.get("image_url"),
                              "genres": page.get("genres"),
                              "weight": page.get("weight"),
                              "weight_unit": page.get("weight_unit"),
                              "product_type": page.get("product_type") or r["format"],
                              "upc": r["upc"], "price": page.get("price"),
                              "canon_artist": db.alias_for(page.get("artist") or r["artist"]),
                              "tier": 2, "source": "search (page verified)",
                              "kw_extra": extra,
                              "artist_match": (page.get("artist") or r["artist"]).lower()
                                              == (p["vendor"] or "").lower()})
            cands += found
        except Exception as e:
            raise HTTPException(502, str(e))
    cands.sort(key=lambda c: c["tier"])
    db.decorate_candidates(variant_id, cands)
    p["siblings"] = [x for x in p["variants"] if x["variant_id"] != variant_id]
    for c in cands:
        c["suggested"] = db.suggest_parts(c)
        c["defaults"] = _defaults(_FMT.get((c.get("product_type") or "").strip().lower(), ""))
    return {"items": cands[:15]}


@router.get("/{product_id}/receipts")
def product_receipts(product_id: str):
    return {"items": db.list_product_receipts(product_id)}


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
    all_vs = [v.model_dump(exclude_unset=True) for v in body.variants]
    new_vs = [v for v in all_vs if not v.get("id")]
    vs = [v for v in all_vs if v.get("id")]
    client = _client(creds)
    cfg = db.get_config()
    try:
        if "category" in p:
            cat = client.find_category(p.pop("category"))
            p["category_id"] = strip_gid(cat["id"])
            p["category_name"] = cat["name"]
        if p:
            client.update_product(product_id, p, cfg)
        if vs:
            client.update_variants(product_id, vs, cfg)
        existing = (db.get_product_detail(product_id) or {}).get("variants", [])
        only_default = len(existing) == 1 and (
            not existing[0]["title"] or existing[0]["title"] == "Default Title")
        created = (client.create_variants(product_id, new_vs, cfg, only_default)
                   if new_vs else [])
        all_ids = None
        for v in vs:
            if v.get("channels") is not None:
                client.set_variant_channels(v["id"], v["channels"])
        for v, c in zip(new_vs, created):
            if v.get("channels") is None:
                all_ids = all_ids or [x["id"] for x in client.list_channels()]
            client.set_variant_channels(
                c["id"], v["channels"] if v.get("channels") is not None else all_ids)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    db.update_local(product_id, p, vs)
    if new_vs:
        db.add_local_variants(product_id, new_vs, created)
    for v in vs:
        if v.get("upc"):
            db.drop_from_match_cache(v["id"])
    return {"ok": True}