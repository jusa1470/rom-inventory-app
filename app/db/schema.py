import sqlite3

MIGRATIONS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS app_config (
        id                       INTEGER PRIMARY KEY CHECK (id = 1),
        shopify_api_version      TEXT    DEFAULT '2025-01',
        shopify_location_id      TEXT,
        shopify_upc_ns           TEXT    DEFAULT 'custom',
        shopify_upc_key          TEXT    DEFAULT 'upc',
        shopify_genres_ns        TEXT    DEFAULT 'custom',
        shopify_genres_key       TEXT    DEFAULT 'genres',
        shopify_type_ns          TEXT    DEFAULT 'custom',
        shopify_type_key         TEXT    DEFAULT 'type',
        shopify_description_ns   TEXT    DEFAULT 'custom',
        shopify_description_key  TEXT    DEFAULT 'description',
        shopify_release_date_ns  TEXT    DEFAULT 'custom',
        shopify_release_date_key TEXT    DEFAULT 'release_date',
        shopify_variant_tags_ns  TEXT    DEFAULT 'custom',
        shopify_variant_tags_key TEXT    DEFAULT 'variant_tags',
        last_shopify_sync        TEXT,
        dry_run                  INTEGER DEFAULT 0,
        page_size                INTEGER DEFAULT 50,
        created_at               TEXT    DEFAULT (datetime('now')),
        updated_at               TEXT    DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS shopify_products (
        product_id    TEXT PRIMARY KEY,
        title         TEXT,
        vendor        TEXT,
        status        TEXT,
        product_type  TEXT,
        tags          TEXT,
        handle        TEXT,
        category_id   TEXT,
        category_name TEXT,
        genres        TEXT,
        type          TEXT,
        last_synced   TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS shopify_variants (
        variant_id          TEXT PRIMARY KEY,
        product_id          TEXT NOT NULL REFERENCES shopify_products(product_id) ON DELETE CASCADE,
        title               TEXT,
        barcode             TEXT,
        sku                 TEXT,
        upc                 TEXT,
        description         TEXT,
        release_date        TEXT,
        variant_tags        TEXT,
        price               TEXT,
        cost                TEXT,
        taxable             INTEGER DEFAULT 1,
        inventory_item_id   TEXT,
        inventory_quantity  INTEGER DEFAULT 0,
        weight              REAL,
        weight_unit         TEXT
    );

    CREATE TABLE IF NOT EXISTS shopify_images (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        variant_id  TEXT NOT NULL REFERENCES shopify_variants(variant_id) ON DELETE CASCADE,
        media_id    TEXT,
        url         TEXT,
        position    INTEGER DEFAULT 0,
        UNIQUE(variant_id, media_id)
    );

    CREATE TABLE IF NOT EXISTS sync_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        action     TEXT NOT NULL,
        status     TEXT NOT NULL,
        details    TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE INDEX IF NOT EXISTS idx_products_title    ON shopify_products(title);
    CREATE INDEX IF NOT EXISTS idx_variants_product  ON shopify_variants(product_id);
    CREATE INDEX IF NOT EXISTS idx_variants_upc      ON shopify_variants(upc);
    CREATE INDEX IF NOT EXISTS idx_variants_barcode  ON shopify_variants(barcode);
    CREATE INDEX IF NOT EXISTS idx_variants_sku      ON shopify_variants(sku);
    CREATE INDEX IF NOT EXISTS idx_images_variant    ON shopify_images(variant_id);
    """,
]


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for n, sql in enumerate(MIGRATIONS, start=1):
        if n <= version:
            continue
        try:
            conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={n};\nCOMMIT;")
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
    conn.execute("INSERT INTO app_config (id) VALUES (1) ON CONFLICT(id) DO NOTHING")
    conn.commit()