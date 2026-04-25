"""
Startup bootstrap logic.
Determines whether this is a first run or a subsequent open, then
triggers the appropriate sync strategy for both Webami and Shopify.
"""

import logging

import db.database as db
from tmp.shopify_sync import ShopifySyncOrchestrator
from backend.sync.bridge import GapFiller, PriceBridge
from backend.webami.webami_sync import WebamiSyncOrchestrator

logger = logging.getLogger(__name__)

_webami = WebamiSyncOrchestrator()
_shopify = ShopifySyncOrchestrator()


def run_startup_sync() -> dict:
    """
    Called once on app open.
    - First run  → full sync everything
    - Subsequent → incremental sync only
    """
    results = {}

    is_first_run_webami = db.get_sync_state("webami_orders") is None
    if is_first_run_webami:
        logger.info("First run detected for WebAmi — running full sync")
        results["webami_orders"] = _webami.sync_orders_full()
    else:
        logger.info("Subsequent run for WebAmi — running incremental sync")
        results["webami_orders"] = _webami.sync_orders_incremental()

    is_first_run_shopify = db.get_sync_state("shopify_products") is None
    if is_first_run_shopify:
        logger.info("First run detected for Shopify — running full sync")
        results["shopify"] = _shopify.sync_all()
    else:
        logger.info("Subsequent run for Shopify — running incremental sync")
        results["shopify"] = _shopify.sync_incremental()
    
    # Always run bridge tasks after data is fresh
    # results["price_bridge"] = _price_bridge.sync_prices_to_shopify()
    # results["gap_fill"] = _gap_filler.fill_missing_fields()

    logger.info(f"Startup sync complete: {results}")
    return results