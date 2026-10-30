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