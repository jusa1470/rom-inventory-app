"""
Global cancellation token and sync state tracker.

cancel.py is the single source of truth the backend writes and the
frontend polls. It tracks:
  - whether a cancel has been requested (_event)
  - what is currently running (_running_label)
  - the outcome of the last sync (_last_result)

The /sync/running endpoint reads all three so the frontend always has
an accurate, complete picture regardless of whether it was watching
when the sync started or finished.
"""

from _thread import lock
import threading
from datetime import datetime, timezone
from typing import Literal, Optional

_event = threading.Event()
_lock: lock = threading.Lock()

_running_label: str = ""
_last_result: Optional[dict] = None

# ── Cancellation ──────────────────────────────────────────────────────

def request_cancel() -> None:
    _event.set()

def reset() -> None:
    _event.clear()

def cancelled() -> bool:
    return _event.is_set()

# ── Running label ─────────────────────────────────────────────────────

def set_running(label: str) -> None:
    global _running_label, _last_result
    with _lock:
        _running_label = label
        _last_result = None  # clear previous result when a new sync starts

def clear_running() -> None:
    global _running_label
    with _lock:
        _running_label = ""

def running_label() -> str:
    with _lock:
        return _running_label

# ── Last result ───────────────────────────────────────────────────────

def set_result(
    status: Literal["completed", "cancelled", "failed"],
    label: str,
    detail: Optional[str] = None,
    counts: Optional[dict] = None,
) -> None:
    global _last_result
    with _lock:
        _last_result = {
            "status": status,
            "label": label,
            "detail": detail,
            "counts": counts or {},
            "at": datetime.now(timezone.utc),
        }

def last_result() -> Optional[dict]:
    with _lock:
        return _last_result

def clear_result() -> None:
    global _last_result
    with _lock:
        _last_result = None