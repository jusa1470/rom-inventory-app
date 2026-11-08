from app.db.connection import get_conn, row, rows, transaction


_ITEM_SORT = {
    "position": "position", "title": "title COLLATE NOCASE", "artist": "artist COLLATE NOCASE",
    "format": "format COLLATE NOCASE", "upc": "upc", "qty": "quantity", "price": "price",
    "received": "received", "left": "(quantity - received)",
}


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
        conn.execute(
            "UPDATE webami_products SET stale=1 WHERE id IN ("
            "SELECT product_id FROM webami_order_items WHERE order_guid=? AND product_id IS NOT NULL)",
            (order["guid"],))


def list_webami_orders(search: str = "", page: int = 1, per_page: int = 50, status: str = "") -> dict:
    conn = get_conn()
    where, params = "", []
    if search:
        like = f"%{search}%"
        where = ("WHERE number LIKE ? OR name LIKE ? OR guid IN ("
                 "SELECT order_guid FROM webami_order_items "
                 "WHERE upc LIKE ? OR title LIKE ? OR artist LIKE ?)")
        params = [like] * 5
    inner = (
        "SELECT o.*, "
        "(SELECT COALESCE(SUM(quantity),0) FROM webami_order_items i WHERE i.order_guid=o.guid) AS total_qty, "
        "(SELECT COALESCE(SUM(qty),0) FROM receipts r WHERE r.order_guid=o.guid AND r.reversed_at IS NULL) AS received "
        f"FROM webami_orders o {where}")
    sql = ("SELECT * FROM (SELECT *, CASE WHEN received<=0 THEN 'open' "
           "WHEN received>=total_qty THEN 'complete' ELSE 'partial' END AS status "
           f"FROM ({inner}))")
    if status == "outstanding":
        sql += " WHERE status!='complete'"
    elif status in ("open", "partial", "complete"):
        sql += f" WHERE status='{status}'"
    total = conn.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    items = rows(conn.execute(
        f"{sql} ORDER BY submitted_at DESC LIMIT ? OFFSET ?",
        [*params, per_page, (max(page, 1) - 1) * per_page]).fetchall())
    return {"items": items, "total": total}


def get_webami_order(guid: str, q: str = "", sort: str = "position",
                     direction: str = "asc", only: str = ""):
    conn = get_conn()
    order = conn.execute("SELECT * FROM webami_orders WHERE guid=?", (guid,)).fetchone()
    if not order:
        return None
    order = dict(order)
    order["items"] = rows(conn.execute(
        "SELECT i.*, COALESCE((SELECT SUM(qty) FROM receipts r WHERE r.order_guid=i.order_guid "
        "AND r.upc=i.upc AND r.reversed_at IS NULL),0) AS received, "
        "COALESCE((SELECT qty FROM receipt_queue q WHERE q.order_guid=i.order_guid "
        "AND q.upc=i.upc),0) AS queued, "
        "(SELECT variant_id FROM shopify_variants v WHERE v.upc=i.upc LIMIT 1) AS variant_id "
        "FROM webami_order_items i WHERE i.order_guid=? ORDER BY position",
        (guid,)).fetchall())
    if q:
        ql = q.lower()
        order["items"] = [i for i in order["items"] if ql in " ".join(
            str(i.get(k) or "") for k in ("title", "artist", "upc", "sku")).lower()]
    if only == "outstanding":
        order["items"] = [i for i in order["items"] if i["received"] < i["quantity"]]
    elif only == "new":
        order["items"] = [i for i in order["items"] if not i["variant_id"]]
    elif only == "received":
        order["items"] = [i for i in order["items"] if i["received"] >= i["quantity"]]
    key = sort if sort in _ITEM_SORT else "position"
    def k(i):
        v = {"qty": i["quantity"], "left": i["quantity"] - i["received"]}.get(key, i.get(key))
        return (v is None, v.lower() if isinstance(v, str) else v)
    order["items"].sort(key=k, reverse=direction == "desc")
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


def get_incomplete_order_guids() -> set[str]:
    """Orders whose stored item rows don't match the list page's #SKUs."""
    return {r[0] for r in get_conn().execute(
        "SELECT o.guid FROM webami_orders o "
        "LEFT JOIN webami_order_items i ON i.order_guid = o.guid "
        "GROUP BY o.guid HAVING COUNT(i.id) != o.sku_count")}


def get_variant_by_upc(upc: str):
    return row(get_conn().execute(
        "SELECT variant_id, product_id, inventory_item_id, inventory_quantity "
        "FROM shopify_variants WHERE upc=? LIMIT 1", (upc,)).fetchone())


def log_receipt(guid: str, upc: str, qty: int, variant_id) -> None:
    with transaction() as conn:
        conn.execute("INSERT INTO receipts (order_guid, upc, qty, variant_id) VALUES (?,?,?,?)",
                     (guid, upc, qty, variant_id))


def get_variant(variant_id: str):
    return row(get_conn().execute(
        "SELECT v.variant_id, v.product_id, v.inventory_item_id, v.inventory_quantity, v.upc, "
        "v.title AS variant_title, CAST(v.cost AS REAL) AS cost, p.title AS product_title "
        "FROM shopify_variants v JOIN shopify_products p ON p.product_id=v.product_id "
        "WHERE v.variant_id=?", (variant_id,)).fetchone())


def get_receipt(rid: int):
    return row(get_conn().execute("SELECT * FROM receipts WHERE id=?", (rid,)).fetchone())


def reverse_receipt(rid: int) -> None:
    with transaction() as conn:
        conn.execute("UPDATE receipts SET reversed_at=datetime('now') WHERE id=?", (rid,))


def list_order_receipts(guid: str) -> list[dict]:
    return rows(get_conn().execute(
        "SELECT r.id, r.upc, r.qty, r.created_at, r.reversed_at, "
        "(SELECT title FROM webami_order_items i WHERE i.order_guid=r.order_guid "
        "AND i.upc=r.upc LIMIT 1) AS title "
        "FROM receipts r WHERE r.order_guid=? ORDER BY r.id DESC", (guid,)).fetchall())


def rq_set(guid: str, upc: str, qty: int) -> None:
    with transaction() as conn:
        if qty > 0:
            conn.execute(
                "INSERT INTO receipt_queue (order_guid, upc, qty) VALUES (?,?,?) "
                "ON CONFLICT(order_guid, upc) DO UPDATE SET qty=excluded.qty", (guid, upc, qty))
        else:
            conn.execute("DELETE FROM receipt_queue WHERE order_guid=? AND upc=?", (guid, upc))


def rq_target(guid: str, upc: str, action, variant_id, product_id) -> None:
    with transaction() as conn:
        conn.execute("UPDATE receipt_queue SET action=?, variant_id=?, product_id=? "
                     "WHERE order_guid=? AND upc=?", (action, variant_id, product_id, guid, upc))


def rq_list() -> list[dict]:
    return rows(get_conn().execute(
        "SELECT q.order_guid, q.upc, q.qty, q.action AS t_action, q.variant_id AS t_variant, "
        "q.product_id AS t_product, o.number, i.title, i.artist, i.quantity AS ordered, "
        "i.price AS wm_cost, i.product_id AS wp_id "
        "FROM receipt_queue q JOIN webami_orders o ON o.guid=q.order_guid "
        "LEFT JOIN webami_order_items i ON i.order_guid=q.order_guid AND i.upc=q.upc "
        "GROUP BY q.order_guid, q.upc ORDER BY o.submitted_at DESC, i.position").fetchall())


def outstanding_items() -> list[dict]:
    return rows(get_conn().execute(
        "SELECT i.upc, MAX(i.title) AS title, MAX(i.artist) AS artist, SUM(i.quantity) AS ordered, "
        "SUM(COALESCE((SELECT SUM(qty) FROM receipts r WHERE r.order_guid=i.order_guid "
        "AND r.upc=i.upc AND r.reversed_at IS NULL),0)) AS received, "
        "COUNT(DISTINCT i.order_guid) AS orders "
        "FROM webami_order_items i GROUP BY i.upc HAVING ordered > received "
        "ORDER BY artist COLLATE NOCASE, title COLLATE NOCASE").fetchall())


def list_product_receipts(product_id: str) -> list[dict]:
    return rows(get_conn().execute(
        "SELECT r.id, r.upc, r.qty, r.created_at, r.reversed_at, o.number "
        "FROM receipts r JOIN webami_orders o ON o.guid=r.order_guid "
        "WHERE r.upc IN (SELECT upc FROM shopify_variants WHERE product_id=? "
        "AND upc IS NOT NULL AND upc!='') ORDER BY r.id DESC", (product_id,)).fetchall())