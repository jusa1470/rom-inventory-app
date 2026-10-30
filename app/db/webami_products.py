import re

from app.db.connection import get_conn, rows, transaction

_COLS = ("title", "artist", "vendor", "product_type", "sku", "upc",
         "price", "your_price", "wmsid")


def norm(s) -> str:
    s = re.sub(r"[\[\(]\s*explicit( content)?\s*[\]\)]", " ", s or "", flags=re.I)
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def fingerprint(d: dict) -> str:
    return "|".join(norm(d.get(k)) for k in ("title", "artist", "vendor", "product_type"))


def get_unresolved_items() -> list[dict]:
    return rows(get_conn().execute(
        "SELECT upc, sku, href, title, artist, format, price FROM webami_order_items "
        "WHERE product_id IS NULL AND upc IS NOT NULL GROUP BY upc").fetchall())


def save_webami_product(data: dict, extra_ids=(), update: bool = True) -> int:
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
        if pid is None:
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
    return pid