from difflib import SequenceMatcher
import logging
import re

from app import config
from app.db.connection import get_conn, rows, transaction
from app.webami.webami_helper import _COLS, _FEAT, norm


logger: logging.Logger = logging.getLogger(__name__)
_cache: dict = {"key": None, "data": None}

MATCH_MIN = 0.70


def sim(a, b) -> float:
    a, b = norm(a), norm(b)
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def good_match(s_title, s_vendor, w_title, w_artist) -> bool:
    return (sim(_simplify(s_title), _simplify(w_title)) >= config.WEBAMI_MATCH_MIN
            and sim(s_vendor, w_artist) >= config.WEBAMI_MATCH_MIN)


def _tokens(s) -> set[str]:
    return {t for t in norm(s).split() if len(t) > 2}


def fingerprint(d: dict) -> str:
    return "|".join(norm(d.get(k)) for k in ("title", "artist", "vendor", "product_type"))


def get_unresolved_items() -> list[dict]:
    return rows(get_conn().execute(
        "SELECT upc, sku, href, title, artist, format, price FROM webami_order_items "
        "WHERE product_id IS NULL GROUP BY COALESCE(upc, sku, href) "
        "UNION ALL "
        "SELECT p.upc, p.sku, p.href, p.title, p.artist, p.product_type AS format, p.price "
        "FROM webami_products p WHERE p.stale=1").fetchall())


def save_webami_product(data: dict, extra_ids=(), update: bool = True, use_fingerprint: bool = False) -> int:
    """Find (by wmsid/upc/sku alias, then fingerprint) or create the product;
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
        conn.execute("UPDATE webami_products SET stale=0 WHERE id=?", (pid,))
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
                    f"UPDATE webami_products SET {sets}, stale=0, last_synced=datetime('now') WHERE id=?",
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
    return pid


def _simplify(t: str) -> str:
    return re.sub(r"[\[\(].*?[\]\)]", " ", t or "").strip()


def format_ok(shopify_type: str | None, wfmt: str | None) -> bool:
    t, f = (shopify_type or "").lower(), (wfmt or "").lower()
    if not t or not f:
        return True
    if t == "vinyl":
        return any(k in f for k in ("lp", "vinyl", "single"))
    if t == "cd":
        return f == "cd"
    if t == "cassette":
        return "cassette" in f
    return True


def suggest_title(shopify_title: str, webami_title: str, features: str | None = None, description: str | None = None) -> str:
    """Shopify title plus one (feature, feature) group from the WebAMI title."""
    w = webami_title or ""
    have = norm(shopify_title)
    feats: list[str] = []

    def add(f):
        f = re.sub(r"\s+", " ", f).strip(" -–,/")
        n = norm(f)
        if n and n not in have and n not in {norm(x) for x in feats} \
                and n not in ("explicit", "explicit content", "vinyl", "lp"):
            feats.append(f)

    stripped = re.sub(r"[\[\(][^\]\)]*[\]\)]", " ", w)
    for m in re.findall(r"[\[\(]([^\]\)]+)[\]\)]", w):
        for f in (_FEAT.findall(m) or [m]):
            add(f)
    tail = re.split(r"\s+-\s+", stripped, maxsplit=1)
    if len(tail) > 1:
        for f in (_FEAT.findall(tail[1]) or [tail[1]]):
            add(f)
    for f in _FEAT.findall(tail[0]):
        add(f)
    for chunk in re.split(r"[;,]", re.sub(r"^[\[\(]|[\]\)]$", "", (features or "").strip())):
        if "explicit" in chunk.lower() or "parental" in chunk.lower():
            continue
        for f in (_FEAT.findall(chunk) or [chunk]):
            add(f)
    for f in _FEAT.findall(description or ""):
        add(f)
    return f"{shopify_title} ({', '.join(feats)})" if feats else shopify_title


def _index() -> dict:
    """token -> list of WebAMI products (by title/artist tokens)."""
    idx: dict[str, list[dict]] = {}
    for w in rows(get_conn().execute(
            "SELECT id, title, artist, vendor, product_type, upc, sku, price, your_price, "
            "href, wmsid, features, description FROM webami_products "
            "WHERE upc IS NOT NULL AND upc != ''").fetchall()):
        w["_ta"] = norm(_simplify(w["title"]))
        w["_aa"] = norm(w["artist"])
        for t in _tokens(w["artist"]):
            idx.setdefault(t, []).append(w)
    return idx


def suggest_local(p: dict, idx: dict | None = None) -> list[dict]:
    idx = _index() if idx is None else idx
    stype = p.get("type") or p.get("product_type")
    seen, out = set(), []
    for t in _tokens(p["vendor"]):
        for w in idx.get(t, []):
            if w["id"] in seen:
                continue
            seen.add(w["id"])
            if format_ok(stype, w["product_type"]) and good_match(
                    p["title"], p["vendor"], w["title"], w["artist"]):
                out.append({**{k: v for k, v in w.items() if not k.startswith("_")},
                            "tier": 1 if w["wmsid"] else 3,
                            "source": "orders" if w["wmsid"] else "order line only",
                            "artist_match": True})
    return out


def _cache_key(q: str) -> tuple:
    c = get_conn()
    return (q,
            c.execute("SELECT COUNT(*), MAX(last_synced) FROM webami_products").fetchone()[:],
            c.execute("SELECT COUNT(*), MAX(last_synced) FROM shopify_products").fetchone()[:],
            c.execute("SELECT COUNT(*) FROM upc_ignored").fetchone()[0])


def list_unmatched(page: int = 1, per_page: int = 25, q: str = "", only_suggested: bool = False) -> dict:
    conn = get_conn()
    where = ("(p.upc IS NULL OR p.upc='') AND NOT EXISTS (SELECT 1 FROM shopify_variants v "
             "WHERE v.product_id=p.product_id AND v.upc IS NOT NULL AND v.upc != '') "
             "AND p.product_id NOT IN (SELECT product_id FROM upc_ignored) "
             "AND COALESCE(p.type, p.product_type) IN ('Vinyl','CD','Cassette') "
             "AND TRIM(p.title) NOT LIKE '%- U' AND TRIM(p.title) != '- U' "
             "AND (',' || LOWER(REPLACE(COALESCE(p.tags,''), ' ', '')) || ',') NOT LIKE '%used%'")
    params: list = []
    if q:
        where += " AND (p.title LIKE ? OR p.vendor LIKE ?)"
        params = [f"%{q}%"] * 2
    sel = (f"SELECT p.product_id, p.title, p.vendor, p.type, p.product_type, "
           f"(SELECT v.variant_id FROM shopify_variants v WHERE v.product_id=p.product_id "
           f" ORDER BY v.rowid LIMIT 1) AS variant_id, "
           f"(SELECT v.cost FROM shopify_variants v WHERE v.product_id=p.product_id "
           f" ORDER BY v.rowid LIMIT 1) AS cost "
           f"FROM shopify_products p WHERE {where} "
           f"ORDER BY p.vendor COLLATE NOCASE, p.title COLLATE NOCASE")
    idx = _index()

    def enrich(p):
        c = suggest_local(p, idx)
        c.sort(key=lambda w: (w["tier"], -sim(p["title"], w["title"]) - sim(p["vendor"], w["artist"])))
        for w in c:
            w["suggested_title"] = suggest_title(p["title"], w["title"], w.get("features"), w.get("description"))
        p["suggestions"] = c[:5]
        return p

    if only_suggested:
        key = _cache_key(q)
        if _cache["key"] != key:
            _cache["data"] = [p for p in map(enrich, rows(conn.execute(sel, params).fetchall()))
                              if p["suggestions"]]
            _cache["key"] = key
        allp = _cache["data"]
        return {"items": allp[(max(page, 1) - 1) * per_page:][:per_page], "total": len(allp)}
    total = conn.execute(
        f"SELECT COUNT(*) FROM shopify_products p WHERE {where}", params).fetchone()[0]
    items = rows(conn.execute(
        f"{sel} LIMIT ? OFFSET ?",
        [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())
    return {"items": [enrich(p) for p in items], "total": total}


def ignore_product(product_id: str) -> None:
    with transaction() as conn:
        conn.execute("INSERT OR IGNORE INTO upc_ignored (product_id) VALUES (?)", (product_id,))
    drop_from_match_cache(product_id)


def reset_webami_products() -> None:
    with transaction() as conn:
        conn.execute("UPDATE webami_order_items SET product_id = NULL")
        conn.execute("DELETE FROM webami_product_ids")
        conn.execute("DELETE FROM webami_products")


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


def drop_from_match_cache(product_id: str) -> None:
    if _cache["data"]:
        _cache["data"] = [p for p in _cache["data"] if p["product_id"] != product_id]