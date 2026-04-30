"""
Background job scheduler.
Checks every 3 hours, runs if the configured interval has elapsed.
"""

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

import config
import db.database as db
import sync.cancel as cancel
from sync.bridge import BridgeService
from webami.webami_service import WebamiSyncService
from shopify.shopify_service import ShopifySyncService

logger: logging.Logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()
_bridge = BridgeService()
_webami = WebamiSyncService()
_shopify = ShopifySyncService()

INTERVAL_TRIGGER = 3

def _hours_since_last_sync(state_key: str) -> float | None:
    state: db.SyncStateDTO | None = db.get_sync_state(state_key)
    if not state or not state.last_sync:
        return None
    last: datetime = state.last_sync
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    delta: timedelta = datetime.now(timezone.utc) - last
    return delta.total_seconds() / 3600

def _safe_run(fn, state_key: str, interval_hours: int):
    def wrapper():
        if cancel.running_label():
            logger.info(f"Skipping scheduled {fn.__name__} — sync already running")
            return

        hours_since: float | None = _hours_since_last_sync(state_key)

        if hours_since is not None and hours_since < interval_hours:
            logger.info(
                f"Skipping scheduled {fn.__name__} — "
                f"last sync {hours_since:.1f}h ago, interval is {interval_hours}h"
            )
            return

        logger.info(
            f"Running scheduled {fn.__name__} — "
            + ("never synced" if hours_since is None else f"last sync {hours_since:.1f}h ago")
        )

        try:
            fn()
        except Exception:
            logger.exception(f"Scheduled job {fn.__name__} failed")

    return wrapper

def start() -> None:
    _scheduler.add_job(
        func=_safe_run(_webami.sync_orders_recent, "webami_orders", config.WEBAMI_ORDER_SYNC_INTERVAL_HOURS),
        trigger=IntervalTrigger(hours=INTERVAL_TRIGGER),
        id="webami_orders",
        replace_existing=True,
        max_instances=1,
    )
    # _scheduler.add_job(
    #     func=_safe_run(_bridge.push_prices, "webami_prices", config.WEBAMI_PRICE_SYNC_INTERVAL_HOURS),
    #     trigger=IntervalTrigger(hours=INTERVAL_TRIGGER),
    #     id="price_sync",
    #     replace_existing=True,
    #     max_instances=1,
    # )
    _scheduler.add_job(
        func=_safe_run(_shopify.run_recent, "shopify_products", config.SHOPIFY_SYNC_INTERVAL_HOURS),
        trigger=IntervalTrigger(hours=INTERVAL_TRIGGER),
        id="shopify_products",
        replace_existing=True,
        max_instances=1,
    )
    _scheduler.start()
    logger.info("Scheduler started")

def stop() -> None:
    _scheduler.shutdown(wait=False)
    logger.info("Scheduler stopped")