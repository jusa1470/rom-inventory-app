from _thread import _local
import sqlite3
import threading
from contextlib import contextmanager
from typing import Generator, Optional

from app import config

_local = threading.local()


def _make_conn() -> sqlite3.Connection:
    conn: sqlite3.Connection = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    if not getattr(_local, "conn", None):
        _local.conn = _make_conn()
    return _local.conn


@contextmanager
def transaction() -> Generator[sqlite3.Connection, None, None]:
    conn: sqlite3.Connection = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def strip_gid(gid) -> Optional[str]:
    if not gid:
        return None
    return str(gid).rsplit("/", 1)[-1]


def row(r) -> Optional[dict]:
    return dict(r) if r else None


def rows(rs) -> list[dict]:
    return [dict(r) for r in rs]