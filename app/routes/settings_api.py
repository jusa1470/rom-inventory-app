from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, Field

from app import config, db
from app.auth import get_creds, require_session

router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_session)]
)


class SettingsIn(BaseModel):
    shopify_api_version: str = Field(
        default="2025-01", min_length=7, max_length=7, pattern=r"^\d{4}-\d{2}$"
    )
    shopify_type_ns: str = Field(default="custom", min_length=1)
    shopify_type_key: str = Field(default="type", min_length=1)
    shopify_genres_ns: str = Field(default="custom", min_length=1)
    shopify_genres_key: str = Field(default="genres", min_length=1)
    shopify_upc_ns: str = Field(default="custom", min_length=1)
    shopify_upc_key: str = Field(default="upc", min_length=1)
    shopify_description_ns: str = Field(default="custom", min_length=1)
    shopify_description_key: str = Field(default="description", min_length=1)
    shopify_release_date_ns: str = Field(default="custom", min_length=1)
    shopify_release_date_key: str = Field(default="release_date", min_length=1)
    shopify_variant_tags_ns: str = Field(default="custom", min_length=1)
    shopify_variant_tags_key: str = Field(default="variant_tags", min_length=1)
    dry_run: bool = Field(default=False)
    page_size: int = Field(default=100, ge=10, le=200)


def _build_settings_response(cfg: dict, creds: dict) -> dict:
    if not isinstance(cfg, dict):
        raise HTTPException(500, "Invalid config")
    if not isinstance(creds, dict):
        raise HTTPException(500, "Invalid creds")

    return {
        "dry_run": bool(cfg.get("dry_run")),
        "shopify_location_id": cfg.get("shopify_location_id") or "",
        "last_shopify_sync": cfg.get("last_shopify_sync") or "",
        "shopify_store": cfg.get("shopify_store") or "",
        "shopify_token_set": bool(
            creds.get("shopify_token_enc")
        ),  # Never send encrypted values - just indicate if set
    }


@router.get("/")
def get_settings():
    cfg = db.get_config()
    creds = get_creds()
    return _build_settings_response(cfg, creds)


@router.put("/")
def update_settings(body: SettingsIn):
	cfg = db.get_config()
	creds = get_creds()
	db.upsert_config(**body.model_dump())
	return _build_settings_response(cfg, creds)