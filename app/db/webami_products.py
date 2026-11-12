"""WebAMI product storage and Shopify match suggestions (DB layer)."""
from difflib import SequenceMatcher
import logging

from app import config, db
from app.db.artists import alias_for, alias_map, canon, key
from app.db.connection import get_conn, rows, transaction
from app.webami.webami_classify import kw_eval, suggest_parts
from app.webami.webami_helper import (
    _COLS, fingerprint, format_ok, norm, simplify, tokens)

logger: logging.Logger = logging.getLogger(__name__)
_cache: dict = {"key": None, "data": None}


def _variants(conn, product_id: str) -> list[dict]:
    return rows(conn.execute(
        "SELECT variant_id, title, upc, inventory_quantity FROM shopify_variants "
        "WHERE product_id=? ORDER BY rowid", (product_id,)).fetchall())

# ── similarity ───────────────────────────────────────────────────────

def sim(a, b) -> float:
    a, b = norm(a), norm(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def good_match(s_title, s_vendor, w_title, w_artist) -> bool:
    return (sim(simplify(s_title), simplify(w_title)) >= config.WEBAMI_MATCH_MIN
            and sim(s_vendor, w_artist) >= config.WEBAMI_MATCH_MIN)


# ── order item resolution / product storage ──────────────────────────

def get_unresolved_items() -> list[dict]:
    return rows(get_conn().execute(
        "SELECT upc, sku, href, title, artist, format, price FROM webami_order_items "
        "WHERE product_id IS NULL GROUP BY COALESCE(upc, sku, href) "
        "UNION ALL "
        "SELECT p.upc, p.sku, p.href, p.title, p.artist, p.product_type AS format, p.price "
        "FROM webami_products p WHERE p.stale=1").fetchall())


def save_webami_product(data: dict, extra_ids=(), update: bool = True,
                        use_fingerprint: bool = False) -> int:
    """Find (by wmsid/upc/sku alias, then fingerprint if allowed) or create the product;
    record all ids as aliases and link matching order items."""
    ids = [("wmsid", data.get("wmsid")), ("upc", data.get("upc")),
           ("sku", data.get("sku")), *extra_ids]
    ids = [(k, v) for k, v in ids if v]
    fp = fingerprint(data)
    with transaction() as conn:
        pid = None
        for kind, val in ids:
            r = conn.execute(
                "SELECT product_id FROM webami_product_ids WHERE kind=? AND value=?",
                (kind, val)).fetchone()
            if r:
                pid = r[0]
                break
        if pid is None and use_fingerprint:
            r = conn.execute(
                "SELECT id FROM webami_products WHERE fingerprint=?", (fp,)).fetchone()
            pid = r[0] if r else None
        if pid is None:
            cur = conn.execute(
                f"INSERT INTO webami_products (fingerprint, {', '.join(_COLS)}) "
                f"VALUES (?{', ?' * len(_COLS)})",
                [fp, *[data.get(c) for c in _COLS]])
            pid = cur.lastrowid
        elif update:
            vals = {c: data[c] for c in _COLS if data.get(c) is not None}
            if vals:
                sets = ", ".join(f"{k}=?" for k in vals)
                conn.execute(
                    f"UPDATE webami_products SET {sets}, last_synced=datetime('now') WHERE id=?",
                    [*vals.values(), pid])
        for kind, val in ids:
            conn.execute(
                "INSERT INTO webami_product_ids (product_id, kind, value) VALUES (?, ?, ?) "
                "ON CONFLICT(kind, value) DO UPDATE SET last_seen=datetime('now')",
                (pid, kind, val))
            if kind in ("upc", "sku"):
                conn.execute(
                    f"UPDATE webami_order_items SET product_id=? "
                    f"WHERE product_id IS NULL AND {kind}=?", (pid, val))
        conn.execute("UPDATE webami_products SET stale=0 WHERE id=?", (pid,))
    return pid


def get_webami_product_by_id(product_id: int):
    conn = get_conn()
    p = conn.execute("SELECT * FROM webami_products WHERE id=?", (product_id,)).fetchone()
    if not p:
        return None
    p = dict(p)
    p["ids"] = rows(conn.execute(
        "SELECT kind, value, first_seen, last_seen FROM webami_product_ids "
        "WHERE product_id=? ORDER BY kind, first_seen", (product_id,)).fetchall())
    return p


def reset_webami_products() -> None:
    with transaction() as conn:
        conn.execute("UPDATE webami_order_items SET product_id = NULL")
        conn.execute("DELETE FROM webami_product_ids")
        conn.execute("DELETE FROM webami_products")


# ── local suggestions (from synced WebAMI products) ──────────────────

def _index() -> dict:
    """artist token -> list of WebAMI products."""
    idx: dict[str, list[dict]] = {}
    for w in rows(get_conn().execute(
            "SELECT id, title, artist, vendor, product_type, upc, sku, price, your_price, "
            "href, wmsid, features, description, release_date, weight, weight_unit, image_url, genres "
            "FROM webami_products "
            "WHERE upc IS NOT NULL AND upc != ''").fetchall()):
        for t in tokens(w["artist"]):
            idx.setdefault(t, []).append(w)
    return idx


def suggest_local(p: dict, idx: dict | None = None) -> list[dict]:
    idx = _index() if idx is None else idx
    stype = p.get("type") or p.get("product_type")
    amap = alias_map()
    pv = canon(p["vendor"], amap)
    seen, out = set(), []
    for t in tokens(p["vendor"]):
        for w in idx.get(t, []):
            if w["id"] in seen:
                continue
            seen.add(w["id"])
            wa = canon(w["artist"], amap)
            if format_ok(stype, w["product_type"]) and good_match(
                    p["title"], pv, w["title"], wa):
                missing, extra = kw_eval(p, w)
                if missing:
                    continue
                out.append({**w, "kw_extra": extra,
                            "tier": 1 if w["wmsid"] else 3,
                            "source": "orders" if w["wmsid"] else "order line only",
                            "artist_match": key(pv) == key(wa),
                            "canon_artist": alias_for(w["artist"], amap)})
    return out


# ── UPC match review list (variants without a UPC) ───────────────────

def _cache_key(q: str) -> tuple:
    c = get_conn()
    return ("variants", q,
            c.execute("SELECT COUNT(*), MAX(last_synced) FROM webami_products").fetchone()[:],
            c.execute("SELECT COUNT(*), MAX(last_synced) FROM shopify_products").fetchone()[:],
            c.execute("SELECT COUNT(*), MAX(rowid) FROM artist_aliases").fetchone()[:])


def decorate_candidates(variant_id: str, cands: list[dict]) -> None:
    """Add used_by (Shopify variants already holding this WebAMI product's UPCs) and orders."""
    conn = get_conn()
    for w in cands:
        upcs = {w["upc"]}
        if w.get("id"):
            upcs |= {r[0] for r in conn.execute(
                "SELECT value FROM webami_product_ids WHERE product_id=? AND kind='upc'",
                (w["id"],))}
        marks = ",".join("?" * len(upcs))
        w["used_by"] = rows(conn.execute(
            "SELECT p.title, v.title AS variant_title, v.variant_id FROM shopify_variants v "
            f"JOIN shopify_products p ON p.product_id=v.product_id "
            f"WHERE v.upc IN ({marks}) AND v.variant_id != ?",
            [*upcs, variant_id or ""]).fetchall())
        w["orders"] = rows(conn.execute(
            "SELECT o.number, o.submitted_at, i.quantity FROM webami_order_items i "
            "JOIN webami_orders o ON o.guid=i.order_guid WHERE i.product_id=? "
            "ORDER BY o.submitted_at DESC LIMIT 3", (w["id"],)).fetchall()) if w.get("id") else []


def _decorate_page(items: list[dict]) -> list[dict]:
    conn = get_conn()
    for p in items:
        p["siblings"] = rows(conn.execute(
            "SELECT title, upc, cost FROM shopify_variants WHERE product_id=? AND variant_id!=? "
            "ORDER BY rowid", (p["product_id"], p["variant_id"])).fetchall())
        decorate_candidates(p["variant_id"], p["suggestions"])
    return items


def is_identical(p: dict) -> bool:
    if not p["suggestions"]:
        return False
    s = p["suggestions"][0]
    sg = s["suggested"]
    n = lambda v: str(v or "").strip().lower()
    try:
        cost_ok = round(float(p["cost"]), 2) == round(float(s["price"]), 2)
    except (TypeError, ValueError):
        return False
    return (cost_ok and n(p["title"]) == n(sg["title"])
            and n(p["variant_title"]) == n(db.variant_title(sg))
            and bool(s["artist_match"])
            and format_ok(p.get("type") or p.get("product_type"), s["product_type"]))


def list_unmatched_variants(page: int = 1, per_page: int = 25, q: str = "",
                            only_suggested: bool = False, identical: bool = False) -> dict:
    conn = get_conn()
    where = ("(v.upc IS NULL OR v.upc='') "
             "AND COALESCE(p.type, p.product_type) IN ('Vinyl','CD','Cassette') "
             "AND v.variant_id NOT IN (SELECT product_id FROM upc_ignored) "
             "AND TRIM(p.title) NOT LIKE '% - U' "
             "AND (',' || LOWER(REPLACE(COALESCE(p.tags,''), ' ', '')) || ',') NOT LIKE '%,used,%'")
    params: list = []
    if q:
        where += " AND (p.title LIKE ? OR p.vendor LIKE ? OR v.title LIKE ?)"
        params = [f"%{q}%"] * 3
    sel = ("SELECT p.product_id, p.title, p.vendor, p.type, p.product_type, "
           "v.variant_id, v.title AS variant_title, v.cost, "
           "COALESCE((SELECT i.url FROM shopify_images i WHERE i.product_id=p.product_id "
           " AND i.media_id=v.media_id), (SELECT i.url FROM shopify_images i "
           " WHERE i.product_id=p.product_id ORDER BY i.position LIMIT 1)) AS image_url "
           "FROM shopify_variants v JOIN shopify_products p ON p.product_id=v.product_id "
           f"WHERE {where} ORDER BY p.vendor COLLATE NOCASE, p.title COLLATE NOCASE, v.rowid")
    idx = _index()

    def enrich(p):
        c = suggest_local(p, idx)
        c.sort(key=lambda w: (w["tier"], len(w["kw_extra"]),
                              -sim(p["title"], w["title"]) - sim(p["vendor"], w["artist"])))
        for w in c:
            w["suggested"] = suggest_parts(w)
        p["suggestions"] = c[:5]
        return p

    if only_suggested or identical:
        key = _cache_key(q)
        if _cache["key"] != key:
            _cache["data"] = [p for p in map(enrich, rows(conn.execute(sel, params).fetchall()))
                              if p["suggestions"]]
            _cache["key"] = key
        allp = _cache["data"]
        if identical:
            allp = [p for p in allp if is_identical(p)]
        return {"items": _decorate_page(allp[(max(page, 1) - 1) * per_page:][:per_page]), "total": len(allp)}
    total = conn.execute(
        "SELECT COUNT(*) FROM shopify_variants v JOIN shopify_products p "
        f"ON p.product_id=v.product_id WHERE {where}", params).fetchone()[0]
    items = rows(conn.execute(
        f"{sel} LIMIT ? OFFSET ?", [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())
    return {"items": _decorate_page([enrich(p) for p in items]), "total": total}


def drop_from_match_cache(variant_id: str) -> None:
    if _cache["data"]:
        _cache["data"] = [p for p in _cache["data"] if p["variant_id"] != variant_id]


def ignore_product(variant_id: str) -> None:
    with transaction() as conn:
        conn.execute("INSERT OR IGNORE INTO upc_ignored (product_id) VALUES (?)", (variant_id,))
    drop_from_match_cache(variant_id)


def shopify_candidates(w: dict, limit: int = 5) -> list[dict]:
    conn = get_conn()
    amap = alias_map()
    wt = w.get("product_type")
    wv = canon(w.get("artist") or w.get("vendor"), amap)
    out = []
    for p in rows(conn.execute(
            "SELECT product_id, title, vendor, type, product_type FROM shopify_products")):
        if not (tokens(p["vendor"]) & tokens(wv)):
            continue
        if not format_ok(p["type"] or p["product_type"], wt):
            continue
        ts = sim(simplify(p["title"]), simplify(w["title"]))
        vs = sim(canon(p["vendor"], amap), wv)
        if ts >= 0.6 and vs >= 0.6:
            out.append({**p, "score": ts + vs})
    out.sort(key=lambda x: -x["score"])
    out = out[:limit]
    for p in out:
        p["variants"] = _variants(conn, p["product_id"])
    return out


def search_shopify(q: str, limit: int = 15) -> list[dict]:
    conn = get_conn()
    like = f"%{q}%"
    out = rows(conn.execute(
        "SELECT product_id, title, vendor FROM shopify_products WHERE title LIKE ? OR vendor LIKE ? "
        "OR product_id IN (SELECT product_id FROM shopify_variants WHERE upc LIKE ?) "
        "ORDER BY vendor COLLATE NOCASE, title COLLATE NOCASE LIMIT ?",
        [like, like, like, limit]).fetchall())
    for p in out:
        p["variants"] = _variants(conn, p["product_id"])
    return out