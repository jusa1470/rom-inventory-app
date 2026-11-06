"""In-memory job tracker for background threads.

Jobs are fire-and-forget daemon threads; the frontend polls their status.
"""

import logging
import threading
import uuid
from typing import Any, Callable

from app.db.sync_log import start_timer

logger: logging.Logger = logging.getLogger(__name__)

_jobs: dict[str, dict[str, Any]] = {}
_lock: threading.Lock = threading.Lock()


def create(name: str) -> str:
    job_id = uuid.uuid4().hex[:8]
    with _lock:
        _jobs[job_id] = {
            "id": job_id,
            "name": name,
            "status": "running",
            "progress": 0,
            "total": 0,
            "message": "Starting…",
            "error": None,
            "result": None,
        }
    return job_id


def update(job_id: str, **kwargs: Any) -> None:
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def get(job_id: str) -> dict[str, Any]:
    with _lock:
        return dict(_jobs.get(job_id, {"status": "not_found"}))


def start(name: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> str:
    """Create a job, run fn(job_id, *args, **kwargs) in a daemon thread, return job_id."""
    job_id = create(name)

    def _run() -> None:
        start_timer()
        try:
            result = fn(job_id, *args, **kwargs)
            if is_cancelled(job_id):
                update(job_id, result=result)
            else:
                update(job_id, status="done", result=result)
        except BaseException as exc:
            logger.exception("Job %s (%s) failed", job_id, name)
            update(job_id, status="error", cancelled=True,
                   error=f"{type(exc).__name__}: {exc}", message=f"Error: {exc}")

    threading.Thread(target=_run, daemon=True).start()
    return job_id


def cancel(job_id: str) -> bool:
    with _lock:
        job = _jobs.get(job_id)
        if job and job["status"] == "running":
            job["cancelled"] = True
            job["status"] = "cancelled"
            job["message"] = "Cancelled"
            return True
    return False


def is_cancelled(job_id: str) -> bool:
    with _lock:
        return bool(_jobs.get(job_id, {}).get("cancelled"))


def get_running() -> list[dict[str, Any]]:
    with _lock:
        return [dict(j) for j in _jobs.values() if j["status"] == "running"]


def _thread_hook(args) -> None:
    """Uncaught exception in any thread: fail every running job so the UI shows it."""
    logger.error("Uncaught thread exception", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    with _lock:
        for job in _jobs.values():
            if job["status"] == "running":
                job.update(status="error", cancelled=True,
                           error=f"{args.exc_type.__name__}: {args.exc_value}",
                           message=f"Error: {args.exc_value}")


threading.excepthook = _thread_hook