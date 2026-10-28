"""Shopify OAuth (authorization code grant) helpers. Pure functions, no app state."""

import hashlib
import hmac
import re
from urllib.parse import urlencode

import requests

# Vault keys for each store: shop domain, offline access token, granted scopes.
STORES: dict[str, dict[str, str]] = {
    "main": {"store": "shopify_store", "token": "shopify_token", "scope": "shopify_scope"},
    "test": {
        "store": "test_shopify_store",
        "token": "test_shopify_token",
        "scope": "test_shopify_scope",
    },
}

DEFAULT_SCOPES: list[str] = [
    "read_customers", "read_price_rules", "write_price_rules", "read_files",
    "write_inventory", "read_inventory", "read_locations", "read_metaobjects",
    "write_metaobjects", "read_all_orders", "read_orders", "write_orders",
    "read_products", "write_products", "read_publications", "write_publications",
    "read_themes",
]

SHOP_RE = re.compile(r"^[a-z0-9][a-z0-9-]*\.myshopify\.com$")
SCOPE_RE = re.compile(r"^[a-z_]+$")


def normalize_scopes(raw: str) -> list[str]:
    """Split on commas/whitespace, drop duplicates (keeping order), validate names."""
    scopes: dict[str, None] = {}
    for item in re.split(r"[,\s]+", raw.strip()):
        if not item:
            continue
        if not SCOPE_RE.match(item):
            raise ValueError(f"Invalid scope: {item}")
        scopes.setdefault(item, None)
    if not scopes:
        raise ValueError("At least one scope is required")
    return list(scopes)


def authorize_url(
    shop: str, client_id: str, scopes: list[str], redirect_uri: str, state: str
) -> str:
    query = urlencode({
        "client_id": client_id,
        "scope": ",".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    })
    return f"https://{shop}/admin/oauth/authorize?{query}"


def verify_hmac(params: dict[str, str], client_secret: str) -> bool:
    """Check the signature Shopify adds to the callback query string."""
    given = params.get("hmac", "")
    message = "&".join(f"{k}={v}" for k, v in sorted(params.items()) if k != "hmac")
    expected = hmac.new(client_secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, given)


def exchange_code(shop: str, client_id: str, client_secret: str, code: str) -> dict:
    """Trade the authorization code for an access token. Returns Shopify's JSON."""
    resp = requests.post(
        f"https://{shop}/admin/oauth/access_token",
        json={"client_id": client_id, "client_secret": client_secret, "code": code},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if not data.get("access_token"):
        raise RuntimeError("Shopify returned no access token")
    return data