from datetime import datetime, timezone
import logging
import time

from app import config, db
from app.jobs.tracker import is_cancelled, update
from app.shopify import ShopifyClient

logger: logging.Logger = logging.getLogger(__name__)

PROGRESS_EVERY: int = 5


def run_shopify_sync(job_id: str, store: str, token: str, full: bool = False) -> dict:
    """Pull Shopify products into the local cache. Incremental unless full=True."""
    try:
        return _sync(job_id, store, token, full)
    except Exception as exc:
        db.log_sync("shopify_sync", "error", str(exc))
        raise


def _sync(job_id: str, store: str, token: str, full: bool) -> dict:
    cfg = db.get_config() or {}
    client = ShopifyClient(
        store, token, cfg.get("shopify_api_version") or config.DEFAULT_API_VERSION
    )
    # Recorded before the pull so products edited mid-sync are picked up next time.
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    synced = 0
    errors = 0

    update(job_id, message="Fetching Shopify location…")
    try:
        location_id = client.get_primary_location_id()
        if location_id:
            db.upsert_config(shopify_location_id=location_id)
    except Exception:
        logger.warning("Could not fetch Shopify location", exc_info=True)

    since = None if full else cfg.get("last_shopify_sync")
    query = f"updated_at:>'{since}'" if since else None
    try:
        total = client.count_products(query)
    except Exception:
        logger.warning("Could not count products", exc_info=True)
        total = 0
    update(job_id, total=total, message="Syncing products…")
    t0: float = time.monotonic()

    for node in client.iter_bulk_products(
        cfg,
        query,
        on_status=lambda msg: update(job_id, message=msg),
        cancelled=lambda: is_cancelled(job_id),
    ):
        if is_cancelled(job_id):
            break
        try:
            db.save_product(node)
            synced += 1
        except Exception:
            errors += 1
            logger.exception("Error saving product %s", node.get("id"))
        done = synced + errors
        if done % PROGRESS_EVERY == 0:
            update(job_id, progress=done, message=f"Synced {done} of {total or '?'} products…")

    if is_cancelled(job_id):
        status = "cancelled"
    elif errors:
        status = "partial"
    else:
        status = "done"

    # Only advance the incremental cursor after a clean run, so failed
    # products are retried next time.
    if status == "done":
        db.upsert_config(last_shopify_sync=started)

    logger.info("Shopify sync %s: %d products in %.1fs", status, synced, time.monotonic() - t0)
    db.log_sync("shopify_sync", status, f"synced:{synced} errors:{errors}")
    update(job_id, progress=synced + errors,
           message=f"{status.capitalize()} - {synced} products synced, {errors} errors")
    return {"status": status, "synced": synced, "errors": errors}