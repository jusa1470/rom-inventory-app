from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import logging
from pathlib import Path
import uvicorn

from app import auth, db
from app.routes import artists_api, matches_api, missing_api, prices_api, products_api, settings_api, shopify_oauth_api, sync_api, orders_api

STATIC = Path(__file__).resolve().parent.parent / "static"
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logging.getLogger("watchfiles").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(artists_api.router)
app.include_router(auth.router)
app.include_router(matches_api.router)
app.include_router(missing_api.router)
app.include_router(orders_api.router)
app.include_router(prices_api.router)
app.include_router(products_api.router)
app.include_router(settings_api.router)
app.include_router(shopify_oauth_api.router)
app.include_router(shopify_oauth_api.callback_router)
app.include_router(sync_api.router)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


@app.get("/{path:path}")
def spa(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "Not Found")
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True,
                reload_excludes=["static", "inventory.db", "node_modules", "__pycache__",
                                 ".venv"])