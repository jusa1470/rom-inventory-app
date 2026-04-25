# import logging
# from datetime import datetime, timezone

# import db.database as db
# import sync.cancel as cancel
# from sync.base import SyncJob

# from webami import orders as order_fetcher
# from webami import scraper
# from db.models import WebamiProduct

# logger = logging.getLogger(__name__)


# class WebamiSyncService(SyncJob):
#     job_name = "Webami"

#     def _execute(self, mode: str) -> dict:
#         if mode == "full":
#             return self._sync_all()
#         else:
#             return self._sync_incremental()

#     def _sync_all(self) -> dict:
#         orders = order_fetcher.get_all_orders()
#         return self._process_orders(orders)

#     def _sync_incremental(self) -> dict:
#         known = db.get_all_order_guids()
#         recent = order_fetcher.get_recent_orders()
#         new_orders = [o for o in recent if o.guid not in known]
#         return self._process_orders(new_orders)

#     def _process_orders(self, orders):
#         new_upcs = set()
#         completed = 0

#         for order in orders:
#             if cancel.cancelled():
#                 break

#             guid, upcs = order_fetcher.parse_order_page_worker(order.guid)

#             order.raw_upcs = upcs
#             order.number_of_products = len(upcs)

#             db.upsert_order(order)

#             for upc in upcs:
#                 new_upcs.add(upc)

#             completed += 1

#         scraped = self._scrape_products(new_upcs)

#         return {
#             "orders_processed": completed,
#             "products_scraped": scraped,
#         }

#     def _scrape_products(self, upcs):
#         count = 0

#         for upc in upcs:
#             if cancel.cancelled():
#                 break

#             data = scraper.scrape_product_page(upc)

#             if data:
#                 db.upsert_webami_product(
#                     WebamiProduct(
#                         upc=data["upc"],
#                         album=data.get("album"),
#                         artist=data.get("artist"),
#                         image_urls=data.get("image_urls"),
#                         features=data.get("features"),
#                         weight_grams=data.get("weight_grams"),
#                         cost=data.get("cost"),
#                         format=data.get("format"),
#                     )
#                 )
#                 count += 1

#         return count

#     def _update_state(self, mode: str) -> None:
#         db.set_sync_state(
#             "webami_orders",
#             datetime.now(timezone.utc),
#         )


"""
Webami sync service.

Responsibilities:
- Fetch orders (full / incremental)
- Scrape missing products
- Refresh prices

Uses DTOs at boundaries, ORM only at DB layer.
"""

import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional

import db.database as db
from db.models import WebamiProduct, WebamiOrder
from webami.scraper import scrape_product_page, get_cost
from webami.orders import fetch_orders  # assume this returns WebamiOrderDTOs
import sync.cancel as cancel

logger = logging.getLogger(__name__)

MAX_WORKERS = 6  # tune based on Webami limits


class WebamiSyncService:
    # ── ORDERS ─────────────────────────────────────────

    def run_full(self) -> dict:
        cancel.set_running("Webami full sync")
        try:
            orders = fetch_orders()  # full fetch
            return self._process_orders(orders, full=True)
        except Exception as e:
            cancel.set_result("failed", "Webami full sync", detail=str(e))
            logger.exception("Webami full sync failed")
            raise
        finally:
            cancel.clear_running()

    def run_incremental(self) -> dict:
        cancel.set_running("Webami incremental sync")
        try:
            state = db.get_sync_state("webami_orders")
            since = state["last_sync"] if state else None

            orders = fetch_orders(since=since)
            return self._process_orders(orders, full=False)
        except Exception as e:
            cancel.set_result("failed", "Webami incremental sync", detail=str(e))
            logger.exception("Webami incremental sync failed")
            raise
        finally:
            cancel.clear_running()

    def _process_orders(self, orders: List[dict], full: bool) -> dict:
        existing = db.get_all_order_guids()
        new_orders = 0
        upcs_to_scrape = set()

        for o in orders:
            if cancel.cancelled():
                break

            if o["guid"] not in existing:
                new_orders += 1
                upcs_to_scrape.update(o["raw_upcs"])

            db.upsert_order(WebamiOrder(
                guid=o["guid"],
                order_number=o.get("order_number"),
                order_name=o.get("order_name"),
                order_date=o.get("order_date"),
                number_of_products=len(o["raw_upcs"]),
                raw_upcs=o["raw_upcs"],
            ))

        scraped = self._scrape_products(list(upcs_to_scrape))

        db.set_sync_state(
            "webami_orders",
            datetime.now(timezone.utc)
        )

        result = {
            "orders_processed": len(orders),
            "new_orders": new_orders,
            "products_scraped": scraped,
        }

        cancel.set_result("completed", "Webami orders", counts=result)
        return result

    # ── PRODUCTS ───────────────────────────────────────

    def _scrape_products(self, upcs: List[str]) -> int:
        if not upcs:
            return 0

        existing = db.get_all_upcs()
        targets = [u for u in upcs if u not in existing]

        if not targets:
            return 0

        logger.info(f"Scraping {len(targets)} new products")

        count = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {
                executor.submit(scrape_product_page, upc): upc
                for upc in targets
            }

            for future in as_completed(futures):
                if cancel.cancelled():
                    break

                upc = futures[future]

                try:
                    dto = future.result()
                    if not dto:
                        continue

                    db.upsert_webami_product(WebamiProduct(
                        upc=dto["upc"],
                        album=dto["album"],
                        artist=dto["artist"],
                        image_urls=dto["image_urls"],
                        features=dto["features"],
                        weight_grams=dto["weight_grams"],
                        cost=dto["cost"],
                        format=dto["format"],
                    ))

                    count += 1

                except Exception:
                    logger.exception(f"Failed scraping UPC {upc}")

        return count

    # ── PRICES ─────────────────────────────────────────

    def run_prices(self, upcs: Optional[List[str]] = None) -> dict:
        cancel.set_running("Webami price sync")
        try:
            if upcs:
                targets = upcs
            else:
                targets = list(db.get_all_upcs())

            updated = 0

            for upc in targets:
                if cancel.cancelled():
                    break

                cost = get_cost(upc)
                if cost is None:
                    continue

                db.update_product_cost(upc, cost)
                updated += 1

            db.set_sync_state(
                "webami_prices",
                datetime.now(timezone.utc)
            )

            result = {"updated": updated}
            cancel.set_result("completed", "Webami prices", counts=result)

            return result

        except Exception as e:
            cancel.set_result("failed", "Webami prices", detail=str(e))
            logger.exception("Webami price sync failed")
            raise

        finally:
            cancel.clear_running()