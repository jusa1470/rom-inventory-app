from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app import config, db
from app.auth import get_creds, require_session
from app.shopify.shopify_client import ShopifyClient

router = APIRouter(
    prefix="/api/orders", tags=["orders"], dependencies=[Depends(require_session)]
)


class Line(BaseModel):
    upc: str
    qty: int


class Stage(BaseModel):
    lines: list[Line]


class QtyIn(BaseModel):
    qty: int


class ResolveIn(BaseModel):
    action: Literal["map", "variant", "new"]
    variant_id: str | None = None
    product_id: str | None = None
    title: str | None = None
    vtitle: str | None = None


class Push(BaseModel):
    create_new: bool = True
    cost_keys: list[str] = []
    keys: list[str] | None = None


class Keys(BaseModel):
    keys: list[str]


_LBS = {"lb": 1, "lbs": 1, "oz": 1 / 16, "kg": 2.20462, "g": 1 / 453.592}


def _vtitle(s: dict) -> str:
    none = lambda x: not x or x.lower() == "none"
    return " | ".join(x for x in (s["edition"] or "Standard",
                                  None if none(s["color"]) else s["color"],
                                  None if none(s["attributes"]) else s["attributes"]) if x)


def _client(creds: dict):
    cfg = db.get_config()
    return ShopifyClient(creds["shopify_store"], creds["shopify_token"],
                         cfg.get("shopify_api_version") or config.DEFAULT_API_VERSION), cfg


def _left(guid: str, upc: str) -> int:
    o = db.get_webami_order(guid)
    ls = [i for i in (o or {}).get("items", []) if i["upc"] == upc]
    return max(0, sum(i["quantity"] for i in ls) - ls[0]["received"]) if ls else 0


def _wp_for(guid: str, upc: str) -> dict:
    o = db.get_webami_order(guid)
    it = next((i for i in (o or {}).get("items", []) if i["upc"] == upc), None)
    wp = it and it.get("product_id") and db.get_webami_product_by_id(it["product_id"])
    if not wp:
        raise HTTPException(404, "No WebAMI product for this item")
    return wp


def _build(wp: dict, upc: str, qty: int = 0):
    s = db.suggest_parts(wp)
    fmt = {"LP": "Vinyl"}.get(wp.get("product_type"), wp.get("product_type"))
    genres = [g.strip() for g in (wp.get("genres") or "").split(",") if g.strip()]
    p = {"title": s["title"], "vendor": db.canon(wp.get("artist") or wp.get("vendor")),
         "status": "ACTIVE", "type": fmt, "genres": genres}
    v = {"title": _vtitle(s), "upc": upc, "inventory_quantity": qty,
         "description": wp.get("description") or "",
         "release_date": wp.get("release_date") or ""}
    if wp.get("price") is not None:
        v |= {"cost": f"{wp['price']:.2f}", "price": f"{wp['price'] / 0.66:.2f}"}
    if wp.get("weight") is not None:
        v["weight"] = round(wp["weight"] * _LBS.get((wp.get("weight_unit") or "").lower(), 1), 4)
    return p, v


def _apply(client, cfg, orders: dict, guid: str, upc: str, qty: int, create_new: bool,
           cost: float | None = None):
    v = db.get_variant_by_upc(upc)
    if v:
        vs = [{"id": v["variant_id"], "inventory_item_id": v["inventory_item_id"],
               "inventory_quantity": (v["inventory_quantity"] or 0) + qty}]
        if cost is not None:
            vs[0] |= {"cost": f"{cost:.2f}", "price": f"{cost / 0.66:.2f}"}
        client.update_variants(v["product_id"], vs, cfg)
        db.update_local(v["product_id"], {}, vs)
        db.log_receipt(guid, upc, qty, v["variant_id"])
        return "updated"
    if not create_new:
        return None
    if guid not in orders:
        orders[guid] = db.get_webami_order(guid)
    it = next((i for i in (orders[guid] or {}).get("items", []) if i["upc"] == upc), None)
    wp = it and it.get("product_id") and db.get_webami_product_by_id(it["product_id"])
    if not wp:
        return None
    p, variant = _build(wp, upc, qty)
    pid = client.create_product(p, cfg)
    made = client.create_variants(pid, [variant], cfg)
    db.add_local_product(pid, p)
    db.add_local_variants(pid, [variant], made)
    db.log_receipt(guid, upc, qty, made[0]["id"])
    return "created"


@router.get("")
def list_orders(
    q: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    status: str = "",
):
    res = db.list_webami_orders(q.strip() if q else "", page, per_page, status)
    return {**res, "page": page, "per_page": per_page}


# fixed paths must stay above /{guid}
@router.get("/outstanding")
def outstanding():
    return {"items": db.outstanding_items()}


@router.get("/queue")
def get_queue():
    return {"items": db.rq_list()}


@router.get("/{guid}/items/{upc}/candidates")
def candidates(guid: str, upc: str):
    wp = _wp_for(guid, upc)
    s = db.suggest_parts(wp)
    return {"webami": {**wp, "suggested": s, "vtitle": _vtitle(s)},
            "items": db.shopify_candidates(wp)}


@router.post("/{guid}/items/{upc}/resolve")
def resolve(guid: str, upc: str, body: ResolveIn, creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    wp = _wp_for(guid, upc)
    client, cfg = _client(creds)
    try:
        if body.action == "map":
            v = db.get_variant(body.variant_id or "")
            if not v:
                raise HTTPException(404, "Variant not found")
            pf = {"title": body.title} if body.title else {}
            vs = [{"id": v["variant_id"], "upc": upc}]
            if body.vtitle:
                vs[0]["title"] = body.vtitle
            if pf:
                client.update_product(v["product_id"], pf, cfg)
            client.update_variants(v["product_id"], vs, cfg)
            db.update_local(v["product_id"], pf, vs)
            db.drop_from_match_cache(v["variant_id"])
        elif body.action == "variant":
            if not body.product_id:
                raise HTTPException(400, "product_id required")
            _, variant = _build(wp, upc)
            if body.vtitle:
                variant["title"] = body.vtitle
            made = client.create_variants(body.product_id, [variant], cfg)
            db.add_local_variants(body.product_id, [variant], made)
        else:
            p, variant = _build(wp, upc)
            if body.title:
                p["title"] = body.title
            if body.vtitle:
                variant["title"] = body.vtitle
            pid = client.create_product(p, cfg)
            made = client.create_variants(pid, [variant], cfg)
            db.add_local_product(pid, p)
            db.add_local_variants(pid, [variant], made)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    return {"ok": True}


@router.post("/queue/remove")
def queue_remove_many(body: Keys):
    for k in body.keys:
        g, u = k.split("|", 1)
        db.rq_set(g, u, 0)
    return {"ok": True}


@router.delete("/queue")
def queue_clear():
    for r in db.rq_list():
        db.rq_set(r["order_guid"], r["upc"], 0)
    return {"ok": True}


@router.put("/queue/{guid}/{upc}")
def queue_set(guid: str, upc: str, body: QtyIn):
    qty = min(body.qty, _left(guid, upc))
    db.rq_set(guid, upc, qty)
    return {"ok": True, "qty": qty}


@router.delete("/queue/{guid}/{upc}")
def queue_remove(guid: str, upc: str):
    db.rq_set(guid, upc, 0)
    return {"ok": True}


@router.post("/queue/push")
def queue_push(body: Push = Push(), creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    client, cfg = _client(creds)
    orders: dict = {}
    updated = created = 0
    skipped, errors = [], []
    for r in db.rq_list():
        if body.keys is not None and f"{r['order_guid']}|{r['upc']}" not in body.keys:
            continue
        upd = f"{r['order_guid']}|{r['upc']}" in body.cost_keys and r["wm_cost"] is not None
        try:
            res = _apply(client, cfg, orders, r["order_guid"], r["upc"], r["qty"],
                         body.create_new, r["wm_cost"] if upd else None)
        except Exception as e:
            errors.append(f"{r['upc']}: {e}")
            continue
        if res is None:
            skipped.append(r["upc"])
            continue
        db.rq_set(r["order_guid"], r["upc"], 0)
        updated += res == "updated"
        created += res == "created"
    return {"ok": not errors, "updated": updated, "created": created,
            "skipped": skipped, "errors": errors}


@router.post("/receipts/{rid}/undo")
def undo_receipt(rid: int, creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    r = db.get_receipt(rid)
    if not r or r["reversed_at"]:
        raise HTTPException(404, "Receipt not found or already undone")
    v = db.get_variant(r["variant_id"]) if r["variant_id"] else None
    if v:
        client, cfg = _client(creds)
        vs = [{"id": v["variant_id"], "inventory_item_id": v["inventory_item_id"],
               "inventory_quantity": max(0, (v["inventory_quantity"] or 0) - r["qty"])}]
        try:
            client.update_variants(v["product_id"], vs, cfg)
        except RuntimeError as e:
            raise HTTPException(502, str(e))
        db.update_local(v["product_id"], {}, vs)
    db.reverse_receipt(rid)
    return {"ok": True}


@router.post("/{guid}/stage")
def stage(guid: str, body: Stage):
    for ln in body.lines:
        db.rq_set(guid, ln.upc, min(ln.qty, _left(guid, ln.upc)))
    return {"ok": True}


@router.get("/{guid}/receipts")
def order_receipts(guid: str):
    return {"items": db.list_order_receipts(guid)}


@router.get("/{guid}")
def get_order(guid: str, q: str = "", sort: str = "position",
              direction: str = Query("asc", alias="dir"), only: str = ""):
    order = db.get_webami_order(guid, q, sort, direction, only)
    if not order:
        raise HTTPException(404, "Order not found")
    return order


@router.get("/products/{product_id}")
def get_webami_product_route(product_id: int):
    p = db.get_webami_product_by_id(product_id)
    if not p:
        raise HTTPException(404, "Product not found")
    return p