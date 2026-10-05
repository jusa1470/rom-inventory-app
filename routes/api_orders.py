import csv
import io
from flask import Blueprint, jsonify, request, session

import db.database as db
from db.database import db_conn
from services import jobs
from services.jobs import update, is_cancelled
from shopify.client import ShopifyClient

bp = Blueprint("orders", __name__)


def _require_auth():
    if not session.get("authenticated"):
        return jsonify({"error": "Not authenticated"}), 401
    return None


# ─────────────────────────────────────────────
# Orders list
# ─────────────────────────────────────────────

@bp.get("/api/orders")
def list_orders():
    err = _require_auth()
    if err: return err
    return jsonify(db.get_orders(
        page=int(request.args.get("page", 1)),
        per_page=min(int(request.args.get("per_page", 30)), 100),
        sort=request.args.get("sort", "order_date_desc"),
        q_number=request.args.get("q_number", "").strip(),
        q_name=request.args.get("q_name", "").strip(),
        status_filter=request.args.get("status", "").strip(),
    ))


@bp.get("/api/orders/<int:order_id>")
def get_order(order_id: int):
    err = _require_auth()
    if err: return err
    order = db.get_order_detail(order_id)
    if not order:
        return jsonify({"error": "Order not found"}), 404
    return jsonify(order)


# ─────────────────────────────────────────────
# Import: CSV
# ─────────────────────────────────────────────

@bp.post("/api/orders/import/csv")
def import_csv():
    err = _require_auth()
    if err: return err
    data     = request.get_json(silent=True) or {}
    csv_text = (data.get("csv") or "").strip()
    if not csv_text:
        return jsonify({"error": "No CSV data provided"}), 400
    try:
        orders_created, items_created = _parse_csv(csv_text)
        return jsonify({"ok": True, "orders": orders_created, "items": items_created})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


def _parse_csv(text: str) -> tuple[int, int]:
    reader     = csv.DictReader(io.StringIO(text))
    fieldnames = [f.strip().lower().replace(" ", "_") for f in (reader.fieldnames or [])]
    reader.fieldnames = fieldnames

    def _col(row, *keys):
        return next((row.get(k) for k in keys if row.get(k)), "")

    buckets: dict[str, list[dict]] = {}
    for raw in reader:
        row = {k.strip().lower().replace(" ", "_"): (v or "").strip() for k, v in raw.items()}
        upc = _col(row, "upc", "barcode")
        if not upc:
            continue
        order_num  = _col(row, "order_number", "order_no", "po_number") or "IMPORT"
        order_date = _col(row, "order_date", "date") or None
        item = {
            "webami_upc":           upc,
            "title":                _col(row, "title", "description"),
            "vendor":               _col(row, "vendor", "artist"),
            "format":               _col(row, "format", "type"),
            "unit_cost":            _sfloat(_col(row, "unit_cost", "cost", "price")),
            "total_cost":           _sfloat(_col(row, "total_cost", "extended")),
            "quantity_ordered":     _sint(_col(row, "qty_ordered", "quantity", "qty")),
            "quantity_in_stock":    _sint(_col(row, "qty_in_stock", "in_stock")),
            "quantity_backordered": _sint(_col(row, "qty_backordered", "backordered")),
            "_date": order_date,
        }
        buckets.setdefault(order_num, []).append(item)

    orders_created = items_created = 0
    for order_num, items in buckets.items():
        order_date = next((i.pop("_date", None) for i in items), None)
        for i in items: i.pop("_date", None)
        oid = db.create_order({"guid": f"csv_{order_num}",
                               "order_number": order_num,
                               "order_date": order_date,
                               "total_products": len(items)})
        orders_created += 1
        for item in items:
            db.create_order_item(oid, item)
            items_created += 1
    return orders_created, items_created


# ─────────────────────────────────────────────
# Import: pasted order detail HTML
# ─────────────────────────────────────────────

@bp.post("/api/orders/import/html")
def import_html():
    err = _require_auth()
    if err: return err
    data = request.get_json(silent=True) or {}
    html = (data.get("html") or "").strip()
    if not html:
        return jsonify({"error": "No HTML provided"}), 400
    try:
        from webami.order_parser import parse_order_detail
        detail = parse_order_detail(html)
        if not detail.get("items"):
            return jsonify({"error": "No order items found in HTML"}), 400
        oid = db.create_order({
            "guid": detail.get("order_number"),
            "order_number":    detail.get("order_number"),
            "order_name":      "",
            "order_date":      detail.get("order_date"),
            "total_products":  len(detail["items"]),
            "notes":           detail.get("invoice_number"),
        })
        for item in detail["items"]:
            item["vendor"] = item.pop("artist", None) or item.get("vendor")
            db.create_order_item(oid, item)
        return jsonify({"ok": True, "orders": 1, "items": len(detail["items"])})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ─────────────────────────────────────────────
# Auto-sync all orders from live Webami session
# ─────────────────────────────────────────────

@bp.post("/api/orders/sync-webami")
def sync_webami_orders():
    err = _require_auth()
    if err: return err
    job_id = jobs.start("Webami Order Sync", _run_webami_order_sync)
    return jsonify({"job_id": job_id})


def _run_webami_order_sync(job_id: str) -> dict:
    from webami.order_parser import scrape_orders_list_page, scrape_order_detail
    from services.jobs import update

    update(job_id, message="Fetching orders list…")

    # Scrape all pages of the orders list
    all_order_headers: list[dict] = []
    for page in range(1, 51):  # max 50 pages
        if jobs.is_cancelled(job_id): break
        update(job_id, message=f"Scraping orders list page {page}…")
        try:
            orders = scrape_orders_list_page(page)
        except Exception as e:
            break
        if not orders:
            break
        all_order_headers.extend(orders)
        if len(orders) < 25:   # last page (default 25/page)
            break

    update(job_id, message=f"Found {len(all_order_headers)} orders - fetching details…",
           total=len(all_order_headers))

    with db_conn() as _c:
        existing_guids = {r[0] for r in _c.execute("SELECT guid FROM webami_orders").fetchall()}

    orders_saved = items_saved = skipped = errors = 0

    for i, hdr in enumerate(all_order_headers):
        if jobs.is_cancelled(job_id): break
        if hdr.get("guid") in existing_guids:
            skipped += 1
            continue
        update(job_id, progress=i,
               message=f"Syncing order {hdr['order_number']} ({i+1}/{len(all_order_headers)})…")
        try:
            detail = scrape_order_detail(hdr["guid"])
            oid = db.create_order({
                "guid": hdr["guid"],
                "order_number":    hdr["order_number"],
                "order_name":      hdr.get("order_name") or "",
                "order_date":      detail.get("order_date") or hdr.get("order_date"),
                "total_products":  len(detail.get("items", [])),
                "notes":           detail.get("invoice_number"),
            })
            for item in detail.get("items", []):
                item["vendor"] = item.pop("artist", None) or item.get("vendor")
                db.create_order_item(oid, item)
                items_saved += 1
            orders_saved += 1
        except Exception as e:
            errors += 1
            import logging
            logging.getLogger(__name__).error(f"Order {hdr.get('guid')}: {e}")

    db.log_sync("webami_order_sync", "done",
                f"orders:{orders_saved} items:{items_saved} skipped:{skipped} errors:{errors}")
    return {"orders": orders_saved, "items": items_saved, "skipped": skipped, "errors": errors}


# ─────────────────────────────────────────────
# Receiving
# ─────────────────────────────────────────────

@bp.post("/api/orders/<int:order_id>/receive")
def receive_items(order_id: int):
    err = _require_auth()
    if err: return err

    data  = request.get_json(silent=True) or {}
    items = data.get("items") or []
    if not items:
        return jsonify({"error": "No items provided"}), 400
    
    if db.is_dry_run():
        preview = [
            {"item_id": int(e.get("order_item_id")), "qty": int(e.get("quantity_received") or 0),
                "dry_run": True, "shopify_updated": False}
            for e in items if e.get("order_item_id") and int(e.get("quantity_received") or 0) > 0
        ]
        return jsonify({"ok": True, "dry_run": True, "results": preview})

    store       = session.get("shopify_store")
    token       = session.get("shopify_token")
    cfg         = db.get_config() or {}
    location_id = cfg.get("shopify_location_id")

    client  = ShopifyClient(store, token) if (store and token) else None
    results = []

    # Load order once
    order = db.get_order_detail(order_id)
    item_map = {i["id"]: i for i in (order.get("items") or [])} if order else {}

    for entry in items:
        item_id  = int(entry.get("order_item_id") or 0)
        qty      = int(entry.get("quantity_received") or 0)
        push     = bool(entry.get("push_to_shopify", True))

        if not item_id or qty <= 0:
            continue

        shopify_updated = False
        matched_item    = item_map.get(item_id)

        unit_cost = matched_item.get("unit_cost") if matched_item else None

        if push and not db.is_dry_run() and client and location_id and matched_item and matched_item.get("inventory_item_id"):
            try:
                client.adjust_inventory(
                    matched_item["inventory_item_id"],
                    location_id,
                    qty,
                )
                if unit_cost:
                    try:
                        client.update_inventory_item_cost(matched_item["inventory_item_id"], unit_cost)
                    except Exception as ce:
                        import logging; logging.getLogger(__name__).warning(f"Cost push failed: {ce}")
                shopify_updated = True
            except Exception as e:
                results.append({"item_id": item_id, "error": str(e)})
                continue

        if unit_cost and matched_item and matched_item.get("webami_upc"):
            db.update_webami_cost(matched_item["webami_upc"], unit_cost)

        db.add_received(item_id, qty, shopify_updated, unit_cost=unit_cost)
        results.append({"item_id": item_id, "qty": qty, "shopify_updated": shopify_updated})

    return jsonify({"ok": True, "results": results})


@bp.delete("/api/orders/received/<int:received_id>")
def remove_received(received_id: int):
    err = _require_auth()
    if err: return err
    if db.is_dry_run():
        return jsonify({"ok": True, "dry_run": True})
    db.delete_received(received_id)
    return jsonify({"ok": True})


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────

def _sfloat(v: str):
    try:
        return float(str(v).replace("$", "").replace(",", ""))
    except Exception:
        return None


def _sint(v: str) -> int:
    try:
        return int(float(v))
    except Exception:
        return 0
