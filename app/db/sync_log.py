import threading
import time

from app.db.connection import get_conn, rows, transaction

_t = threading.local()


def start_timer() -> None:
    _t.t0 = time.monotonic()


def log_sync(action: str, status: str, details: str | None = None) -> None:
    t0 = getattr(_t, "t0", None)
    secs = round(time.monotonic() - t0, 1) if t0 else None
    with transaction() as conn:
        conn.execute(
            "INSERT INTO sync_log (action, status, details, seconds) VALUES (?, ?, ?, ?)",
            (action, status, details, secs),
        )


def get_sync_log(limit: int = 50) -> list[dict]:
    return rows(get_conn().execute(
        "SELECT * FROM sync_log ORDER BY id DESC LIMIT ?", (limit,)).fetchall())