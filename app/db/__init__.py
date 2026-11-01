from app.db.app_config import get_config, is_dry_run, upsert_config
from app.db.connection import get_conn, transaction
from app.db.schema import init_db as _apply_schema
from app.db.shopify_products import (
    count_products,
    get_filter_options,
    get_product_detail,
    list_products,
    save_shopify_product,
    update_local,
    delete_products_not_synced_since
)
from app.db.sync_log import get_sync_log, log_sync
from app.db.webami_orders import get_known_order_guids, get_webami_order, list_webami_orders, save_order, get_webami_stats, get_incomplete_order_guids
from app.db.webami_products import (
    get_unresolved_items, 
    save_webami_product, 
    get_webami_product_by_id, 
    suggest_local, 
    suggest_title, 
    ignore_product, 
    list_unmatched,
    good_match,
    reset_webami_products,
    drop_from_match_cache,
)


def init_db() -> None:
    _apply_schema(get_conn())


__all__: list[str] = [
    "init_db",
    # App config functions
    "get_config", "is_dry_run", "upsert_config",
    # Connection functions
    "get_conn", "transaction",
    # Shopify product functions
    "count_products", "get_filter_options", "get_product_detail", "list_products", "save_shopify_product", 
    "update_local", "delete_products_not_synced_since",
    # Sync log functions
    "get_sync_log", "log_sync",
    # Webami order functions
    "get_known_order_guids", "get_webami_order", "list_webami_orders", "save_order", "get_webami_stats", 
    "get_incomplete_order_guids",
    # Webami product functions
    "get_unresolved_items", "save_webami_product", "get_webami_product_by_id", "suggest_local", "suggest_title", 
    "ignore_product", "list_unmatched", "good_match", "reset_webami_products", "drop_from_match_cache"
]