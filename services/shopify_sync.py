"""
Background job: pull all Shopify products into the local cache.
Uses the updated GraphQL schema matching the store's actual query structure.
"""

import logging
from datetime import datetime, timezone

import db.database as db
from services import jobs
from shopify.client import ShopifyClient

logger = logging.getLogger(__name__)


def run_shopify_sync(job_id: str, store: str, token: str) -> dict:
    client = ShopifyClient(store, token)
    total  = 0
    errors = 0

    # Cache primary location ID
    jobs.update(job_id, message="Fetching Shopify location…")
    try:
        loc_id = client.get_primary_location_id()
        if loc_id:
            db.upsert_config(shopify_location_id=loc_id)
    except Exception as e:
        logger.warning(f"Could not fetch location: {e}")

    jobs.update(job_id, message="Syncing products…")

    cfg = db.get_config() or {}
    last_sync = cfg.get("last_shopify_sync")
    sync_query = f"updated_at:>'{last_sync}'" if last_sync else None
    if sync_query:
        logger.info(f"Incremental sync: {sync_query}")

    for product in client.iter_all_products(query=sync_query):
        if jobs.is_cancelled(job_id):
            logger.info("Shopify sync cancelled")
            break
        try:
            product_id = db._sid(product["id"])
            product["upc"] = (product.get("upc")       or {}).get("value")
            product["genres"] = (product.get("genres") or {}).get("value")

            db.upsert_shopify_product(product)

            # ── Images (new schema: preview.image.url) ──────────
            db.clear_shopify_images(product_id)
            pos = 0
            for media in (product.get("media") or {}).get("nodes", []):
                preview = media.get("preview") or {}
                image   = preview.get("image") or {}
                url     = image.get("url")
                if url:
                    db.upsert_shopify_image(product_id, media.get("id"), url, pos)
                    pos += 1

            # ── Variants ────────────────────────────────────────
            for variant in (product.get("variants") or {}).get("nodes", []):
                db.upsert_shopify_variant(product_id, variant)

            total += 1
            if total % 100 == 0:
                jobs.update(job_id, progress=total, message=f"Synced {total} products…")

        except Exception as e:
            errors += 1
            logger.error(f"Error syncing product {product.get('id')}: {e}")

    # FIX #3 - store real timestamp, not literal SQL string
    now = datetime.now(timezone.utc).isoformat()
    db.upsert_config(last_shopify_sync=now)
    db.log_sync("shopify_sync", "done", f"synced:{total} errors:{errors}")
    jobs.update(job_id, progress=total,
                message=f"Done - {total} products synced, {errors} errors")
    return {"synced": total, "errors": errors}
