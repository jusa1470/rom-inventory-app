from concurrent.futures import ThreadPoolExecutor
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


def _do_product(client, cfg, cats, pid, f):
    f = {k: v.strip() for k, v in f.items() if (v or "").strip()}
    if "genres" in f:
        f["genres"] = [g.strip() for g in f["genres"].split(",") if g.strip()]
    if "category" in f:
        name = f.pop("category")
        if name not in cats:
            cats[name] = client.find_category(name)
        f["category_id"], f["category_name"] = strip_gid(cats[name]["id"]), cats[name]["name"]
    client.update_product(pid, f, cfg)
    return f


def _do_variants(client, cfg, pid, items):
    vs, imgs = [], []
    for id_, f in items:
        f = {k: v.strip() for k, v in f.items() if (v or "").strip()}
        img = f.pop("image", None)
        if "weight" in f:
            f["weight"] = float(f["weight"])
        if f:
            vs.append({"id": id_, **f})
        if img:
            imgs.append((id_, img))
    if vs:
        client.update_variants(pid, vs, cfg)
    errs = {}
    for id_, img in imgs:
        try:
            client.set_variant_image(pid, id_, img)
        except Exception as e:
            errs[id_] = str(e)
    return vs, errs


@router.post("/queue/push")
def queue_push(body: Push = Push(), creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True, "pushed": 0, "errors": []}
    cfg = db.get_config()
    client = ShopifyClient(creds["shopify_store"], creds["shopify_token"])
    cats: dict = {}
    prods, vby = [], {}
    for r in db.mq_list():
        if body.keys is not None and f"{r['kind']}|{r['id']}" not in body.keys:
            continue
        if r["kind"] == "products":
            prods.append(r)
        else:
            vby.setdefault(r["product_id"], {}).setdefault(r["id"], {})[r["field"]] = r["value"]
    pg: dict = {}
    for r in prods:
        pg.setdefault(r["id"], {})[r["field"]] = r["value"]

    def run(t):
        try:
            if t[0] == "p":
                return t, _do_product(client, cfg, cats, t[1], t[2]), None
            return t, _do_variants(client, cfg, t[1], t[2]), None
        except Exception as e:
            return t, None, e

    tasks = [("p", i, f) for i, f in pg.items()]
    tasks += [("v", pid, list(d.items())) for pid, d in vby.items()]
    pushed, errors = 0, []
    with ThreadPoolExecutor(4) as pool:
        results = list(pool.map(run, tasks))
    for t, res, err in results:
        if err:
            errors.append(f"{t[1]}: {err}")
            continue
        if t[0] == "p":
            db.update_local(t[1], res, [])
            db.mq_remove([{"kind": "products", "id": t[1]}])
            db.mq_review("products", [t[1]], False)
            pushed += 1
        else:
            vs, errs = res
            if vs:
                db.update_local(t[1], {}, vs)
            errors += [f"{i}: {e}" for i, e in errs.items()]
            for id_, _ in t[2]:
                if id_ in errs:
                    continue
                db.mq_remove([{"kind": "variants", "id": id_}])
                db.mq_review("variants", [id_], False)
                pushed += 1
    if pushed:
        sync_after_push(creds)
    return {"ok": not errors, "pushed": pushed, "errors": errors}