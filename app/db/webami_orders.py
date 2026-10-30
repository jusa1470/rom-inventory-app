from app.db.connection import get_conn, rows, transaction


def get_known_order_guids() -> set[str]:
    return {r[0] for r in get_conn().execute("SELECT guid FROM webami_orders")}


def save_order(order: dict, items: list[dict]) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO webami_orders (guid, number, name, submitted_at, sku_count) "
            "VALUES (?, ?, ?, ?, ?) ON CONFLICT(guid) DO UPDATE SET "
            "number=excluded.number, name=excluded.name, submitted_at=excluded.submitted_at, "
            "sku_count=excluded.sku_count, last_synced=datetime('now')",
            (order["guid"], order["number"], order["name"], order["submitted_at"], order["sku_count"]),
        )
        conn.execute("DELETE FROM webami_order_items WHERE order_guid=?", (order["guid"],))
        conn.executemany(
            "INSERT INTO webami_order_items "
            "(order_guid, position, upc, sku, href, format, title, artist, quantity, price) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(order["guid"], i["position"], i["upc"], i["sku"], i["href"], i["format"],
              i["title"], i["artist"], i["quantity"], i["price"]) for i in items],
        )
        conn.execute(
            "UPDATE webami_order_items SET product_id = COALESCE("
            "(SELECT product_id FROM webami_product_ids WHERE kind='upc' AND value=webami_order_items.upc),"
            "(SELECT product_id FROM webami_product_ids WHERE kind='sku' AND value=webami_order_items.sku)) "
            "WHERE order_guid=? AND product_id IS NULL",
            (order["guid"],),
        )


def list_webami_orders(search: str = "", page: int = 1, per_page: int = 50) -> dict:
    conn = get_conn()
    where, params = "", []
    if search:
        like = f"%{search}%"
        where = ("WHERE number LIKE ? OR name LIKE ? OR guid IN ("
                 "SELECT order_guid FROM webami_order_items "
                 "WHERE upc LIKE ? OR title LIKE ? OR artist LIKE ?)")
        params = [like] * 5
    total = conn.execute(f"SELECT COUNT(*) FROM webami_orders {where}", params).fetchone()[0]
    items = rows(conn.execute(
        f"SELECT o.*, (SELECT COALESCE(SUM(quantity),0) FROM webami_order_items i "
        f"WHERE i.order_guid=o.guid) AS total_qty FROM webami_orders o {where} "
        f"ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
        [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())
    return {"items": items, "total": total}


def get_webami_order(guid: str):
    conn = get_conn()
    order = conn.execute("SELECT * FROM webami_orders WHERE guid=?", (guid,)).fetchone()
    if not order:
        return None
    order = dict(order)
    order["items"] = rows(conn.execute(
        "SELECT * FROM webami_order_items WHERE order_guid=? ORDER BY position",
        (guid,)).fetchall())
    return order


def get_webami_stats() -> dict:
    c = get_conn()
    one = lambda sql: c.execute(sql).fetchone()[0]
    return {
        "orders": one("SELECT COUNT(*) FROM webami_orders"),
        "items": one("SELECT COUNT(*) FROM webami_order_items"),
        "products": one("SELECT COUNT(*) FROM webami_products"),
        "last_sync": one("SELECT MAX(created_at) FROM sync_log "
                         "WHERE action='webami_sync' AND status='done'"),
    }