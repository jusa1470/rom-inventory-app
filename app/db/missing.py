from app.db.connection import get_conn, rows

_E = lambda c: f"COALESCE(TRIM({c}),'')=''"
_NUM = lambda c: f"COALESCE(CAST({c} AS REAL),0)<=0"
FIELDS = {
    "products": {
        "vendor": _E("p.vendor"), "product_type": _E("p.product_type"),
        "type": _E("p.type"), "genres": _E("p.genres"), "category": _E("p.category_id"),
    },
    "variants": {
        "image": "NOT EXISTS (SELECT 1 FROM shopify_images i WHERE i.product_id=v.product_id "
                 "AND i.media_id=v.media_id AND COALESCE(i.url,'')!='')",
        "price": _NUM("v.price"), "cost": _NUM("v.cost"), "weight": _NUM("v.weight"),
        "release_date": _E("v.release_date"), "upc": _E("v.upc"),
    },
}


def list_missing(kind: str, fields: list[str], q: str = "", page: int = 1, per_page: int = 50) -> dict:
    conn = get_conn()
    flags = FIELDS[kind]
    use = [f for f in fields if f in flags] or list(flags)
    sel = ", ".join(f"({flags[f]}) AS {f}" for f in flags)
    where = "(" + " OR ".join(flags[f] for f in use) + ")"
    params: list = []
    if q:
        where += " AND (p.title LIKE ? OR p.vendor LIKE ?)"
        params = [f"%{q}%"] * 2
    if kind == "products":
        frm = "FROM shopify_products p"
        cols = "p.product_id, p.title, p.vendor, NULL AS variant_id, NULL AS variant_title"
        order = "p.title COLLATE NOCASE"
    else:
        frm = "FROM shopify_variants v JOIN shopify_products p ON p.product_id=v.product_id"
        cols = "p.product_id, p.title, p.vendor, v.variant_id, v.title AS variant_title"
        order = "p.title COLLATE NOCASE, v.rowid"
    total = conn.execute(f"SELECT COUNT(*) {frm} WHERE {where}", params).fetchone()[0]
    items = rows(conn.execute(
        f"SELECT {cols}, {sel} {frm} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())
    for r in items:
        r["missing"] = [f for f in flags if r.pop(f)]
    return {"items": items, "total": total}