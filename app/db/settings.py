from typing import Optional

from app.db.connection import _row, get_conn


CONFIG_COLUMNS = {
    "id", "shopify_store", "shopify_api_version", "shopify_location_id",
    "shopify_upc_ns", "shopify_upc_key", "shopify_genres_ns", "shopify_genres_key",
    "shopify_type_ns", "shopify_type_key", "shopify_description_ns",
    "shopify_description_key", "shopify_releast_date_ns", "shopify_releast_date_key",
    "shopify_variant_tags_ns", "shopify_variant_tags_key", "last_shopify_sync",
    "dry_run", "created_at", "updated_at", "page_size"
}


def get_config() -> Optional[dict]:
    return _row(get_conn().execute("SELECT * FROM app_config WHERE id=1").fetchone())


def upsert_config(**kwargs) -> None:
    unknown = kwargs.keys() - CONFIG_COLUMNS
    if unknown:
        raise ValueError(f"Unknown config columns: {', '.join(sorted(unknown))}")

    if not kwargs:
        return

    conn = get_conn()
    sets = ", ".join(f"{column} = ?" for column in kwargs)
    values = list(kwargs.values())

    conn.execute(
        f"UPDATE app_config SET {sets} WHERE id = 1",
        values,
    )
    conn.commit()


def is_dry_run() -> bool:
    cfg = get_config() or {}
    return bool(cfg.get("dry_run"))