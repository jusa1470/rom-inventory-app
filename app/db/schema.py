import sqlite3


SCHEMA_VERSION = 1

MIGRATIONS = [
  """
  CREATE TABLE IF NOT EXISTS app_config (
    id                       INTEGER PRIMARY KEY CHECK (id = 1),
    shopify_store            TEXT,
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
    shopify_releast_date_ns  TEXT    DEFAULT 'custom',
    shopify_releast_date_key TEXT    DEFAULT 'release_date',
    shopify_variant_tags_ns  TEXT    DEFAULT 'custom',
    shopify_variant_tags_key TEXT    DEFAULT 'variant_tags',
    last_shopify_sync        TEXT,
    dry_run                  INTEGER DEFAULT 0,
    created_at               TEXT    DEFAULT (datetime('now')),
    updated_at               TEXT    DEFAULT (datetime('now')),
    page_size                INTEGER DEFAULT 50
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
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id TEXT NOT NULL REFERENCES shopify_products(product_id) ON DELETE CASCADE,
    media_id   TEXT,
    url        TEXT,
    position   INTEGER DEFAULT 0,
    UNIQUE(product_id, media_id)
  );

  CREATE TABLE IF NOT EXISTS sync_log (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    action     TEXT NOT NULL,
    status     TEXT NOT NULL,
    details    TEXT,
    created_at TEXT DEFAULT (datetime('now'))
  );

  CREATE INDEX IF NOT EXISTS 
    idx_shopify_products_title ON shopify_products(title),
    idx_shopify_products_upc ON shopify_products(upc),
    idx_shopify_variants_product_id ON shopify_variants(product_id),
    idx_shopify_images_product_id ON shopify_images(product_id)
  """,
]

def init_db(conn: sqlite3.Connection) -> None:
  """Initialize the database schema and apply migrations."""
  conn.execute("PRAGMA journal_mode=WAL")
  user_version = conn.execute("PRAGMA user_version").fetchone()[0]
  for i, migration in enumerate(MIGRATIONS):
    if i + 1 > user_version:
      conn.execute("BEGIN")
      try:
        conn.executescript(migration)
        conn.execute(f"PRAGMA user_version={i + 1}")
        conn.commit()
      except Exception:
        conn.rollback()
        raise
  conn.execute(
    """
    INSERT OR IGNORE INTO app_config (id)
    VALUES (1)
    ON CONFLICT(id) DO NOTHING
    """
  )
  conn.commit()