"""
Simple in-memory job tracker for background threads.
Jobs are fire-and-forget threads; status is polled by the frontend.
"""

import threading
import uuid
from typing import Any, Callable, Optional

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create(name: str) -> str:
    job_id = uuid.uuid4().hex[:8]
    with _lock:
        _jobs[job_id] = {
            "id":       job_id,
            "name":     name,
            "status":   "running",
            "progress": 0,
            "total":    0,
            "message":  "Starting…",
            "error":    None,
            "result":   None,
        }
    return job_id


def update(job_id: str, **kwargs) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def get(job_id: str) -> dict:
    with _lock:
        return dict(_jobs.get(job_id, {"status": "not_found"}))


def start(name: str, fn: Callable, *args, **kwargs) -> str:
    """Create a job, run fn(job_id, *args, **kwargs) in a daemon thread, return job_id."""
    job_id = create(name)

    def _run():
        try:
            result = fn(job_id, *args, **kwargs)
            update(job_id, status="done", message="Complete", result=result)
        except Exception as exc:
            import traceback
            update(job_id, status="error", error=str(exc),
                   message=f"Error: {exc}",
                   _traceback=traceback.format_exc())

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return job_id


def cancel(job_id: str) -> bool:
    with _lock:
        if job_id in _jobs and _jobs[job_id].get("status") == "running":
            _jobs[job_id]["cancelled"] = True
            _jobs[job_id]["status"] = "cancelled"
            _jobs[job_id]["message"] = "Cancelled"
            return True
    return False


def is_cancelled(job_id: str) -> bool:
    with _lock:
        return bool(_jobs.get(job_id, {}).get("cancelled"))
    

def get_running() -> list[dict]:
    with _lock:
        return [dict(j) for j in _jobs.values() if j.get("status") == "running"]