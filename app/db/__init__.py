from app.db.app_config import get_config, is_dry_run, upsert_config
from app.db.artists import (
    add_alias, alias_for, alias_map, canon, list_aliases, mismatches, 
    remove_alias, set_ignored, vendor_changes
)
from app.db.connection import get_conn, transaction
from app.db.missing import list_missing
from app.db.prices import (
    get_price_variants, save_price_check, resolve_price_check, list_price_changes,
    price_queue_add, price_queue_remove, price_queue_filtered, price_queue_set, list_price_queue,
)
from app.db.schema import init_db as _apply_schema
from app.db.shopify_products import (
    count_products, get_filter_options, get_product_detail, list_products,
    save_shopify_product, update_local, delete_products_not_synced_since, 
    add_local_variants, add_local_product, delete_local_product, delete_local_variant
)
from app.db.sync_log import get_sync_log, log_sync
from app.db.webami_orders import (
    get_known_order_guids, get_webami_order, list_webami_orders, save_order, get_webami_stats, 
    get_incomplete_order_guids, get_variant_by_upc, log_receipt, get_variant, get_receipt, 
    reverse_receipt, list_order_receipts, rq_set, rq_list, outstanding_items, list_product_receipts,
    rq_target
)
from app.db.webami_products import (
    get_unresolved_items, save_webami_product, get_webami_product_by_id, ignore_product,
    list_unmatched_variants, good_match, reset_webami_products,
    drop_from_match_cache, suggest_local, decorate_candidates, shopify_candidates, search_shopify
)
from app.webami.webami_classify import kw_eval, suggest_parts, variant_kws


def init_db() -> None:
    _apply_schema(get_conn())


__all__: list[str] = [
    "init_db",
    
    # App config functions
    "get_config", "is_dry_run", "upsert_config",
    
    # Artists functions
    "add_alias", "alias_for", "alias_map", "canon", "list_aliases", "mismatches", 
    "remove_alias", "set_ignored", "vendor_changes",
    
    # Connection functions
    "get_conn", "transaction",

    # Missing data functions
    "list_missing",
    
    # Price functions
    "get_price_variants", "save_price_check", "resolve_price_check", "list_price_changes",
    "price_queue_add", "price_queue_remove", "price_queue_filtered", "price_queue_set", "list_price_queue",
    
    # Shopify product functions
    "count_products", "get_filter_options", "get_product_detail", "list_products", "save_shopify_product", 
    "update_local", "delete_products_not_synced_since", "add_local_variants", "add_local_product", 
    "delete_local_product", "delete_local_variant",
    
    # Sync log functions
    "get_sync_log", "log_sync",
    
    # Webami order functions
    "get_known_order_guids", "get_webami_order", "list_webami_orders", "save_order", "get_webami_stats", 
    "get_incomplete_order_guids", "get_variant_by_upc", "log_receipt", "get_variant", "get_receipt", 
    "reverse_receipt", "list_order_receipts", "rq_set", "rq_list", "outstanding_items", "list_product_receipts",
    "rq_target",
    
    # Webami product functions
    "get_unresolved_items", "save_webami_product", "get_webami_product_by_id", "ignore_product",
    "list_unmatched_variants", "good_match", "reset_webami_products",
    "drop_from_match_cache", "suggest_local", "decorate_candidates", "shopify_candidates", "search_shopify",
    
    # Webami classify functions
    "kw_eval", "suggest_parts", "variant_kws",
]