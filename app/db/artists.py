import re

from app.db.connection import get_conn, rows, transaction
from app.webami.webami_helper import norm


def list_aliases() -> list[dict]:
    return rows(get_conn().execute(
        "SELECT alias, canonical FROM artist_aliases "
        "ORDER BY canonical COLLATE NOCASE, alias COLLATE NOCASE").fetchall())


def alias_map() -> dict[str, str]:
    return {r[0]: r[1] for r in get_conn().execute(
        "SELECT alias_norm, canonical FROM artist_aliases")}


def canon(name, amap: dict | None = None) -> str:
    amap = alias_map() if amap is None else amap
    return amap.get(key(name), (name or "").strip())


def add_alias(alias: str, canonical: str) -> None:
    a, c = key(alias), (canonical or "").strip()
    if not a or not c or a == c:
        raise ValueError("Alias and canonical name must differ")
    with transaction() as conn:
        conn.execute("INSERT OR REPLACE INTO artist_aliases (alias_norm, alias, canonical) "
                     "VALUES (?,?,?)", (a, alias.strip(), c))


def remove_alias(alias: str) -> None:
    with transaction() as conn:
        conn.execute("DELETE FROM artist_aliases WHERE alias_norm=?", (key(alias),))


def key(s) -> str:
    """Case/space-insensitive, keeps symbols (& vs +)."""
    return re.sub(r"\s+", " ", (s or "").strip())


def vendor_changes() -> list[dict]:
    amap = alias_map()
    out = []
    for r in get_conn().execute("SELECT product_id, title, vendor FROM shopify_products"):
        new = amap.get(key(r["vendor"]))
        if new and new != r["vendor"]:
            out.append({"product_id": r["product_id"], "title": r["title"],
                        "vendor": r["vendor"], "new_vendor": new})
    return out


def alias_for(name, amap: dict | None = None) -> str | None:
    amap = alias_map() if amap is None else amap
    return amap.get(key(name))


def mismatches() -> list[dict]:
    amap = alias_map()
    ign = {(r[0], r[1]) for r in get_conn().execute(
        "SELECT vendor_key, artist_key FROM mismatch_ignored")}
    out, seen = [], set()
    for r in get_conn().execute(
            "SELECT p.product_id, p.title, p.vendor, w.artist FROM shopify_variants v "
            "JOIN shopify_products p ON p.product_id=v.product_id "
            "JOIN webami_products w ON w.upc=v.upc "
            "WHERE v.upc!='' AND COALESCE(w.artist,'')!='' AND COALESCE(p.vendor,'')!=''"):
        pair = (key(r["vendor"]), key(r["artist"]))
        if pair in seen or key(canon(r["vendor"], amap)) == key(canon(r["artist"], amap)):
            continue
        seen.add(pair)
        out.append({"title": r["title"], "vendor": r["vendor"], "artist": r["artist"],
                    "ignored": pair in ign})
    return out


def set_ignored(vendor: str, artist: str, ignored: bool) -> None:
    with transaction() as conn:
        if ignored:
            conn.execute("INSERT OR IGNORE INTO mismatch_ignored VALUES (?,?)",
                         (key(vendor), key(artist)))
        else:
            conn.execute("DELETE FROM mismatch_ignored WHERE vendor_key=? AND artist_key=?",
                         (key(vendor), key(artist)))