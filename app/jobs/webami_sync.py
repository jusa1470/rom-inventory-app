import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

from app import config, db
from app.jobs.tracker import is_cancelled, update
from app.webami import WebamiClient
from app.webami.webami_client import find_match

logger = logging.getLogger(__name__)


def run_webami_sync(job_id: str, base_url: str, username: str, password: str) -> dict:
    try:
        return _sync(job_id, base_url, username, password)
    except Exception as exc:
        db.log_sync("webami_sync", "error", str(exc))
        raise


def _resolve(client: WebamiClient, job_id: str) -> int:
    pending = db.get_unresolved_items()
    update(job_id, total=len(pending), progress=0, unit="order items", message=f"Resolving {len(pending)} order items…")
    errors = done = 0

    def _try(fn):
        try:
            return fn()
        except Exception:
            logger.warning("WebAMI lookup failed", exc_info=True)
            return None

    def _page(href):
        p = _try(lambda: client.get_product(href)) if href else None
        return p if p and p.get("title") else None

    def fetch(i):
        page = _page(i["href"])
        if page:
            return page, i["href"]
        searches = []
        if i["upc"]:
            searches.append(lambda: client.search_upc(i["upc"]))
        searches.append(lambda: client.search_site(i["title"], i["artist"], i["format"]))
        for search in searches:
            res = _try(search)
            upc = res and find_match(res, i["title"], i["artist"], i["format"])
            if upc:
                href = f"/{upc}"
                page = _page(href)
                if page:
                    return page, href
        return None, None

    start = time.monotonic()
    with ThreadPoolExecutor(config.WEBAMI_WORKERS_MAX) as pool:
        futs = {pool.submit(fetch, i): i for i in pending}
        for fut in as_completed(futs):
            if is_cancelled(job_id):
                for f in futs:
                    f.cancel()
                break
            i = futs[fut]
            extra = [("upc", i["upc"]), ("sku", i["sku"])]
            try:
                page, href = fut.result()
                if page:
                    ids = extra if href != i["href"] else [
                        (k, v) for k, v in extra if k == "upc" or v == page.get("sku")]
                    db.save_webami_product({**page, "href": href}, ids)
                else:  # page gone: build from the order line
                    db.save_webami_product({
                        "title": i["title"], "artist": i["artist"],
                        "product_type": i["format"], "upc": i["upc"],
                        "sku": i["sku"], "price": i["price"], "href": i["href"],
                    }, extra, update=False, use_fingerprint=True)
            except Exception:
                errors += 1
                logger.exception("Error resolving WebAMI product %s", i["upc"])
            done += 1
            update(job_id, progress=done, workers=client.limiter.limit,
                   message=f"Resolved {done} of {len(pending)} order items…")
    return errors


def _sync(job_id, base_url, username, password) -> dict:
    client = WebamiClient(base_url, username, password)
    update(job_id, message="Listing WebAMI orders…")
    new = client.list_new_orders(db.get_known_order_guids())
    update(job_id, total=len(new), unit="orders", message=f"Fetching {len(new)} new orders…")
    synced = errors = 0

    with ThreadPoolExecutor(config.WEBAMI_WORKERS_MAX) as pool:
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
            update(job_id, progress=synced + errors, workers=client.limiter.limit,
                   message=f"Synced {synced + errors} of {len(new)} orders…")

    if not is_cancelled(job_id):
        errors += _resolve(client, job_id)
    status = "cancelled" if is_cancelled(job_id) else "partial" if errors else "done"
    db.log_sync("webami_sync", status, f"synced:{synced} errors:{errors}")
    update(job_id, progress=synced + errors,
           message=f"{status.capitalize()} - {synced} orders synced, {errors} errors")
    return {"status": status, "synced": synced, "errors": errors}


def run_webami_resolve(job_id: str, base_url: str, username: str, password: str) -> dict:
    try:
        client = WebamiClient(base_url, username, password)
        errors = _resolve(client, job_id)
    except Exception as exc:
        db.log_sync("webami_resolve", "error", str(exc))
        raise
    status = "cancelled" if is_cancelled(job_id) else "partial" if errors else "done"
    db.log_sync("webami_resolve", status, f"errors:{errors}")
    update(job_id, message=f"{status.capitalize()} - {errors} errors")
    return {"status": status, "synced": db.get_webami_stats()["products"], "errors": errors}