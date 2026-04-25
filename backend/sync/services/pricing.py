"""
Price sync service.

Flow:
Webami DB (cost) →
calculate price →
Shopify DB lookup →
push to Shopify →
update local variant DB
"""

import logging
from typing import Optional, List

import db.database as db
from shopify.client import ShopifyClient
import config
import sync.cancel as cancel

logger = logging.getLogger(__name__)


def _calculate_price(cost: float) -> float:
    """Centralized pricing formula."""
    return round(cost / (1 - config.MARGIN), 2)


class PriceSyncService:
    def __init__(self):
        self.client = ShopifyClient()

    # ── PUBLIC ENTRYPOINT ──────────────────────────────

    def run_full(self, upcs: Optional[List[str]] = None) -> dict:
        cancel.set_running("Price sync")

        try:
            products = self._get_targets(upcs)

            updated = 0
            skipped = 0

            for wp in products:
                if cancel.cancelled():
                    break

                cost = wp["cost"]
                if cost is None:
                    skipped += 1
                    continue

                sp = self._find_shopify_product(wp["upc"])
                if not sp:
                    skipped += 1
                    continue

                new_price = _calculate_price(cost)
                current_price = self._get_current_price(sp)

                if current_price == new_price:
                    skipped += 1
                    continue

                try:
                    self._update_shopify_price(sp, new_price)
                    updated += 1

                    logger.info(
                        f"UPC {wp['upc']}: {current_price} → {new_price}"
                    )

                except Exception:
                    logger.exception(f"Failed updating price for {wp['upc']}")

            result = {"updated": updated, "skipped": skipped}
            cancel.set_result("completed", "Price sync", counts=result)

            return result

        except Exception as e:
            cancel.set_result("failed", "Price sync", detail=str(e))
            logger.exception("Price sync failed")
            raise

        finally:
            cancel.clear_running()

    # ── TARGET SELECTION ──────────────────────────────

    def _get_targets(self, upcs: Optional[List[str]]) -> list[dict]:
        if upcs:
            results = []
            for u in upcs:
                rows = db.search_webami_products(u)
                if rows:
                    results.append(rows[0])
            return results

        return db.search_webami_products_with_cost()

    def _find_shopify_product(self, upc: str) -> Optional[dict]:
        results = db.search_shopify_products(upc)
        return results[0] if results else None

    # ── PRICE HELPERS ────────────────────────────────

    def _get_current_price(self, sp: dict) -> Optional[float]:
        variants = sp.get("variants")

        if not variants:
            return None

        try:
            # assuming variants already stored as JSON list
            first = variants[0] if isinstance(variants, list) else None
            if first:
                return float(first.get("price", 0))
        except Exception:
            pass

        return None

    def _update_shopify_price(self, sp: dict, new_price: float) -> None:
        variants = sp.get("variants") or []

        if not variants:
            return

        variant_inputs = [
            {
                "id": v["id"],
                "price": str(new_price),
            }
            for v in variants
        ]

        self.client.update_product({
            "id": sp["product_id"],
            "variants": variant_inputs,
        })