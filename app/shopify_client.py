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
  inventoryItem { id unitCost { amount } }
"""

PRODUCTS_QUERY = """
query($cursor: String, $query: String, $first: Int!, $vfirst: Int!) {
  products(first: $first, after: $cursor, query: $query, sortKey: UPDATED_AT) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id handle title vendor status tags productType createdAt updatedAt
      category { id fullName }
      options { name position }
      media(first: 1) { nodes { preview { image { url } } } }
      upc: metafield(namespace: "custom", key: "upc") { value }
      genres: metafield(namespace: "custom", key: "genres") { value }
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
        # Rate-limit bucket tracking (updated from every response)
        self._available: Optional[float] = None
        self._restore_rate: float = 50.0
        self._last_cost: float = 0.0
        self._seen_at: float = 0.0

    @classmethod
    def from_creds(cls, creds: dict) -> "ShopifyClient":
        return cls(creds["shopify_store"], creds["shopify_token"])

    # ── core ──────────────────────────────────────────────────────────

    def _record_cost(self, data: dict) -> Optional[float]:
        """Track the cost bucket. Returns the wait (s) needed to afford the last query again."""
        cost = (data.get("extensions") or {}).get("cost") or {}
        ts = cost.get("throttleStatus") or {}
        if "currentlyAvailable" in ts:
            self._available = float(ts["currentlyAvailable"])
            self._restore_rate = float(ts.get("restoreRate") or self._restore_rate)
            self._seen_at = time.monotonic()
        if cost.get("requestedQueryCost"):
            self._last_cost = float(cost["requestedQueryCost"])
        return self._wait_needed()

    def _wait_needed(self) -> float:
        """Seconds to wait until the bucket can cover the last query's requested cost."""
        if self._available is None or not self._last_cost:
            return 0.0
        now_available = min(
            self._available + (time.monotonic() - self._seen_at) * self._restore_rate,
            1000.0,
        )
        deficit = self._last_cost * 1.1 - now_available   # 10% margin
        return max(0.0, deficit / self._restore_rate)

    def _request(self, query: str, variables: Optional[dict] = None, retries: int = 6) -> dict:
        payload = {"query": query, "variables": variables or {}}
        for attempt in range(retries):
            wait = 2 ** attempt
            pre = self._wait_needed()
            if pre > 0:
                logger.info("Pacing: waiting %.1fs for rate-limit bucket", pre)
                time.sleep(pre)
            try:
                resp = requests.post(self.url, json=payload, headers=self.headers, timeout=60)
                if resp.status_code == 429 or resp.status_code >= 500:
                    wait = float(resp.headers.get("Retry-After", wait))
                    logger.warning("Shopify %s, retrying in %ss", resp.status_code, wait)
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                self._record_cost(data)
                errors = data.get("errors")
                if errors:
                    if any((e.get("extensions") or {}).get("code") == "THROTTLED" for e in errors):
                        wait = max(self._wait_needed(), 1.0)
                        logger.warning("Throttled, retrying in %.1fs", wait)
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
            "genres": (node.get("genres") or {}).get("value"),
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


# ── apply-step API (create / archive) ────────────────────────────────

class ShopifyUserError(RuntimeError):
    pass


_Q_VARIANTS_FRESH = """
query($ids: [ID!]!) {
  nodes(ids: $ids) {
    ... on ProductVariant {
      id sku barcode price taxable
      selectedOptions { name value }
      inventoryItem {
        id
        unitCost { amount }
        measurement { weight { value unit } }
        inventoryLevels(first: 10) {
          nodes { location { id } quantities(names: ["available"]) { name quantity } }
        }
      }
      product {
        id title vendor productType tags status descriptionHtml
        category { id }
        upc: metafield(namespace: "custom", key: "upc") { value type }
        genres: metafield(namespace: "custom", key: "genres") { value type }
        media(first: 10) { nodes { ... on MediaImage { image { url } alt } } }
      }
    }
  }
}"""

_Q_LOCATIONS = "query { locations(first: 20) { nodes { id name isPrimary } } }"

_Q_PRODUCT_VARIANTS = """
query($id: ID!) {
  product(id: $id) {
    id handle status
    variants(first: 100) { nodes { id selectedOptions { name value } inventoryItem { id } } }
  }
}"""

_M_PRODUCT_CREATE = """
mutation($product: ProductCreateInput!, $media: [CreateMediaInput!]) {
  productCreate(product: $product, media: $media) {
    product { id handle status }
    userErrors { field message }
  }
}"""

_M_VARIANTS_CREATE = """
mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkCreate(productId: $productId, variants: $variants) {
    productVariants { id selectedOptions { name value } inventoryItem { id } }
    userErrors { field message }
  }
}"""

_M_VARIANTS_UPDATE = """
mutation($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id }
    userErrors { field message }
  }
}"""

_M_INV_SET = """
mutation($input: InventorySetQuantitiesInput!) {
  inventorySetQuantities(input: $input) { userErrors { field message } }
}"""

_M_INV_ADJUST = """
mutation($input: InventoryAdjustQuantitiesInput!) {
  inventoryAdjustQuantities(input: $input) { userErrors { field message } }
}"""

_Q_PUBLICATIONS = "query { publications(first: 30) { nodes { id name } } }"

_M_PUBLISH = """
mutation($id: ID!, $input: [PublicationInput!]!) {
  publishablePublish(id: $id, input: $input) { userErrors { field message } }
}"""

_M_PRODUCT_UPDATE = """
mutation($product: ProductUpdateInput!) {
  productUpdate(product: $product) { product { id status } userErrors { field message } }
}"""


def _mutate(self, query: str, variables: dict, key: str) -> dict:
    data = self._request(query, variables)["data"][key]
    errs = data.get("userErrors") or []
    if errs:
        raise ShopifyUserError("; ".join(f"{'.'.join(map(str, e.get('field') or []))}: {e['message']}" for e in errs))
    return data


def fetch_variants(self, ids: list[str]) -> dict[str, dict]:
    """Fresh data (price, cost, weight, per-location 'available', product info) keyed by variant GID."""
    out: dict[str, dict] = {}
    for i in range(0, len(ids), 10):
        for node in self._request(_Q_VARIANTS_FRESH, {"ids": ids[i:i + 10]})["data"]["nodes"]:
            if node:
                out[node["id"]] = node
    return out


def available_at(node: dict, location_id: str) -> int:
    for lvl in ((node.get("inventoryItem") or {}).get("inventoryLevels") or {}).get("nodes", []):
        if lvl["location"]["id"] == location_id:
            for q in lvl.get("quantities") or []:
                if q["name"] == "available":
                    return int(q["quantity"])
    return 0


def primary_location_id(self) -> str:
    nodes = self._request(_Q_LOCATIONS)["data"]["locations"]["nodes"]
    for n in nodes:
        if n.get("isPrimary"):
            return n["id"]
    if nodes:
        return nodes[0]["id"]
    raise RuntimeError("No Shopify locations found")


def create_product(self, product: dict, media: list[dict]) -> dict:
    return self._mutate(_M_PRODUCT_CREATE, {"product": product, "media": media or None}, "productCreate")["product"]


def get_product_variants(self, product_id: str) -> list[dict]:
    p = self._request(_Q_PRODUCT_VARIANTS, {"id": product_id})["data"]["product"]
    return p["variants"]["nodes"] if p else []


def bulk_create_variants(self, product_id: str, variants: list[dict]) -> list[dict]:
    if not variants:
        return []
    return self._mutate(_M_VARIANTS_CREATE, {"productId": product_id, "variants": variants},
                        "productVariantsBulkCreate")["productVariants"]


def bulk_update_variants(self, product_id: str, variants: list[dict]) -> None:
    if variants:
        self._mutate(_M_VARIANTS_UPDATE, {"productId": product_id, "variants": variants}, "productVariantsBulkUpdate")


def set_quantities(self, location_id: str, items: list[tuple[str, int]]) -> None:
    if items:
        self._mutate(_M_INV_SET, {"input": {
            "name": "available", "reason": "correction", "ignoreCompareQuantity": True,
            "quantities": [{"inventoryItemId": i, "locationId": location_id, "quantity": q} for i, q in items],
        }}, "inventorySetQuantities")


def adjust_quantities(self, location_id: str, items: list[tuple[str, int]]) -> None:
    if items:
        self._mutate(_M_INV_ADJUST, {"input": {
            "name": "available", "reason": "correction",
            "changes": [{"inventoryItemId": i, "locationId": location_id, "delta": d} for i, d in items],
        }}, "inventoryAdjustQuantities")


def set_product_status(self, product_id: str, status: str) -> None:
    self._mutate(_M_PRODUCT_UPDATE, {"product": {"id": product_id, "status": status}}, "productUpdate")


def online_store_publication_id(self) -> str:
    for n in self._request(_Q_PUBLICATIONS)["data"]["publications"]["nodes"]:
        if (n.get("name") or "").strip().lower() == "online store":
            return n["id"]
    raise RuntimeError("Online Store publication not found (token needs read_publications / write_publications)")


def publish_product(self, product_id: str, publication_id: str) -> None:
    self._mutate(_M_PUBLISH, {"id": product_id, "input": [{"publicationId": publication_id}]}, "publishablePublish")


for _fn in (online_store_publication_id, publish_product, _mutate, fetch_variants, primary_location_id, create_product, get_product_variants,
            bulk_create_variants, bulk_update_variants, set_quantities, adjust_quantities, set_product_status):
    setattr(ShopifyClient, _fn.__name__, _fn)
ShopifyClient.available_at = staticmethod(available_at)
