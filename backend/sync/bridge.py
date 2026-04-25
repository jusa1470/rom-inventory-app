"""
Bridge between Webami and Shopify.
All db helpers now return plain dicts — accessed with ["key"] not .attr.
"""

import json
import logging
from typing import Optional

import config
import db.database as db
import sync.cancel as cancel
from shopify.client import ShopifyClient

logger = logging.getLogger(__name__)


def _calculate_price(cost: float) -> float:
    return round(cost / (1 - config.MARGIN), 2)


class PriceBridge:
    def __init__(self):
        self.client = ShopifyClient()

    def sync_prices_to_shopify(self, upcs: list[str] | None = None) -> dict:
        cancel.set_running("Price bridge")
        try:
            updated = 0
            skipped = 0

            webami_products = self._get_webami_targets(upcs)

            for wp in webami_products:
                if wp["cost"] is None:
                    skipped += 1
                    continue

                expected_price = _calculate_price(wp["cost"])
                sp = self._find_shopify_product(wp["upc"])
                if sp is None:
                    skipped += 1
                    continue

                current_price = self._get_current_price(sp)
                if current_price == expected_price:
                    skipped += 1
                    continue

                try:
                    self._push_price(
                        sp["product_id"], sp["variants"],
                        expected_price, wp["cost"],
                    )
                    updated += 1
                    logger.info(
                        f"UPC {wp['upc']}: price updated "
                        f"{current_price} → {expected_price}"
                    )
                except Exception as e:
                    logger.error(f"UPC {wp['upc']}: price push failed — {e}")

            result = {"updated": updated, "skipped": skipped}
            cancel.set_result("completed", "Price bridge", counts=result)
            logger.info(f"Price bridge: {updated} updated, {skipped} unchanged/skipped")
            return result
        except Exception as e:
            cancel.set_result("failed", "Price bridge", detail=str(e))
            logger.error(f"Price bridge failed: {e}")
            raise
        finally:
            cancel.clear_running()

    def _get_webami_targets(self, upcs: list[str] | None) -> list[dict]:
        if upcs:
            results = []
            for u in upcs:
                rows = db.search_webami_products(u)
                if rows:
                    results.append(rows[0])
            return results
        # All products with a known cost — query returning dicts
        return db.search_webami_products_with_cost()

    def _find_shopify_product(self, upc: str) -> Optional[dict]:
        results = db.search_shopify_products(upc)
        return results[0] if results else None

    def _get_current_price(self, sp: dict) -> Optional[float]:
        if not sp.get("variants"):
            return None
        try:
            variants = json.loads(sp["variants"])
            if variants:
                return float(variants[0].get("price", 0))
        except (json.JSONDecodeError, IndexError, ValueError):
            pass
        return None

    def _push_price(self, product_id: str, variants_json: str,
                    new_price: float, cost: float) -> None:
        variants = json.loads(variants_json) if variants_json else []
        variant_inputs = [
            {"id": v["id"], "price": str(new_price)}
            for v in variants
        ]
        self.client.update_product({
            "id": product_id,
            "variants": variant_inputs,
        })


class GapFiller:
    def __init__(self):
        self.client = ShopifyClient()

    def fill_missing_fields(self, product_ids: list[str] | None = None) -> dict:
        cancel.set_running("Gap filler")
        try:
            filled = 0
            skipped = 0

            targets = self._get_targets(product_ids)

            for sp in targets:
                if not sp.get("upc"):
                    skipped += 1
                    continue

                wp_list = db.search_webami_products(sp["upc"])
                if not wp_list:
                    skipped += 1
                    continue
                wp = wp_list[0]

                updates = self._compute_updates(sp, wp)
                if not updates:
                    skipped += 1
                    continue

                try:
                    updates["id"] = sp["product_id"]
                    self.client.update_product(updates)
                    filled += 1
                except Exception as e:
                    logger.error(f"Gap fill failed for {sp['product_id']}: {e}")

            result = {"filled": filled, "skipped": skipped}
            cancel.set_result("completed", "Gap filler", counts=result)
            logger.info(f"Gap filler: {filled} filled, {skipped} skipped")
            return result
        except Exception as e:
            cancel.set_result("failed", "Gap filler", detail=str(e))
            logger.error(f"Gap filler failed: {e}")
            raise
        finally:
            cancel.clear_running()

    def _get_targets(self, product_ids: list[str] | None) -> list[dict]:
        if product_ids:
            return [p for sid in product_ids
                    if (p := db.get_shopify_product(sid)) is not None]
        return db.search_shopify_products("")   # empty query = all

    def _compute_updates(self, sp: dict, wp: dict) -> dict:
        updates = {}
        image_urls = json.loads(sp.get("image_urls") or "[]")
        if not image_urls:
            wp_images = json.loads(wp.get("image_urls") or "[]")
            if wp_images:
                updates["images"] = [{"src": wp_images[0]}]
        if not sp.get("tags") or sp["tags"] == "[]":
            fmt = config.FORMAT_NAMES.get(wp.get("format", ""))
            if fmt:
                updates["tags"] = f"New,{fmt}"
        if not sp.get("product_type") and wp.get("format"):
            fmt = config.FORMAT_NAMES.get(wp["format"])
            updates["productType"] = (
                f"Media > Music & Sound Recordings > {fmt}" if fmt
                else "Media > Music & Sound Recordings"
            )
        return updates