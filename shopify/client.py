import logging
import time
from typing import Any, Optional

import requests
import config

logger = logging.getLogger(__name__)

# ─── GID helpers ─────────────────────────────────────────────────────────────

def _gid(type_: str, id_: str) -> str:
    """Numeric or existing GID → full GID."""
    s = str(id_ or "")
    return s if s.startswith("gid://") else f"gid://shopify/{type_}/{s}"

def strip_gid(gid_or_num: str) -> str:
    """'gid://shopify/Product/123' → '123'  (safe to call on plain numbers too)."""
    s = str(gid_or_num or "")
    return s.split("/")[-1] if "/" in s else s

# ─── Queries / Mutations ──────────────────────────────────────────────────────

_Q_PRODUCTS = """
query GetProducts($first: Int!, $after: String, $query: String) {
  products(first: $first, after: $after, query: $query) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title vendor status tags handle updatedAt productType
      category { id name }
      upc:        metafield(namespace: "custom",  key: "upc")        { value }
      genres: metafield(namespace: "shopify", key: "music-genres") { value }
      media(first: 3) {
        nodes { id preview { image { url } } }
      }
      variants(first: 2) {
        nodes {
          id title barcode price sku
          inventoryQuantity
          inventoryItem {
            id
            unitCost { amount currencyCode }
            measurement { weight { value unit } }
          }
        }
      }
    }
  }
}
"""

_Q_LOCATIONS = "query { locations(first: 10) { nodes { id name isPrimary } } }"

_M_ADJUST = """
mutation AdjustInventory($input: InventoryAdjustQuantitiesInput!) {
  inventoryAdjustQuantities(input: $input) {
    inventoryAdjustmentGroup { createdAt }
    userErrors { field message }
  }
}"""

_M_PRICE = """
mutation UpdateVariantPrice($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price }
    userErrors { field message }
  }
}"""

_M_UPDATE_PRODUCT = """
mutation UpdateProduct($input: ProductInput!) {
  productUpdate(input: $input) {
    product { id title vendor }
    userErrors { field message }
  }
}"""

_M_METAFIELDS = """
mutation SetMetafields($metafields: [MetafieldsSetInput!]!) {
  metafieldsSet(metafields: $metafields) {
    metafields { key value }
    userErrors { field message }
  }
}"""

_M_MEDIA = """
mutation CreateProductMedia($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media { ... on MediaImage { id image { url } } }
    userErrors { field message }
  }
}"""

_M_VARIANT_BULK = """
mutation UpdateVariant($productId: ID!, $variants: [ProductVariantsBulkInput!]!) {
  productVariantsBulkUpdate(productId: $productId, variants: $variants) {
    productVariants { id price }
    userErrors { field message }
  }
}"""

_M_INVENTORY_COST = """
mutation UpdateInventoryCost($id: ID!, $input: InventoryItemUpdateInput!) {
  inventoryItemUpdate(id: $id, input: $input) {
    inventoryItem { id unitCost { amount } }
    userErrors { field message }
  }
}"""


_Q_ORDERS_LINE_ITEMS = """
query OrdersForLastSold($first: Int!, $after: String) {
  orders(first: $first, after: $after, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    nodes {
      name
      createdAt
      lineItems(first: 50) {
        nodes { title vendor }
      }
    }
  }
}
"""

class ShopifyClient:
    def __init__(self, store: str, token: str, api_version: str = None):
        self.store   = store.rstrip("/")
        self.token   = token
        self.version = api_version or config.SHOPIFY_API_VERSION
        self.url     = f"https://{self.store}/admin/api/{self.version}/graphql.json"
        self._s      = requests.Session()
        self._s.headers.update({
            "Content-Type":           "application/json",
            "X-Shopify-Access-Token": self.token,
        })

    # ── Core GQL with rate-limit handling ─────────────────────────────────────

    def gql(self, query: str, variables: dict = None) -> dict:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        for attempt in range(4):
            resp = self._s.post(self.url, json=payload, timeout=30)

            # 429 - respect Retry-After header
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2))
                logger.warning(f"Shopify 429 - sleeping {wait}s (attempt {attempt+1})")
                time.sleep(wait)
                continue

            resp.raise_for_status()
            body = resp.json()

            # Throttle check - slow down when bucket is nearly empty
            throttle = (
                (body.get("extensions") or {})
                .get("cost", {})
                .get("throttleStatus", {})
            )
            available = throttle.get("currentlyAvailable", 1000)
            restore   = throttle.get("restoreRate", 50)
            if available < 150:
                wait = max(1.0, (150 - available) / max(restore, 1))
                logger.info(f"Shopify bucket low ({available}) - sleeping {wait:.1f}s")
                time.sleep(wait)

            errors = body.get("errors", [])
            if errors:
                if any("throttled" in str(e).lower() for e in errors):
                    logger.warning(f"Shopify throttled - sleeping 3s (attempt {attempt+1})")
                    time.sleep(3)
                    continue
                raise RuntimeError(f"Shopify GQL error: {errors}")

            return body.get("data", {})

        raise RuntimeError("Shopify API rate limit exceeded after retries")

    def _check(self, data: dict, key: str) -> None:
        errs = (data.get(key) or {}).get("userErrors", [])
        if errs:
            raise RuntimeError(f"Shopify {key}: {errs}")

    # ── Products ──────────────────────────────────────────────────────────────

    def iter_all_products(self, query: str = None, page_delay: float = 0.5):
        """Yields each product node. page_delay avoids hammering the bucket."""
        cursor = None
        while True:
            data = self.gql(_Q_PRODUCTS, {"first": config.SHOPIFY_PAGE_SIZE, "after": cursor, "query": query})
            page = data.get("products", {})
            for node in page.get("nodes", []):
                yield node
            info = page.get("pageInfo", {})
            if not info.get("hasNextPage"):
                break
            cursor = info["endCursor"]
            time.sleep(page_delay)

    # ── Locations ─────────────────────────────────────────────────────────────

    def get_primary_location_id(self) -> Optional[str]:
        data  = self.gql(_Q_LOCATIONS)
        nodes = (data.get("locations") or {}).get("nodes", [])
        for n in nodes:
            if n.get("isPrimary"):
                return n["id"]
        return nodes[0]["id"] if nodes else None

    # ── Inventory ─────────────────────────────────────────────────────────────

    def adjust_inventory(self, inventory_item_id: str, location_id: str, delta: int) -> dict:
        data = self.gql(_M_ADJUST, {"input": {
            "reason": "received", "name": "available",
            "changes": [{
                "inventoryItemId": _gid("InventoryItem", inventory_item_id),
                "locationId":      location_id,   # already full GID from Shopify
                "delta":           delta,
            }],
        }})
        self._check(data, "inventoryAdjustQuantities")
        return data

    # ── Pricing ───────────────────────────────────────────────────────────────

    def update_variant_price(self, product_id: str, variant_id: str, price: str) -> dict:
        data = self.gql(_M_PRICE, {
            "productId": _gid("Product", product_id),
            "variants":  [{"id": _gid("ProductVariant", variant_id), "price": price}],
        })
        self._check(data, "productVariantsBulkUpdate")
        return data

    # ── Product update ────────────────────────────────────────────────────────

    def update_product(self, product_input: dict) -> dict:
        inp = dict(product_input)
        if "id" in inp:
            inp["id"] = _gid("Product", inp["id"])
        data = self.gql(_M_UPDATE_PRODUCT, {"input": inp})
        self._check(data, "productUpdate")
        return data

    # ── Metafields ────────────────────────────────────────────────────────────

    def set_metafields(self, owner_id: str, metafields: list[dict]) -> dict:
        gid_owner = _gid("Product", owner_id)
        for m in metafields:
            m.setdefault("ownerId", gid_owner)
        data = self.gql(_M_METAFIELDS, {"metafields": metafields})
        self._check(data, "metafieldsSet")
        return data

    # ── Media ─────────────────────────────────────────────────────────────────

    def create_media_from_urls(self, product_id: str, urls: list[str]) -> dict:
        data = self.gql(_M_MEDIA, {
            "productId": _gid("Product", product_id),
            "media": [{"originalSource": u, "mediaContentType": "IMAGE"} for u in urls],
        })
        self._check(data, "productCreateMedia")
        return data

    # ── Variant bulk ──────────────────────────────────────────────────────────

    def update_variant_bulk(self, product_id: str, variant_id: str,
                            price: str = None, weight: float = None,
                            weight_unit: str = None) -> dict:
        v: dict = {"id": _gid("ProductVariant", variant_id)}
        if price is not None:
            v["price"] = price
        if weight is not None and weight_unit:
            v["inventoryItem"] = {
                "measurement": {"weight": {"value": weight, "unit": weight_unit.upper()}}
            }
        data = self.gql(_M_VARIANT_BULK, {
            "productId": _gid("Product", product_id),
            "variants":  [v],
        })
        self._check(data, "productVariantsBulkUpdate")
        return data
    
    def update_inventory_item_cost(self, inventory_item_id: str, cost: float) -> dict:
        data = self.gql(_M_INVENTORY_COST, {
            "id":    _gid("InventoryItem", inventory_item_id),
            "input": {"cost": f"{cost:.2f}"},
        })
        self._check(data, "inventoryItemUpdate")
        return data


    # def iter_orders_with_line_items(self, page_delay: float = 0.5):
    #     cursor = None
    #     while True:
    #         data = self.gql(_Q_ORDERS_LINE_ITEMS, {"first": 50, "after": cursor})
    #         page = data.get("orders", {})
    #         for node in page.get("nodes", []):
    #             yield node
    #         info = page.get("pageInfo", {})
    #         if not info.get("hasNextPage"):
    #             break
    #         cursor = info["endCursor"]
    #         time.sleep(page_delay)

    def iter_orders_with_line_items(self, page_delay: float = 0.5):
        cursor = None
        count = 0

        while True:
            data = self.gql(
                _Q_ORDERS_LINE_ITEMS,
                {"first": 50, "after": cursor}
            )

            page = data.get("orders", {})

            for node in page.get("nodes", []):
                count += 1
                yield node

            info = page.get("pageInfo", {})

            print(
                f"Page complete: {count} orders total | "
                f"hasNextPage={info.get('hasNextPage')}"
            )

            if not info.get("hasNextPage"):
                break

            cursor = info["endCursor"]
            time.sleep(page_delay)