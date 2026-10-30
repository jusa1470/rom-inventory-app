import json
import logging
import requests
import time
from typing import Any, Callable, Iterator, Optional

from app import config
from app.shopify.queries import (
    BULK_PRODUCT_MF,
    BULK_VARIANT_MF,
    M_BULK_CANCEL,
    M_BULK_RUN,
    M_INVENTORY_SET,
    M_PRODUCT_UPDATE,
    M_VARIANTS_UPDATE,
    Q_BULK_STATUS,
    Q_PRODUCT_OPTIONS,
    Q_TAXONOMY,
    bulk_products_query,
    Q_LOCATIONS,
    Q_MORE_VARIANTS,
    Q_PRODUCTS,
    Q_PRODUCTS_COUNT,
    VARIANT_METAFIELDS,
    vars_from_cfg,
)

logger: logging.Logger = logging.getLogger(__name__)


def _mfs(f: dict, entries: list, cfg: dict) -> list[dict]:
    out = []
    for alias, ns_col, key_col in entries:
        if alias in f:
            val = f[alias]
            if isinstance(val, list):
                val = json.dumps(val)
            out.append({"namespace": cfg[ns_col], "key": cfg[key_col], "value": str(val)})
    return out


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

    # ── Bulk export ───────────────────────────────────────────────────────────

    def _run_bulk_query(
        self,
        inner: str,
        on_status: Optional[Callable[[str], None]] = None,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> Optional[str]:
        """Start a bulk query, wait for it, return the result file URL (None if empty/cancelled)."""
        data = self.gql(M_BULK_RUN, {"query": inner})
        result = data.get("bulkOperationRunQuery") or {}
        if result.get("userErrors"):
            raise RuntimeError(f"Shopify bulk query: {result['userErrors']}")
        op_id = result["bulkOperation"]["id"]

        while True:
            if cancelled and cancelled():
                self.gql(M_BULK_CANCEL, {"id": op_id})
                return None
            op = self.gql(Q_BULK_STATUS, {"id": op_id}).get("node") or {}
            status = op.get("status")
            if status == "COMPLETED":
                return op.get("url")
            if status in ("FAILED", "CANCELED", "EXPIRED"):
                raise RuntimeError(
                    f"Shopify bulk operation {status}: {op.get('errorCode')}"
                )
            if on_status:
                on_status(
                    f"Shopify is preparing the export… {op.get('objectCount') or 0} records"
                )
            time.sleep(config.SHOPIFY_BULK_POLL_SECONDS)

    @staticmethod
    def _bulk_lines(url: str) -> Iterator[dict]:
        # Plain request on purpose: the result file is on Google storage, so the
        # Shopify token header must not be sent.
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            for line in resp.iter_lines():
                if line:
                    yield json.loads(line)

    def iter_bulk_products(
        self,
        cfg: dict,
        query: Optional[str] = None,
        on_status: Optional[Callable[[str], None]] = None,
        cancelled: Optional[Callable[[], bool]] = None,
    ) -> Iterator[dict]:
        """Yield product nodes in the same shape as iter_all_products, via a bulk export.

        The JSONL has one record per line; child records carry __parentId and follow
        their parent: product, its media/variants, each variant's media.
        """
        url = self._run_bulk_query(bulk_products_query(cfg, query), on_status, cancelled)
        if not url:
            return
        product: Optional[dict] = None
        variants: dict[str, dict] = {}
        for obj in self._bulk_lines(url):
            parent = obj.get("__parentId")
            if parent is None:
                if product:
                    yield product
                product = {**obj, "media": {"nodes": []}, "variants": {"nodes": []}}
                variants = {}
            elif "/ProductVariant/" in parent:
                nodes = variants[parent]["media"]["nodes"]
                if len(nodes) < 1:  # a variant has at most 1 image
                    nodes.append(obj)
            elif "/ProductVariant/" in obj["id"]:
                variant = {**obj, "media": {"nodes": []}}
                variants[obj["id"]] = variant
                product["variants"]["nodes"].append(variant)
            else:
                nodes = product["media"]["nodes"]
                if len(nodes) < 3:  # a product has at most 3 images
                    nodes.append(obj)
        if product:
            yield product
    
    def find_category(self, name: str) -> dict:
        data = self.gql(Q_TAXONOMY, {"search": name})
        nodes = ((data.get("taxonomy") or {}).get("categories") or {}).get("nodes", [])
        hits = [n for n in nodes
                if name.strip().lower() in (n["name"].lower(), n["fullName"].lower())]
        if len(hits) != 1:
            raise RuntimeError(
                f"Category '{name}': {'not found' if not hits else 'ambiguous, use full name'}")
        return hits[0]

    def update_product(self, product_id: str, f: dict, cfg: dict) -> None:
        inp: dict[str, Any] = {"id": f"gid://shopify/Product/{product_id}"}
        for local, api in (("title", "title"), ("vendor", "vendor"), ("status", "status"),
                           ("product_type", "productType"), ("tags", "tags"),
                           ("handle", "handle")):
            if local in f:
                inp[api] = f[local]
        if "category_id" in f:
            inp["category"] = f"gid://shopify/TaxonomyCategory/{f['category_id']}"
        mfs = _mfs(f, BULK_PRODUCT_MF, cfg)
        if mfs:
            inp["metafields"] = mfs
        data = self.gql(M_PRODUCT_UPDATE, {"product": inp})
        errs = (data.get("productUpdate") or {}).get("userErrors")
        if errs:
            raise RuntimeError(f"productUpdate: {errs}")

    def _option_names(self, product_id: str) -> list[str]:
        data = self.gql(Q_PRODUCT_OPTIONS, {"id": f"gid://shopify/Product/{product_id}"})
        return [o["name"] for o in (data.get("product") or {}).get("options", [])]

    def update_variants(self, product_id: str, variants: list[dict], cfg: dict) -> None:
        options: Optional[list[str]] = None
        bulk: list[dict] = []
        for f in variants:
            v: dict[str, Any] = {"id": f"gid://shopify/ProductVariant/{f['id']}"}
            if "price" in f:
                v["price"] = f["price"]
            inv: dict[str, Any] = {}
            if "cost" in f:
                inv["cost"] = f["cost"]
            if "weight" in f:
                inv["measurement"] = {"weight": {"value": f["weight"], "unit": "POUNDS"}}
            if inv:
                v["inventoryItem"] = inv
            if "title" in f:
                options = options or self._option_names(product_id)
                parts = [s.strip() for s in f["title"].split(" / ")]
                if len(parts) != len(options):
                    raise RuntimeError(f"Variant title needs {len(options)} part(s) separated by ' / '")
                v["optionValues"] = [{"optionName": o, "name": n} for o, n in zip(options, parts)]
            mfs = _mfs(f, BULK_VARIANT_MF, cfg)
            if mfs:
                v["metafields"] = mfs
            if len(v) > 1:
                bulk.append(v)
        if bulk:
            data = self.gql(
                M_VARIANTS_UPDATE,
                {"productId": f"gid://shopify/Product/{product_id}", "variants": bulk},
            )
            errs = (data.get("productVariantsBulkUpdate") or {}).get("userErrors")
            if errs:
                raise RuntimeError(f"variantsUpdate: {errs}")

        qty = [
            {
                "inventoryItemId": f"gid://shopify/InventoryItem/{f['inventory_item_id']}",
                "locationId": cfg["shopify_location_id"],
                "quantity": f["inventory_quantity"],
            }
            for f in variants if "inventory_quantity" in f
        ]
        if qty:
            if not cfg.get("shopify_location_id"):
                raise RuntimeError("No location id; run a sync first")
            data = self.gql(M_INVENTORY_SET, {"input": {
                "name": "available", "reason": "correction",
                "ignoreCompareQuantity": True, "quantities": qty,
            }})
            errs = (data.get("inventorySetQuantities") or {}).get("userErrors")
            if errs:
                raise RuntimeError(f"inventorySetQuantities: {errs}")

    # ── Locations ─────────────────────────────────────────────────────────────

    def get_primary_location_id(self) -> Optional[str]:
        data = self.gql(Q_LOCATIONS)
        nodes = (data.get("locations") or {}).get("nodes", [])
        for n in nodes:
            if n.get("isPrimary"):
                return n["id"]
        return nodes[0]["id"] if nodes else None
