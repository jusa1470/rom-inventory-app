import logging
from concurrent.futures import ThreadPoolExecutor, as_completed

from app import config, db
from app.jobs.tracker import is_cancelled, update
from app.webami import WebamiClient
from app.webami.webami_client import find_match
from app.webami.webami_helper import WEBAMI_FMT

logger = logging.getLogger(__name__)


def run_price_check(job_id: str, base_url: str, username: str, password: str) -> dict:
    try:
        return _check(job_id, base_url, username, password)
    except Exception as exc:
        db.log_sync("price_check", "error", str(exc))
        raise


def _check(job_id, base_url, username, password) -> dict:
    client = WebamiClient(base_url, username, password)
    vs = db.get_price_variants()
    update(job_id, total=len(vs), progress=0, unit="variants",
           message=f"Checking {len(vs)} variants…")

    def valid(href):
        try:
            p = client.fetch_product(href)
        except Exception:
            logger.warning("WebAMI page failed: %s", href, exc_info=True)
            return None
        return p if p.get("title") else None

    def check(v):
        p = valid(f"/{v['upc']}")
        if p and p.get("price") is not None:
            return {"status": "ok", "wm_upc": v["upc"], "wm_title": p["title"], "new_cost": p["price"]}
        fmt = WEBAMI_FMT.get(v["type"], "")
        for search in (lambda: client.search_upc(v["upc"]),
                       lambda: client.search_site(v["title"], v["vendor"] or "", fmt)):
            try:
                res = search()
            except Exception:
                continue
            u = find_match(res, v["title"], v["vendor"] or "", fmt)
            if u and u != v["upc"]:
                sp = valid(f"/{u}")
                if sp:
                    return {"status": "review", "suggest_upc": u, "suggest_title": sp["title"]}
        return {"status": "review"}

    done = errors = review = 0
    with ThreadPoolExecutor(config.WEBAMI_WORKERS_MAX) as pool:
        futs = {pool.submit(check, v): v for v in vs}
        for fut in as_completed(futs):
            if is_cancelled(job_id):
                for f in futs:
                    f.cancel()
                break
            v = futs[fut]
            try:
                r = fut.result()
                db.save_price_check(v["variant_id"], v["upc"], **r)
                review += r["status"] == "review"
            except Exception:
                errors += 1
                logger.exception("Price check failed for %s", v["variant_id"])
            done += 1
            update(job_id, progress=done, workers=client.limiter.limit,
                   message=f"Checked {done} of {len(vs)} variants…")
    status = "cancelled" if is_cancelled(job_id) else "partial" if errors else "done"
    db.log_sync("price_check", status, f"checked:{done} review:{review} errors:{errors}")
    update(job_id, message=f"{status.capitalize()} - {done} checked, {review} need review")
    return {"status": status, "synced": done, "errors": errors}