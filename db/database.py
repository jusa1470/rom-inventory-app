"""
All SQLite access lives here. No ORM - plain sqlite3 with Row factory.
Background jobs use the db_conn() context manager.
Flask routes use get_conn() which stores a per-request connection in Flask's g.
"""

import json
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Optional

import config
from services.feature_parser import _OMPS_RE, _OST_RE, suggest_title, _SPECIAL_ED_RE, _COLOR_RE


_local = threading.local()
_IMG_KEY_RE = re.compile(r'(\d+[-_]\d+\.(?:jpg|jpeg|png|webp|gif))', re.IGNORECASE)


# ─────────────────────────────────────────────
# Connection helpers
# ─────────────────────────────────────────────

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    if not getattr(_local, "conn", None):
        _local.conn = _make_conn()
    return _local.conn


@contextmanager
def db_conn():
    conn = _make_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _j(v) -> Optional[str]:
    return json.dumps(v) if v is not None else None


def _uj(v):
    return json.loads(v) if v else None


def _sid(gid: str) -> str:
    if not gid:
        return gid
    s = str(gid)
    return s.split("/")[-1] if "/" in s else s


def _row(r) -> Optional[dict]:
    return dict(r) if r else None


def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


# ─────────────────────────────────────────────
# DB init + seeding
# ─────────────────────────────────────────────

def init_db():
    schema_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(schema_path) as f:
        schema = f.read()
    with db_conn() as conn:
        conn.executescript(schema)
    _run_migrations()
    _seed_feature_rules()
    _update_global_config()


def _run_migrations():
    with db_conn() as conn:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        def _cols(table):
            return [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]


def _update_global_config():
    cfg = get_config()
    if cfg and cfg.get("webami_base_url"):
        config.WEBAMI_BASE_URL = cfg["webami_base_url"]
    if cfg and cfg.get("target_margin"):
        config.TARGET_MARGIN = cfg["target_margin"]


def _seed_feature_rules():
    conn = _make_conn()
    try:
        if conn.execute("SELECT COUNT(*) FROM feature_rules").fetchone()[0] > 0:
            return
        defaults = [
            ("Gatefold LP Jacket", "iexact",    "drop",         None,                       10, "Packaging - ignore"),
            ("Gatefold",           "iexact",    "drop",         None,                        9, "Packaging - ignore"),
            ("Sticker on Cover",   "icontains", "drop",         None,                        8, "Sticker note - ignore"),
            ("Indie Exclusive",    "iexact",    "title_suffix", " (IEX)",                   10, None),
            ("Indie Exclusive",    "iexact",    "add_tag",      "Indie Exclusive",           10, None),
            ("Colored Vinyl",      "iexact",    "add_tag",      "Colored Vinyl",              7, None),
            ("Anniversary Edition","icontains", "title_suffix", " (Anniversary Edition)",     8, None),
            ("Deluxe Edition",     "icontains", "title_suffix", " (Deluxe Edition)",          8, None),
            ("Expanded Edition",   "icontains", "title_suffix", " (Expanded Edition)",        8, None),
            ("Limited Edition",    "icontains", "title_suffix", " (Limited Edition)",         8, None),
            ("Reissue",            "iexact",    "title_suffix", " (Reissue)",                 7, None),
            ("Reissue",            "iexact",    "add_tag",      "Reissue",                    7, None),
            ("2LP",                "iexact",    "add_tag",      "2LP",                        5, None),
            ("3LP",                "iexact",    "add_tag",      "3LP",                        5, None),
            ("4LP",                "iexact",    "add_tag",      "4LP",                        5, None),
            ("Picture Disc",       "icontains", "add_tag",      "Picture Disc",               6, None),
            (r"^(Red|Blue|Green|Yellow|White|Black|Purple|Orange|Pink|Gold|Silver|Clear|Translucent|Brown|Violet|Gray|Grey)\s+Vinyl$",
             "regex", "title_suffix", " - $1", 9, "Color Vinyl → title suffix"),
            ("Red",         "iexact", "title_suffix", " - Red",         3, "Vinyl color"),
            ("Blue",        "iexact", "title_suffix", " - Blue",        3, "Vinyl color"),
            ("Green",       "iexact", "title_suffix", " - Green",       3, "Vinyl color"),
            ("Yellow",      "iexact", "title_suffix", " - Yellow",      3, "Vinyl color"),
            ("White",       "iexact", "title_suffix", " - White",       3, "Vinyl color"),
            ("Black",       "iexact", "title_suffix", " - Black",       3, "Vinyl color"),
            ("Purple",      "iexact", "title_suffix", " - Purple",      3, "Vinyl color"),
            ("Orange",      "iexact", "title_suffix", " - Orange",      3, "Vinyl color"),
            ("Pink",        "iexact", "title_suffix", " - Pink",        3, "Vinyl color"),
            ("Gold",        "iexact", "title_suffix", " - Gold",        3, "Vinyl color"),
            ("Silver",      "iexact", "title_suffix", " - Silver",      3, "Vinyl color"),
            ("Clear",       "iexact", "title_suffix", " - Clear",       3, "Vinyl color"),
            ("Translucent", "iexact", "title_suffix", " - Translucent", 3, "Vinyl color"),
        ]
        conn.executemany(
            "INSERT INTO feature_rules (match_text,match_type,action_type,action_value,priority,notes) VALUES (?,?,?,?,?,?)",
            defaults,
        )
        conn.commit()
    finally:
        conn.close()


# ─────────────────────────────────────────────
# App config
# ─────────────────────────────────────────────

def has_setup() -> bool:
    r = get_conn().execute("SELECT password_hash FROM app_config WHERE id=1").fetchone()
    return bool(r and r["password_hash"])


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


def is_dry_run() -> bool:
    cfg = get_config() or {}
    return bool(cfg.get("dry_run"))


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


def get_field_variances(fields: list[str], page: int = 1, per_page: int = 20,
                         q_title: str = '', hide_u: bool = True) -> dict:
    conn = get_conn()

    # Mapped products (existing behavior)
    conds = ["pm.status='active'"]
    params = []
    if q_title:
        conds.append("sp.title LIKE ?")
        params.append(f"%{q_title}%")
    if hide_u:
        conds.append("(sp.title IS NULL OR sp.title NOT LIKE '%- U')")
    where = "WHERE " + " AND ".join(conds)

    rows = _rows(conn.execute(
        f"""SELECT sp.product_id, sp.title AS sp_title, sp.vendor AS sp_vendor, sp.tags AS sp_tags,
                   sv.price AS sp_price, sv.cost AS sp_cost, sv.weight AS sp_weight,
                   sv.weight_unit AS sp_weight_unit, sv.variant_id,
                   si.url AS sp_image,
                   wp.title AS wp_title, wp.artist AS wp_artist,
                   wp.cost AS wp_cost, wp.weight_grams AS wp_weight_grams,
                   wp.upc AS webami_upc, pm.webami_upc AS mapped_upc,
                   oi.title AS oi_title, oi.vendor AS oi_vendor, oi.unit_cost AS oi_cost
            FROM shopify_products sp
            JOIN product_mappings pm ON pm.product_id=sp.product_id
            LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
            LEFT JOIN shopify_images si ON si.product_id=sp.product_id AND si.position=0
            LEFT JOIN webami_products wp ON wp.upc=pm.webami_upc
            LEFT JOIN webami_order_items oi ON oi.webami_upc=pm.webami_upc
            {where}
            GROUP BY sp.product_id
            ORDER BY sp.title ASC""", params).fetchall())

    # Unmapped products whose vendor matches a known alias_name (artist-only check)
    if "artist" in fields:
        uconds = ["pm.id IS NULL", "sp.vendor IS NOT NULL", "sp.vendor != ''"]
        uparams = []
        if q_title:
            uconds.append("sp.title LIKE ?")
            uparams.append(f"%{q_title}%")
        if hide_u:
            uconds.append("(sp.title IS NULL OR sp.title NOT LIKE '%- U')")
        uwhere = "WHERE " + " AND ".join(uconds)
        unmapped_rows = _rows(conn.execute(
            f"""SELECT sp.product_id, sp.title AS sp_title, sp.vendor AS sp_vendor, sp.tags AS sp_tags,
                       sv.price AS sp_price, sv.cost AS sp_cost, sv.weight AS sp_weight,
                       sv.weight_unit AS sp_weight_unit, sv.variant_id,
                       si.url AS sp_image,
                       NULL AS wp_title, NULL AS wp_artist, NULL AS wp_cost, NULL AS wp_weight_grams,
                       NULL AS webami_upc, NULL AS mapped_upc,
                       NULL AS oi_title, NULL AS oi_vendor, NULL AS oi_cost
                FROM shopify_products sp
                LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
                LEFT JOIN shopify_images si ON si.product_id=sp.product_id AND si.position=0
                LEFT JOIN product_mappings pm ON pm.product_id=sp.product_id
                JOIN artist_aliases aa ON aa.alias_name=sp.vendor COLLATE BINARY
                {uwhere}
                GROUP BY sp.product_id
                ORDER BY sp.title ASC""", uparams).fetchall())
        rows = rows + unmapped_rows

    diffs = []
    ignored = get_ignored_variances()
    overrides = get_title_overrides()
    for r in rows:
        d = dict(r)
        # Fall back to order-item data when no webami_products row exists
        src_title  = d.get("wp_title")  or d.get("oi_title")
        src_artist = d.get("wp_artist") or d.get("oi_vendor")
        src_cost   = d.get("wp_cost")   if d.get("wp_title") else d.get("oi_cost")
        src_weight_grams = d.get("wp_weight_grams") if d.get("wp_title") else None

        row_diffs = {}
        if "title" in fields and src_title and d["product_id"] not in overrides:
            sp_norm = (d.get("sp_title") or "").strip()
            wp_norm = (src_title or "").strip()
            suggested = suggest_title(sp_norm, wp_norm)
            if suggested != sp_norm:
                row_diffs["title"] = {"old": d.get("sp_title"), "new": suggested}
                combined = f"{sp_norm} {wp_norm}"
                if _OST_RE.search(combined) or _OMPS_RE.search(combined):
                    existing_tags = (d.get("sp_tags") or "").lower()
                    if "soundtrack" not in existing_tags:
                        row_diffs["tags"] = {"old": d.get("sp_tags"), "new": (d.get("sp_tags")+", soundtrack" if d.get("sp_tags") else "soundtrack")}
        if "artist" in fields:
            sp_vendor = d.get("sp_vendor") or ""
            artist_val = src_artist or ""

            # If Shopify vendor is already a canonical_name (regardless of Webami), it's correct — skip
            is_canonical = conn.execute(
                "SELECT 1 FROM artist_aliases WHERE canonical_name=? COLLATE BINARY",
                (sp_vendor,)).fetchone()

            if not is_canonical:
                alias_row = conn.execute(
                    "SELECT canonical_name FROM artist_aliases WHERE alias_name=? COLLATE BINARY",
                    (sp_vendor,)).fetchone()

                if alias_row:
                    resolved = alias_row["canonical_name"]
                    # Still needs pushing to Shopify even though the mapping already exists
                    if resolved != sp_vendor:
                        row_diffs["artist"] = {"old": sp_vendor, "new": resolved, "via_alias": True}
                elif artist_val and sp_vendor != artist_val:
                    row_diffs["artist"] = {"old": sp_vendor, "new": artist_val, "via_alias": False}
        if "cost" in fields:
            sp_cost = float(d.get("sp_cost") or 0)
            src_cost_f = float(src_cost or 0)
            if src_cost_f and abs(sp_cost - src_cost_f) > 0.01:
                row_diffs["cost"] = {"old": d.get("sp_cost"), "new": src_cost}
        if "weight" in fields and src_weight_grams:
            sp_w = float(d.get("sp_weight") or 0)
            wp_w = round(src_weight_grams / 453.592, 4)
            if abs(sp_w - wp_w) > 0.001:
                row_diffs["weight"] = {"old": d.get("sp_weight"), "new": wp_w}
        if row_diffs:
            row_diffs = {
                f: v for f, v in row_diffs.items()
                if (d["product_id"], f, str(v.get("old") or ''), str(v.get("new") or '')) not in ignored
            }
            if row_diffs:
                d["wp_title"]  = src_title
                d["wp_artist"] = src_artist
                d["wp_cost"]   = src_cost
                d["diffs"] = row_diffs
                diffs.append(d)

    total = len(diffs)
    offset = (page - 1) * per_page
    return {"items": diffs[offset:offset+per_page], "total": total, "page": page,
            "per_page": per_page, "pages": max(1, (total+per_page-1)//per_page)}


def ignore_variance(product_id: str, field: str, old_value: str, new_value: str) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO variance_ignores (product_id,field,old_value,new_value)
           VALUES (?,?,?,?)
           ON CONFLICT(product_id,field,old_value,new_value) DO NOTHING""",
        (product_id, field, old_value, new_value))
    conn.commit()


def get_ignored_variances() -> set:
    rows = get_conn().execute(
        "SELECT product_id, field, old_value, new_value FROM variance_ignores").fetchall()
    return {(r[0], r[1], str(r[2] or ''), str(r[3] or '')) for r in rows}


def clear_ignored_variance(product_id: str, field: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM variance_ignores WHERE product_id=? AND field=?", (product_id, field))
    conn.commit()


def set_title_override(product_id: str, correct_title: str) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO title_overrides (product_id,correct_title) VALUES (?,?)
           ON CONFLICT(product_id) DO UPDATE SET correct_title=excluded.correct_title""",
        (product_id, correct_title))
    conn.commit()


def get_title_overrides() -> dict:
    rows = get_conn().execute("SELECT product_id, correct_title FROM title_overrides").fetchall()
    return {r[0]: r[1] for r in rows}


def delete_title_override(product_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM title_overrides WHERE product_id=?", (product_id,))
    conn.commit()


def ignore_unmatched(product_id: str, notes: str = None) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO unmatched_ignores (product_id,notes) VALUES (?,?)
           ON CONFLICT(product_id) DO UPDATE SET notes=excluded.notes""",
        (product_id, notes))
    conn.commit()


def unignore_unmatched(product_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM unmatched_ignores WHERE product_id=?", (product_id,))
    conn.commit()


def get_unmatched_ignores() -> set:
    rows = get_conn().execute("SELECT product_id FROM unmatched_ignores").fetchall()
    return {r[0] for r in rows}


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


def get_shopify_products(
    page: int = 1,
    per_page: int = 50,
    search: str = "",
    status_filter: str = "",
    mapped_filter: str = "",
    format_filter: str = "",
    sort: str = "title_asc",
    title_filter: str = "",
    vendor_filter: str = "",
    upc_filter: str = "",
    category_filter: str = "",
    ptype_filter: str = "",
    tags_filter: str = "",
    genres_filter: str = "",
) -> dict:
    conn = get_conn()
    conditions = []
    params: list[Any] = []

    if search:
        conditions.append("(sp.title LIKE ? OR sp.vendor LIKE ? OR sp.upc LIKE ?)")
        s = f"%{search}%"
        params += [s, s, s]
    if status_filter:
        conditions.append("sp.status=?")
        params.append(status_filter.upper())
    if format_filter:
        conditions.append("wp.format=?")
        params.append(format_filter)
    if mapped_filter == "mapped":
        conditions.append("pm.status='active'")
    elif mapped_filter == "pending":
        conditions.append("pm.status='pending'")
    elif mapped_filter == "unmatched":
        conditions.append("pm.id IS NULL")
    if title_filter:
        conditions.append("sp.title LIKE ?"); params.append(f"%{title_filter}%")
    if vendor_filter:
        conditions.append("sp.vendor LIKE ?"); params.append(f"%{vendor_filter}%")
    if upc_filter:
        conditions.append("sp.upc LIKE ?"); params.append(f"%{upc_filter}%")
    if category_filter:
        conditions.append("sp.category_name=?"); params.append(category_filter)
    if ptype_filter:
        conditions.append("sp.product_type=?"); params.append(ptype_filter)
    if tags_filter:
        conditions.append("sp.tags LIKE ?"); params.append(f"%{tags_filter}%")
    if genres_filter:
        conditions.append("sp.genres LIKE ?"); params.append(f"%{genres_filter}%")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    _sort_map = {
        "title_asc":    "sp.title ASC",
        "title_desc":   "sp.title DESC",
        "vendor_asc":   "COALESCE(MAX(wp.artist), sp.vendor) ASC",
        "vendor_desc":  "COALESCE(MAX(wp.artist), sp.vendor) DESC",
        "upc_asc":      "(sp.upc IS NULL) ASC, sp.upc ASC",
        "upc_desc":     "(sp.upc IS NULL) ASC, sp.upc DESC",
        "format_asc":   "(MAX(wp.format) IS NULL) ASC, MAX(wp.format) ASC",
        "format_desc":  "(MAX(wp.format) IS NULL) ASC, MAX(wp.format) DESC",
        "category_asc": "(sp.category_name IS NULL) ASC, sp.category_name ASC",
        "category_desc":"(sp.category_name IS NULL) ASC, sp.category_name DESC",
        "cost_asc":     "(COALESCE(MAX(wp.cost), MAX(sv.cost)) IS NULL) ASC, CAST(COALESCE(MAX(wp.cost), MAX(sv.cost)) AS REAL) ASC",
        "cost_desc":    "(COALESCE(MAX(wp.cost), MAX(sv.cost)) IS NULL) ASC, CAST(COALESCE(MAX(wp.cost), MAX(sv.cost)) AS REAL) DESC",
        "price_asc":    "(MAX(sv.price) IS NULL) ASC, CAST(MAX(sv.price) AS REAL) ASC",
        "price_desc":   "(MAX(sv.price) IS NULL) ASC, CAST(MAX(sv.price) AS REAL) DESC",
        "qty_asc":      "MAX(sv.inventory_quantity) ASC",
        "qty_desc":     "MAX(sv.inventory_quantity) DESC",
        "mapped_asc":   "(MAX(pm.status) IS NULL) ASC, MAX(pm.status) ASC",
        "mapped_desc":  "(MAX(pm.status) IS NULL) ASC, MAX(pm.status) DESC",
    }
    order_by = _sort_map.get(sort, "sp.title ASC")

    joins = f"""
        FROM shopify_products sp
        LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
        LEFT JOIN shopify_images  si ON si.product_id=sp.product_id AND si.position=0
        LEFT JOIN product_mappings pm ON pm.product_id=sp.product_id
        LEFT JOIN webami_products  wp ON wp.upc=pm.webami_upc
        {where}
    """

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT sp.product_id {joins})", params
    ).fetchone()
    total = count_row[0] if count_row else 0

    offset = (page - 1) * per_page
    rows = conn.execute(
        f"""SELECT
              sp.product_id, sp.title, sp.vendor, sp.status,
              sp.product_type, sp.tags, sp.category_name, sp.upc, sp.genres,
              MAX(sv.variant_id) AS variant_id, MAX(sv.price) AS price,
              MAX(sv.cost) AS cost, MAX(sv.inventory_quantity) AS inventory_quantity,
              MAX(si.url) AS image_url,
              MAX(pm.status) AS map_status, MAX(pm.confidence) AS confidence, MAX(pm.score) AS score,
              MAX(wp.upc) AS webami_upc, MAX(wp.title) AS webami_title,
              MAX(wp.artist) AS artist, MAX(wp.format) AS format, MAX(wp.cost) AS webami_cost
            {joins}
            GROUP BY sp.product_id
            ORDER BY {order_by}
            LIMIT ? OFFSET ?""",
        params + [per_page, offset],
    ).fetchall()

    return {
        "items": _rows(rows),
        "total": total,
        "page": page,
        "per_page": per_page,
        "pages": max(1, (total + per_page - 1) // per_page),
    }


def get_distinct_categories() -> list[str]:
    rows = get_conn().execute(
        "SELECT DISTINCT category_name FROM shopify_products WHERE category_name IS NOT NULL AND category_name!='' ORDER BY category_name").fetchall()
    return [r[0] for r in rows]


def get_distinct_product_types() -> list[str]:
    rows = get_conn().execute(
        "SELECT DISTINCT product_type FROM shopify_products WHERE product_type IS NOT NULL AND product_type!='' ORDER BY product_type").fetchall()
    return [r[0] for r in rows]


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


def get_products_with_missing_fields(page=1, per_page=20, field_filter='', sort='title_asc',
                                      q_title='', q_vendor='', status_filter='', q_category=''):
    _sort_map = {
        'title_asc':   'sp.title ASC',         'title_desc':   'sp.title DESC',
        'vendor_asc':  'LOWER(sp.vendor) ASC NULLS LAST', 'vendor_desc': 'LOWER(sp.vendor) DESC NULLS LAST',
        'status_asc':  'sp.status ASC',         'status_desc':  'sp.status DESC',
    }
    order_by = _sort_map.get(sort, 'sp.title ASC')
    conn = get_conn()
    _fc = {
        'title':        "sp.title IS NULL OR sp.title=''",
        'vendor':       "sp.vendor IS NULL OR sp.vendor=''",
        'product_type': "sp.product_type IS NULL OR sp.product_type=''",
        'category':     "sp.category_name IS NULL OR sp.category_name=''",
        'images':       "(SELECT COUNT(*) FROM shopify_images si2 WHERE si2.product_id=sp.product_id)=0",
        'cost':         "sv.cost IS NULL OR sv.cost=''",
        'price':        "sv.price IS NULL OR sv.price='' OR CAST(sv.price AS REAL)=0",
        'weight':       "sv.weight IS NULL",
        'weight_unit':  "sv.weight_unit IS NULL OR sv.weight_unit=''",
        'upc':          "sp.upc IS NULL OR sp.upc=''",
        'genre':        "sp.genres IS NULL OR sp.genres=''",
    }
    conds = [f"({_fc[field_filter]})" if field_filter in _fc else "(" + " OR ".join(_fc.values()) + ")"]
    params = []
    if q_title:    conds.append("sp.title LIKE ?");   params.append(f"%{q_title}%")
    if q_vendor:   conds.append("sp.vendor LIKE ?");  params.append(f"%{q_vendor}%")
    if status_filter: conds.append("sp.status=?");    params.append(status_filter.upper())
    if q_category: conds.append("sp.category_name LIKE ?"); params.append(f"%{q_category}%")
    where = "WHERE " + " AND ".join(conds)
    base = f"""FROM shopify_products sp
        LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
        LEFT JOIN shopify_images si ON si.product_id=sp.product_id AND si.position=0
        LEFT JOIN product_mappings pm ON pm.product_id=sp.product_id AND pm.status='active'
        LEFT JOIN webami_products wp ON wp.upc=pm.webami_upc
        {where}"""
    total = conn.execute(f"SELECT COUNT(DISTINCT sp.product_id) {base}", params).fetchone()[0]
    rows = conn.execute(f"""
        SELECT sp.product_id, sp.title, sp.vendor, sp.product_type, sp.category_name, sp.upc, sp.status,
               sv.variant_id, sv.price, sv.cost, sv.weight, sv.weight_unit,
               si.url AS image_url, pm.status AS map_status, pm.webami_upc,
               CASE WHEN sp.title IS NULL OR sp.title='' THEN 1 ELSE 0 END missing_title,
               CASE WHEN sp.vendor IS NULL OR sp.vendor='' THEN 1 ELSE 0 END missing_vendor,
               CASE WHEN sp.product_type IS NULL OR sp.product_type='' THEN 1 ELSE 0 END missing_product_type,
               CASE WHEN sp.category_name IS NULL OR sp.category_name='' THEN 1 ELSE 0 END missing_category,
               CASE WHEN (SELECT COUNT(*) FROM shopify_images si2 WHERE si2.product_id=sp.product_id)=0 THEN 1 ELSE 0 END missing_images,
               CASE WHEN sv.cost IS NULL OR sv.cost='' THEN 1 ELSE 0 END missing_cost,
               CASE WHEN sv.price IS NULL OR sv.price='' OR CAST(sv.price AS REAL)=0 THEN 1 ELSE 0 END missing_price,
               CASE WHEN sv.weight IS NULL THEN 1 ELSE 0 END missing_weight,
               CASE WHEN sv.weight_unit IS NULL OR sv.weight_unit='' THEN 1 ELSE 0 END missing_weight_unit,
               CASE WHEN sp.upc IS NULL OR sp.upc='' THEN 1 ELSE 0 END missing_upc,
               CASE WHEN sp.genres IS NULL OR sp.genres='' THEN 1 ELSE 0 END missing_genre
        {base} GROUP BY sp.product_id ORDER BY {order_by} LIMIT ? OFFSET ?""",
        params + [per_page, (page-1)*per_page]).fetchall()
    return {"items": _rows(rows), "total": total, "page": page,
            "per_page": per_page, "pages": max(1,(total+per_page-1)//per_page)}


def get_unmapped_products() -> list[dict]:
    return _rows(get_conn().execute(
        """SELECT sp.product_id, sp.title, sp.vendor, sp.upc
           FROM shopify_products sp
           LEFT JOIN product_mappings pm ON pm.product_id=sp.product_id AND pm.status='active'
           WHERE pm.id IS NULL""").fetchall())


def count_shopify_products() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM shopify_products").fetchone()[0]


# ─────────────────────────────────────────────
# Webami products
# ─────────────────────────────────────────────

def upsert_webami_product(p: dict) -> None:
    conn = get_conn()
    upc    = p.get("upc")
    title  = p.get("title")
    artist = (p.get("artist") or "").strip()
    fmt    = p.get("format")

    if upc and title and fmt:
        dup = conn.execute(
            """SELECT upc FROM webami_products
               WHERE LOWER(TRIM(title))=LOWER(TRIM(?))
                 AND LOWER(TRIM(COALESCE(artist,'')))=LOWER(TRIM(?))
                 AND LOWER(TRIM(format))=LOWER(TRIM(?))
                 AND upc != ?
               ORDER BY last_synced DESC LIMIT 1""",
            (title, artist, fmt, upc)).fetchone()
        if dup:
            old_upc = dup[0]
            conn.execute(
                """INSERT INTO upc_aliases (retired_upc,active_upc,notes)
                   VALUES (?,?,'auto: duplicate title/artist/format')
                   ON CONFLICT(retired_upc) DO UPDATE SET active_upc=excluded.active_upc""",
                (old_upc, upc))
            conn.execute("UPDATE product_mappings SET webami_upc=? WHERE webami_upc=?", (upc, old_upc))
            conn.execute("UPDATE webami_order_items SET webami_upc=? WHERE webami_upc=?", (upc, old_upc))
            conn.execute("DELETE FROM webami_products WHERE upc=?", (old_upc,))

    conn.execute(
        """INSERT INTO webami_products
           (upc,title,artist,brand,format,genres,features,image_urls,weight_grams,cost,last_synced)
           VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))
           ON CONFLICT(upc) DO UPDATE SET
             title=excluded.title, artist=excluded.artist, brand=excluded.brand,
             format=excluded.format, genres=excluded.genres, features=excluded.features,
             image_urls=excluded.image_urls, weight_grams=excluded.weight_grams,
             cost=excluded.cost, last_synced=datetime('now')""",
        (
            p.get("upc"), p.get("title"), p.get("artist"), p.get("brand"),
            p.get("format"),
            _j(p.get("genres")), _j(p.get("features")), _j(p.get("image_urls")),
            p.get("weight_grams"), p.get("cost"),
        ),
    )
    conn.commit()


def get_webami_product(upc: str) -> Optional[dict]:
    r = _row(get_conn().execute("SELECT * FROM webami_products WHERE upc=?", (upc,)).fetchone())
    if r:
        r["genres"]     = _uj(r.get("genres"))
        r["features"]   = _uj(r.get("features"))
        r["image_urls"] = _uj(r.get("image_urls"))
    return r


def update_webami_cost(upc: str, cost: float) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE webami_products SET cost=?, last_cost_sync=datetime('now') WHERE upc=?",
        (cost, upc))
    conn.commit()


def get_all_webami_products() -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT upc, title, artist, format, cost FROM webami_products").fetchall())


def count_webami_products() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM webami_products").fetchone()[0]


# ─────────────────────────────────────────────
# UPC aliases
# ─────────────────────────────────────────────

def upsert_product_alias(retired_upc: str, active_upc: str, notes: str = None) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO upc_aliases (retired_upc,active_upc,notes)
           VALUES (?,?,?)
           ON CONFLICT(retired_upc) DO UPDATE SET active_upc=excluded.active_upc""",
        (retired_upc, active_upc, notes),
    )
    conn.commit()


def get_alias(retired_upc: str) -> Optional[dict]:
    return _row(get_conn().execute(
        "SELECT * FROM upc_aliases WHERE retired_upc=?", (retired_upc,)).fetchone())


def get_all_aliases() -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT * FROM upc_aliases ORDER BY created_at DESC").fetchall())


def delete_alias(retired_upc: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM upc_aliases WHERE retired_upc=?", (retired_upc,))
    conn.commit()


def find_webami_upc_by_title(title: str) -> Optional[str]:
    """Search webami cache then order items for a UPC matching this title."""
    if not title:
        return None
    conn = get_conn()
    # 1. Exact match in webami cache
    row = conn.execute(
        "SELECT upc FROM webami_products WHERE LOWER(title)=LOWER(?) LIMIT 1",
        (title,)).fetchone()
    if row: return row[0]
    # 2. Exact match in order items
    row = conn.execute(
        "SELECT webami_upc FROM webami_order_items WHERE LOWER(title)=LOWER(?) AND webami_upc IS NOT NULL LIMIT 1",
        (title,)).fetchone()
    if row: return row[0]
    # 3. Partial match in order items (first 30 chars)
    row = conn.execute(
        "SELECT webami_upc FROM webami_order_items WHERE title LIKE ? AND webami_upc IS NOT NULL LIMIT 1",
        (f"%{title[:30]}%",)).fetchone()
    return row[0] if row else None


# ─────────────────────────────────────────────
# Product mappings  (product ↔ webami product)
# ─────────────────────────────────────────────

def upsert_mapping(product_id: str, webami_upc: str, confidence: str, score: float,
                   status: str = "active") -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO product_mappings (product_id,webami_upc,confidence,score,status,updated_at)
           VALUES (?,?,?,?,?,datetime('now'))
           ON CONFLICT(product_id) DO UPDATE SET
             webami_upc=excluded.webami_upc, confidence=excluded.confidence,
             score=excluded.score, status=excluded.status, updated_at=datetime('now')""",
        (product_id, webami_upc, confidence, score, status),
    )
    conn.commit()


def confirm_mapping(product_id: str, webami_upc: str) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO product_mappings (product_id,webami_upc,confidence,score,status,updated_at)
           VALUES (?,?,'manual',1.0,'active',datetime('now'))
           ON CONFLICT(product_id) DO UPDATE SET
             webami_upc=excluded.webami_upc, confidence='manual',
             status='active', updated_at=datetime('now')""",
        (product_id, webami_upc),
    )
    conn.commit()


def reject_mapping(product_id: str) -> None:
    conn = get_conn()
    conn.execute(
        "UPDATE product_mappings SET status='rejected', updated_at=datetime('now') WHERE product_id=?",
        (product_id,),
    )
    conn.commit()


def delete_mapping(product_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM product_mappings WHERE product_id=?", (product_id,))
    conn.commit()


def force_map_product(product_id: str, webami_upc: str) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO product_mappings (product_id,webami_upc,confidence,score,status,updated_at)
           VALUES (?,?,'manual_unverified',1.0,'active',datetime('now'))
           ON CONFLICT(product_id) DO UPDATE SET
             webami_upc=excluded.webami_upc, confidence='manual_unverified',
             status='active', updated_at=datetime('now')""",
        (product_id, webami_upc),
    )
    conn.commit()


def get_active_mapped_products_with_upc() -> list[dict]:
    return _rows(get_conn().execute(
        """SELECT pm.product_id, pm.webami_upc, sp.title
           FROM product_mappings pm
           JOIN shopify_products sp ON sp.product_id=pm.product_id
           WHERE pm.status='active'""").fetchall())


def get_review_queue(page: int = 1, per_page: int = 20, hide_dash_u: bool = False) -> dict:
    conn = get_conn()
    rows = conn.execute(
        """SELECT pm.*, sp.upc, sp.product_id, sp.category_name,
                  sp.title AS sp_title, sp.vendor,
                  sv.price AS sv_price, sv.cost AS sv_cost,
                  si.url AS sp_image,
                  wp.title AS wp_title, wp.artist, wp.format, wp.cost AS wp_cost, wp.image_urls,
                  oi.title AS oi_title, oi.vendor AS oi_vendor, oi.format AS oi_format,
                  oi.unit_cost AS oi_cost
           FROM product_mappings pm
           JOIN shopify_products sp ON sp.product_id=pm.product_id
           JOIN shopify_variants sv ON sv.product_id=sp.product_id
           LEFT JOIN shopify_images si ON si.product_id=sp.product_id AND si.position=0
           LEFT JOIN webami_products wp ON wp.upc=pm.webami_upc
           LEFT JOIN webami_order_items oi ON oi.webami_upc=pm.webami_upc
           WHERE pm.status='pending'
           GROUP BY pm.id
           ORDER BY pm.score DESC""").fetchall()

    all_items = []
    for r in rows:
        d = dict(r)
        if hide_dash_u and d.get("sp_title") and d["sp_title"].endswith("- U"):
            continue
        d["wp_image"] = (_uj(d.get("image_urls")) or [None])[0]
        # Fall back to order-item data when no webami_products row exists
        if not d.get("wp_title"):
            d["wp_title"] = d.get("oi_title")
            d["artist"]   = d.get("artist") or d.get("oi_vendor")
            d["format"]   = d.get("format") or d.get("oi_format")
            d["wp_cost"]  = d.get("wp_cost") or d.get("oi_cost")
        all_items.append(d)

    total  = len(all_items)
    offset = (page - 1) * per_page
    return {"items": all_items[offset:offset + per_page], "total": total,
            "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page)}


def get_unmatched_queue(page: int = 1, per_page: int = 20, q_title: str = '',
                         q_vendor: str = '', q_category: str = '',
                         sort: str = 'title_asc') -> dict:
    _sort_map = {
        'title_asc':    'sp.title ASC',           'title_desc':    'sp.title DESC',
        'vendor_asc':   'sp.vendor ASC NULLS LAST','vendor_desc':  'sp.vendor DESC NULLS LAST',
        'category_asc': 'sp.category_name ASC NULLS LAST', 'category_desc': 'sp.category_name DESC NULLS LAST',
        'cost_asc':     'CAST(sv.cost AS REAL) ASC NULLS LAST', 'cost_desc': 'CAST(sv.cost AS REAL) DESC NULLS LAST',
    }
    order_by = _sort_map.get(sort, 'sp.title ASC')
    conn = get_conn()
    conds = ["pm.id IS NULL", "sp.product_id NOT IN (SELECT product_id FROM unmatched_ignores)"]
    params = []
    if q_title:
        conds.append("sp.title LIKE ?")
        params.append(f"%{q_title}%")
    if q_vendor:
        conds.append("sp.vendor LIKE ?")
        params.append(f"%{q_vendor}%")
    if q_category:
        conds.append("sp.category_name LIKE ?")
        params.append(f"%{q_category}%")
    where = "WHERE " + " AND ".join(conds)
    base = f"""FROM shopify_products sp
        LEFT JOIN product_mappings pm ON pm.product_id=sp.product_id
        LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
        LEFT JOIN shopify_images si ON si.product_id=sp.product_id AND si.position=0
        {where}"""
    total = conn.execute(f"SELECT COUNT(*) {base}", params).fetchone()[0]
    rows = _rows(conn.execute(
        f"""SELECT sp.product_id, sp.title, sp.vendor, sp.upc, sp.category_name,
                   sv.cost, si.url AS image_url
            {base} GROUP BY sp.product_id ORDER BY {order_by} LIMIT ? OFFSET ?""",
        params + [per_page, (page-1)*per_page]).fetchall())
    return {"items": rows, "total": total, "page": page, "per_page": per_page,
            "pages": max(1, (total+per_page-1)//per_page)}


def get_stats() -> dict:
    conn = get_conn()
    total_products  = conn.execute("SELECT COUNT(*) FROM shopify_products").fetchone()[0]
    total_variants  = conn.execute("SELECT COUNT(*) FROM shopify_variants").fetchone()[0]
    auto_mapped     = conn.execute(
        "SELECT COUNT(*) FROM product_mappings WHERE status='active' AND confidence!='manual'").fetchone()[0]
    manual_mapped   = conn.execute(
        "SELECT COUNT(*) FROM product_mappings WHERE status='active' AND confidence='manual'").fetchone()[0]
    pending_review  = conn.execute(
        "SELECT COUNT(*) FROM product_mappings WHERE status='pending'").fetchone()[0]
    rejected        = conn.execute(
        "SELECT COUNT(*) FROM product_mappings WHERE status='rejected'").fetchone()[0]
    mapped_any      = conn.execute(
        "SELECT COUNT(DISTINCT product_id) FROM product_mappings WHERE status='active'").fetchone()[0]
    unmatched       = total_products - mapped_any - pending_review - rejected
    dup_pending     = conn.execute(
        "SELECT COUNT(*) FROM duplicate_groups WHERE status='pending'").fetchone()[0]
    total_orders    = conn.execute("SELECT COUNT(*) FROM webami_orders").fetchone()[0]
    pending_receive = conn.execute(
        """SELECT COUNT(*) FROM webami_order_items oi
           JOIN webami_orders o ON o.id=oi.order_id
           WHERE o.status != 'complete'
             AND oi.quantity_ordered > COALESCE(
               (SELECT SUM(r.quantity_received) FROM received_items r WHERE r.order_item_id=oi.id), 0)"""
    ).fetchone()[0]
    unknown_features = conn.execute(
        "SELECT COUNT(*) FROM unknown_features WHERE resolved=0").fetchone()[0]
    webami_cached   = conn.execute("SELECT COUNT(*) FROM webami_products").fetchone()[0]

    return {
        "total_products":  total_products,
        "total_variants":  total_variants,
        "auto_mapped":     auto_mapped,
        "manual_mapped":   manual_mapped,
        "pending_review":  pending_review,
        "rejected":        rejected,
        "unmatched":       max(0, unmatched),
        "dup_pending":     dup_pending,
        "total_orders":    total_orders,
        "pending_receive": pending_receive,
        "unknown_features":unknown_features,
        "webami_cached":   webami_cached,
    }


# ─────────────────────────────────────────────
# Duplicate groups
# ─────────────────────────────────────────────

def get_duplicate_groups(page: int = 1, per_page: int = 20) -> dict:
    conn = get_conn()
    total = conn.execute(
        "SELECT COUNT(*) FROM duplicate_groups WHERE status='pending'").fetchone()[0]
    offset = (page - 1) * per_page
    groups = _rows(conn.execute(
        "SELECT * FROM duplicate_groups WHERE status='pending' ORDER BY id LIMIT ? OFFSET ?",
        (per_page, offset)).fetchall())
    for g in groups:
        members = _rows(conn.execute(
            """SELECT dgm.*, sp.title, sp.vendor, sp.status, sp.tags, sp.category_name,
                      sv.price, sv.cost, sv.inventory_quantity,
                      wp.format, wp.cost AS webami_cost,
                      si.url AS image_url
               FROM duplicate_group_members dgm
               JOIN shopify_products sp ON sp.product_id=dgm.product_id
               LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
               LEFT JOIN product_mappings pm ON pm.product_id=sp.product_id AND pm.status='active'
               LEFT JOIN webami_products wp ON wp.upc=pm.webami_upc
               LEFT JOIN shopify_images si ON si.product_id=sp.product_id AND si.position=0
               WHERE dgm.group_id=?
               GROUP BY dgm.id""", (g["id"],)).fetchall())
        g["members"] = members
    return {"items": groups, "total": total, "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page)}


def resolve_duplicate_group(group_id: int, action: str) -> None:
    conn = get_conn()
    conn.execute("UPDATE duplicate_groups SET status=? WHERE id=?", (action, group_id))
    conn.commit()


def save_duplicate_groups(groups: list[dict]) -> int:
    conn = get_conn()
    saved = 0
    for g in groups:
        key = g["key"]
        exists = conn.execute(
            "SELECT id FROM duplicate_groups WHERE normalized_key=? AND status='pending'",
            (key,)).fetchone()
        if exists:
            continue
        cur = conn.execute(
            "INSERT INTO duplicate_groups (normalized_key) VALUES (?)", (key,))
        gid = cur.lastrowid
        for pid in g["product_ids"]:
            conn.execute(
                "INSERT OR IGNORE INTO duplicate_group_members (group_id,product_id) VALUES (?,?)",
                (gid, pid))
        saved += 1
    conn.commit()
    return saved


# ─────────────────────────────────────────────
# Feature rules
# ─────────────────────────────────────────────

def get_feature_rules(enabled_only: bool = False, sort: str = 'priority_desc',
                       q_text: str = '', q_value: str = '',
                       match_type: str = '', action_type: str = '') -> list[dict]:
    _sort_map = {
        'match_text_asc':  'match_text ASC',   'match_text_desc':  'match_text DESC',
        'match_type_asc':  'match_type ASC',   'match_type_desc':  'match_type DESC',
        'action_type_asc': 'action_type ASC',  'action_type_desc': 'action_type DESC',
        'priority_asc':    'priority ASC, id', 'priority_desc':    'priority DESC, id',
    }
    order_by = _sort_map.get(sort, 'priority DESC, id')
    conds, params = [], []
    if enabled_only:  conds.append("enabled=1")
    if q_text:        conds.append("match_text LIKE ?");    params.append(f"%{q_text}%")
    if q_value:       conds.append("action_value LIKE ?");  params.append(f"%{q_value}%")
    if match_type:    conds.append("match_type=?");         params.append(match_type)
    if action_type:   conds.append("action_type=?");        params.append(action_type)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    return _rows(get_conn().execute(
        f"SELECT * FROM feature_rules {where} ORDER BY {order_by}", params).fetchall())


def create_feature_rule(rule: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO feature_rules (match_text,match_type,action_type,action_value,priority,enabled,notes)
           VALUES (?,?,?,?,?,?,?)""",
        (rule["match_text"], rule["match_type"], rule["action_type"],
         rule.get("action_value"), rule.get("priority", 0), rule.get("enabled", 1), rule.get("notes")))
    conn.commit()
    return cur.lastrowid


def update_feature_rule(rule_id: int, rule: dict) -> None:
    conn = get_conn()
    conn.execute(
        """UPDATE feature_rules SET match_text=?,match_type=?,action_type=?,action_value=?,
           priority=?,enabled=?,notes=? WHERE id=?""",
        (rule["match_text"], rule["match_type"], rule["action_type"],
         rule.get("action_value"), rule.get("priority", 0), rule.get("enabled", 1),
         rule.get("notes"), rule_id))
    conn.commit()


def delete_feature_rule(rule_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM feature_rules WHERE id=?", (rule_id,))
    conn.commit()


# ─────────────────────────────────────────────
# Unknown features
# ─────────────────────────────────────────────

def log_unknown_feature(text: str) -> None:
    conn = get_conn()
    conn.execute(
        """INSERT INTO unknown_features (feature_text) VALUES (?)
           ON CONFLICT(feature_text) DO UPDATE SET
             seen_count=seen_count+1, last_seen=datetime('now'), resolved=0""",
        (text,))
    conn.commit()


def get_unknown_features(resolved: bool = False) -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT * FROM unknown_features WHERE resolved=? ORDER BY seen_count DESC",
        (1 if resolved else 0,)).fetchall())


def resolve_unknown_feature(feature_id: int) -> None:
    conn = get_conn()
    conn.execute("UPDATE unknown_features SET resolved=1 WHERE id=?", (feature_id,))
    conn.commit()


# ─────────────────────────────────────────────
# Artist aliases
# ─────────────────────────────────────────────

def get_artist_aliases() -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT * FROM artist_aliases ORDER BY alias_name").fetchall())


def create_artist_alias(alias: str, canonical: str) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO artist_aliases (alias_name,canonical_name) VALUES (?,?)",
        (alias.strip(), canonical.strip()))
    conn.commit()
    return cur.lastrowid


def delete_artist_alias(alias_id: int) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM artist_aliases WHERE id=?", (alias_id,))
    conn.commit()


def resolve_artist(name: str) -> str:
    if not name:
        return name
    r = get_conn().execute(
        "SELECT canonical_name FROM artist_aliases WHERE alias_name=? COLLATE BINARY",
        (name,)).fetchone()
    return r["canonical_name"] if r else name


# ─────────────────────────────────────────────
# Orders
# ─────────────────────────────────────────────

def create_order(order: dict) -> int:
    conn = get_conn()
    guid = order.get("guid") or order.get("webami_order_id")
    conn.execute(
        """INSERT INTO webami_orders
           (guid,order_number,order_name,order_date,total_products,notes)
           VALUES (?,?,?,?,?,?)
           ON CONFLICT(guid) DO UPDATE SET
             order_number=excluded.order_number,
             order_name=excluded.order_name,
             order_date=excluded.order_date""",
        (guid, order.get("order_number"), order.get("order_name"),
         order.get("order_date"), order.get("total_products", 0), order.get("notes")))
    conn.commit()
    row = conn.execute("SELECT id FROM webami_orders WHERE guid=?", (guid,)).fetchone()
    return row[0] if row else 0


def create_order_item(order_id: int, item: dict) -> int:
    conn = get_conn()
    cur = conn.execute(
        """INSERT INTO webami_order_items
           (order_id,webami_upc,title,vendor,format,unit_cost,total_cost,
            quantity_ordered,quantity_in_stock,quantity_backordered)
           VALUES (?,?,?,?,?,?,?,?,?,?)""",
        (order_id, item.get("webami_upc") or item.get("upc"),
         item.get("title"), item.get("vendor"), item.get("format"),
         item.get("unit_cost") or item.get("cost"),
         item.get("total_cost"),
         item.get("quantity_ordered") or item.get("qty_ordered") or 0,
         item.get("quantity_in_stock") or item.get("in_stock") or 0,
         item.get("quantity_backordered") or item.get("backordered") or 0))
    conn.commit()
    return cur.lastrowid


def get_orders(page: int = 1, per_page: int = 30, sort: str = 'order_date_desc',
               q_number: str = '', q_name: str = '', status_filter: str = '') -> dict:
    _sort_map = {
        'order_number_asc':    'o.order_number ASC',    'order_number_desc':    'o.order_number DESC',
        'order_name_asc':      'LOWER(o.order_name) ASC NULLS LAST',
        'order_name_desc':     'LOWER(o.order_name) DESC NULLS LAST',
        'order_date_asc':      'o.order_date ASC',      'order_date_desc':      'o.order_date DESC, o.id DESC',
        'item_count_asc':      'item_count ASC',        'item_count_desc':      'item_count DESC',
        'total_qty_asc':       'total_qty ASC',         'total_qty_desc':       'total_qty DESC',
        'total_received_asc':  'total_received ASC',    'total_received_desc':  'total_received DESC',
        'status_asc':          'o.status ASC',          'status_desc':          'o.status DESC',
    }
    order_by = _sort_map.get(sort, 'o.order_date DESC, o.id DESC')
    conds, params = [], []
    if q_number:
        conds.append("o.order_number LIKE ?"); params.append(f"%{q_number}%")
    if q_name:
        conds.append("o.order_name LIKE ?"); params.append(f"%{q_name}%")
    if status_filter:
        conds.append("o.status=?"); params.append(status_filter)
    where = ("WHERE " + " AND ".join(conds)) if conds else ""
    conn = get_conn()
    total = conn.execute(f"SELECT COUNT(*) FROM webami_orders o {where}", params).fetchone()[0]
    offset = (page - 1) * per_page
    rows = _rows(conn.execute(
        f"""SELECT o.id, o.guid AS webami_order_id, o.order_number, o.order_name,
                  o.order_date, o.status, o.notes, o.created_at,
                  COUNT(oi.id) AS item_count,
                  COALESCE(SUM(oi.quantity_ordered),0) AS total_qty,
                  COALESCE(SUM(r.quantity_received),0) AS total_received
           FROM webami_orders o
           LEFT JOIN webami_order_items oi ON oi.order_id=o.id
           LEFT JOIN received_items r ON r.order_item_id=oi.id
           {where}
           GROUP BY o.id ORDER BY {order_by} LIMIT ? OFFSET ?""",
        params + [per_page, offset]).fetchall())
    return {"items": rows, "total": total, "page": page, "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page)}


def get_order_detail(order_id: int) -> Optional[dict]:
    conn = get_conn()
    order = _row(conn.execute("SELECT * FROM webami_orders WHERE id=?", (order_id,)).fetchone())
    if not order:
        return None
    items = _rows(conn.execute(
        """SELECT oi.*,
                  COALESCE(SUM(r.quantity_received),0) AS total_received,
                  pm.webami_upc AS mapped_upc,
                  sv.variant_id, sv.inventory_item_id,
                  sp.title AS sp_title, sp.product_id,
                  si.url AS sp_image,
                  wp.title AS wp_title, wp.image_urls AS wp_images
           FROM webami_order_items oi
           LEFT JOIN received_items r ON r.order_item_id=oi.id
           LEFT JOIN product_mappings pm ON pm.webami_upc=oi.webami_upc AND pm.status='active'
           LEFT JOIN shopify_products sp ON sp.product_id=pm.product_id
           LEFT JOIN shopify_variants sv ON sv.product_id=sp.product_id
           LEFT JOIN shopify_images si ON si.product_id=sp.product_id AND si.position=0
           LEFT JOIN webami_products wp ON wp.upc=oi.webami_upc
           WHERE oi.order_id=?
           GROUP BY oi.id
           ORDER BY oi.id""",
        (order_id,)).fetchall())
    for item in items:
        item["wp_image"] = (_uj(item.get("wp_images")) or [None])[0]
        item.pop("wp_images", None)
        item["received_records"] = _rows(conn.execute(
            "SELECT id, quantity_received, received_at FROM received_items WHERE order_item_id=? ORDER BY id",
            (item["id"],)).fetchall())
    order["items"] = items
    return order


def get_order_item_candidates() -> list[dict]:
    return _rows(get_conn().execute(
        """SELECT DISTINCT webami_upc AS upc, title, vendor AS artist, format, unit_cost AS cost
           FROM webami_order_items
           WHERE webami_upc IS NOT NULL AND title IS NOT NULL""").fetchall())


def add_received(order_item_id: int, qty: int, shopify_updated: bool = False, unit_cost: float = None) -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO received_items (order_item_id,quantity_received,unit_cost,shopify_updated) VALUES (?,?,?,?)",
        (order_item_id, qty, unit_cost, 1 if shopify_updated else 0))
    conn.commit()
    _refresh_order_status(order_item_id, conn)
    return cur.lastrowid


def delete_received(received_id: int) -> None:
    conn = get_conn()
    row = conn.execute(
        "SELECT order_item_id FROM received_items WHERE id=?", (received_id,)).fetchone()
    conn.execute("DELETE FROM received_items WHERE id=?", (received_id,))
    conn.commit()
    if row:
        _refresh_order_status(row[0], conn)


def _refresh_order_status(order_item_id: int, conn: sqlite3.Connection) -> None:
    order_id = conn.execute(
        "SELECT order_id FROM webami_order_items WHERE id=?", (order_item_id,)).fetchone()
    if not order_id:
        return
    oid = order_id[0]
    row = conn.execute(
        """SELECT
             SUM(oi.quantity_ordered) AS total_ordered,
             COALESCE(SUM(r.quantity_received),0) AS total_received
           FROM webami_order_items oi
           LEFT JOIN received_items r ON r.order_item_id=oi.id
           WHERE oi.order_id=?""", (oid,)).fetchone()
    if row:
        status = "complete" if row[1] >= row[0] else ("partial" if row[1] > 0 else "pending")
        conn.execute("UPDATE webami_orders SET status=? WHERE id=?", (status, oid))
    conn.commit()


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