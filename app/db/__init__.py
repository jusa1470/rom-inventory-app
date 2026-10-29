from app.db.connection import get_conn, transaction
from app.db.shopify_products import (
    count_products,
    get_filter_options,
    get_product_detail,
    list_products,
    save_product,
    update_local,
)
from app.db.schema import init_db as _apply_schema
from app.db.app_config import get_config, is_dry_run, upsert_config
from app.db.sync_log import get_sync_log, log_sync


def init_db() -> None:
    _apply_schema(get_conn())


__all__: list[str] = [
    "count_products", "get_conn", "get_config", "get_filter_options", "get_product_detail",
    "get_sync_log", "init_db", "is_dry_run", "list_products", "log_sync",
    "save_product", "transaction", "upsert_config", "update_local",
]