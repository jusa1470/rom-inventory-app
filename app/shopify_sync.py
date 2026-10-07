"""Shopify -> local DB sync. Runs in a background thread; status is polled."""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Iterable, Optional

from app import db
from app.shopify_client import ShopifyClient

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_status: dict = {"running": False, "mode": None, "processed": 0, "total": None,
                 "message": "", "error": None, "finished_at": None}
_cancel = threading.Event()


def status() -> dict:
    return dict(_status)


def cancel() -> None:
    _cancel.set()


def start(client: ShopifyClient, mode: str) -> bool:
    """Start a sync thread. Returns False if one is already running."""
    if mode not in ("full", "recent"):
        raise ValueError("mode must be 'full' or 'recent'")
    with _lock:
        if _status["running"]:
            return False
        _cancel.clear()
        _status.update(running=True, mode=mode, processed=0, total=None,
                       message="Starting…", error=None, finished_at=None)
    threading.Thread(target=_run, args=(client, mode), daemon=True).start()
    return True


def _run(client: ShopifyClient, mode: str) -> None:
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        since: Optional[str] = None
        if mode == "recent":
            since = db.get_state("shopify_last_sync")
            if not since:
                mode = "full"
                _status["mode"] = "full"

        _status["total"] = client.count_products(since)
        _status["message"] = f"Syncing {_status['total']} products…"

        seen: set[str] = set()
        for product in client.iter_products(since):
            if _cancel.is_set():
                _status["message"] = "Cancelled"
                return
            upsert_product(product)
            seen.add(product["product_id"])
            _status["processed"] = len(seen)

        if mode == "full":
            _delete_missing(seen)
        db.set_state("shopify_last_sync", started)
        _status["message"] = f"Done — {len(seen)} products"
    except Exception as e:
        logger.exception("Shopify sync failed")
        _status["error"] = str(e)
        _status["message"] = "Failed"
    finally:
        _status["running"] = False
        _status["finished_at"] = datetime.now(timezone.utc).isoformat()


def upsert_product(p: dict) -> None:
    with db.connect() as conn:
        conn.execute(
            """INSERT INTO shopify_products
               (product_id,handle,title,vendor,status,product_type,category_id,category_name,
                tags,upc_metafield,genres,image_urls,option_names,created_at,updated_at,last_synced)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
               ON CONFLICT(product_id) DO UPDATE SET
                 handle=excluded.handle, title=excluded.title, vendor=excluded.vendor,
                 status=excluded.status, product_type=excluded.product_type,
                 category_id=excluded.category_id, category_name=excluded.category_name,
                 tags=excluded.tags, upc_metafield=excluded.upc_metafield, genres=excluded.genres,
                 image_urls=excluded.image_urls, option_names=excluded.option_names,
                 created_at=excluded.created_at, updated_at=excluded.updated_at,
                 last_synced=excluded.last_synced""",
            (p["product_id"], p["handle"], p["title"], p["vendor"], p["status"],
             p["product_type"], p["category_id"], p["category_name"],
             json.dumps(p["tags"]), p["upc_metafield"], p["genres"], json.dumps(p["image_urls"]),
             json.dumps(p["option_names"]), p["created_at"], p["updated_at"]),
        )
        ids = [v["variant_id"] for v in p["variants"]]
        for v in p["variants"]:
            conn.execute(
                """INSERT INTO shopify_variants
                   (variant_id,product_id,title,sku,barcode,price,cost,taxable,position,options,
                    inventory_item_id,inventory_quantity,weight,weight_unit)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(variant_id) DO UPDATE SET
                     product_id=excluded.product_id, title=excluded.title, sku=excluded.sku,
                     barcode=excluded.barcode, price=excluded.price, cost=excluded.cost,
                     taxable=excluded.taxable, position=excluded.position, options=excluded.options,
                     inventory_item_id=excluded.inventory_item_id,
                     inventory_quantity=excluded.inventory_quantity,
                     weight=excluded.weight, weight_unit=excluded.weight_unit""",
                (v["variant_id"], p["product_id"], v["title"], v["sku"], v["barcode"],
                 v["price"], v["cost"], v["taxable"], v["position"], json.dumps(v["options"]),
                 v["inventory_item_id"], v["inventory_quantity"], v["weight"], v["weight_unit"]),
            )
        # drop local variants that no longer exist on this product
        if ids:
            marks = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM shopify_variants WHERE product_id=? AND variant_id NOT IN ({marks})",
                [p["product_id"], *ids],
            )
        else:
            conn.execute("DELETE FROM shopify_variants WHERE product_id=?", (p["product_id"],))


def _delete_missing(seen: Iterable[str]) -> None:
    seen = set(seen)
    with db.connect() as conn:
        local = {r["product_id"] for r in conn.execute("SELECT product_id FROM shopify_products")}
        gone = list(local - seen)
        for i in range(0, len(gone), 500):
            chunk = gone[i:i + 500]
            conn.execute(
                f"DELETE FROM shopify_products WHERE product_id IN ({','.join('?' * len(chunk))})",
                chunk,
            )
