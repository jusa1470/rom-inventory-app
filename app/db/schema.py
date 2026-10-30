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
        upc           TEXT,
        last_synced   TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS shopify_variants (
        variant_id          TEXT PRIMARY KEY,
        product_id          TEXT NOT NULL REFERENCES shopify_products(product_id) ON DELETE CASCADE,
        title               TEXT,
        upc                 TEXT,
        description         TEXT,
        release_date        TEXT,
        variant_tags        TEXT,
        price               TEXT,
        cost                TEXT,
        media_id            TEXT,
        taxable             INTEGER DEFAULT 1,
        inventory_item_id   TEXT,
        inventory_quantity  INTEGER DEFAULT 0,
        weight              REAL,
        weight_unit         TEXT
    );

    CREATE TABLE shopify_images (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id  TEXT NOT NULL REFERENCES shopify_products(product_id) ON DELETE CASCADE,
        media_id    TEXT NOT NULL,
        url         TEXT,
        position    INTEGER DEFAULT 0,
        UNIQUE(product_id, media_id)
    );

    CREATE TABLE IF NOT EXISTS sync_log (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        action     TEXT NOT NULL,
        status     TEXT NOT NULL,
        details    TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    
    CREATE TABLE webami_orders (
        guid         TEXT PRIMARY KEY,
        number       TEXT NOT NULL,
        name         TEXT,
        submitted_at TEXT,
        sku_count    INTEGER DEFAULT 0,
        last_synced  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE webami_order_items (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        order_guid TEXT NOT NULL REFERENCES webami_orders(guid) ON DELETE CASCADE,
        position   INTEGER NOT NULL,
        upc        TEXT,
        title      TEXT,
        artist     TEXT,
        quantity   INTEGER DEFAULT 0,
        price      REAL,
        UNIQUE(order_guid, position)
    );
    CREATE TABLE webami_products (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        fingerprint  TEXT,
        title        TEXT,
        artist       TEXT,
        vendor       TEXT,
        product_type TEXT,
        sku          TEXT,
        upc          TEXT,
        price        REAL,
        your_price   REAL,
        wmsid        TEXT,
        created_at   TEXT DEFAULT (datetime('now')),
        last_synced  TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE webami_product_ids (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL REFERENCES webami_products(id) ON DELETE CASCADE,
        kind       TEXT NOT NULL,
        value      TEXT NOT NULL,
        first_seen TEXT DEFAULT (datetime('now')),
        last_seen  TEXT DEFAULT (datetime('now')),
        UNIQUE(kind, value)
    );

    CREATE INDEX IF NOT EXISTS idx_products_title       ON shopify_products(title);
    CREATE INDEX IF NOT EXISTS idx_products_upc         ON shopify_products(upc);
    CREATE INDEX IF NOT EXISTS idx_variants_product     ON shopify_variants(product_id);
    CREATE INDEX IF NOT EXISTS idx_variants_upc         ON shopify_variants(upc);
    CREATE INDEX IF NOT EXISTS idx_images_product       ON shopify_images(product_id);
    CREATE INDEX IF NOT EXISTS idx_webami_items_order   ON webami_order_items(order_guid);
    CREATE INDEX IF NOT EXISTS idx_webami_items_upc     ON webami_order_items(upc);
    CREATE INDEX IF NOT EXISTS idx_webami_products_fp   ON webami_products(fingerprint);
    CREATE INDEX IF NOT EXISTS idx_webami_ids_product   ON webami_product_ids(product_id);
    CREATE INDEX IF NOT EXISTS idx_webami_items_prod    ON webami_order_items(product_id);
    CREATE VIEW shopify_upcs AS
        SELECT upc, product_id, NULL AS variant_id, 'product' AS source
          FROM shopify_products WHERE upc IS NOT NULL AND upc != ''
        UNION ALL
        SELECT upc, product_id, variant_id, 'variant'
          FROM shopify_variants WHERE upc IS NOT NULL AND upc != '';
    """,
]

# when shopify UPCs move to variants add this:
    # DROP VIEW shopify_upcs;
    # CREATE VIEW shopify_upcs AS
    #     SELECT upc, product_id, variant_id, 'variant' AS source
    #       FROM shopify_variants WHERE upc IS NOT NULL AND upc != '';


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