from typing import Optional

from app.db.connection import get_conn, row, transaction

CONFIG_COLUMNS: set[str] = {
    "shopify_api_version", "shopify_location_id",
    "shopify_upc_ns", "shopify_upc_key",
    "shopify_genres_ns", "shopify_genres_key",
    "shopify_type_ns", "shopify_type_key",
    "shopify_description_ns", "shopify_description_key",
    "shopify_release_date_ns", "shopify_release_date_key",
    "shopify_variant_tags_ns", "shopify_variant_tags_key",
    "last_shopify_sync", "dry_run", "page_size",
}


def get_config() -> Optional[dict]:
    return row(get_conn().execute("SELECT * FROM app_config WHERE id=1").fetchone())


def upsert_config(**kwargs) -> None:
    unknown: set[str] = kwargs.keys() - CONFIG_COLUMNS
    if unknown:
        raise ValueError(f"Unknown config columns: {', '.join(sorted(unknown))}")
    if not kwargs:
        return
    sets: str = ", ".join(f"{k} = ?" for k in kwargs)
    with transaction() as conn:
        conn.execute(
            f"UPDATE app_config SET {sets}, updated_at = datetime('now') WHERE id = 1",
            list(kwargs.values()),
        )


def is_dry_run() -> bool:
    return bool((get_config() or {}).get("dry_run"))