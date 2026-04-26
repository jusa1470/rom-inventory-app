"""
Shopify sync service.
Fetches products from Shopify and persists into local DB.
"""

import logging
from datetime import datetime, timezone

import db.database as db
import sync.cancel as cancel
from shopify.client import ShopifyClient
from db.models import ShopifyProduct, ShopifyVariant

logger = logging.getLogger(__name__)


class ShopifySyncService:
    def __init__(self):
        self.client = ShopifyClient()

    # ── Helpers ───────────────────────────────────────────────────────

    def _parse_iso_datetime(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception as e:
            logger.warning(f"Invalid datetime: {value} ({e})")
            return None

    # ── Public entrypoints ────────────────────────────────────────────

    def run_full(self) -> dict:
        return self._run_sync(full=True)

    def run_incremental(self) -> dict:
        return self._run_sync(full=False)

    # ── Core sync ─────────────────────────────────────────────────────

    def _run_sync(self, full: bool) -> dict:
        label = "Shopify full sync" if full else "Shopify incremental sync"
        cancel.reset()
        cancel.set_running(label)

        try:
            since = None
            if not full:
                state = db.get_sync_state("shopify_products")
                if state and state.last_sync:
                    since = state.last_sync.strftime("%Y-%m-%dT%H:%M:%S%z")

            processed = 0

            for product in self.client.fetch_all_products(since=since):
                if cancel.cancelled():
                    cancel.set_result("cancelled", label)
                    return {"cancelled": True}

                self._upsert_product(product)
                self._upsert_variants(product)
                processed += 1

                if processed % 50 == 0:
                    logger.info(f"{label}: processed {processed}")

            db.set_sync_state("shopify_products", datetime.now(timezone.utc))

            result = {"processed": processed}
            cancel.set_result("completed", label, counts=result)
            logger.info(f"{label} complete: {processed} products")
            return result

        except Exception as e:
            cancel.set_result("failed", label, detail=str(e))
            logger.exception(f"{label} failed")
            raise

        finally:
            cancel.clear_running()

    # ── Persistence ───────────────────────────────────────────────────

    def _upsert_product(self, p: dict) -> None:
        db.upsert_shopify_product(ShopifyProduct(
            product_id=p["product_id"],
            title=p["title"],
            vendor=p["vendor"],
            status=p["status"],
            tags=p["tags"],
            product_type=p["product_type"],
            image_urls=p["images"],
            upc=p["upc"],
            updated_at=self._parse_iso_datetime(p["updated_at"]),
        ))

    def _upsert_variants(self, p: dict) -> None:
        for v in p["variants"]:
            db.upsert_shopify_variant(ShopifyVariant(
                variant_id=v["id"],
                product_id=p["product_id"],
                inventory_quantity=v.get("inventory_quantity") or 0,
                taxable=v.get("taxable", True),
                cost=v.get("cost") or 0.0,
                price=v.get("price") or 0.0,
                weight=v.get("weight") or 0.0,
                weight_unit=v.get("weight_unit") or "g",
                updated_at=self._parse_iso_datetime(v.get("updated_at")),
            ))