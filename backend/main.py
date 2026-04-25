"""
App entry point.
"""

import logging
import logging.config
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
from api.routes import router
from credentials import CredentialStore, CredentialError
from db.database import init_db
from sync.scheduler import start as start_scheduler, stop as stop_scheduler
from workers.startup import run_startup_sync

# ── Test Mode ─────────────────────────────────────────────────────────


# ── Logging setup ─────────────────────────────────────────────────────
# Format matches what you see in the terminal:
#   2026-04-18 18:57:52,648 [INFO] webami.scraper:166 — message
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d — %(message)s"
LOG_DATE   = "%Y-%m-%d %H:%M:%S"

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format=LOG_FORMAT,
    datefmt=LOG_DATE,
)

# Silence uvicorn's access log for the high-frequency polling endpoint
# so it doesn't spam the terminal every 2.5 seconds.
class _SuppressPollingFilter(logging.Filter):
    _SUPPRESS = {"/api/sync/running"}

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in self._SUPPRESS)

logging.getLogger("uvicorn.access").addFilter(_SuppressPollingFilter())

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"


def _check_credentials():
    store = CredentialStore()
    if store.is_first_run():
        logger.info("First run — launching setup wizard")
        store.setup_wizard()


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        _check_credentials()
    except CredentialError as e:
        logger.critical(f"Credential error: {e}")
        sys.exit(1)

    init_db()
    start_scheduler()

    import asyncio
    asyncio.create_task(run_in_threadpool(run_startup_sync))

    yield

    stop_scheduler()
    logger.info("App shutdown complete")


app = FastAPI(title=config.APP_NAME, lifespan=lifespan)
app.include_router(router, prefix="/api")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=False)