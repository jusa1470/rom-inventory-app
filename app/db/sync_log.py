from app.db.connection import _rows, get_conn


def log_sync(action: str, status: str, details: str = None) -> None:
    conn = get_conn()
    conn.execute("INSERT INTO sync_log (action,status,details) VALUES (?,?,?)",
                 (action, status, details))
    conn.commit()


def get_sync_log(limit: int = 50) -> list[dict]:
    return _rows(get_conn().execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall())