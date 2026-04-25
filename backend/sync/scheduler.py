# """
# Background job scheduler.
# Runs price sync and gap filling on a configurable interval.
# """

# import logging

# from apscheduler.schedulers.background import BackgroundScheduler
# from apscheduler.triggers.interval import IntervalTrigger

# import config as config
# from sync.bridge import GapFiller, PriceBridge
# from webami.webami_sync import WebamiSyncOrchestrator

# logger = logging.getLogger(__name__)

# _scheduler = BackgroundScheduler()
# _webami = WebamiSyncOrchestrator()
# _price_bridge = PriceBridge()
# _gap_filler = GapFiller()


# def _job_price_sync():
#     logger.info("Scheduled: price sync starting")
#     _webami.sync_prices()
#     _price_bridge.sync_prices_to_shopify()


# def _job_gap_fill():
#     logger.info("Scheduled: gap fill starting")
#     _gap_filler.fill_missing_fields()


# def start():
#     _scheduler.add_job(
#         func=_job_price_sync,
#         trigger=IntervalTrigger(hours=config.WEBAMI_PRICE_SYNC_INTERVAL_HOURS),
#         id="price_sync",
#         replace_existing=True,
#         max_instances=1,
#     )
#     _scheduler.add_job(
#         func=_job_gap_fill,
#         trigger=IntervalTrigger(hours=24),
#         id="gap_fill",
#         replace_existing=True,
#         max_instances=1,
#     )
#     _scheduler.start()
#     logger.info("Scheduler started")


# def stop():
#     _scheduler.shutdown(wait=False)
#     logger.info("Scheduler stopped")


# def trigger_price_sync_now():
#     """Manually fire a price sync outside the schedule."""
#     _scheduler.add_job(
#         func=_job_price_sync,
#         id="price_sync_manual",
#         replace_existing=True,
#     )


from sync.services.pricing import PriceSyncService
from sync.services.gap_fill import GapFillService

_price = PriceSyncService()
_gap_fill = GapFillService()


def _job_price_sync():
    _price.run()


def _job_gap_fill():
    _gap_fill.run()