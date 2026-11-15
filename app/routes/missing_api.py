from typing import Literal
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from app import db
from app.auth import get_creds, require_session
from app.db.connection import strip_gid
from app.routes.sync_api import sync_after_push
from app.shopify.shopify_client import ShopifyClient

router = APIRouter(prefix="/api/missing", tags=["missing"], dependencies=[Depends(require_session)])
Kind = Literal["products", "variants"]


class Item(BaseModel):
    kind: Kind
    id: str
    field: str | None = None
    value: str | None = None


class Items(BaseModel):
    items: list[Item]


class Rev(BaseModel):
    kind: Kind
    ids: list[str]
    on: bool = True


class Push(BaseModel):
    keys: list[str] | None = None


@router.get("")
def missing(kind: Kind = "products", q: str | None = None, review: bool = False,
            fields: list[str] | None = Query(None), page: int = Query(1, ge=1),
            per_page: int = Query(50, ge=1, le=200)):
    res = db.list_missing(kind, fields or [], q.strip() if q else "", page, per_page, review)
    return {**res, "page": page, "per_page": per_page}


@router.post("/stage")
def stage(body: Items):
    db.mq_set([i.model_dump() for i in body.items if i.field and (i.value or "").strip()])
    return {"ok": True}


@router.post("/review")
def review(body: Rev):
    db.mq_review(body.kind, body.ids, body.on)
    return {"ok": True}


@router.get("/queue")
def queue():
    return {"items": db.mq_list()}


@router.post("/queue/remove")
def queue_remove(body: Items):
    db.mq_remove([i.model_dump() for i in body.items])
    return {"ok": True}


def _apply(client, cfg, kind, id_, pid, f):
    f = {k: v.strip() for k, v in f.items() if (v or "").strip()}
    if kind == "products":
        if "genres" in f:
            f["genres"] = [g.strip() for g in f["genres"].split(",") if g.strip()]
        if "category" in f:
            c = client.find_category(f.pop("category"))
            f["category_id"], f["category_name"] = strip_gid(c["id"]), c["name"]
        client.update_product(pid, f, cfg)
        db.update_local(pid, f, [])
        return
    img = f.pop("image", None)
    if "weight" in f:
        f["weight"] = float(f["weight"])
    if f:
        v = {"id": id_, **f}
        client.update_variants(pid, [v], cfg)
        db.update_local(pid, {}, [v])
    if img:
        client.set_variant_image(pid, id_, img)


@router.post("/queue/push")
def queue_push(body: Push = Push(), creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True, "pushed": 0, "errors": []}
    cfg = db.get_config()
    client = ShopifyClient(creds["shopify_store"], creds["shopify_token"])
    groups: dict = {}
    for r in db.mq_list():
        if body.keys is not None and f"{r['kind']}|{r['id']}" not in body.keys:
            continue
        groups.setdefault((r["kind"], r["id"], r["product_id"]), {})[r["field"]] = r["value"]
    pushed, errors = 0, []
    for (kind, id_, pid), f in groups.items():
        try:
            _apply(client, cfg, kind, id_, pid, f)
        except Exception as e:
            errors.append(f"{id_}: {e}")
            continue
        db.mq_remove([{"kind": kind, "id": id_}])
        db.mq_review(kind, [id_], False)
        pushed += 1
    if pushed:
        sync_after_push(creds)
    return {"ok": not errors, "pushed": pushed, "errors": errors}