"""
All SQLite access lives here. No ORM - plain sqlite3 with Row factory.
Background jobs use the db_conn() context manager.
Flask routes use get_conn() which stores a per-request connection in Flask's g.
"""

from contextlib import contextmanager
import os
import re
import sqlite3
import threading
from typing import Optional

import app.config as config


_IMG_KEY_RE = re.compile(r'(\d+[-_]\d+\.(?:jpg|jpeg|png|webp|gif))', re.IGNORECASE)



# ─────────────────────────────────────────────
# DB init + seeding
# ─────────────────────────────────────────────



# ─────────────────────────────────────────────
# App config
# ─────────────────────────────────────────────

def get_config() -> Optional[dict]:
    return _row(get_conn().execute("SELECT * FROM app_config WHERE id=1").fetchone())


def upsert_config(**kwargs) -> None:
    kwargs["updated_at"] = "datetime('now')"
    conn = get_conn()
    existing = conn.execute("SELECT id FROM app_config WHERE id=1").fetchone()
    if existing:
        sets = ", ".join(f"{k}=?" for k in kwargs if k != "updated_at")
        sets += ", updated_at=datetime('now')"
        vals = [v for k, v in kwargs.items() if k != "updated_at"]
        conn.execute(f"UPDATE app_config SET {sets} WHERE id=1", vals)
    else:
        cols = ", ".join(k for k in kwargs if k != "updated_at")
        cols += ", updated_at"
        placeholders = ", ".join("?" for k in kwargs if k != "updated_at") + ", datetime('now')"
        vals = [v for k, v in kwargs.items() if k != "updated_at"]
        conn.execute(f"INSERT INTO app_config (id,{cols}) VALUES (1,{placeholders})", vals)
    conn.commit()


# ─────────────────────────────────────────────
# Shopify products
# ─────────────────────────────────────────────

def upsert_shopify_product(p: dict) -> None:
    conn = get_conn()
    pid = _sid(p.get("id") or p.get("product_id") or "")
    cat = p.get("category") or {}

    existing = conn.execute(
        "SELECT * FROM shopify_products WHERE product_id=?", (pid,)).fetchone()

    def _val(key, transform=None, default=None):
        if key in p:
            v = p[key]
            return transform(v) if transform and v is not None else v
        if existing is not None:
            return existing[key] if key in existing.keys() else default
        return default

    title    = _val("title")
    vendor   = _val("vendor")
    status   = _val("status")
    ptype    = p.get("productType") if "productType" in p else _val("product_type")
    tags_raw = p.get("tags") if "tags" in p else None
    if tags_raw is not None:
        tags = ",".join(tags_raw) if isinstance(tags_raw, list) else tags_raw
    else:
        tags = existing["tags"] if existing is not None else None
    handle = _val("handle")
    cat_id = _sid(cat.get("id") or "") if isinstance(cat, dict) and cat else (_val("category_id"))
    cat_name = cat.get("name") if isinstance(cat, dict) and cat else _val("category_name")
    upc    = _val("upc")
    genres = _val("genres")

    conn.execute(
        """INSERT INTO shopify_products
           (product_id,title,vendor,status,product_type,tags,handle,
            category_id,category_name,upc,genres,last_synced)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(product_id) DO UPDATE SET
             title=excluded.title, vendor=excluded.vendor, status=excluded.status,
             product_type=excluded.product_type, tags=excluded.tags, handle=excluded.handle,
             category_id=excluded.category_id, category_name=excluded.category_name,
             upc=excluded.upc, genres=excluded.genres,
             last_synced=datetime('now')""",
        (pid, title, vendor, status, ptype, tags, handle, cat_id, cat_name, upc, genres),
    )
    conn.commit()


def upsert_shopify_variant(product_id: str, v: dict) -> None:
    conn = get_conn()
    inv      = v.get("inventoryItem") or {}
    cost_obj = inv.get("unitCost") or {}
    meas     = inv.get("measurement") or {}
    wt       = meas.get("weight") or {}
    weight      = wt.get("value")   or v.get("weight")
    weight_unit = wt.get("unit")    or v.get("weightUnit") or v.get("weight_unit")
    conn.execute(
        """INSERT INTO shopify_variants
           (variant_id,product_id,price,cost,inventory_item_id,
            inventory_quantity,weight,weight_unit)
           VALUES (?,?,?,?,?,?,?,?)
           ON CONFLICT(variant_id) DO UPDATE SET
             price=excluded.price, cost=excluded.cost,
             inventory_item_id=excluded.inventory_item_id,
             inventory_quantity=excluded.inventory_quantity,
             weight=excluded.weight, weight_unit=excluded.weight_unit""",
        (
            _sid(v.get("id") or v.get("variant_id") or ""),
            product_id,
            v.get("price"),
            cost_obj.get("amount") if cost_obj else v.get("cost"),
            _sid(inv.get("id") or v.get("inventory_item_id") or ""),
            v.get("inventoryQuantity") or v.get("inventory_quantity") or 0,
            weight,
            weight_unit,
        ),
    )
    conn.commit()


def _img_key(url: str) -> str:
    m = _IMG_KEY_RE.search(url or '')
    return m.group(1).lower() if m else ''


def upsert_shopify_image(product_id: str, media_id: str, url: str, position: int) -> None:
    conn = get_conn()
    key = _img_key(url)
    if key:
        exists = conn.execute(
            "SELECT 1 FROM shopify_images WHERE product_id=? AND LOWER(url) LIKE ?",
            (product_id, f'%{key}')).fetchone()
        if exists:
            return
    conn.execute(
        """INSERT INTO shopify_images (product_id,media_id,url,position)
           VALUES (?,?,?,?)
           ON CONFLICT(product_id, media_id) DO NOTHING""",
        (product_id, media_id, url, position),
    )
    conn.commit()


def clear_shopify_images(product_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM shopify_images WHERE product_id=?", (product_id,))
    conn.commit()


def get_shopify_product_detail(product_id: str) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM shopify_products WHERE product_id=?", (product_id,)).fetchone()
    if not row:
        return None
    product = dict(row)
    product["product_id"] = product["product_id"]   # backward-compat alias
    product["variants"] = _rows(conn.execute(
        "SELECT * FROM shopify_variants WHERE product_id=? ORDER BY rowid",
        (product_id,)).fetchall())
    product["images"] = _rows(conn.execute(
        "SELECT * FROM shopify_images WHERE product_id=? ORDER BY position",
        (product_id,)).fetchall())
    product["mapping"] = _row(conn.execute(
        """SELECT pm.*, wp.title as wt, wp.artist, wp.format, wp.weight_grams, wp.cost as wcost, wp.image_urls
           FROM product_mappings pm
           LEFT JOIN webami_products wp ON wp.upc=pm.webami_upc
           WHERE pm.product_id=?""", (product_id,)).fetchone())
    return product


def count_shopify_products() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM shopify_products").fetchone()[0]


# ─────────────────────────────────────────────
# Sync log
# ─────────────────────────────────────────────

def log_sync(action: str, status: str, details: str = None) -> None:
    conn = get_conn()
    conn.execute("INSERT INTO sync_log (action,status,details) VALUES (?,?,?)",
                 (action, status, details))
    conn.commit()


def get_sync_log(limit: int = 50) -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall())