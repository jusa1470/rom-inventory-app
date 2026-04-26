"""
Bridge between Webami and Shopify.
Handles price pushes and field gap filling.
"""

import logging
from typing import Optional

import config
import db.database as db
import sync.cancel as cancel
from shopify.client import ShopifyClient
from objects.dtos import WebamiProductDTO, ShopifyProductDTO

logger = logging.getLogger(__name__)


def _calculate_price(cost: float) -> float:
    return round(cost / (1 - config.MARGIN), 2)


class BridgeService:
    def __init__(self):
        self.client = ShopifyClient()

    # ── Prices ────────────────────────────────────────────────────────

    def push_prices(self, upcs: Optional[list[str]] = None) -> dict:
        cancel.reset()
        cancel.set_running("Price bridge")
        try:
            targets = self._get_webami_targets(upcs)
            updated = 0
            skipped = 0

            for wp in targets:
                if cancel.cancelled():
                    break

                if wp.cost is None:
                    skipped += 1
                    continue

                sp = self._find_shopify_product(wp.upc)
                if not sp:
                    skipped += 1
                    continue

                new_price = _calculate_price(wp.cost)
                current_price = self._get_current_price(sp)

                if current_price == new_price:
                    skipped += 1
                    continue

                try:
                    self._push_price(sp, new_price)
                    updated += 1
                    logger.info(f"UPC {wp.upc}: {current_price} → {new_price}")
                except Exception:
                    logger.exception(f"Price push failed for {wp.upc}")

            result = {"updated": updated, "skipped": skipped}
            cancel.set_result("completed", "Price bridge", counts=result)
            return result

        except Exception as e:
            cancel.set_result("failed", "Price bridge", detail=str(e))
            logger.exception("Price bridge failed")
            raise

        finally:
            cancel.clear_running()

    # ── Gap fill ──────────────────────────────────────────────────────

    def fill_gaps(self, product_ids: Optional[list[str]] = None) -> dict:
        cancel.reset()
        cancel.set_running("Gap fill")
        try:
            targets = self._get_shopify_targets(product_ids)
            filled = 0
            skipped = 0

            for sp in targets:
                if cancel.cancelled():
                    break

                if not sp.upc:
                    skipped += 1
                    continue

                wp_list = db.search_webami_products(sp.upc)
                if not wp_list:
                    skipped += 1
                    continue

                updates = self._compute_gap_updates(sp, wp_list[0])
                if not updates:
                    skipped += 1
                    continue

                try:
                    updates["id"] = sp.product_id
                    self.client.update_product(updates)
                    filled += 1
                except Exception:
                    logger.exception(f"Gap fill failed for {sp.product_id}")

            result = {"filled": filled, "skipped": skipped}
            cancel.set_result("completed", "Gap fill", counts=result)
            return result

        except Exception as e:
            cancel.set_result("failed", "Gap fill", detail=str(e))
            logger.exception("Gap fill failed")
            raise

        finally:
            cancel.clear_running()

    # ── Shared helpers ────────────────────────────────────────────────

    def _find_shopify_product(self, upc: str) -> Optional[ShopifyProductDTO]:
        results = db.search_shopify_products(upc)
        return results[0] if results else None

    def _get_current_price(self, sp: ShopifyProductDTO) -> Optional[float]:
        variants = db.get_shopify_variants(sp.product_id)
        if not variants:
            return None
        try:
            return float(variants[0].price)
        except (TypeError, ValueError):
            return None

    # ── Price helpers ─────────────────────────────────────────────────

    def _get_webami_targets(self, upcs: Optional[list[str]]) -> list[WebamiProductDTO]:
        if upcs:
            results = []
            for u in upcs:
                rows = db.search_webami_products(u)
                if rows:
                    results.append(rows[0])
            return results
        return db.search_webami_products_with_cost()

    def _push_price(self, sp: ShopifyProductDTO, new_price: float) -> None:
        variants = db.get_shopify_variants(sp.product_id)
        self.client.update_product({
            "id": sp.product_id,
            "variants": [{"id": v.variant_id, "price": str(new_price)} for v in variants],
        })

    # ── Gap fill helpers ──────────────────────────────────────────────

    def _get_shopify_targets(self, product_ids: Optional[list[str]]) -> list[ShopifyProductDTO]:
        if product_ids:
            return [p for pid in product_ids if (p := db.get_shopify_product(pid))]
        return db.search_shopify_products("")

    def _compute_gap_updates(self, sp: ShopifyProductDTO, wp: WebamiProductDTO) -> dict:
        updates = {}

        if not sp.image_urls:
            images = wp.image_urls or []
            if images:
                updates["images"] = [{"src": images[0]}]

        if not sp.tags:
            format = config.FORMAT_NAMES.get(wp.format or "")
            if format:
                updates["tags"] = f"New,{format}"

        if not sp.product_type and wp.format:
            format = config.FORMAT_NAMES.get(wp.format)
            updates["productType"] = (
                f"Media > Music & Sound Recordings > {format}"
                if format else "Media > Music & Sound Recordings"
            )

        return updates