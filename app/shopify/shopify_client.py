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
    M_MEDIA_CREATE,
    M_METAFIELDS_DELETE,
    M_OPTION_UPDATE,
    M_PRODUCT_CREATE,
    M_PRODUCT_DELETE,
    M_PRODUCT_UPDATE,
    M_PUBLISH,
    M_UNPUBLISH,
    M_VARIANT_MEDIA,
    M_VARIANTS_CREATE,
    M_VARIANTS_DELETE,
    M_VARIANTS_UPDATE,
    Q_BULK_STATUS,
    Q_MEDIA_STATUS,
    Q_PRODUCT_OPTIONS,
    Q_PUBLICATIONS,
    Q_TAXONOMY,
    Q_VARIANT_PUBS,
    bulk_products_query,
    Q_LOCATIONS,
    Q_PRODUCTS_COUNT,
)

logger: logging.Logger = logging.getLogger(__name__)
OPTION_NAME = "Edition | Color | Attributes"
_PRODUCT_FIELDS = (("title", "title"), ("vendor", "vendor"), ("status", "status"),
                   ("product_type", "productType"), ("tags", "tags"), ("handle", "handle"))

def _check(data: dict, key: str) -> None:
    errs = (data.get(key) or {}).get("userErrors")
    if errs:
        raise RuntimeError(f"{key}: {errs}")


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
        inp = {"id": f"gid://shopify/Product/{product_id}", **self._product_input(f)}
        if "category_id" in f:
            inp["category"] = f"gid://shopify/TaxonomyCategory/{f['category_id']}"
        clear = [a for a, _, _ in BULK_PRODUCT_MF if f.get(a) == ""]
        mfs = _mfs({k: v for k, v in f.items() if not (k in clear)}, BULK_PRODUCT_MF, cfg)
        if mfs:
            inp["metafields"] = mfs
        if len(inp) > 1:
            _check(self.gql(M_PRODUCT_UPDATE, {"product": inp}), "productUpdate")
        if clear:
            ids = [{"ownerId": f"gid://shopify/Product/{product_id}",
                    "namespace": cfg[ns], "key": cfg[key]}
                   for a, ns, key in BULK_PRODUCT_MF if a in clear]
            _check(self.gql(M_METAFIELDS_DELETE, {"metafields": ids}), "metafieldsDelete")
    
    def create_product(self, f: dict, cfg: dict) -> str:
        f = {k: v for k, v in f.items() if v not in ("", None, [])}
        inp = self._product_input(f)
        inp: dict[str, Any] = {}
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
        res = self.gql(M_PRODUCT_CREATE, {"product": inp}).get("productCreate") or {}
        if res.get("userErrors"):
            raise RuntimeError(f"productCreate: {res['userErrors']}")
        return res["product"]["id"].rsplit("/", 1)[-1]

    def delete_product(self, product_id: str) -> None:
        data = self.gql(M_PRODUCT_DELETE,
                        {"input": {"id": f"gid://shopify/Product/{product_id}"}})
        _check(data, "productDelete")

    def delete_variant(self, product_id: str, variant_id: str) -> None:
        data = self.gql(M_VARIANTS_DELETE, {
            "productId": f"gid://shopify/Product/{product_id}",
            "variantsIds": [f"gid://shopify/ProductVariant/{variant_id}"]})
        _check(data, "productVariantsBulkDelete")

    @staticmethod
    def _cname(pub: dict) -> str:
        return (pub.get("app") or {}).get("title") or pub["id"].rsplit("/", 1)[-1]

    def list_channels(self) -> list[dict]:
        nodes = (self.gql(Q_PUBLICATIONS).get("publications") or {}).get("nodes", [])
        return [{"id": n["id"], "name": self._cname(n)} for n in nodes]

    def variant_channels(self, variant_id: str) -> list[dict]:
        d = self.gql(Q_VARIANT_PUBS,
                     {"id": f"gid://shopify/ProductVariant/{variant_id}"}).get("productVariant") or {}
        return [{"id": n["publication"]["id"], "name": self._cname(n["publication"])}
                for n in (d.get("resourcePublications") or {}).get("nodes", [])
                if n.get("isPublished")]

    def set_variant_channels(self, variant_id: str, ids: list[str]) -> None:
        gid = f"gid://shopify/ProductVariant/{variant_id}"
        cur = {c["id"] for c in self.variant_channels(variant_id)}
        want = set(ids)
        for mut, key, s in ((M_PUBLISH, "publishablePublish", want - cur),
                            (M_UNPUBLISH, "publishableUnpublish", cur - want)):
            if not s:
                continue
            data = self.gql(mut, {"id": gid, "input": [{"publicationId": i} for i in s]})
            _check(data, key)
    
    def publish_product(self, product_id: str, ids: list[str]) -> None:
        if not ids:
            return
        data = self.gql(M_PUBLISH, {
            "id": f"gid://shopify/Product/{product_id}",
            "input": [{"publicationId": i} for i in ids]})
        _check(data, "publishablePublish")

    def _options(self, product_id: str) -> list[dict]:
        data = self.gql(Q_PRODUCT_OPTIONS, {"id": f"gid://shopify/Product/{product_id}"})
        return (data.get("product") or {}).get("options", [])

    def _option_names(self, product_id: str) -> list[str]:
        return [o["name"] for o in self._options(product_id)]
    
    def _rename_option(self, product_id: str) -> list[str]:
        opts = self._options(product_id)
        if len(opts) == 1 and opts[0]["name"] != OPTION_NAME:
            res = self.gql(M_OPTION_UPDATE, {
                "productId": f"gid://shopify/Product/{product_id}",
                "option": {"id": opts[0]["id"], "name": OPTION_NAME}})
            errs = (res.get("productOptionUpdate") or {}).get("userErrors")
            if errs:
                raise RuntimeError(f"optionUpdate: {errs}")
            return [OPTION_NAME]
        return [o["name"] for o in opts]

    def update_variants(self, product_id: str, variants: list[dict], cfg: dict) -> None:
        options: Optional[list[str]] = None
        bulk: list[dict] = []
        for f in variants:
            v: dict[str, Any] = {"id": f"gid://shopify/ProductVariant/{f['id']}"}
            if "price" in f:
                v["price"] = f["price"]
            inv = self._inventory_input(f)
            if inv:
                v["inventoryItem"] = inv
            if "title" in f:
                options = options or self._option_names(product_id)
                parts = ([f["title"].strip()] if len(options) == 1
                         else [s.strip() for s in f["title"].split(" / ")])
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
            _check(data, "productVariantsBulkUpdate")

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
            _check(data, "inventorySetQuantities")
    
    def upload_image(self, product_id: str, url: str, timeout: int = 60) -> str:
        res = self.gql(M_MEDIA_CREATE, {
            "productId": f"gid://shopify/Product/{product_id}",
            "media": [{"originalSource": url, "mediaContentType": "IMAGE"}]}
        ).get("productCreateMedia") or {}
        if res.get("mediaUserErrors"):
            raise RuntimeError(f"productCreateMedia: {res['mediaUserErrors']}")
        mid = res["media"][0]["id"]
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            st = (self.gql(Q_MEDIA_STATUS, {"id": mid}).get("node") or {}).get("status")
            if st == "READY":
                return mid
            if st == "FAILED":
                raise RuntimeError(f"Image upload failed: {url}")
            time.sleep(1)
        raise RuntimeError(f"Image upload timed out: {url}")
    
    def create_variants(self, product_id: str, variants: list[dict], cfg: dict,
                        replace_default: bool = True) -> list[dict]:
        options = self._rename_option(product_id)
        bulk: list[dict] = []
        for f in variants:
            v: dict[str, Any] = {}
            if f.get("barcode"):
                v["barcode"] = f["barcode"]
            if "price" in f:
                v["price"] = f["price"]
            inv = self._inventory_input(f)
            if inv:
                v["inventoryItem"] = inv
            title = (f.get("title") or "Standard").strip()
            parts = [title] if len(options) == 1 else [s.strip() for s in title.split(" / ")]
            if len(parts) != len(options):
                raise RuntimeError(f"Variant title needs {len(options)} part(s) separated by ' / '")
            v["optionValues"] = [{"optionName": o, "name": n} for o, n in zip(options, parts)]
            mfs = _mfs(f, BULK_VARIANT_MF, cfg)
            if mfs:
                v["metafields"] = mfs
            if "inventory_quantity" in f and cfg.get("shopify_location_id"):
                v["inventoryQuantities"] = [{"availableQuantity": f["inventory_quantity"],
                                             "locationId": cfg["shopify_location_id"]}]
            bulk.append(v)
        data = self.gql(M_VARIANTS_CREATE, {
            "productId": f"gid://shopify/Product/{product_id}", "variants": bulk,
            "strategy": "REMOVE_STANDALONE_VARIANT" if replace_default else "DEFAULT"})
        res = data.get("productVariantsBulkCreate") or {}
        if res.get("userErrors"):
            raise RuntimeError(f"variantsCreate: {res['userErrors']}")
        cache: dict[str, str] = {}
        links = []
        for n, f in zip(res["productVariants"], variants):
            if f.get("image_url"):
                url = f["image_url"]
                if url not in cache:
                    cache[url] = self.upload_image(product_id, url)
                links.append({"variantId": n["id"], "mediaIds": [cache[url]]})
            elif f.get("media_id"):
                links.append({"variantId": n["id"],
                              "mediaIds": [f"gid://shopify/MediaImage/{f['media_id']}"]})
        if links:
            r = self.gql(M_VARIANT_MEDIA, {
                "productId": f"gid://shopify/Product/{product_id}", "variantMedia": links})
            errs = (r.get("productVariantAppendMedia") or {}).get("userErrors")
            if errs:
                raise RuntimeError(f"variantMedia: {errs}")
        return [{"id": n["id"].rsplit("/", 1)[-1],
                 "inventory_item_id": n["inventoryItem"]["id"].rsplit("/", 1)[-1]}
                for n in res["productVariants"]]

    # ── Locations ─────────────────────────────────────────────────────────────

    def get_primary_location_id(self) -> Optional[str]:
        data = self.gql(Q_LOCATIONS)
        nodes = (data.get("locations") or {}).get("nodes", [])
        for n in nodes:
            if n.get("isPrimary"):
                return n["id"]
        return nodes[0]["id"] if nodes else None
    
    @staticmethod
    def _product_input(f: dict) -> dict:
        inp = {api: f[local] for local, api in _PRODUCT_FIELDS if local in f}
        if "category_id" in f:
            inp["category"] = f"gid://shopify/TaxonomyCategory/{f['category_id']}"
        return inp

    @staticmethod
    def _inventory_input(f: dict) -> dict:
        inv = {}
        if "cost" in f:
            inv["cost"] = f["cost"]
        if "weight" in f:
            inv["measurement"] = {"weight": {"value": f["weight"], "unit": "POUNDS"}}
        return inv
