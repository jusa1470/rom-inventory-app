import sqlite3
from contextlib import contextmanager

from app import config

SCHEMA = """
-- ── Shopify cache (read-only mirror) ───────────────────────────────
CREATE TABLE IF NOT EXISTS shopify_products (
  product_id    TEXT PRIMARY KEY,
  handle        TEXT,
  title         TEXT,
  vendor        TEXT,
  status        TEXT,
  product_type  TEXT,
  category_id   TEXT,
  category_name TEXT,
  tags          TEXT,            -- JSON list
  upc_metafield TEXT,            -- facts.upc
  image_urls    TEXT,            -- JSON list
  option_names  TEXT,            -- JSON list, e.g. ["Edition","Color","Attributes"]
  created_at    TEXT,
  updated_at    TEXT,
  last_synced   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sp_handle ON shopify_products(handle);
CREATE INDEX IF NOT EXISTS idx_sp_upc    ON shopify_products(upc_metafield);

CREATE TABLE IF NOT EXISTS shopify_variants (
  variant_id         TEXT PRIMARY KEY,
  product_id         TEXT NOT NULL REFERENCES shopify_products(product_id) ON DELETE CASCADE,
  title              TEXT,
  sku                TEXT,
  barcode            TEXT,
  price              REAL,
  cost               REAL,
  taxable            INTEGER,
  position           INTEGER,
  options            TEXT,       -- JSON [{"name":..,"value":..}]
  inventory_item_id  TEXT,
  inventory_quantity INTEGER,    -- snapshot; re-pulled before apply
  weight             REAL,
  weight_unit        TEXT
);
CREATE INDEX IF NOT EXISTS idx_sv_product ON shopify_variants(product_id);
CREATE INDEX IF NOT EXISTS idx_sv_barcode ON shopify_variants(barcode);

-- ── Catalog plan: existing products -> new product/variants ────────
-- A plan_product is one proposed Shopify product (artist-title-format).
-- A plan_variant maps ONE existing variant to its new variant slot.
-- source_* ids are deliberately NOT foreign keys so the mapping survives
-- the source being archived/deleted after apply.
CREATE TABLE IF NOT EXISTS plan_products (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  handle         TEXT UNIQUE NOT NULL,      -- artist-title-format
  title          TEXT NOT NULL,
  vendor         TEXT,
  product_type   TEXT,
  category_id    TEXT,
  status         TEXT DEFAULT 'draft',      -- draft | approved | applied | skipped
  new_product_id TEXT,                      -- set once created in Shopify
  notes          TEXT,
  created_at     TEXT DEFAULT (datetime('now')),
  updated_at     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS plan_variants (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  plan_product_id   INTEGER NOT NULL REFERENCES plan_products(id) ON DELETE CASCADE,
  source_product_id TEXT NOT NULL,
  source_variant_id TEXT NOT NULL UNIQUE,   -- each existing variant maps once
  edition           TEXT NOT NULL DEFAULT 'Standard',
  color             TEXT,
  attributes        TEXT,
  confidence        REAL,                   -- parser confidence, 0..1
  status            TEXT DEFAULT 'needs_review',  -- ready | needs_review | approved | applied
  new_variant_id    TEXT,                   -- set once created in Shopify
  notes             TEXT,
  updated_at        TEXT DEFAULT (datetime('now')),
  unknown_terms     TEXT,                   -- JSON list of terms with no rule yet
  reason            TEXT,                   -- why it needs review
  manual            INTEGER DEFAULT 0       -- user edited; rebuilds leave it alone
);

-- Classification rules the user has taught the app. Auto-classification only
-- happens when every word of a title is explained by a rule.
-- kind: edition | color | attribute | ignore | title | format | default
CREATE TABLE IF NOT EXISTS term_rules (
  term       TEXT PRIMARY KEY,   -- normalized phrase, or a ~pseudo term
  kind       TEXT NOT NULL,
  value      TEXT,
  created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pv_plan   ON plan_variants(plan_product_id);
CREATE INDEX IF NOT EXISTS idx_pv_source ON plan_variants(source_product_id);

-- ── Misc ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sync_state (
  key   TEXT PRIMARY KEY,
  value TEXT
);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        # migrate plan_variants created by an earlier version of the schema
        for table, additions in (
            ("plan_variants", (("unknown_terms", "TEXT"), ("reason", "TEXT"), ("manual", "INTEGER DEFAULT 0"),
                               ("new_inventory_item_id", "TEXT"), ("qty_copied", "INTEGER"),
                               ("archived_at", "TEXT"))),
            ("plan_products", (("created_at_shopify", "TEXT"), ("new_status", "TEXT"), ("error", "TEXT"),
                               ("category_name", "TEXT"), ("format", "TEXT"))),
        ):
            cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, ddl in additions:
                if col not in cols:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def get_state(key: str) -> str | None:
    with connect() as conn:
        row = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None


def set_state(key: str, value: str) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO sync_state(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
