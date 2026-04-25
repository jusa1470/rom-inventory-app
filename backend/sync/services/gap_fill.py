"""
Gap fill service.

Purpose:
Fill missing Shopify product fields using Webami DB as source of truth.

This includes:
- images
- tags
- product type
"""

import logging
from typing import Optional, List

import db.database as db
import config
import sync.cancel as cancel
from shopify.client import ShopifyClient

logger = logging.getLogger(__name__)


class GapFillService:
    def __init__(self):
        self.client = ShopifyClient()

    # ── PUBLIC ENTRYPOINT ─────────────────────────────

    def run_full(self, product_ids: Optional[List[str]] = None) -> dict:
        cancel.set_running("Gap fill")

        try:
            targets = self._get_targets(product_ids)

            filled = 0
            skipped = 0

            for sp in targets:
                if cancel.cancelled():
                    break

                upc = sp.get("upc")
                if not upc:
                    skipped += 1
                    continue

                wp_list = db.search_webami_products(upc)
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

                except Exception:
                    logger.exception(f"Gap fill failed for {sp['product_id']}")

            result = {"filled": filled, "skipped": skipped}
            cancel.set_result("completed", "Gap fill", counts=result)

            return result

        except Exception as e:
            cancel.set_result("failed", "Gap fill", detail=str(e))
            logger.exception("Gap fill failed")
            raise

        finally:
            cancel.clear_running()

    # ── TARGET SELECTION ──────────────────────────────

    def _get_targets(self, product_ids: Optional[List[str]]) -> list[dict]:
        if product_ids:
            return [
                p for pid in product_ids
                if (p := db.get_shopify_product(pid)) is not None
            ]

        return db.search_shopify_products("")

    # ── UPDATE LOGIC ────────────────────────────────

    def _compute_updates(self, sp: dict, wp: dict) -> dict:
        updates = {}

        # ── IMAGES ────────────────────────────────
        if not sp.get("image_urls"):
            wp_images = wp.get("image_urls") or []
            if wp_images:
                updates["images"] = [{"src": wp_images[0]}]

        # ── TAGS ──────────────────────────────────
        if not sp.get("tags"):
            fmt = wp.get("format")
            if fmt:
                friendly = config.FORMAT_NAMES.get(fmt)
                if friendly:
                    updates["tags"] = f"New,{friendly}"

        # ── PRODUCT TYPE ──────────────────────────
        if not sp.get("product_type") and wp.get("format"):
            fmt = config.FORMAT_NAMES.get(wp["format"])

            updates["productType"] = (
                f"Media > Music & Sound Recordings > {fmt}"
                if fmt
                else "Media > Music & Sound Recordings"
            )

        return updates