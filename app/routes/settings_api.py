from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app import db
from app.auth import get_creds, require_session
from app.shopify.oauth import DEFAULT_SCOPES, STORES

router = APIRouter(
    prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_session)]
)


class SettingsIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    shopify_api_version: str = Field(pattern=r"^\d{4}-\d{2}$")
    shopify_type_ns: str = Field(min_length=1)
    shopify_type_key: str = Field(min_length=1)
    shopify_genres_ns: str = Field(min_length=1)
    shopify_genres_key: str = Field(min_length=1)
    shopify_upc_ns: str = Field(min_length=1)
    shopify_upc_key: str = Field(min_length=1)
    shopify_description_ns: str = Field(min_length=1)
    shopify_description_key: str = Field(min_length=1)
    shopify_release_date_ns: str = Field(min_length=1)
    shopify_release_date_key: str = Field(min_length=1)
    shopify_variant_tags_ns: str = Field(min_length=1)
    shopify_variant_tags_key: str = Field(min_length=1)
    dry_run: bool
    page_size: int = Field(ge=10, le=200)


def _settings_response(cfg: dict, creds: dict) -> dict:
    return {
        **{field: cfg[field] for field in SettingsIn.model_fields},
        "dry_run": bool(cfg["dry_run"]),
        # System-managed, read-only
        "shopify_location_id": cfg.get("shopify_location_id") or "",
        "last_shopify_sync": cfg.get("last_shopify_sync") or "",
        # Credentials come from the vault; the token itself is never returned
        "stores": {
            name: {
                "store": creds.get(keys["store"]) or "",
                "token_set": bool(creds.get(keys["token"])),
                "scope": creds.get(keys["scope"]) or "",
            }
            for name, keys in STORES.items()
        },
        "oauth_ready": bool(creds.get("shopify_client_id") and creds.get("shopify_client_secret")),
        "default_scopes": ",".join(DEFAULT_SCOPES),
    }


@router.get("")
def get_settings(creds: dict = Depends(get_creds)):
    return _settings_response(db.get_config(), creds)


@router.put("")
def update_settings(body: SettingsIn, creds: dict = Depends(get_creds)):
    data = body.model_dump()
    data["dry_run"] = int(data["dry_run"])
    db.upsert_config(**data)
    return _settings_response(db.get_config(), creds)