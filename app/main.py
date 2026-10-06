import secrets
import time
from pathlib import Path

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contextlib import asynccontextmanager

from app import db, shopify_sync, vault
from app.shopify_client import ShopifyClient

STATIC = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(lifespan=lifespan)

# In-memory state: decrypted credentials live only while the app runs.
_creds: dict | None = None
_sessions: set[str] = set()
_fails: list[float] = []


class Login(BaseModel):
    password: str


def require_session(rs_session: str | None = Cookie(default=None)) -> None:
    if not rs_session or rs_session not in _sessions:
        raise HTTPException(401, "Locked")


def get_creds() -> dict:
    if _creds is None:
        raise HTTPException(401, "Locked")
    return _creds


@app.post("/api/login")
def login(body: Login, response: Response):
    global _creds
    now = time.time()
    _fails[:] = [t for t in _fails if now - t < 60]
    if len(_fails) >= 5:
        raise HTTPException(429, "Too many attempts, wait a minute")
    try:
        _creds = vault.open_vault(body.password)
    except vault.VaultError as e:
        _fails.append(now)
        raise HTTPException(401, str(e))
    token = secrets.token_urlsafe(32)
    _sessions.add(token)
    response.set_cookie("rs_session", token, httponly=True, samesite="strict")
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response, rs_session: str | None = Cookie(default=None)):
    _sessions.discard(rs_session or "")
    response.delete_cookie("rs_session")
    return {"ok": True}


@app.get("/api/me", dependencies=[Depends(require_session)])
def me():
    return {"ok": True}


@app.post("/api/sync/shopify", dependencies=[Depends(require_session)])
def sync_shopify(mode: str = "recent"):
    if mode not in ("full", "recent"):
        raise HTTPException(400, "mode must be full or recent")
    if not shopify_sync.start(ShopifyClient.from_creds(get_creds()), mode):
        raise HTTPException(409, "A sync is already running")
    return shopify_sync.status()


@app.post("/api/sync/cancel", dependencies=[Depends(require_session)])
def sync_cancel():
    shopify_sync.cancel()
    return {"ok": True}


@app.get("/api/sync/status", dependencies=[Depends(require_session)])
def sync_status():
    return {**shopify_sync.status(), "last_sync": db.get_state("shopify_last_sync")}


@app.get("/api/shopify/products", dependencies=[Depends(require_session)])
def list_products(q: str = "", limit: int = 50, offset: int = 0):
    limit = max(1, min(limit, 200))
    like = f"%{q.strip()}%"
    where = """WHERE (:q = '' OR p.title LIKE :like OR p.vendor LIKE :like OR p.handle LIKE :like
               OR p.upc_metafield LIKE :like
               OR EXISTS (SELECT 1 FROM shopify_variants v WHERE v.product_id=p.product_id
                          AND (v.barcode LIKE :like OR v.sku LIKE :like)))"""
    params = {"q": q.strip(), "like": like, "limit": limit, "offset": offset}
    with db.connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM shopify_products p {where}", params).fetchone()[0]
        rows = conn.execute(
            f"""SELECT p.product_id, p.handle, p.title, p.vendor, p.status, p.product_type,
                       p.upc_metafield, p.image_urls,
                       COUNT(v.variant_id) AS variant_count,
                       MIN(v.price) AS price, SUM(v.inventory_quantity) AS inventory,
                       MIN(v.barcode) AS barcode
                FROM shopify_products p LEFT JOIN shopify_variants v ON v.product_id=p.product_id
                {where} GROUP BY p.product_id ORDER BY p.title LIMIT :limit OFFSET :offset""",
            params,
        ).fetchall()
    return {"total": total, "rows": [dict(r) for r in rows]}


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{path:path}")
def spa(path: str):
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
