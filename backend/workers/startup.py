"""
Startup bootstrap.
Runs once on app open — full sync on first run, incremental after that.
"""

import logging

import db.database as db
from webami.webami_service import WebamiSyncService
from shopify.shopify_service import ShopifySyncService

logger = logging.getLogger(__name__)

_webami = WebamiSyncService()
_shopify = ShopifySyncService()

def run_startup_sync() -> None:
    is_first_run_webami: bool = db.get_sync_state("webami_orders") is None
    if is_first_run_webami:
        logger.info("First run — Webami full sync")
        _webami.sync_orders_full()
    else:
        logger.info("Subsequent run — Webami incremental sync")
        _webami.sync_orders_incremental()

    is_first_run_shopify: bool = db.get_sync_state("shopify_products") is None
    if is_first_run_shopify:
        logger.info("First run — Shopify full sync")
        _shopify.run_full()
    else:
        logger.info("Subsequent run — Shopify incremental sync")
        _shopify.run_incremental()