from app import config
from app.db.artists import canon
from app.db.connection import get_conn, rows, transaction
from app.db.prices import sell_price
from app.webami.webami_classify import suggest_parts, variant_title
from app.webami.webami_helper import SHOPIFY_TYPE, to_lbs

_E = lambda c: f"COALESCE(TRIM({c}),'')=''"
_NUM = lambda c: f"COALESCE(CAST({c} AS REAL),0)<=0"
FIELDS = {
    "products": {
        "title": _E("p.title"), "vendor": _E("p.vendor"), "product_type": _E("p.product_type"),
        "type": _E("p.type"), "genres": _E("p.genres"), "category": _E("p.category_id"),
    },
    "variants": {
        "title": "COALESCE(TRIM(v.title),'') IN ('','Default Title')",
        "image": "NOT EXISTS (SELECT 1 FROM shopify_images i WHERE i.product_id=v.product_id "
                 "AND i.media_id=v.media_id AND COALESCE(i.url,'')!='')",
        "price": _NUM("v.price"), "cost": _NUM("v.cost"), "weight": _NUM("v.weight"),
        "release_date": _E("v.release_date"), "upc": _E("v.upc"),
        "description": _E("v.description"),
    },
}
OPTIONAL = {"description"}  # only checked when explicitly selected


def _wm(c, upc):
    r = (c.execute("SELECT * FROM webami_products WHERE upc=? LIMIT 1", (upc,)).fetchone()
         or c.execute("SELECT w.* FROM webami_products w JOIN webami_product_ids i "
                      "ON i.product_id=w.id WHERE i.kind='upc' AND i.value=? LIMIT 1",
                      (upc,)).fetchone())
    return dict(r) if r else None


def _sug(kind, w):
    s = suggest_parts(w)
    fmt = (config.type_for_format(w.get("product_type"))
           or SHOPIFY_TYPE.get((w.get("product_type") or "").strip().lower(), ""))
    cat = config.category(fmt) or {}
    cost = w.get("price")
    if kind == "products":
        d = {"title": s["title"], "vendor": canon(w.get("artist") or w.get("vendor")),
             "product_type": cat.get("product_type"), "type": fmt, "category": cat.get("category"),
             "genres": ", ".join(g for g in (w.get("genres") or "").split(",") if g)}
    else:
        d = {"title": variant_title(s), "image": w.get("image_url"),
             "release_date": w.get("release_date"), "upc": w.get("upc"),
             "description": w.get("description"),
             "cost": None if cost is None else f"{cost:.2f}",
             "price": None if cost is None else f"{sell_price(cost):.2f}",
             "weight": to_lbs(w.get("weight"), w.get("weight_unit"))}
    return {k: str(v) for k, v in d.items() if v not in (None, "", 0)}


def list_missing(kind: str, fields: list[str], q: str = "", page: int = 1,
                 per_page: int = 50, review: bool = False) -> dict:
    conn = get_conn()
    flags = FIELDS[kind]
    use = [f for f in fields if f in flags] or [f for f in flags if f not in OPTIONAL]
    sel = ", ".join(f"({flags[f]}) AS f_{f}" for f in flags)
    where = "(" + " OR ".join(flags[f] for f in use) + ")"
    params: list = []
    if q:
        where += " AND (p.title LIKE ? OR p.vendor LIKE ?)"
        params = [f"%{q}%"] * 2
    idc = "p.product_id" if kind == "products" else "v.variant_id"
    if review:
        where += f" AND EXISTS (SELECT 1 FROM missing_review m WHERE m.kind=? AND m.id={idc})"
        params.append(kind)
    if kind == "products":
        frm = "FROM shopify_products p"
        cols = ("p.product_id AS id, p.product_id, p.title, p.vendor, NULL AS variant_id, "
                "NULL AS variant_title, p.type AS ptype, p.product_type AS pptype, "
                "(SELECT x.upc FROM shopify_variants x WHERE x.product_id=p.product_id "
                "AND COALESCE(x.upc,'')!='' LIMIT 1) AS u")
        order = "p.title COLLATE NOCASE"
    else:
        frm = "FROM shopify_variants v JOIN shopify_products p ON p.product_id=v.product_id"
        cols = ("v.variant_id AS id, p.product_id, p.title, p.vendor, v.variant_id, "
                "v.title AS variant_title, p.type AS ptype, p.product_type AS pptype, v.upc AS u")
        order = "p.title COLLATE NOCASE, v.rowid"
    total = conn.execute(f"SELECT COUNT(*) {frm} WHERE {where}", params).fetchone()[0]
    items = rows(conn.execute(
        f"SELECT {cols}, {sel} {frm} WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())
    staged: dict = {}
    for r in conn.execute("SELECT id, field, value FROM missing_queue WHERE kind=?", (kind,)):
        staged.setdefault(r["id"], {})[r["field"]] = r["value"]
    revs = {r[0] for r in conn.execute("SELECT id FROM missing_review WHERE kind=?", (kind,))}
    idx = None
    for r in items:
        r["missing"] = [f for f in flags if r.pop(f"f_{f}")]
        ptype, pptype, u = r.pop("ptype"), r.pop("pptype"), r.pop("u")
        w = _wm(conn, u) if u else None
        if w is None and kind == "variants":
            from app.db.webami_products import _index, suggest_local
            idx = idx or _index()
            c = suggest_local({"title": r["title"], "vendor": r["vendor"] or "", "type": ptype,
                               "product_type": pptype, "variant_title": r["variant_title"]}, idx)
            w = c[0] if c else None
        r["suggest"] = {k: v for k, v in (_sug(kind, w) if w else {}).items()
                        if k in r["missing"]}
        r["staged"] = staged.get(r["id"], {})
        r["review"] = r["id"] in revs
    return {"items": items, "total": total}


def mq_set(items: list[dict]) -> None:
    with transaction() as c:
        c.executemany(
            "INSERT INTO missing_queue (kind,id,field,value) VALUES (?,?,?,?) "
            "ON CONFLICT(kind,id,field) DO UPDATE SET value=excluded.value",
            [(i["kind"], i["id"], i["field"], i["value"]) for i in items])


def mq_remove(items: list[dict]) -> None:
    with transaction() as c:
        for i in items:
            if i.get("field"):
                c.execute("DELETE FROM missing_queue WHERE kind=? AND id=? AND field=?",
                          (i["kind"], i["id"], i["field"]))
            else:
                c.execute("DELETE FROM missing_queue WHERE kind=? AND id=?", (i["kind"], i["id"]))


def mq_review(kind: str, ids: list[str], on: bool) -> None:
    with transaction() as c:
        for i in ids:
            if on:
                c.execute("INSERT OR IGNORE INTO missing_review (kind,id) VALUES (?,?)", (kind, i))
            else:
                c.execute("DELETE FROM missing_review WHERE kind=? AND id=?", (kind, i))


def mq_list() -> list[dict]:
    return rows(get_conn().execute(
        "SELECT q.kind, q.id, q.field, q.value, "
        "CASE q.kind WHEN 'products' THEN p.title ELSE pv.title END AS title, "
        "CASE q.kind WHEN 'products' THEN p.vendor ELSE pv.vendor END AS vendor, "
        "v.title AS variant_title, COALESCE(v.product_id, p.product_id) AS product_id "
        "FROM missing_queue q "
        "LEFT JOIN shopify_products p ON q.kind='products' AND p.product_id=q.id "
        "LEFT JOIN shopify_variants v ON q.kind='variants' AND v.variant_id=q.id "
        "LEFT JOIN shopify_products pv ON pv.product_id=v.product_id "
        "ORDER BY title COLLATE NOCASE, q.id").fetchall())