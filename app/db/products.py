from typing import Optional

from app.db.connection import _row, _rows, _sid, get_conn
from app.db.db import _img_key


def upsert_product(p: dict) -> None:
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


def upsert_variant(product_id: str, v: dict) -> None:
    conn = get_conn()
    inv      = v.get("inventoryItem") or {}
    cost_obj = inv.get("unitCost") or {}
    meas     = inv.get("measurement") or {}
    wt       = meas.get("weight") or {}
    weight      = wt.get("value")   or v.get("weight")
    weight_unit = wt.get("unit")    or v.get("weightUnit") or v.get("weight_unit")
    conn.execute(
        """INSERT INTO shopify_variants
           (variant_id,product_id,title,barcode,sku,upc,description,
            release_date,variant_tags,price,cost,inventory_item_id,
            inventory_quantity,weight,weight_unit)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(variant_id) DO UPDATE SET
             price=excluded.price, cost=excluded.cost,
             inventory_item_id=excluded.inventory_item_id,
             inventory_quantity=excluded.inventory_quantity,
             weight=excluded.weight, weight_unit=excluded.weight_unit""",
        (
            _sid(v.get("id") or v.get("variant_id") or ""),
            product_id,
            v.get("title"),
            v.get("barcode"),
            v.get("sku"),
            v.get("upc"),
            v.get("description"),
            v.get("release_date"),
            v.get("variant_tags"),
            v.get("price"),
            cost_obj.get("amount") if cost_obj else v.get("cost"),
            _sid(inv.get("id") or v.get("inventory_item_id") or ""),
            v.get("inventoryQuantity") or v.get("inventory_quantity") or 0,
            weight,
            weight_unit,
        ),
    )
    conn.commit()


def upsert_image(product_id: str, media_id: str, url: str, position: int) -> None:
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


def clear_images(product_id: str) -> None:
    conn = get_conn()
    conn.execute("DELETE FROM shopify_images WHERE product_id=?", (product_id,))
    conn.commit()


def get_product_detail(product_id: str) -> Optional[dict]:
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
    return product


def count_products() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM shopify_products").fetchone()[0]


def list_products(search: str = "", page: int = 1, per_page: int = 50) -> dict:
    conn = get_conn()
    conditions = []
    params = []

    if search:
        conditions.append("(sp.title LIKE ? OR sp.vendor LIKE ? OR sp.upc LIKE ?)")
        s = f"%{search}%"
        params.extend([s, s, s])

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    joins = f"""
        FROM shopify_products sp
        LEFT JOIN shopify_variants sv ON sv.product_id = sp.product_id
        LEFT JOIN shopify_images si
            ON si.product_id = sp.product_id AND si.position = 0
        {where}
    """

    count_row = conn.execute(
        f"SELECT COUNT(*) FROM (SELECT DISTINCT sp.product_id {joins})",
        params,
    ).fetchone()
    total = count_row[0] if count_row else 0

    offset = (page - 1) * per_page
    rows = conn.execute(
        f"""
        SELECT
            sp.product_id, sp.title, sp.vendor, sp.status,
            sp.product_type, sp.tags, sp.category_name, sp.upc, sp.genres,
            MAX(sv.variant_id) AS variant_id,
            MAX(sv.price) AS price,
            MAX(sv.cost) AS cost,
            MAX(sv.inventory_quantity) AS inventory_quantity,
            MAX(si.url) AS image_url
        {joins}
        GROUP BY sp.product_id
        ORDER BY sp.title ASC
        LIMIT ? OFFSET ?
        """,
        params + [per_page, offset],
    ).fetchall()

    return {
        "items": _rows(rows),
        "total": total,
    }




