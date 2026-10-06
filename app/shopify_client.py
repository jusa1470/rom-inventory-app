"""Shopify Admin GraphQL client (read-only for now)."""

import logging
import time
from typing import Generator, Optional

import requests

from app import config

logger = logging.getLogger(__name__)

_VARIANT_FIELDS = """
  id title sku barcode price position taxable inventoryQuantity
  selectedOptions { name value }
  inventoryItem {
    id
    unitCost { amount }
    measurement { weight { value unit } }
  }
"""

PRODUCTS_QUERY = """
query($cursor: String, $query: String, $first: Int!, $vfirst: Int!) {
  products(first: $first, after: $cursor, query: $query, sortKey: UPDATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id handle title vendor status tags productType createdAt updatedAt
      category { id fullName }
      options { name position }
      media(first: 3) { nodes { preview { image { url } } } }
      upc: metafield(namespace: "facts", key: "upc") { value }
      variants(first: $vfirst) {
        pageInfo { hasNextPage endCursor }
        nodes { %s }
      }
    }
  }
}
""" % _VARIANT_FIELDS

MORE_VARIANTS_QUERY = """
query($id: ID!, $cursor: String, $first: Int!) {
  product(id: $id) {
    variants(first: $first, after: $cursor) {
      pageInfo { hasNextPage endCursor }
      nodes { %s }
    }
  }
}
""" % _VARIANT_FIELDS

COUNT_QUERY = """
query($query: String) { productsCount(query: $query) { count } }
"""


class ShopifyClient:
    def __init__(self, store: str, token: str, api_version: str = config.SHOPIFY_API_VERSION):
        store = store.strip().removeprefix("https://").removeprefix("http://").rstrip("/")
        if "." not in store:
            store += ".myshopify.com"
        self.url = f"https://{store}/admin/api/{api_version}/graphql.json"
        self.headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}

    @classmethod
    def from_creds(cls, creds: dict) -> "ShopifyClient":
        return cls(creds["shopify_store"], creds["shopify_token"])

    # ── core ──────────────────────────────────────────────────────────

    def _request(self, query: str, variables: Optional[dict] = None, retries: int = 5) -> dict:
        payload = {"query": query, "variables": variables or {}}
        for attempt in range(retries):
            wait = 2 ** attempt
            try:
                resp = requests.post(self.url, json=payload, headers=self.headers, timeout=60)
                if resp.status_code == 429 or resp.status_code >= 500:
                    logger.warning("Shopify %s, retrying in %ss", resp.status_code, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                errors = data.get("errors")
                if errors:
                    if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                        logger.warning("Throttled, retrying in %ss", wait)
                        time.sleep(wait)
                        continue
                    raise RuntimeError(f"GraphQL errors: {errors}")
                return data
            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise
                logger.warning("Request failed (%s), retrying in %ss", e, wait)
                time.sleep(wait)
        raise RuntimeError("Shopify request failed after retries")

    # ── read ──────────────────────────────────────────────────────────

    def count_products(self, since: Optional[str] = None) -> int:
        data = self._request(COUNT_QUERY, {"query": self._since_filter(since)})
        return data["data"]["productsCount"]["count"]

    def iter_products(self, since: Optional[str] = None) -> Generator[dict, None, None]:
        cursor = None
        while True:
            data = self._request(PRODUCTS_QUERY, {
                "cursor": cursor,
                "query": self._since_filter(since),
                "first": config.SHOPIFY_PAGE_SIZE,
                "vfirst": config.SHOPIFY_VARIANTS_INLINE,
            })
            page = data["data"]["products"]
            for node in page["nodes"]:
                yield self._map_product(node)
            if not page["pageInfo"]["hasNextPage"]:
                return
            cursor = page["pageInfo"]["endCursor"]

    @staticmethod
    def _since_filter(since: Optional[str]) -> Optional[str]:
        return f"updated_at:>'{since}'" if since else None

    def _all_variants(self, node: dict) -> list[dict]:
        variants = list(node["variants"]["nodes"])
        info = node["variants"]["pageInfo"]
        while info["hasNextPage"]:
            data = self._request(MORE_VARIANTS_QUERY, {
                "id": node["id"], "cursor": info["endCursor"], "first": 100,
            })
            page = data["data"]["product"]["variants"]
            variants.extend(page["nodes"])
            info = page["pageInfo"]
        return variants

    # ── mapping ───────────────────────────────────────────────────────

    def _map_product(self, node: dict) -> dict:
        cat = node.get("category") or {}
        return {
            "product_id": node["id"],
            "handle": node.get("handle"),
            "title": node.get("title"),
            "vendor": node.get("vendor"),
            "status": node.get("status"),
            "product_type": node.get("productType"),
            "category_id": cat.get("id"),
            "category_name": cat.get("fullName"),
            "tags": node.get("tags") or [],
            "upc_metafield": (node.get("upc") or {}).get("value"),
            "image_urls": [
                m["preview"]["image"]["url"]
                for m in (node.get("media") or {}).get("nodes", [])
                if m.get("preview") and m["preview"].get("image")
            ],
            "option_names": [o["name"] for o in sorted(node.get("options") or [], key=lambda o: o["position"])],
            "created_at": node.get("createdAt"),
            "updated_at": node.get("updatedAt"),
            "variants": [self._map_variant(v) for v in self._all_variants(node)],
        }

    @staticmethod
    def _map_variant(v: dict) -> dict:
        item = v.get("inventoryItem") or {}
        cost = (item.get("unitCost") or {}).get("amount")
        weight = ((item.get("measurement") or {}).get("weight")) or {}
        return {
            "variant_id": v["id"],
            "title": v.get("title"),
            "sku": v.get("sku"),
            "barcode": v.get("barcode"),
            "price": float(v["price"]) if v.get("price") is not None else None,
            "cost": float(cost) if cost is not None else None,
            "taxable": 1 if v.get("taxable", True) else 0,
            "position": v.get("position"),
            "options": v.get("selectedOptions") or [],
            "inventory_item_id": item.get("id"),
            "inventory_quantity": v.get("inventoryQuantity"),
            "weight": weight.get("value"),
            "weight_unit": weight.get("unit"),
        }
