"""
Shopify GraphQL client.
Handles auth, pagination, rate limiting, retries, and response normalization.
"""

import logging
import time
from typing import Generator, Literal, Optional

import requests

import config
from credentials import CredentialStore

logger: logging.Logger = logging.getLogger(__name__)
_creds = CredentialStore()

PAGE_SIZE: Literal[25] = config.SHOPIFY_PAGE_SIZE

# ── GraphQL ───────────────────────────────────────────────────────────

PRODUCTS_QUERY = """
query($cursor: String, $query: String, $page_size: Int) {
  products(first: $page_size, after: $cursor, query: $query) {
    pageInfo { hasNextPage endCursor }
    nodes {
      id title vendor status tags updatedAt productType

      media(first: 3) {
        nodes {
          preview {
            image { url }
          }
        }
      }

      variants(first: 2) {
        nodes {
          id price inventoryQuantity taxable updatedAt
          inventoryItem {
            unitCost { amount }
            measurement {
              weight { value unit }
            }
          }
        }
      }

      upc: metafield(namespace: "facts", key: "upc") {
        value
      }

      musicGenre: metafield(namespace: "shopify", key: "music-genre") {
        references(first: 3) {
          nodes {
            ... on Metaobject {
              fields { value }
            }
          }
        }
      }
    }
  }
}
"""

CREATE_PRODUCT_MUTATION = """
mutation productCreate($input: ProductInput!) {
  productCreate(input: $input) {
    product { id }
    userErrors { field message }
  }
}
"""

UPDATE_PRODUCT_MUTATION = """
mutation productUpdate($input: ProductInput!) {
  productUpdate(input: $input) {
    product { id }
    userErrors { field message }
  }
}
"""

DELETE_PRODUCT_MUTATION = """
mutation productDelete($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors { field message }
  }
}
"""

TOTAL_PRODUCTS_COUNT_QUERY = """
query($query: String) {
  productsCount(query: $query) {
    count
  }
}
"""

# ── Client ────────────────────────────────────────────────────────────

class ShopifyClient:
    def __init__(self):
        self._token: Optional[str] = None
        self._url: Optional[str] = None

    # ── Config ────────────────────────────────────────────────────────

    @property
    def token(self) -> str:
        if self._token is None:
            key: Literal['test_shopify_token'] | Literal['shopify_token'] = "test_shopify_token" if config.IS_TEST_MODE else "shopify_token"
            self._token = _creds.get(key)
        return self._token

    @property
    def url(self) -> str:
        if self._url is None:
            self._url = (
                config.TEST_SHOPIFY_GRAPHQL_URL
                if config.IS_TEST_MODE
                else config.SHOPIFY_GRAPHQL_URL
            )
        return self._url

    @property
    def headers(self) -> dict:
        return {
            "Content-Type": "application/json",
            "X-Shopify-Access-Token": self.token,
        }

    # ── Core request ──────────────────────────────────────────────────

    def _request(self, query: str, variables: dict | None = None, retries: int = 3) -> dict:
        payload = {"query": query, "variables": variables or {}}

        for attempt in range(retries):
            wait = 2 ** attempt

            try:
                resp: requests.Response = requests.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=30,
                )

                if resp.status_code == 429:
                    logger.warning(f"Rate limited — retrying in {wait}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if "errors" in data:
                    raise RuntimeError(f"GraphQL errors: {data['errors']}")

                return data

            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise
                logger.warning(f"Request failed ({e}) — retrying in {wait}s")
                time.sleep(wait)

        raise RuntimeError("Shopify request failed after retries")
    
    def _count_request(self, retries: int = 3) -> dict:
        for attempt in range(retries):
            wait = 2 ** attempt

            try:
                resp: requests.Response = requests.post(
                    self.url,
                    headers=self.headers,
                    timeout=30,
                )

                if resp.status_code == 429:
                    logger.warning(f"Rate limited — retrying in {wait}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if "errors" in data:
                    raise RuntimeError(f"Product count errors: {data['errors']}")

                return data

            except requests.RequestException as e:
                if attempt == retries - 1:
                    raise
                logger.warning(f"Request failed ({e}) — retrying in {wait}s")
                time.sleep(wait)

        raise RuntimeError("Shopify request failed after retries")

    # ── Read ──────────────────────────────────────────────────────────

    def fetch_products_count(self, since: Optional[str] = None) -> int:
        query_filter: str | None = f'updated_at:>"{since}"' if since else None
        data = self._request(
            TOTAL_PRODUCTS_COUNT_QUERY,
            {
                "query": query_filter
            }
        )
        count = data["data"]["productsCount"]["count"]
        if count and count >= 0:
            return count
        return -1

    def fetch_all_products(self, since: Optional[str] = None) -> Generator[dict, None, None]:
        cursor = None
        query_filter: str | None = f'updated_at:>"{since}"' if since else None

        while True:
            data = self._request(
                PRODUCTS_QUERY,
                {
                    "cursor": cursor,
                    "query": query_filter,
                    "page_size": PAGE_SIZE,
                },
            )

            page = data["data"]["products"]

            for node in page["nodes"]:
                yield self._map_product(node)

            if not page["pageInfo"]["hasNextPage"]:
                break

            cursor = page["pageInfo"]["endCursor"]

    # ── Write ─────────────────────────────────────────────────────────

    def create_product(self, input_data: dict) -> str:
        data = self._request(CREATE_PRODUCT_MUTATION, {"input": input_data})
        result = data["data"]["productCreate"]
        self._raise_on_user_errors(result["userErrors"])
        product = result.get("product")
        if not product:
            raise RuntimeError("No product returned")
        return product["id"]

    def update_product(self, input_data: dict) -> str:
        data = self._request(UPDATE_PRODUCT_MUTATION, {"input": input_data})
        result = data["data"]["productUpdate"]
        self._raise_on_user_errors(result["userErrors"])
        product = result.get("product")
        if not product:
            raise RuntimeError("No product returned")
        return result["product"]["id"]

    def delete_product(self, product_id: str) -> str:
        data = self._request(DELETE_PRODUCT_MUTATION, {"input": {"id": product_id}})
        result = data["data"]["productDelete"]
        self._raise_on_user_errors(result["userErrors"])
        return result["deletedProductId"]

    # ── Mapping ───────────────────────────────────────────────────────

    def _map_product(self, node: dict) -> dict:
        return {
            "product_id": node["id"],
            "title": node["title"],
            "vendor": node["vendor"],
            "status": node["status"],
            "tags": node.get("tags") or [],
            "product_type": node.get("productType"),
            "updated_at": node.get("updatedAt"),
            "upc": node.get("upc", {}).get("value") if node.get("upc") else None,
            "images": [
                m["preview"]["image"]["url"]
                for m in node.get("media", {}).get("nodes", [])
                if m.get("preview") and m["preview"].get("image")
            ],
            "variants": [
                {
                    "id": v["id"],
                    "price": float(v["price"]),
                    "inventory_quantity": v.get("inventoryQuantity"),
                    "taxable": v.get("taxable", True),
                    "cost": (
                        float(v["inventoryItem"]["unitCost"]["amount"])
                        if v.get("inventoryItem") and v["inventoryItem"].get("unitCost")
                        else None
                    ),
                    "weight": (
                        v["inventoryItem"]["measurement"]["weight"]["value"]
                        if v.get("inventoryItem") and v["inventoryItem"].get("measurement")
                        else None
                    ),
                    "weight_unit": (
                        v["inventoryItem"]["measurement"]["weight"]["unit"]
                        if v.get("inventoryItem") and v["inventoryItem"].get("measurement")
                        else None
                    ),
                    "updated_at": v.get("updatedAt"),
                }
                for v in node.get("variants", {}).get("nodes", [])
            ],
        }

    # ── Errors ────────────────────────────────────────────────────────

    @staticmethod
    def _raise_on_user_errors(errors: list[dict]) -> None:
        if errors:
            msg: str = "; ".join(f"{e.get('field')}: {e.get('message')}" for e in errors)
            raise RuntimeError(f"Shopify userErrors: {msg}")