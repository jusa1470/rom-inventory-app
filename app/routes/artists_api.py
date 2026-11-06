from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app import config, db
from app.auth import get_creds, require_session
from app.shopify.shopify_client import ShopifyClient

router = APIRouter(prefix="/api/artists", tags=["artists"],
                   dependencies=[Depends(require_session)])


class Ids(BaseModel):
    product_ids: list[str]


class AliasIn(BaseModel):
    alias: str
    canonical: str


@router.get("")
def list_artists():
    return {"items": db.list_aliases()}


@router.post("")
def add_artist(body: AliasIn):
    try:
        db.add_alias(body.alias, body.canonical)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@router.delete("")
def remove_artist(alias: str):
    db.remove_alias(alias)
    return {"ok": True}


@router.get("/changes")
def changes():
    return {"items": db.vendor_changes()}


@router.post("/apply")
def apply(body: Ids, creds: dict = Depends(get_creds)):
    if db.is_dry_run():
        return {"ok": True, "dry_run": True, "updated": 0, "errors": []}
    cfg = db.get_config()
    client = ShopifyClient(creds["shopify_store"], creds["shopify_token"],
                           cfg.get("shopify_api_version") or config.DEFAULT_API_VERSION)
    updated, errors = 0, []
    for c in db.vendor_changes():
        if c["product_id"] not in body.product_ids:
            continue
        try:
            client.update_product(c["product_id"], {"vendor": c["new_vendor"]}, cfg)
        except Exception as e:
            errors.append(f"{c['title']}: {e}")
            continue
        db.update_local(c["product_id"], {"vendor": c["new_vendor"]}, [])
        updated += 1
    return {"ok": not errors, "updated": updated, "errors": errors}


@router.get("/mismatches")
def mismatches():
    return {"items": db.mismatches()}


@router.post("/mismatches/ignore")
def ignore_mm(vendor: str, artist: str):
    db.set_ignored(vendor, artist, True)
    return {"ok": True}


@router.delete("/mismatches/ignore")
def unignore_mm(vendor: str, artist: str):
    db.set_ignored(vendor, artist, False)
    return {"ok": True}