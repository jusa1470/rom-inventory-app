from app.db.connection import get_conn, rows, transaction

DIV = 0.66  # 34% margin: price = cost / 0.66
_FROM = ("FROM price_checks c JOIN shopify_variants v ON v.variant_id=c.variant_id "
         "JOIN shopify_products p ON p.product_id=v.product_id "
         "LEFT JOIN price_queue q ON q.variant_id=c.variant_id")
_OLD = "COALESCE(CAST(v.cost AS REAL),0)"
_TYPE = "COALESCE(p.type, p.product_type)"


def get_price_variants() -> list[dict]:
    return rows(get_conn().execute(
        f"SELECT v.variant_id, v.upc, p.title, p.vendor, {_TYPE} AS type "
        "FROM shopify_variants v JOIN shopify_products p ON p.product_id=v.product_id "
        "WHERE v.upc IS NOT NULL AND v.upc != '' AND TRIM(p.title) NOT LIKE '% - U' "
        "AND (',' || LOWER(REPLACE(COALESCE(p.tags,''),' ','')) || ',') NOT LIKE '%,used,%'"
    ).fetchall())


def save_price_check(variant_id, upc, status, wm_upc=None, wm_title=None, new_cost=None,
                     suggest_upc=None, suggest_title=None) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO price_checks (variant_id, upc, wm_upc, wm_title, new_cost, "
            "status, suggest_upc, suggest_title, checked_at) VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
            (variant_id, upc, wm_upc, wm_title, new_cost, status, suggest_upc, suggest_title))


def resolve_price_check(variant_id: str, wm_upc: str, wm_title: str, new_cost: float) -> None:
    with transaction() as conn:
        conn.execute(
            "UPDATE price_checks SET wm_upc=?, wm_title=?, new_cost=?, status='ok', "
            "suggest_upc=NULL, suggest_title=NULL, checked_at=datetime('now') WHERE variant_id=?",
            (wm_upc, wm_title, new_cost, variant_id))


def _where(f: dict):
    review = f.get("review")
    w, p = ["c.status=?"], ["review" if review else "ok"]
    if not review:
        w.append(f"ABS(c.new_cost - {_OLD}) >= 0.005")
        if bool(f.get("increase")) != bool(f.get("decrease")):
            w.append(f"c.new_cost {'>' if f.get('increase') else '<'} {_OLD}")
    if f.get("title"):
        w.append("(p.title LIKE ? OR v.title LIKE ?)")
        p += [f"%{f['title']}%"] * 2
    if f.get("vendor"):
        w.append("p.vendor LIKE ?")
        p.append(f"%{f['vendor']}%")
    if f.get("type"):
        w.append(f"{_TYPE}=?")
        p.append(f["type"])
    return " AND ".join(w), p


def list_price_changes(f: dict, page: int = 1, per_page: int = 50) -> dict:
    conn = get_conn()
    w, p = _where(f)
    total = conn.execute(f"SELECT COUNT(*) {_FROM} WHERE {w}", p).fetchone()[0]
    items = rows(conn.execute(
        f"SELECT c.variant_id, p.product_id, p.title, v.title AS variant_title, p.vendor, "
        f"{_TYPE} AS type, v.upc, CAST(v.cost AS REAL) AS old_cost, c.new_cost, "
        f"CAST(v.price AS REAL) AS old_price, ROUND(c.new_cost/{DIV},2) AS calc_price, "
        f"c.suggest_upc, c.suggest_title, (q.variant_id IS NOT NULL) AS queued "
        f"{_FROM} WHERE {w} ORDER BY p.vendor COLLATE NOCASE, p.title COLLATE NOCASE, v.rowid "
        f"LIMIT ? OFFSET ?", [*p, per_page, (max(page, 1) - 1) * per_page]).fetchall())
    return {"items": items, "total": total}


def price_queue_add(ids: list[str]) -> None:
    if not ids:
        return
    with transaction() as conn:
        conn.execute(
            f"INSERT OR IGNORE INTO price_queue (variant_id, new_price) "
            f"SELECT variant_id, ROUND(new_cost/{DIV},2) FROM price_checks "
            f"WHERE new_cost IS NOT NULL AND variant_id IN ({','.join('?' * len(ids))})", ids)


def price_queue_remove(ids: list[str]) -> None:
    if not ids:
        return
    with transaction() as conn:
        conn.execute(
            f"DELETE FROM price_queue WHERE variant_id IN ({','.join('?' * len(ids))})", ids)


def price_queue_filtered(f: dict, add: bool) -> None:
    w, p = _where({**f, "review": False})
    with transaction() as conn:
        if add:
            conn.execute(
                f"INSERT OR IGNORE INTO price_queue (variant_id, new_price) "
                f"SELECT c.variant_id, ROUND(c.new_cost/{DIV},2) {_FROM} WHERE {w}", p)
        else:
            conn.execute(
                f"DELETE FROM price_queue WHERE variant_id IN (SELECT c.variant_id {_FROM} WHERE {w})", p)


def price_queue_set(variant_id: str, price: float) -> None:
    with transaction() as conn:
        conn.execute("UPDATE price_queue SET new_price=? WHERE variant_id=?", (price, variant_id))


def list_price_queue() -> list[dict]:
    return rows(get_conn().execute(
        f"SELECT q.variant_id, p.product_id, p.title, v.title AS variant_title, p.vendor, v.upc, "
        f"CAST(v.cost AS REAL) AS old_cost, c.new_cost, CAST(v.price AS REAL) AS old_price, "
        f"q.new_price FROM price_queue q JOIN price_checks c ON c.variant_id=q.variant_id "
        f"JOIN shopify_variants v ON v.variant_id=q.variant_id "
        f"JOIN shopify_products p ON p.product_id=v.product_id "
        f"ORDER BY p.vendor COLLATE NOCASE, p.title COLLATE NOCASE").fetchall())


def sell_price(cost: float) -> float:
    return round(cost / DIV, 2)