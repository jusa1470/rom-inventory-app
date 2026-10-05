-- ─────────────────────────────────────────────
-- App config (single row, id always = 1)
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS app_config (
  id                       INTEGER PRIMARY KEY DEFAULT 1,
  password_hash            TEXT,
  shopify_store            TEXT,
  shopify_token_enc        TEXT,
  shopify_api_version      TEXT    DEFAULT '2025-01',
  shopify_location_id      TEXT,
  shopify_upc_ns           TEXT    DEFAULT 'custom',
  shopify_upc_key          TEXT    DEFAULT 'upc',
  shopify_genres_ns        TEXT    DEFAULT 'custom',
  shopify_genres_key       TEXT    DEFAULT 'genres',
  webami_base_url          TEXT    DEFAULT 'https://aent-m.com',
  webami_username_enc      TEXT,
  webami_password_enc      TEXT,
  target_margin            REAL    DEFAULT 0.34,
  last_shopify_sync        TEXT,
  dry_run                  INTEGER DEFAULT 0,
  last_matcher_run         TEXT,
  created_at               TEXT    DEFAULT (datetime('now')),
  updated_at               TEXT    DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- Shopify cache
-- ─────────────────────────────────────────────
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
  upc           TEXT,
  genres        TEXT,
  last_synced   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS shopify_variants (
  variant_id          TEXT PRIMARY KEY,
  product_id          TEXT NOT NULL REFERENCES shopify_products(product_id) ON DELETE CASCADE,
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

-- ─────────────────────────────────────────────
-- Webami cache
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webami_products (
  upc            TEXT PRIMARY KEY,
  title          TEXT,
  artist         TEXT,
  brand          TEXT,
  format         TEXT,
  genres         TEXT,
  features       TEXT,
  image_urls     TEXT,
  weight_grams   REAL,
  cost           REAL,
  last_synced    TEXT DEFAULT (datetime('now')),
  last_cost_sync TEXT
);

CREATE TABLE IF NOT EXISTS upc_aliases (
  retired_upc TEXT PRIMARY KEY,
  active_upc  TEXT NOT NULL,
  notes       TEXT,
  created_at  TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- Product mappings
-- confidence: exact_upc | alias_upc | fuzzy_auto | fuzzy | manual
-- status:     active | pending | rejected
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS product_mappings (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id  TEXT NOT NULL UNIQUE,
  webami_upc  TEXT NOT NULL,
  confidence  TEXT NOT NULL,
  score       REAL DEFAULT 0,
  status      TEXT DEFAULT 'active',
  notes       TEXT,
  created_at  TEXT DEFAULT (datetime('now')),
  updated_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS variance_ignores (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id TEXT NOT NULL,
  field      TEXT NOT NULL,
  old_value  TEXT,
  new_value  TEXT,
  created_at TEXT DEFAULT (datetime('now')),
  UNIQUE(product_id, field, old_value, new_value)
);

CREATE TABLE IF NOT EXISTS title_overrides (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  product_id   TEXT UNIQUE NOT NULL,
  correct_title TEXT NOT NULL,
  created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS unmatched_ignores (
  product_id TEXT PRIMARY KEY,
  notes      TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- Shopify duplicate detection
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS duplicate_groups (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  normalized_key TEXT NOT NULL,
  status         TEXT DEFAULT 'pending',
  created_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS duplicate_group_members (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  group_id   INTEGER NOT NULL REFERENCES duplicate_groups(id) ON DELETE CASCADE,
  product_id TEXT NOT NULL REFERENCES shopify_products(product_id),
  is_primary INTEGER DEFAULT 0,
  UNIQUE(group_id, product_id)
);

-- ─────────────────────────────────────────────
-- Feature parsing rules
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS feature_rules (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  match_text   TEXT NOT NULL,
  match_type   TEXT NOT NULL DEFAULT 'iexact',
  action_type  TEXT NOT NULL,
  action_value TEXT,
  priority     INTEGER DEFAULT 0,
  enabled      INTEGER DEFAULT 1,
  notes        TEXT,
  created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS unknown_features (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  feature_text TEXT UNIQUE NOT NULL,
  seen_count   INTEGER DEFAULT 1,
  last_seen    TEXT DEFAULT (datetime('now')),
  resolved     INTEGER DEFAULT 0
);

-- ─────────────────────────────────────────────
-- Artist aliases
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS artist_aliases (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  alias_name     TEXT UNIQUE NOT NULL COLLATE NOCASE,
  canonical_name TEXT NOT NULL,
  created_at     TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- Orders
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webami_orders (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  guid             TEXT UNIQUE,
  order_number     TEXT,
  order_name       TEXT,
  order_date       TEXT,
  status           TEXT DEFAULT 'pending',
  total_products   INTEGER DEFAULT 0,
  notes            TEXT,
  created_at       TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS webami_order_items (
  id                    INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id              INTEGER NOT NULL REFERENCES webami_orders(id) ON DELETE CASCADE,
  webami_upc            TEXT,
  title                 TEXT,
  vendor                TEXT,
  format                TEXT,
  unit_cost             REAL,
  total_cost            REAL,
  quantity_ordered      INTEGER DEFAULT 0,
  quantity_in_stock     INTEGER DEFAULT 0,
  quantity_backordered  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS received_items (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  order_item_id     INTEGER NOT NULL REFERENCES webami_order_items(id),
  quantity_received INTEGER NOT NULL DEFAULT 0,
  unit_cost         REAL,
  shopify_updated   INTEGER DEFAULT 0,
  received_at       TEXT DEFAULT (datetime('now')),
  notes             TEXT
);

-- ─────────────────────────────────────────────
-- Sync log
-- ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_log (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  action     TEXT NOT NULL,
  status     TEXT NOT NULL,
  details    TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);

-- ─────────────────────────────────────────────
-- Indexes
-- ─────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_products_upc      ON shopify_products(upc);
CREATE INDEX IF NOT EXISTS idx_variants_product  ON shopify_variants(product_id);
CREATE INDEX IF NOT EXISTS idx_images_product    ON shopify_images(product_id);
CREATE INDEX IF NOT EXISTS idx_mappings_product  ON product_mappings(product_id);
CREATE INDEX IF NOT EXISTS idx_mappings_upc      ON product_mappings(webami_upc);
CREATE INDEX IF NOT EXISTS idx_mappings_status   ON product_mappings(status);
CREATE INDEX IF NOT EXISTS idx_order_items_order ON webami_order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_upc   ON webami_order_items(webami_upc);
CREATE INDEX IF NOT EXISTS idx_received_item     ON received_items(order_item_id);
CREATE INDEX IF NOT EXISTS idx_dup_members       ON duplicate_group_members(product_id);
CREATE INDEX IF NOT EXISTS idx_aliases_active    ON upc_aliases(active_upc);