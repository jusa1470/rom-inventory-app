from typing import Optional

from app.db.connection import get_conn, row, rows, strip_gid, transaction


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


def _save_variant(conn, product_id: str, v: dict) -> str:
    inv = v.get("inventoryItem") or {}
    weight = (inv.get("measurement") or {}).get("weight") or {}
    variant_id = strip_gid(v["id"])
    _upsert(conn, "shopify_variants", "variant_id", {
        "variant_id": variant_id,
        "product_id": product_id,
        "title": v.get("title"),
        "barcode": v.get("barcode"),
        "sku": v.get("sku"),
        "upc": _mf(v, "upc"),
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
    })
    conn.execute("DELETE FROM shopify_images WHERE variant_id=?", (variant_id,))
    for pos, m in enumerate((v.get("media") or {}).get("nodes", [])):
        url = ((m.get("preview") or {}).get("image") or {}).get("url")
        if url:
            conn.execute(
                "INSERT INTO shopify_images (variant_id, media_id, url, position) "
                "VALUES (?, ?, ?, ?)",
                (variant_id, strip_gid(m.get("id")), url, pos),
            )
    return variant_id


def save_product(p: dict) -> None:
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
            "genres": _mf(p, "genres"),
            "type": _mf(p, "type"),
        })
        conn.execute(
            "UPDATE shopify_products SET last_synced=datetime('now') WHERE product_id=?",
            (product_id,))
        keep = [_save_variant(conn, product_id, v)
                for v in (p.get("variants") or {}).get("nodes", [])]
        marks = ",".join("?" * len(keep))
        conn.execute(
            f"DELETE FROM shopify_variants WHERE product_id=?"
            f"{f' AND variant_id NOT IN ({marks})' if keep else ''}",
            [product_id, *keep],
        )


def _attach_images(conn, variants: list[dict]) -> None:
    if not variants:
        return
    ids = [v["variant_id"] for v in variants]
    by_variant = {i: [] for i in ids}
    marks = ",".join("?" * len(ids))
    for r in conn.execute(
        f"SELECT * FROM shopify_images WHERE variant_id IN ({marks}) ORDER BY position", ids):
        by_variant[r["variant_id"]].append(dict(r))
    for v in variants:
        v["images"] = by_variant[v["variant_id"]]


def get_product_detail(product_id: str) -> Optional[dict]:
    conn = get_conn()
    product = row(conn.execute(
        "SELECT * FROM shopify_products WHERE product_id=?", (product_id,)).fetchone())
    if not product:
        return None
    product["variants"] = rows(conn.execute(
        "SELECT * FROM shopify_variants WHERE product_id=? ORDER BY rowid",
        (product_id,)).fetchall())
    _attach_images(conn, product["variants"])
    return product


def count_products() -> int:
    return get_conn().execute("SELECT COUNT(*) FROM shopify_products").fetchone()[0]


def list_products(search: str = "", page: int = 1, per_page: int = 50) -> dict:
    conn = get_conn()
    where, params = "", []
    if search:
        like = f"%{search}%"
        where = """WHERE title LIKE ? OR vendor LIKE ? OR product_id IN (
            SELECT product_id FROM shopify_variants
            WHERE upc LIKE ? OR barcode LIKE ? OR sku LIKE ?)"""
        params = [like] * 5

    total = conn.execute(
        f"SELECT COUNT(*) FROM shopify_products {where}", params).fetchone()[0]
    items = rows(conn.execute(
        f"SELECT * FROM shopify_products {where} "
        f"ORDER BY title COLLATE NOCASE, product_id LIMIT ? OFFSET ?",
        [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())

    if items:
        ids = [p["product_id"] for p in items]
        marks = ",".join("?" * len(ids))
        variants = rows(conn.execute(
            f"SELECT * FROM shopify_variants WHERE product_id IN ({marks}) ORDER BY rowid",
            ids).fetchall())
        _attach_images(conn, variants)
        by_product = {i: [] for i in ids}
        for v in variants:
            by_product[v["product_id"]].append(v)
        for p in items:
            p["variants"] = by_product[p["product_id"]]
            p["image_url"] = next(
                (img["url"] for v in p["variants"] for img in v["images"]), None)
    return {"items": items, "total": total}