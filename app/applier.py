"""Apply the approved catalog plan to Shopify, in two separate steps.

  1. CREATE  – build each approved group as one new product with its variants.
               Fresh price/cost/weight/quantity is pulled from the old variants
               first. New products are DRAFT unless `publish` is set, so the
               storefront never shows both old and new listings by accident.
  3. PUBLISH – (separate button) publish each created product to the Online Store.
  2. ARCHIVE – per group, once created: carry over any sales made on the old
               listing since step 1 (quantity delta), make the new product
               ACTIVE if it is still a draft, then archive the old products.

Both steps are resumable and record exactly what happened per variant
(new_variant_id, qty_copied, archived_at) so the old -> new mapping is kept.
"""

import logging
import threading
from datetime import datetime, timezone
from typing import Callable, Optional

from app import db
from app.shopify_client import ShopifyClient, available_at

logger = logging.getLogger(__name__)

OPTION_NAMES = ["Edition", "Color", "Attributes"]

_lock = threading.Lock()
_cancel = threading.Event()
_status: dict = {"running": False, "step": None, "total": 0, "done": 0, "current": "",
                 "errors": [], "finished_at": None}


def status() -> dict:
    return {**_status, "errors": list(_status["errors"])}


def cancel() -> None:
    _cancel.set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _key(edition: str, color: str, attributes: str) -> tuple:
    return (edition.strip().lower(), color.strip().lower(), attributes.strip().lower())


def _opt_key(selected: list[dict]) -> tuple:
    vals = {o["name"].lower(): o["value"] for o in selected}
    return _key(*(vals.get(n.lower(), "") for n in OPTION_NAMES))


# ── selection ────────────────────────────────────────────────────────

STAGES = {
    # approved, nothing created yet
    "to_create": "g.status='approved' AND g.new_product_id IS NULL",
    # created fully, at least one old product still active
    "to_archive": """g.new_product_id IS NOT NULL
                     AND NOT EXISTS (SELECT 1 FROM plan_variants v WHERE v.plan_product_id=g.id AND v.new_variant_id IS NULL)
                     AND EXISTS (SELECT 1 FROM plan_variants v WHERE v.plan_product_id=g.id AND v.archived_at IS NULL)""",
    # created and every old product archived
    "done": """g.new_product_id IS NOT NULL
               AND NOT EXISTS (SELECT 1 FROM plan_variants v WHERE v.plan_product_id=g.id
                               AND (v.new_variant_id IS NULL OR v.archived_at IS NULL))""",
    # started but incomplete (failed part-way)
    "partial": """g.new_product_id IS NOT NULL
                  AND EXISTS (SELECT 1 FROM plan_variants v WHERE v.plan_product_id=g.id AND v.new_variant_id IS NULL)""",
    # created fully, not yet on the Online Store
    "to_publish": """g.new_product_id IS NOT NULL AND g.published_at IS NULL
                     AND NOT EXISTS (SELECT 1 FROM plan_variants v WHERE v.plan_product_id=g.id AND v.new_variant_id IS NULL)""",
    "all": "g.status='approved' OR g.new_product_id IS NOT NULL",
}


def summary() -> dict:
    with db.connect() as conn:
        return {k: conn.execute(f"SELECT COUNT(*) FROM plan_products g WHERE {w}").fetchone()[0]
                for k, w in STAGES.items()}


def list_groups(stage: str = "all", q: str = "", limit: int = 25, offset: int = 0) -> dict:
    where = STAGES.get(stage, STAGES["all"])
    params = {"q": q.strip(), "like": f"%{q.strip()}%", "limit": limit, "offset": offset}
    qf = "AND (:q='' OR g.title LIKE :like OR g.vendor LIKE :like OR g.handle LIKE :like)"
    with db.connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM plan_products g WHERE ({where}) {qf}", params).fetchone()[0]
        groups = conn.execute(
            f"""SELECT g.id, g.handle, g.title, g.vendor, g.status, g.new_product_id, g.new_status,
                       g.created_at_shopify, g.published_at, g.error FROM plan_products g
                WHERE ({where}) {qf} ORDER BY g.title LIMIT :limit OFFSET :offset""", params).fetchall()
        out = []
        for g in groups:
            vs = conn.execute(
                """SELECT v.id, v.edition, v.color, v.attributes, v.source_product_id, v.source_variant_id,
                          v.new_variant_id, v.qty_copied, v.archived_at,
                          sp.title source_title, sp.status source_status, sv.inventory_quantity cached_qty
                   FROM plan_variants v
                   LEFT JOIN shopify_products sp ON sp.product_id=v.source_product_id
                   LEFT JOIN shopify_variants sv ON sv.variant_id=v.source_variant_id
                   WHERE v.plan_product_id=? ORDER BY v.edition, v.color, v.attributes""", (g["id"],)).fetchall()
            vs = [dict(v) for v in vs]
            out.append({**dict(g), "variants": vs,
                        "n": len(vs),
                        "created": sum(1 for v in vs if v["new_variant_id"]),
                        "archived": sum(1 for v in vs if v["archived_at"])})
    return {"total": total, "groups": out}


def next_group_ids(stage: str, limit: int) -> list[int]:
    with db.connect() as conn:
        return [r["id"] for r in conn.execute(
            f"SELECT g.id FROM plan_products g WHERE {STAGES[stage]} ORDER BY g.title LIMIT ?", (limit,))]


# ── job runner ───────────────────────────────────────────────────────

def start(client: ShopifyClient, step: str, group_ids: list[int], publish: bool = False) -> bool:
    if step not in ("create", "archive", "publish"):
        raise ValueError("step must be create, archive or publish")
    with _lock:
        if _status["running"]:
            return False
        _cancel.clear()
        _status.update(running=True, step=step, total=len(group_ids), done=0, current="",
                       errors=[], finished_at=None)
    threading.Thread(target=_run, args=(client, step, group_ids, publish), daemon=True).start()
    return True


def _run(client, step, group_ids, publish):
    try:
        location = db.get_state("shopify_location_id")
        if not location and step != "publish":
            location = client.primary_location_id()
            db.set_state("shopify_location_id", location)
        if step == "publish":
            pub = db.get_state("online_store_publication_id")
            if not pub:
                pub = client.online_store_publication_id()
                db.set_state("online_store_publication_id", pub)
            fn: Callable = lambda gid: publish_group(client, pub, gid)
        elif step == "create":
            fn = lambda gid: create_group(client, location, gid, publish)
        else:
            fn = lambda gid: archive_group(client, location, gid)
        for gid in group_ids:
            if _cancel.is_set():
                break
            with db.connect() as conn:
                row = conn.execute("SELECT title FROM plan_products WHERE id=?", (gid,)).fetchone()
            _status["current"] = row["title"] if row else str(gid)
            try:
                fn(gid)
                _set_error(gid, None)
            except Exception as e:                     # keep going; the group stays resumable
                logger.exception("group %s failed", gid)
                _set_error(gid, str(e))
                _status["errors"].append({"group_id": gid, "title": _status["current"], "message": str(e)})
            _status["done"] += 1
    except Exception as e:
        logger.exception("apply job failed")
        _status["errors"].append({"group_id": None, "title": "", "message": str(e)})
    finally:
        _status.update(running=False, current="", finished_at=_now())


def _set_error(gid: int, msg: Optional[str]) -> None:
    with db.connect() as conn:
        conn.execute("UPDATE plan_products SET error=? WHERE id=?", (msg, gid))


# ── step 1: create ───────────────────────────────────────────────────

def _variant_input(src: dict, with_options: Optional[tuple] = None) -> dict:
    inv: dict = {"tracked": True}
    if src.get("sku"):
        inv["sku"] = src["sku"]
    item = src.get("inventoryItem") or {}
    cost = (item.get("unitCost") or {}).get("amount")
    if cost is not None:
        inv["cost"] = cost
    weight = ((item.get("measurement") or {}).get("weight"))
    if weight and weight.get("value") is not None:
        inv["measurement"] = {"weight": {"value": weight["value"], "unit": weight["unit"]}}
    d: dict = {"price": src.get("price"), "taxable": src.get("taxable", True), "inventoryItem": inv}
    if src.get("barcode"):
        d["barcode"] = src["barcode"]
    if with_options:
        d["optionValues"] = [{"optionName": n, "name": v} for n, v in zip(OPTION_NAMES, with_options)]
    return d


def create_group(client: ShopifyClient, location_id: str, group_id: int, publish: bool = False) -> None:
    with db.connect() as conn:
        g = dict(conn.execute("SELECT * FROM plan_products WHERE id=?", (group_id,)).fetchone())
        pvs = [dict(r) for r in conn.execute(
            "SELECT * FROM plan_variants WHERE plan_product_id=? ORDER BY edition, color, attributes", (group_id,))]
    if g["status"] != "approved" and not g["new_product_id"]:
        raise ValueError("group is not approved")
    if not pvs or any(not (v["edition"] and v["color"] and v["attributes"]) for v in pvs):
        raise ValueError("group has variants missing Edition / Color / Attributes")
    if len({_key(v["edition"], v["color"], v["attributes"]) for v in pvs}) != len(pvs):
        raise ValueError("group has duplicate variant combinations")

    # fresh pull of everything we copy (this is where "most recent quantities" comes from)
    fresh = client.fetch_variants([v["source_variant_id"] for v in pvs])
    missing = [v["source_variant_id"] for v in pvs if v["source_variant_id"] not in fresh]
    if missing:
        raise ValueError(f"{len(missing)} source variant(s) no longer exist in Shopify — sync and rebuild the plan")

    first = pvs[0]
    if not g["new_product_id"]:
        sources = [fresh[v["source_variant_id"]] for v in pvs]
        tags: list[str] = []
        for s in sources:
            for t in s["product"].get("tags") or []:
                if t not in tags:
                    tags.append(t)
        desc = next((s["product"].get("descriptionHtml") for s in sources if s["product"].get("descriptionHtml")), "")
        urls: list[str] = []
        for s in sources:
            for m in (s["product"].get("media") or {}).get("nodes", []):
                u = (m.get("image") or {}).get("url") if m else None
                if u and u not in urls:
                    urls.append(u)
        product = {
            "title": g["title"], "handle": g["handle"], "vendor": g["vendor"] or "",
            "productType": g["product_type"] or "", "tags": tags, "descriptionHtml": desc or "",
            "status": "ACTIVE" if publish else "DRAFT",
            "productOptions": [{"name": n, "values": [{"name": first[k]}]}
                               for n, k in zip(OPTION_NAMES, ("edition", "color", "attributes"))],
        }
        if g["category_id"]:
            product["category"] = g["category_id"]
        metafields = []
        for key in ("upc", "genres"):          # first source (in variant order) that has a value
            for s in sources:
                mf = (s["product"].get(key) or {})
                if mf.get("value"):
                    metafields.append({"namespace": "custom", "key": key, "type": mf["type"], "value": mf["value"]})
                    break
        if metafields:
            product["metafields"] = metafields
        media = [{"originalSource": u, "mediaContentType": "IMAGE", "alt": g["title"]} for u in urls[:10]]
        created = client.create_product(product, media)
        with db.connect() as conn:
            conn.execute("UPDATE plan_products SET new_product_id=?, handle=?, new_status=?, error=NULL WHERE id=?",
                         (created["id"], created["handle"], created["status"], group_id))
        g["new_product_id"] = created["id"]

    pid = g["new_product_id"]
    existing = {_opt_key(v["selectedOptions"]): v for v in client.get_product_variants(pid)}

    updates, creates = [], []
    for v in pvs:
        k = _key(v["edition"], v["color"], v["attributes"])
        src = fresh[v["source_variant_id"]]
        if k in existing:
            updates.append({"id": existing[k]["id"], **_variant_input(src)})
        else:
            creates.append((k, _variant_input(src, (v["edition"], v["color"], v["attributes"]))))
    client.bulk_update_variants(pid, updates)
    for v in client.bulk_create_variants(pid, [c[1] for c in creates]):
        existing[_opt_key(v["selectedOptions"])] = v

    items, rows = [], []
    for v in pvs:
        k = _key(v["edition"], v["color"], v["attributes"])
        new = existing.get(k)
        if not new:
            raise RuntimeError(f"variant {v['edition']} / {v['color']} / {v['attributes']} was not created")
        qty = available_at(fresh[v["source_variant_id"]], location_id)
        items.append((new["inventoryItem"]["id"], qty))
        rows.append((new["id"], new["inventoryItem"]["id"], qty, v["id"]))
    client.set_quantities(location_id, items)

    with db.connect() as conn:
        conn.executemany(
            "UPDATE plan_variants SET new_variant_id=?, new_inventory_item_id=?, qty_copied=?, "
            "updated_at=datetime('now') WHERE id=?", rows)
        conn.execute("UPDATE plan_products SET created_at_shopify=?, error=NULL WHERE id=?", (_now(), group_id))


# ── publish to Online Store ──────────────────────────────────────────

def publish_group(client: ShopifyClient, publication_id: str, group_id: int) -> None:
    with db.connect() as conn:
        g = dict(conn.execute("SELECT * FROM plan_products WHERE id=?", (group_id,)).fetchone())
    if not g["new_product_id"]:
        raise ValueError("group is not created yet")
    client.publish_product(g["new_product_id"], publication_id)
    with db.connect() as conn:
        conn.execute("UPDATE plan_products SET published_at=? WHERE id=?", (_now(), group_id))


# ── step 2: archive ──────────────────────────────────────────────────

def archive_group(client: ShopifyClient, location_id: str, group_id: int) -> None:
    with db.connect() as conn:
        g = dict(conn.execute("SELECT * FROM plan_products WHERE id=?", (group_id,)).fetchone())
        pvs = [dict(r) for r in conn.execute("SELECT * FROM plan_variants WHERE plan_product_id=?", (group_id,))]
    if not g["new_product_id"] or any(not v["new_variant_id"] for v in pvs):
        raise ValueError("group is not fully created yet")

    pending = [v for v in pvs if not v["archived_at"]]
    sources = sorted({v["source_product_id"] for v in pending})

    # carry over sales/receipts that happened on the old listing since step 1
    fresh = client.fetch_variants([v["source_variant_id"] for v in pending])
    deltas, rows = [], []
    for v in pending:
        node = fresh.get(v["source_variant_id"])
        if not node:
            continue
        cur = available_at(node, location_id)
        delta = cur - (v["qty_copied"] or 0)
        if delta:
            deltas.append((v["new_inventory_item_id"], delta))
        rows.append((cur, v["id"]))
    client.adjust_quantities(location_id, deltas)
    with db.connect() as conn:
        conn.executemany("UPDATE plan_variants SET qty_copied=? WHERE id=?", rows)

    if (g["new_status"] or "").upper() != "ACTIVE":
        client.set_product_status(g["new_product_id"], "ACTIVE")
        with db.connect() as conn:
            conn.execute("UPDATE plan_products SET new_status='ACTIVE' WHERE id=?", (group_id,))

    for src in sources:
        client.set_product_status(src, "ARCHIVED")
        with db.connect() as conn:
            conn.execute("UPDATE plan_variants SET archived_at=? WHERE plan_product_id=? AND source_product_id=?",
                         (_now(), group_id, src))
