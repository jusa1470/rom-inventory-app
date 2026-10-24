from contextlib import contextmanager
import sqlite3
import threading
from typing import Optional

from app import config


_local = threading.local()

def _make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_conn() -> sqlite3.Connection:
    if not getattr(_local, "conn", None):
        _local.conn = _make_conn()
    return _local.conn


def _sid(gid: str) -> str:
    if not gid:
        return gid
    s = str(gid)
    return s.split("/")[-1] if "/" in s else s


def _row(r) -> Optional[dict]:
    return dict(r) if r else None


def _rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


@contextmanager
def transaction():
    conn = _make_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()