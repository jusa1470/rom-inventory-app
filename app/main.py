import secrets
import time
from pathlib import Path

import uvicorn
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from contextlib import asynccontextmanager

from app import applier, db, planner, shopify_sync, vault
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


# ── Catalog plan ────────────────────────────────────────────────────

class RuleIn(BaseModel):
    term: str
    kind: str
    value: str = ""


class VariantEdit(BaseModel):
    edition: str | None = None
    color: str | None = None
    attributes: str | None = None


def _guard(fn, *a):
    try:
        return fn(*a)
    except LookupError as e:
        raise HTTPException(404, str(e))
    except PermissionError as e:
        raise HTTPException(409, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


_plan = [Depends(require_session)]


@app.post("/api/plan/build", dependencies=_plan)
def plan_build():
    return planner.build_plan()


@app.get("/api/plan/groups", dependencies=_plan)
def plan_groups(filter: str = "all", q: str = "", limit: int = 25, offset: int = 0):
    return planner.list_groups(filter, q, max(1, min(limit, 100)), max(0, offset))


@app.get("/api/plan/unknown-terms", dependencies=_plan)
def plan_unknown():
    return planner.unknown_terms()


@app.get("/api/plan/rules", dependencies=_plan)
def plan_rules():
    return planner.list_rules()


@app.post("/api/plan/rules", dependencies=_plan)
def plan_save_rules(rules: list[RuleIn]):
    for r in rules:
        _guard(planner.save_rule, r.term, r.kind, r.value)
    return planner.build_plan()          # rules apply immediately to everything not yet approved/edited


@app.delete("/api/plan/rules", dependencies=_plan)
def plan_delete_rule(term: str):
    planner.delete_rule(term)
    return planner.build_plan()


@app.patch("/api/plan/variants/{variant_id}", dependencies=_plan)
def plan_edit_variant(variant_id: int, body: VariantEdit):
    _guard(planner.edit_variant, variant_id, body.model_dump(exclude_unset=True))
    return {"ok": True}


class MoveIn(BaseModel):
    group_id: int | None = None
    new_title: str = ""


@app.post("/api/plan/variants/{variant_id}/move", dependencies=_plan)
def plan_move(variant_id: int, body: MoveIn):
    _guard(planner.move_variant, variant_id, body.group_id, body.new_title)
    return {"ok": True}


@app.get("/api/plan/groups/{group_id}/addable", dependencies=_plan)
def plan_addable(group_id: int, q: str = ""):
    return _guard(planner.search_addable, group_id, q)


class IgnoreIn(BaseModel):
    variant_ids: list[int]
    scope: str = "product"


class UnignoreIn(BaseModel):
    product_id: str = ""
    category_id: str = ""


@app.post("/api/plan/ignore", dependencies=_plan)
def plan_ignore(body: IgnoreIn):
    _guard(planner.ignore_variants, body.variant_ids, body.scope)
    return {"ok": True}


@app.get("/api/plan/ignored", dependencies=_plan)
def plan_ignored():
    return planner.list_ignored()


@app.post("/api/plan/unignore", dependencies=_plan)
def plan_unignore(body: UnignoreIn):
    return planner.unignore(body.product_id, body.category_id)


@app.post("/api/plan/variants/{variant_id}/keep-duplicates", dependencies=_plan)
def plan_keep_duplicates(variant_id: int):
    return {"marked": _guard(planner.keep_duplicates, variant_id)}


@app.post("/api/plan/variants/{variant_id}/unmark-duplicate", dependencies=_plan)
def plan_unmark_duplicate(variant_id: int):
    _guard(planner.unmark_duplicate, variant_id)
    return {"ok": True}


@app.post("/api/plan/groups/{group_id}/approve", dependencies=_plan)
def plan_approve(group_id: int):
    _guard(planner.set_group_approved, group_id, True)
    return {"ok": True}


@app.post("/api/plan/groups/{group_id}/unapprove", dependencies=_plan)
def plan_unapprove(group_id: int):
    _guard(planner.set_group_approved, group_id, False)
    return {"ok": True}


# ── Apply (create / archive) ────────────────────────────────────────

class ApplyIn(BaseModel):
    group_ids: list[int] = []
    limit: int = 25
    publish: bool = False


@app.get("/api/apply/summary", dependencies=_plan)
def apply_summary():
    return applier.summary()


@app.get("/api/apply/groups", dependencies=_plan)
def apply_groups(stage: str = "all", q: str = "", limit: int = 25, offset: int = 0):
    return applier.list_groups(stage, q, max(1, min(limit, 100)), max(0, offset))


def _apply(step: str, stage: str, body: ApplyIn):
    ids = body.group_ids or applier.next_group_ids(stage, max(1, min(body.limit, 100)))
    if not ids:
        raise HTTPException(400, "Nothing to do")
    if not applier.start(ShopifyClient.from_creds(get_creds()), step, ids, body.publish):
        raise HTTPException(409, "An apply job is already running")
    return applier.status()


@app.post("/api/apply/create", dependencies=_plan)
def apply_create(body: ApplyIn):
    return _apply("create", "to_create", body)


@app.post("/api/apply/archive", dependencies=_plan)
def apply_archive(body: ApplyIn):
    return _apply("archive", "to_archive", body)


@app.post("/api/apply/publish", dependencies=_plan)
def apply_publish(body: ApplyIn):
    return _apply("publish", "to_publish", body)


@app.get("/api/apply/status", dependencies=_plan)
def apply_status():
    return applier.status()


@app.post("/api/apply/cancel", dependencies=_plan)
def apply_cancel():
    applier.cancel()
    return {"ok": True}


@app.get("/api/plan/mapping.csv", dependencies=_plan)
def mapping_csv():
    import csv, io
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["old_product_id", "old_variant_id", "new_product_id", "new_variant_id", "handle",
                "edition", "color", "attributes", "qty_copied", "old_archived_at"])
    with db.connect() as conn:
        for r in conn.execute(
                """SELECT v.source_product_id, v.source_variant_id, g.new_product_id, v.new_variant_id, g.handle,
                          v.edition, v.color, v.attributes, v.qty_copied, v.archived_at
                   FROM plan_variants v JOIN plan_products g ON g.id=v.plan_product_id ORDER BY g.handle"""):
            w.writerow(list(r))
    return Response(out.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=catalog-mapping.csv"})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/{path:path}")
def spa(path: str):
    return FileResponse(STATIC / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
