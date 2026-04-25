# import logging
# from datetime import datetime, timezone

# import db.database as db
# import sync.cancel as cancel
# from sync.base import SyncJob

# from shopify.client import ShopifyClient
# from shopify.parsers import parse_product, parse_variants

# logger = logging.getLogger(__name__)


# class ShopifySyncService(SyncJob):
#     job_name = "Shopify products"

#     def __init__(self):
#         self.client = ShopifyClient()

#     def _execute(self, mode: str) -> dict:
#         since = None

#         if mode == "incremental":
#             state = db.get_sync_state("shopify_products")
#             if state and state["last_sync"]:
#                 since = state["last_sync"].strftime("%Y-%m-%dT%H:%M:%S%z")

#         return self._ingest(since)

#     def _ingest(self, since: str | None) -> dict:
#         count = 0

#         for node in self.client.fetch_all_products(since=since):
#             if cancel.cancelled():
#                 break

#             product = parse_product(node)
#             db.upsert_shopify_product(product)

#             for v in parse_variants(node):
#                 db.upsert_shopify_variant(v)

#             count += 1

#         return {"products_synced": count}

#     def _update_state(self, mode: str) -> None:
#         db.set_sync_state(
#             "shopify_products",
#             datetime.now(timezone.utc),
#         )


"""
Shopify sync service.

Responsibilities:
- Fetch products from Shopify (via client)
- Persist into local DB
- Manage incremental/full sync
- Handle cancellation + sync state

NO parsing logic.
NO raw GraphQL.
NO JSON decoding.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import db.database as db
import sync.cancel as cancel

from shopify.client import ShopifyClient
from db.models import ShopifyProduct, ShopifyVariant

logger = logging.getLogger(__name__)


class ShopifySyncService:
    def __init__(self):
        self.client = ShopifyClient()

    # ────────────────────────────────────────────────────────────────
    # Public entrypoints
    # ────────────────────────────────────────────────────────────────

    def run_full(self) -> dict:
        return self._run_sync(full=True)

    def run_incremental(self) -> dict:
        return self._run_sync(full=False)

    # ────────────────────────────────────────────────────────────────
    # Core sync logic
    # ────────────────────────────────────────────────────────────────

    def _run_sync(self, full: bool) -> dict:
        label = "Shopify full sync" if full else "Shopify incremental sync"
        cancel.set_running(label)

        try:
            state = db.get_sync_state("shopify_products")
            since = None if full or not state else state["last_sync"]

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

            # Save sync state
            db.set_sync_state(
                "shopify_products",
                last_sync=datetime.now(timezone.utc),
            )

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

    # ────────────────────────────────────────────────────────────────
    # Persistence helpers
    # ────────────────────────────────────────────────────────────────

    def _upsert_product(self, p: dict) -> None:
        obj = ShopifyProduct(
            product_id=p["product_id"],
            title=p["title"],
            vendor=p["vendor"],
            status=p["status"],
            tags=p["tags"],
            product_type=p["product_type"],
            image_urls=p["images"],
            upc=p["upc"],
            updated_at=self._parse_dt(p["updated_at"]),
        )

        db.upsert_shopify_product(obj)

    def _upsert_variants(self, p: dict) -> None:
        for v in p["variants"]:
            obj = ShopifyVariant(
                variant_id=v["id"],
                product_id=p["product_id"],
                inventory_quantity=v.get("inventory_quantity") or 0,
                taxable=v.get("taxable", True),
                cost=v.get("cost") or 0.0,
                price=v.get("price") or 0.0,
                weight=v.get("weight") or 0.0,
                weight_unit=v.get("weight_unit") or "g",
                updated_at=self._parse_dt(v.get("updated_at")),
            )

            db.upsert_shopify_variant(obj)

    # ────────────────────────────────────────────────────────────────
    # Utils
    # ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            return None