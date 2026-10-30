import json
from typing import Optional

from app.db.connection import get_conn, row, rows, strip_gid, transaction


SORT_COLUMNS: dict[str, str] = {
    "title": "title COLLATE NOCASE",
    "vendor": "vendor COLLATE NOCASE",
    "status": "status",
    "category": "category_name COLLATE NOCASE",
    "type": "type COLLATE NOCASE",
    "genres": "genres COLLATE NOCASE",
    "tags": "tags COLLATE NOCASE",
    "variants": "(SELECT COUNT(*) FROM shopify_variants v "
                "WHERE v.product_id = shopify_products.product_id)",
    "price": "(SELECT MIN(CAST(v.price AS REAL)) FROM shopify_variants v "
             "WHERE v.product_id = shopify_products.product_id)",
    "qty": "(SELECT COALESCE(SUM(v.inventory_quantity), 0) FROM shopify_variants v "
           "WHERE v.product_id = shopify_products.product_id)",
}
TEXT_FILTERS: dict[str, str] = {"title": "title", "vendor": "vendor"}
VALUE_FILTERS: dict[str, str] = {"status": "status", "category": "category_name", "type": "type"}
LIST_FILTERS: dict[str, str] = {"genres": "genres", "tags": "tags"}

_P_COLS = ("title", "vendor", "status", "product_type", "handle",
           "category_id", "category_name", "type", "upc")
_V_COLS = ("title", "upc", "description", "release_date", "variant_tags",
           "price", "cost", "inventory_quantity", "weight")


def split_list(value: Optional[str]) -> list[str]:
    """Genres/tags arrive as a JSON array or a comma list; return unique clean items."""
    if not value:
        return []
    text = value.strip()
    try:
        parsed = json.loads(text) if text.startswith("[") else None
    except ValueError:
        parsed = None
    raw = parsed if isinstance(parsed, list) else text.split(",")
    items: dict[str, None] = {}
    for item in raw:
        s = str(item).strip().strip('"')
        if s:
            items.setdefault(s, None)
    return list(items)


def norm_code(v) -> Optional[str]:
    """UPC copied exactly as a string."""
    return None if v is None else str(v)


def _mf(node: dict, key: str) -> Optional[str]:
    return (node.get(key) or {}).get("value")


def _upsert(conn, table: str, pk: str, data: dict) -> None:
    cols = ", ".join(data)
    marks = ", ".join(f":{k}" for k in data)
    updates = ", ".join(f"{k}=excluded.{k}" for k in data if k != pk)
    conn.execute(
        f"INSERT INTO {table} ({cols}) VALUES ({marks}) "
        f"ON CONFLICT({pk}) DO UPDATE SET {updates}",
        data,
    )


def _save_images(conn, product_id: str, p: dict) -> None:
    conn.execute("DELETE FROM shopify_images WHERE product_id=?", (product_id,))
    for pos, m in enumerate((p.get("media") or {}).get("nodes", [])):
        url = ((m.get("preview") or {}).get("image") or {}).get("url")
        if url:
            conn.execute(
                "INSERT INTO shopify_images (product_id, media_id, url, position) "
                "VALUES (?, ?, ?, ?)",
                (product_id, strip_gid(m["id"]), url, pos),
            )


def _save_variant(conn, product_id: str, v: dict) -> str:
    inv = v.get("inventoryItem") or {}
    media = (v.get("media") or {}).get("nodes") or []
    weight = (inv.get("measurement") or {}).get("weight") or {}
    variant_id = strip_gid(v["id"])
    _upsert(conn, "shopify_variants", "variant_id", {
        "variant_id": variant_id,
        "product_id": product_id,
        "title": v.get("title"),
        "upc": norm_code(_mf(v, "upc")),
        "description": _mf(v, "description"),
        "release_date": _mf(v, "release_date"),
        "variant_tags": _mf(v, "variant_tags"),
        "price": v.get("price"),
        "cost": (inv.get("unitCost") or {}).get("amount"),
        "taxable": int(bool(v.get("taxable", True))),
        "inventory_item_id": strip_gid(inv.get("id")),
        "inventory_quantity": v.get("inventoryQuantity") or 0,
        "weight": weight.get("value"),
        "weight_unit": weight.get("unit"),
        "media_id": strip_gid(media[0]["id"]) if media else None,
    })
    return variant_id


def save_shopify_product(p: dict) -> None:
    """Upsert one Shopify product node with its variants and variant images."""
    product_id = strip_gid(p["id"])
    cat = p.get("category") or {}
    with transaction() as conn:
        _upsert(conn, "shopify_products", "product_id", {
            "product_id": product_id,
            "title": p.get("title"),
            "vendor": p.get("vendor"),
            "status": p.get("status"),
            "product_type": p.get("productType"),
            "tags": ",".join(p.get("tags") or []),
            "handle": p.get("handle"),
            "category_id": strip_gid(cat.get("id")),
            "category_name": cat.get("name"),
            "genres": ",".join(split_list(_mf(p, "genres"))),
            "type": _mf(p, "type"),
            "upc": norm_code(_mf(p, "upc")),
        })
        conn.execute(
            "UPDATE shopify_products SET last_synced=datetime('now') WHERE product_id=?",
            (product_id,))
        _save_images(conn, product_id, p)
        keep = [_save_variant(conn, product_id, v)
                for v in (p.get("variants") or {}).get("nodes", [])]
        marks = ",".join("?" * len(keep))
        conn.execute(
            f"DELETE FROM shopify_variants WHERE product_id=?"
            f"{f' AND variant_id NOT IN ({marks})' if keep else ''}",
            [product_id, *keep],
        )


def _attach_images(conn, products: list[dict]) -> None:
    """Give each product its `images`; give each variant an `image_url` (via its
    media_id) and each product an `image_url` thumbnail. Call after `variants` is set."""
    if not products:
        return
    ids = [p["product_id"] for p in products]
    marks = ",".join("?" * len(ids))
    by_product = {i: [] for i in ids}
    for r in conn.execute(
        f"SELECT * FROM shopify_images WHERE product_id IN ({marks}) ORDER BY position", ids):
        by_product[r["product_id"]].append(dict(r))
    for p in products:
        images = by_product[p["product_id"]]
        urls = {img["media_id"]: img["url"] for img in images}
        for v in p["variants"]:
            v["image_url"] = urls.get(v.get("media_id"))
        p["images"] = images
        p["image_url"] = (
            next((v["image_url"] for v in p["variants"] if v["image_url"]), None)
            or (images[0]["url"] if images else None)
        )


def get_product_detail(product_id: str) -> Optional[dict]:
    conn = get_conn()
    product = row(conn.execute(
        "SELECT * FROM shopify_products WHERE product_id=?", (product_id,)).fetchone())
    if not product:
        return None
    product["variants"] = rows(conn.execute(
        "SELECT * FROM shopify_variants WHERE product_id=? ORDER BY rowid",
        (product_id,)).fetchall())
    _attach_images(conn, [product])
    return product


def count_products() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM shopify_products").fetchone()[0]


def list_products(
    search: str = "",
    page: int = 1,
    per_page: int = 50,
    sort: str = "title",
    direction: str = "asc",
    filters: Optional[dict[str, list[str]]] = None,
) -> dict:
    conn = get_conn()
    filters = filters or {}
    clauses: list[str] = []
    params: list = []

    if search:
        like = f"%{search}%"
        clauses.append("""(title LIKE ? OR vendor LIKE ? OR product_id IN (
            SELECT product_id FROM shopify_variants
            WHERE upc LIKE ?))""")
        params += [like] * 3
    for key, col in TEXT_FILTERS.items():
        for term in filters.get(key, []):
            clauses.append(f"{col} LIKE ?")
            params.append(f"%{term}%")
    for key, col in VALUE_FILTERS.items():
        vals = filters.get(key)
        if vals:
            clauses.append(f"{col} IN ({','.join('?' * len(vals))})")
            params += vals
    for key, col in LIST_FILTERS.items():
        vals = filters.get(key)
        if vals:
            clauses.append(
                "(" + " OR ".join(f"instr(',' || {col} || ',', ?) > 0" for _ in vals) + ")")
            params += [f",{v}," for v in vals]

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = SORT_COLUMNS.get(sort, SORT_COLUMNS["title"])
    order_dir = "DESC" if direction == "desc" else "ASC"

    total = conn.execute(
        f"SELECT COUNT(*) FROM shopify_products {where}", params).fetchone()[0]
    items = rows(conn.execute(
        f"SELECT * FROM shopify_products {where} "
        f"ORDER BY {order} {order_dir}, product_id LIMIT ? OFFSET ?",
        [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())

    if items:
        ids = [p["product_id"] for p in items]
        marks = ",".join("?" * len(ids))
        variants = rows(conn.execute(
            f"SELECT * FROM shopify_variants WHERE product_id IN ({marks}) ORDER BY rowid",
            ids).fetchall())
        by_product = {i: [] for i in ids}
        for v in variants:
            by_product[v["product_id"]].append(v)
        for p in items:
            p["variants"] = by_product[p["product_id"]]
        _attach_images(conn, items)
    return {"items": items, "total": total}


def get_filter_options() -> dict[str, list[str]]:
    conn = get_conn()

    def distinct(col: str) -> list[str]:
        return [r[0] for r in conn.execute(
            f"SELECT DISTINCT {col} FROM shopify_products "
            f"WHERE {col} IS NOT NULL AND {col} != '' ORDER BY {col} COLLATE NOCASE")]

    def tokens(col: str) -> list[str]:
        found: set[str] = set()
        for (value,) in conn.execute(
            f"SELECT DISTINCT {col} FROM shopify_products "
            f"WHERE {col} IS NOT NULL AND {col} != ''"):
            found.update(split_list(value))
        return sorted(found, key=str.lower)

    return {
        "status": distinct("status"),
        "category": distinct("category_name"),
        "type": distinct("type"),
        "genres": tokens("genres"),
        "tags": tokens("tags"),
    }


def update_local(product_id: str, product: dict, variants: list[dict]) -> None:
    """Mirror a successful Shopify edit into the local cache."""
    with transaction() as conn:
        p = {k: product[k] for k in _P_COLS if k in product}
        for k in ("tags", "genres"):
            if k in product:
                p[k] = ",".join(product[k])
        if p:
            sets = ", ".join(f"{k}=?" for k in p)
            conn.execute(
                f"UPDATE shopify_products SET {sets} WHERE product_id=?",
                [*p.values(), product_id],
            )
        for v in variants:
            cols = {k: v[k] for k in _V_COLS if k in v}
            if "weight" in v:
                cols["weight_unit"] = "POUNDS"
            if cols:
                sets = ", ".join(f"{k}=?" for k in cols)
                conn.execute(
                    f"UPDATE shopify_variants SET {sets} WHERE variant_id=?",
                    [*cols.values(), v["id"]],
                )