from app.db.connection import get_conn, rows, transaction


def log_sync(action: str, status: str, details: str | None = None) -> None:
    with transaction() as conn:
        conn.execute(
            "INSERT INTO sync_log (action, status, details) VALUES (?, ?, ?)",
            (action, status, details),
        )


def get_sync_log(limit: int = 50) -> list[dict]:
    return rows(get_conn().execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall())