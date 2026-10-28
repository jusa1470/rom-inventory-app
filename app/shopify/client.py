import logging
import requests
import time
from typing import Any, Iterator, Optional

from app import config
from app.shopify.queries import (
    Q_LOCATIONS,
    Q_MORE_VARIANTS,
    Q_PRODUCTS,
    Q_PRODUCTS_COUNT,
    VARIANT_METAFIELDS,
    vars_from_cfg,
)

logger: logging.Logger = logging.getLogger(__name__)


class ShopifyClient:
    def __init__(self, store: str, token: str, api_version: str):
        self.store: str = store.rstrip("/")
        self.token: str = token
        self.version: str = api_version
        self.url: str = f"https://{self.store}/admin/api/{self.version}/graphql.json"
        self._s = requests.Session()
        self._s.headers.update(
            {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.token,
            }
        )

    # ── Core GQL with rate-limit handling ─────────────────────────────────────

    def gql(self, query: str, variables: Optional[dict] = None) -> dict:
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        for attempt in range(4):
            resp = self._s.post(self.url, json=payload, timeout=30)

            # 429 - respect Retry-After header
            if resp.status_code == 429:
                wait = float(resp.headers.get("Retry-After", 2))
                logger.warning(
                    "Shopify 429 - sleeping %ss (attempt %d)", wait, attempt + 1
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            body = resp.json()

            # Throttle check - slow down when the cost bucket is nearly empty
            throttle = (
                (body.get("extensions") or {}).get("cost", {}).get("throttleStatus", {})
            )
            available = throttle.get("currentlyAvailable", 1000)
            cost = (body.get("extensions") or {}).get("cost", {})
            available = throttle.get("currentlyAvailable", 1000)
            restore = throttle.get("restoreRate", 50)
            requested = cost.get("requestedQueryCost", 0)
            logger.debug(
                "Shopify cost: requested %s, actual %s, available %s",
                requested, cost.get("actualQueryCost"), available,
            )
            # The next request is rejected unless the bucket holds its requested cost.
            if available < requested:
                wait = (requested - available) / max(restore, 1)
                logger.debug(
                    "Shopify bucket low (%s < %s) - sleeping %.1fs", available, requested, wait
                )
                time.sleep(wait)

            errors = body.get("errors", [])
            if errors:
                if any("throttled" in str(e).lower() for e in errors):
                    logger.warning(
                        "Shopify throttled - sleeping 3s (attempt %d)", attempt + 1
                    )
                    time.sleep(3)
                    continue
                raise RuntimeError(f"Shopify GQL error: {errors}")

            return body.get("data") or {}

        raise RuntimeError("Shopify API rate limit exceeded after retries")

    # ── Products ──────────────────────────────────────────────────────────────
    
    def count_products(self, query: Optional[str] = None) -> int:
        data = self.gql(Q_PRODUCTS_COUNT, {"query": query})
        return int((data.get("productsCount") or {}).get("count") or 0)

    def _fetch_remaining_variants(
        self, product_id: str, after: str, cfg: dict
    ) -> list[dict]:
        """Variants beyond the first page of a product, following the cursor."""
        variables: dict[str, str] = vars_from_cfg(cfg, VARIANT_METAFIELDS)
        variables["variantFirst"] = config.SHOPIFY_VARIANT_PAGE_SIZE
        nodes: list[dict] = []
        cursor: Optional[str] = after
        while cursor:
            data = self.gql(
                Q_MORE_VARIANTS, {**variables, "id": product_id, "after": cursor}
            )
            page = ((data.get("product") or {}).get("variants")) or {}
            nodes.extend(page.get("nodes", []))
            info = page.get("pageInfo") or {}
            cursor = info.get("endCursor") if info.get("hasNextPage") else None
        return nodes

    def iter_all_products(
        self, cfg: dict, query: Optional[str] = None
    ) -> Iterator[dict]:
        """Yield each product node with its complete variants list."""
        base: dict[str, str] = vars_from_cfg(cfg)
        cursor: Optional[str] = None
        while True:
            data = self.gql(
                Q_PRODUCTS,
                {
                    **base,
                    "first": config.SHOPIFY_PAGE_SIZE,
                    "variantFirst": config.SHOPIFY_VARIANT_PAGE_SIZE,
                    "after": cursor,
                    "query": query,
                },
            )
            page = data.get("products") or {}
            for node in page.get("nodes", []):
                variants = node.get("variants") or {}
                info = variants.get("pageInfo") or {}
                if info.get("hasNextPage"):
                    variants.setdefault("nodes", []).extend(
                        self._fetch_remaining_variants(
                            node["id"], info["endCursor"], cfg
                        )
                    )
                yield node
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                break
            cursor = info["endCursor"]

    # ── Locations ─────────────────────────────────────────────────────────────

    def get_primary_location_id(self) -> Optional[str]:
        data = self.gql(Q_LOCATIONS)
        nodes = (data.get("locations") or {}).get("nodes", [])
        for n in nodes:
            if n.get("isPrimary"):
                return n["id"]
        return nodes[0]["id"] if nodes else None
