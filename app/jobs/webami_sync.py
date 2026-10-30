import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import config, db
from app.jobs.tracker import is_cancelled, update
from app.webami import WebamiClient

logger = logging.getLogger(__name__)


def run_webami_sync(job_id: str, base_url: str, username: str, password: str) -> dict:
    try:
        return _sync(job_id, base_url, username, password)
    except Exception as exc:
        db.log_sync("webami_sync", "error", str(exc))
        raise


def _sync(job_id, base_url, username, password) -> dict:
    client = WebamiClient(base_url, username, password)
    update(job_id, message="Listing WebAMI orders…")
    new = client.list_new_orders(db.get_known_order_guids())
    update(job_id, total=len(new), message=f"Fetching {len(new)} new orders…")
    synced = errors = 0

    with ThreadPoolExecutor(config.WEBAMI_WORKERS) as pool:
        futs = {pool.submit(client.get_order_items, o["guid"]): o for o in new}
        for fut in as_completed(futs):
            if is_cancelled(job_id):
                for f in futs:
                    f.cancel()
                break
            order = futs[fut]
            try:
                db.save_order(order, fut.result())
                synced += 1
            except Exception:
                errors += 1
                logger.exception("Error saving WebAMI order %s", order["guid"])
            update(job_id, progress=synced + errors,
                   message=f"Synced {synced + errors} of {len(new)} orders…")

    status = "cancelled" if is_cancelled(job_id) else "partial" if errors else "done"
    db.log_sync("webami_sync", status, f"synced:{synced} errors:{errors}")
    update(job_id, progress=synced + errors,
           message=f"{status.capitalize()} - {synced} orders synced, {errors} errors")
    return {"status": status, "synced": synced, "errors": errors}