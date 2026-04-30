"""
Webami sync service.
Handles orders, products, and prices.
"""

import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import config
import db.database as db
import sync.cancel as cancel
from db.models import WebamiProduct, WebamiOrder
from webami import orders as order_fetcher
from webami import scraper

logger: logging.Logger = logging.getLogger(__name__)

class WebamiSyncService:

    # ── Orders ───────────────────────────────────────────────────────

    def sync_orders_full(self) -> dict:
        cancel.reset()
        cancel.set_running("Webami orders — full")
        logger.info("Webami: full order sync starting")
        try:
            all_orders: list[WebamiOrder] = order_fetcher.get_all_orders()
            result = self._process_orders(all_orders)
            cancel.set_result(
                "cancelled" if result["cancelled"] else "completed",
                "Webami orders — full",
                counts=result,
            )
            return result
        except Exception as e:
            cancel.set_result("failed", "Webami orders — full", detail=str(e))
            logger.error(f"Webami orders full sync failed: {e}")
            raise
        finally:
            cancel.clear_running()

    def sync_orders_recent(self) -> dict:
        cancel.reset()
        cancel.set_running("Webami orders — recent")
        logger.info("Webami: recent order sync starting")
        try:
            known: set[str] = db.get_all_order_guids()
            recent_orders: list[WebamiOrder] = order_fetcher.get_recent_orders()
            new_orders: list[WebamiOrder] = [o for o in recent_orders if o.guid not in known]
            logger.info(f"Webami: {len(new_orders)} new order(s) found")
            result = self._process_orders(new_orders)
            cancel.set_result(
                "cancelled" if result["cancelled"] else "completed",
                "Webami orders — recent",
                counts=result,
            )
            return result
        except Exception as e:
            cancel.set_result("failed", "Webami orders — recent", detail=str(e))
            logger.error(f"Webami orders recent sync failed: {e}")
            raise
        finally:
            cancel.clear_running()

    def _process_orders(self, orders: list[WebamiOrder]) -> dict:
        if not orders:
            return {
                "orders_processed": 0,
                "orders_total": 0,
                "products_scraped": 0,
                "cancelled": cancel.cancelled(),
            }

        known_upcs: set[str] = db.get_all_upcs()
        new_upcs: set[str] = set()
        completed = 0
        total: int = len(orders)

        logger.info(
            f"Webami: fetching {total} order page(s) "
            f"with {config.WEBAMI_ORDER_WORKERS} worker(s)"
        )

        with ThreadPoolExecutor(
            max_workers=config.WEBAMI_ORDER_WORKERS,
            thread_name_prefix="WebamiOrders",
        ) as pool:
            futures = {
                pool.submit(order_fetcher.parse_order_page_worker, order.guid): order
                for order in orders
            }
            for future in as_completed(futures):
                if cancel.cancelled():
                    for f in futures:
                        f.cancel()
                    logger.info("Webami orders: cancelled — draining pool")
                    break

                order: WebamiOrder = futures[future]
                try:
                    guid, items = future.result()
                    upcs = [i["upc"] for i in items]
                    order.number_of_products = len(items)
                    db.upsert_order(order)
                    db.upsert_order_items(guid, items)
                    completed += 1
                    for upc in upcs:
                        if upc not in known_upcs:
                            new_upcs.add(upc)
                    logger.info(f"Order {guid}: done ({completed}/{total})")
                except Exception as e:
                    logger.error(f"Order {order.guid}: failed — {e}")

        scraped: int = self._scrape_products_parallel(new_upcs)

        if not cancel.cancelled():
            db.set_sync_state("webami_orders", datetime.now(timezone.utc))
            db.set_sync_state("webami_products", datetime.now(timezone.utc))

        return {
            "orders_processed": completed,
            "orders_total": total,
            "products_scraped": scraped,
            "cancelled": cancel.cancelled(),
        }

    # ── Products ─────────────────────────────────────────────────────

    def sync_products_full(self) -> dict:
        cancel.reset()
        cancel.set_running("Webami products — full")
        logger.info("Webami: full product sync starting")
        try:
            all_upcs: set[str] = db.get_all_upcs()
            scraped: int = self._scrape_products_parallel(all_upcs)
            if not cancel.cancelled():
                db.set_sync_state("webami_products", datetime.now(timezone.utc))
            result = {
                "products_scraped": scraped,
                "products_total": len(all_upcs),
                "cancelled": cancel.cancelled(),
            }
            cancel.set_result(
                "cancelled" if result["cancelled"] else "completed",
                "Webami products — full",
                counts=result,
            )
            return result
        except Exception as e:
            cancel.set_result("failed", "Webami products — full", detail=str(e))
            logger.error(f"Webami products full sync failed: {e}")
            raise
        finally:
            cancel.clear_running()

    def _scrape_products_parallel(self, upcs: set[str]) -> int:
        if not upcs:
            return 0

        completed = 0
        total: int = len(upcs)

        logger.info(
            f"Webami: starting product scrape — "
            f"{config.WEBAMI_SCRAPE_WORKERS} workers, {total} UPCs"
        )

        with ThreadPoolExecutor(
            max_workers=config.WEBAMI_SCRAPE_WORKERS,
            thread_name_prefix="WebamiScraper",
        ) as pool:
            futures = {
                pool.submit(scraper.scrape_product_page, upc): upc
                for upc in upcs
            }
            for future in as_completed(futures):
                if cancel.cancelled():
                    for f in futures:
                        f.cancel()
                    break

                upc: str = futures[future]
                try:
                    data = future.result()
                    if not data:
                        continue
                    db.upsert_webami_product(WebamiProduct(
                        upc=data["upc"],
                        title=data.get("title"),
                        artist=data.get("artist", ""),
                        brand=data.get("brand", ""),
                        image_urls=data.get("image_urls"),
                        features=data.get("features", ""),
                        genres=data.get("genres", ""),
                        weight_grams=data.get("weight_grams"),
                        cost=data.get("cost"),
                        format=data.get("format"),
                    ))
                    completed += 1
                    if completed % 100 == 0:
                        logger.info(f"UPC {upc}: done ({completed}/{total})")
                except Exception as e:
                    logger.error(f"UPC {upc}: scrape failed — {e}")

        logger.info(f"Webami: scraped {completed}/{total} products")
        return completed

    # ── Prices ───────────────────────────────────────────────────────

    def sync_prices(self, upcs: list[str] | None = None) -> dict:
        cancel.reset()
        cancel.set_running("Webami prices")
        targets: list[str] = list(upcs or db.get_all_upcs())
        logger.info(f"Webami: syncing prices for {len(targets)} product(s)")
        try:
            updated = 0
            for upc in targets:
                if cancel.cancelled():
                    logger.info(f"Webami prices: cancelled after {updated} updates")
                    break
                cost: float | None = scraper.get_cost(upc)
                if cost is not None:
                    db.update_product_cost(upc, cost)
                    updated += 1

            if not cancel.cancelled():
                db.set_sync_state("webami_prices", datetime.now(timezone.utc))

            result = {
                "prices_updated": updated,
                "prices_total": len(targets),
                "cancelled": cancel.cancelled(),
            }
            cancel.set_result(
                "cancelled" if result["cancelled"] else "completed",
                "Webami prices",
                counts=result,
            )
            return result
        except Exception as e:
            cancel.set_result("failed", "Webami prices", detail=str(e))
            logger.error(f"Webami price sync failed: {e}")
            raise
        finally:
            cancel.clear_running()