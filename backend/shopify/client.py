# """
# Shopify GraphQL client.
# Handles pagination, rate limiting, and response parsing.
# """

# import logging
# import time
# from typing import Optional

# import requests

# import config as config
# from credentials import CredentialStore

# logger = logging.getLogger(__name__)
# _creds = CredentialStore()

# PAGE_SIZE = config.SHOPIFY_PAGE_SIZE

# PRODUCTS_QUERY = """
# query($cursor: String, $query: String, $page_size: Int) {
#   products(first: $page_size, after: $cursor, query: $query) {
#     pageInfo { hasNextPage endCursor }
#     nodes {
#       id title vendor status description tags updatedAt productType
#       category { fullName name }
#       media(first: 3) { 
#         nodes {
#           preview {
#             image {
#               url
#             }
#           }
#         }
#       }
#       variants(first: 2) {
#         nodes {
#           id price inventoryQuantity taxable updatedAt
#           inventoryItem {
#             unitCost { amount }
#             measurement {
#               weight {
#                 value unit
#               }
#             }
#           }
#         }
#       }

#       upc: metafield(namespace: "facts", key: "upc") {
#         value
#       }

#       musicGenre: metafield(namespace: "shopify", key: "music-genre") {
#         references(first: 3) {
#           nodes {
#             ... on Metaobject {
#               fields {
#                 value
#               }
#             }
#           }
#         }
#       }
#     }
#   }
# }
# """

# CREATE_PRODUCT_MUTATION = """
# mutation productCreate($input: ProductInput!) {
#   productCreate(input: $input) {
#     product { id }
#     userErrors { field message }
#   }
# }
# """

# UPDATE_PRODUCT_MUTATION = """
# mutation productUpdate($input: ProductInput!) {
#   productUpdate(input: $input) {
#     product { id }
#     userErrors { field message }
#   }
# }
# """

# DELETE_PRODUCT_MUTATION = """
# mutation productDelete($input: ProductDeleteInput!) {
#   productDelete(input: $input) {
#     deletedProductId
#     userErrors { field message }
#   }
# }
# """


# class ShopifyClient:
#     def __init__(self):
#         self._token: str | None = None
#         self._shop_graphql_url: str | None = None

#     @property
#     def token(self) -> str:
#         if self._token is None:
#             if config.IS_TEST_MODE:
#                 self._token = _creds.get("test_shopify_token")
#                 logger.info("Test mode enabled — using test Shopify token")
#             else:
#                 self._token = _creds.get("shopify_token")
#         return self._token

#     @property
#     def headers(self) -> dict:
#         return {
#             "Content-Type": "application/json",
#             "X-Shopify-Access-Token": self.token,
#         }
    
#     @property
#     def shop_graphql_url(self) -> str:
#         if self._shop_graphql_url is None:
#             if config.IS_TEST_MODE:
#                 self._shop_graphql_url = config.TEST_SHOPIFY_GRAPHQL_URL
#                 logger.info(f"Test mode enabled — using shop {self._shop_graphql_url}")
#             else:
#                 self._shop_graphql_url = config.SHOPIFY_GRAPHQL_URL
#         return self._shop_graphql_url

#     def _request(self, query: str, variables: dict | None = None,
#                  retries: int = 3) -> dict:
#         """Execute a GraphQL query/mutation with retry on rate limit."""
#         if self.shop_graphql_url is None:
#             raise RuntimeError("Shopify GraphQL URL not configured")
#         payload = {"query": query, "variables": variables or {}}
#         for attempt in range(retries):
#             resp = requests.post(
#                 self._shop_graphql_url or "<URL_NOT_CONFIGURED>",
#                 json=payload,
#                 headers=self.headers,
#             )
#             if resp.status_code == 429:
#                 wait = 2 ** attempt
#                 logger.warning(f"Shopify rate limited — retrying in {wait}s")
#                 time.sleep(wait)
#                 continue
#             resp.raise_for_status()
#             data = resp.json()
#             if "errors" in data:
#               raise RuntimeError(f"Shopify GraphQL errors: {data['errors']}")
#             return data
#         raise RuntimeError("Shopify request failed after retries")
    
#     def _map_product(self, node: dict) -> dict:
#       return {
#           "product_id": node["id"],
#           "title": node["title"],
#           "vendor": node["vendor"],
#           "status": node["status"],
#           "tags": node.get("tags", []),
#           "product_type": node.get("productType"),
#           "updated_at": node.get("updatedAt"),
#           "upc": node.get("upc", {}).get("value") if node.get("upc") else None,
#           "variants": node.get("variants", {}).get("nodes", []),
#           "images": [
#               m["preview"]["image"]["url"]
#               for m in node.get("media", {}).get("nodes", [])
#               if m.get("preview") and m["preview"].get("image")
#           ],
#       }

#     # ── Read ─────────────────────────────────────────────────────────

#     def fetch_all_products(self, since: Optional[str] = None):
#       cursor = None
#       query_filter = f'updated_at:>"{since}"' if since else None

#       while True:
#           data = self._request(
#               PRODUCTS_QUERY,
#               {"cursor": cursor, "query": query_filter, "page_size": PAGE_SIZE},
#           )

#           page = data["data"]["products"]

#           for node in page["nodes"]:
#               yield self._map_product(node)

#           if not page["pageInfo"]["hasNextPage"]:
#               break

#           cursor = page["pageInfo"]["endCursor"]

#     # ── Write ─────────────────────────────────────────────────────────

#     def create_product(self, input_data: dict) -> str:
#       data = self._request(CREATE_PRODUCT_MUTATION, {"input": input_data})
#       result = data["data"]["productCreate"]

#       self._raise_on_user_errors(result["userErrors"])

#       product = result.get("product")
#       if not product:
#           raise RuntimeError("Shopify returned no product")

#       return product["id"]

#     def update_product(self, input_data: dict) -> str:
#         """input_data must include 'id'. Returns product GID."""
#         data = self._request(UPDATE_PRODUCT_MUTATION, {"input": input_data})
#         result = data["data"]["productUpdate"]
#         self._raise_on_user_errors(result["userErrors"])
#         return result["product"]["id"]

#     def delete_product(self, product_id: str) -> str:
#         """Returns the deleted product GID."""
#         data = self._request(DELETE_PRODUCT_MUTATION, {"input": {"id": product_id}})
#         result = data["data"]["productDelete"]
#         self._raise_on_user_errors(result["userErrors"])
#         return result["deletedProductId"]

#     def bulk_delete_products(self, product_ids: list[str]) -> dict:
#         results = {"deleted": [], "failed": []}
#         for sid in product_ids:
#             try:
#                 self.delete_product(sid)
#                 results["deleted"].append(sid)
#             except Exception:
#                 logger.exception(f"Delete failed for {sid}")
#                 results["failed"].append(sid)
#         return results

#     @staticmethod
#     def _raise_on_user_errors(errors: list[dict]) -> None:
#         if errors:
#             msg = "; ".join(f"{e['field']}: {e['message']}" for e in errors)
#             raise RuntimeError(f"Shopify userErrors: {msg}")



"""
Shopify GraphQL client.
Handles:
- Auth + headers
- Pagination
- Rate limiting + retries
- Response normalization (NO raw GraphQL leaks)
"""

import logging
import time
from typing import Generator, Optional

import requests

import config
from credentials import CredentialStore

logger = logging.getLogger(__name__)
_creds = CredentialStore()

PAGE_SIZE = config.SHOPIFY_PAGE_SIZE


# ── GraphQL ──────────────────────────────────────────────────────────

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


# ── Client ───────────────────────────────────────────────────────────

class ShopifyClient:
    def __init__(self):
        self._token: Optional[str] = None
        self._url: Optional[str] = None

    # ── Config ───────────────────────────────────────────────────────

    @property
    def token(self) -> str:
        if self._token is None:
            key = "test_shopify_token" if config.IS_TEST_MODE else "shopify_token"
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

    # ── Core request ─────────────────────────────────────────────────

    def _request(self, query: str, variables: dict | None = None, retries: int = 3) -> dict:
        payload = {"query": query, "variables": variables or {}}

        for attempt in range(retries):
            try:
                resp = requests.post(
                    self.url,
                    json=payload,
                    headers=self.headers,
                    timeout=30,
                )

                if resp.status_code == 429:
                    wait = 2 ** attempt
                    logger.warning(f"Rate limited — retrying in {wait}s")
                    time.sleep(wait)
                    continue

                resp.raise_for_status()
                data = resp.json()

                if "errors" in data:
                    raise RuntimeError(f"GraphQL errors: {data['errors']}")

                return data

            except requests.RequestException as e:
                wait = 2 ** attempt
                logger.warning(f"Request failed ({e}) — retrying in {wait}s")
                time.sleep(wait)

        raise RuntimeError("Shopify request failed after retries")

    # ── Public: Read ─────────────────────────────────────────────────

    def fetch_all_products(self, since: Optional[str] = None) -> Generator[dict, None, None]:
        """
        Returns normalized product dicts.
        No raw GraphQL leaves this client.
        """
        cursor = None
        query_filter = f'updated_at:>"{since}"' if since else None

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

    # ── Public: Write ────────────────────────────────────────────────

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

        return product["id"]

    def delete_product(self, product_id: str) -> str:
        data = self._request(
            DELETE_PRODUCT_MUTATION,
            {"input": {"id": product_id}},
        )

        result = data["data"]["productDelete"]
        self._raise_on_user_errors(result["userErrors"])

        return result["deletedProductId"]

    def bulk_delete_products(self, product_ids: list[str]) -> dict:
        results = {"deleted": [], "failed": []}

        for pid in product_ids:
            try:
                self.delete_product(pid)
                results["deleted"].append(pid)
            except Exception:
                logger.exception(f"Delete failed for {pid}")
                results["failed"].append(pid)

        return results

    # ── Mapping (CRITICAL LAYER) ─────────────────────────────────────

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
                        if v.get("inventoryItem")
                        and v["inventoryItem"].get("unitCost")
                        else None
                    ),
                    "weight": (
                        v["inventoryItem"]["measurement"]["weight"]["value"]
                        if v.get("inventoryItem")
                        and v["inventoryItem"].get("measurement")
                        else None
                    ),
                    "weight_unit": (
                        v["inventoryItem"]["measurement"]["weight"]["unit"]
                        if v.get("inventoryItem")
                        and v["inventoryItem"].get("measurement")
                        else None
                    ),
                    "updated_at": v.get("updatedAt"),
                }
                for v in node.get("variants", {}).get("nodes", [])
            ],
        }

    # ── Errors ───────────────────────────────────────────────────────

    @staticmethod
    def _raise_on_user_errors(errors: list[dict]) -> None:
        if errors:
            msg = "; ".join(
                f"{e.get('field')}: {e.get('message')}"
                for e in errors
            )
            raise RuntimeError(f"Shopify userErrors: {msg}")