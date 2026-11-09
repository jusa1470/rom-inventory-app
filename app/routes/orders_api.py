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


class Push(BaseModel):
    cost_keys: list[str] = []
    title_keys: list[str] = []
    keys: list[str] | None = None


class Keys(BaseModel):
    keys: list[str]


class Target(BaseModel):
    action: Literal["auto", "use", "variant", "new"]
    variant_id: str | None = None
    product_id: str | None = None


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


def _wp(guid: str, upc: str):
    o = db.get_webami_order(guid)
    it = next((i for i in (o or {}).get("items", []) if i["upc"] == upc), None)
    return it and it.get("product_id") and db.get_webami_product_by_id(it["product_id"])


def _left(guid: str, upc: str) -> int:
    o = db.get_webami_order(guid)
    ls = [i for i in (o or {}).get("items", []) if i["upc"] == upc]
    return max(0, sum(i["quantity"] for i in ls) - ls[0]["received"]) if ls else 0


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


def _plan(r: dict) -> dict:
    a, tv, tp = r["t_action"], r["t_variant"], r["t_product"]
    if a in ("update", "map") and tv:
        return {"action": a, "basis": "manual", "variant_id": tv}
    if a == "variant" and tp:
        return {"action": "variant", "basis": "manual", "product_id": tp}
    if a == "new":
        return {"action": "new", "basis": "manual"}
    v = db.get_variant_by_upc(r["upc"])
    if v:
        return {"action": "update", "basis": "upc", "variant_id": v["variant_id"]}
    wp = db.get_webami_product_by_id(r["wp_id"]) if r["wp_id"] else None
    if wp:
        c = next(iter(db.shopify_candidates(wp, 1)), None)
        if c:
            vt = _vtitle(db.suggest_parts(wp)).lower()
            m = next((x for x in c["variants"]
                      if not x["upc"] and (x["title"] or "").lower() == vt), None)
            if m:
                return {"action": "map", "basis": "closest", "variant_id": m["variant_id"]}
            return {"action": "variant", "basis": "closest", "product_id": c["product_id"]}
    return {"action": "new", "basis": "none"}


def _view(r: dict) -> dict:
    pl = _plan(r)
    if pl.get("variant_id"):
        v = db.get_variant(pl["variant_id"])
        if v:
            pl |= {"product_id": v["product_id"], "product_title": v["product_title"],
                   "variant_title": v["variant_title"], "stock": v["inventory_quantity"],
                   "cost": v["cost"]}
    elif pl.get("product_id"):
        p = db.get_product_detail(pl["product_id"])
        pl["product_title"] = p["title"] if p else None
    if r["wp_id"]:
        wp = db.get_webami_product_by_id(r["wp_id"])
        if wp:
            s = db.suggest_parts(wp)
            pl |= {"new_title": s["title"], "new_vtitle": _vtitle(s)}
    return pl


def _apply(client, cfg, r: dict, pl: dict, cost: float | None, titles: bool = False):
    guid, upc, qty = r["order_guid"], r["upc"], r["qty"]
    if pl["action"] in ("update", "map"):
        v = db.get_variant(pl["variant_id"])
        if not v:
            raise RuntimeError("Target variant no longer exists")
        vs = [{"id": v["variant_id"], "inventory_item_id": v["inventory_item_id"],
               "inventory_quantity": (v["inventory_quantity"] or 0) + qty}]
        if pl["action"] == "map":
            vs[0]["upc"] = upc
        if cost is not None:
            vs[0] |= {"cost": f"{cost:.2f}", "price": f"{cost / 0.66:.2f}"}
        client.update_variants(v["product_id"], vs, cfg)
        db.update_local(v["product_id"], {}, vs)
        db.drop_from_match_cache(v["variant_id"])
        db.log_receipt(guid, upc, qty, v["variant_id"])
        return pl["action"]
    wp = _wp(guid, upc)
    if not wp:
        raise RuntimeError("No synced WebAMI product for this item (run Fetch products)")
    p, variant = _build(wp, upc, qty)
    if pl["action"] == "variant":
        pid = pl["product_id"]
    else:
        pid = client.create_product(p, cfg)
        db.add_local_product(pid, p)
    made = client.create_variants(pid, [variant], cfg)
    db.add_local_variants(pid, [variant], made)
    db.log_receipt(guid, upc, qty, made[0]["id"])
    return pl["action"]


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


@router.get("/queue/count")
def queue_count():
    return {"count": len(db.rq_list())}


@router.get("/queue")
def get_queue():
    return {"items": [{**r, "plan": _view(r)} for r in db.rq_list()]}


@router.get("/queue/{guid}/{upc}/options")
def options(guid: str, upc: str, q: str = ""):
    if q.strip():
        return {"items": db.search_shopify(q.strip())}
    wp = _wp(guid, upc)
    return {"items": db.shopify_candidates(wp, 8) if wp else []}


@router.put("/queue/{guid}/{upc}/target")
def queue_target(guid: str, upc: str, body: Target):
    a = v = p = None
    if body.action == "use":
        x = db.get_variant(body.variant_id or "")
        if not x:
            raise HTTPException(404, "Variant not found")
        a, v = ("update" if x["upc"] == upc else "map"), x["variant_id"]
    elif body.action == "variant":
        if not body.product_id:
            raise HTTPException(400, "product_id required")
        a, p = "variant", body.product_id
    elif body.action == "new":
        a = "new"
    db.rq_target(guid, upc, a, v, p)
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


@router.post("/queue/push")
def queue_push(body: Push = Push(), creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True}
    client, cfg = _client(creds)
    updated = variants = created = 0
    errors = []
    for r in db.rq_list():
        key = f"{r['order_guid']}|{r['upc']}"
        if body.keys is not None and key not in body.keys:
            continue
        try:
            pl = _plan(r)
            cost = (r["wm_cost"] if key in body.cost_keys and r["wm_cost"] is not None
                    and pl["action"] in ("update", "map") else None)
            res = _apply(client, cfg, r, pl, cost)
        except Exception as e:
            errors.append(f"{r['upc']}: {e}")
            continue
        db.rq_set(r["order_guid"], r["upc"], 0)
        updated += res in ("update", "map")
        variants += res == "variant"
        created += res == "new"
    return {"ok": not errors, "updated": updated, "variants": variants,
            "created": created, "errors": errors}


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
    items = (db.get_webami_order(guid) or {}).get("items", [])
    for ln in body.lines:
        rs = [i for i in items if i["upc"] == ln.upc]
        if ln.qty <= 0 or not rs:
            continue
        left = max(0, sum(i["quantity"] for i in rs) - rs[0]["received"])
        db.rq_set(guid, ln.upc, min(rs[0]["queued"] + ln.qty, left))
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