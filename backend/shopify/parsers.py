import logging
import config
from datetime import datetime
from db.models import ShopifyProduct, ShopifyVariant
from utils.parsing import safe_get, parse_iso_datetime, safe_float

logger = logging.getLogger(__name__)


def parse_product(node: dict) -> ShopifyProduct:
    product_id = node.get("id")
    if not product_id:
        raise ValueError("Missing product id")

    image_urls = [
        url
        for media in safe_get(node, "media", "nodes", default=[])
        if (url := safe_get(media, "preview", "image", "url"))
    ]

    music_genres = [
        value
        for ref in safe_get(node, "musicGenre", "references", "nodes", default=[])
        for field in ref.get("fields", [])
        if (value := field.get("value")) and not value.startswith("gid://")
    ]

    return ShopifyProduct(
        product_id=product_id,
        title=node.get("title"),
        vendor=node.get("vendor"),
        status=node.get("status"),
        tags=node.get("tags") or [],
        product_type=node.get("productType"),
        image_urls=image_urls or None,
        upc=safe_get(node, "upc", "value"),
        music_genres=music_genres or None,
        updated_at=parse_iso_datetime(node.get("updatedAt")),
    )


def calculate_price(unit_cost: float) -> float:
    return round(float(unit_cost) / (1 - config.MARGIN), 2)


def parse_variants(node: dict) -> list[ShopifyVariant]:
    product_id = node.get("id")
    if not product_id:
        return []

    variants = []

    for v in safe_get(node, "variants", "nodes", default=[]):
        try:
            variant_id = v.get("id")
            if not variant_id:
                continue

            cost = safe_get(v, "inventoryItem", "unitCost", "amount")
            weight = safe_get(v, "inventoryItem", "measurement", "weight", "value")
            weight_unit = safe_get(v, "inventoryItem", "measurement", "weight", "unit")

            variants.append(ShopifyVariant(
                variant_id=variant_id,
                product_id=product_id,
                inventory_quantity=v.get("inventoryQuantity") or 0,
                taxable=bool(v.get("taxable", True)),
                cost=safe_float(cost),
                price=calculate_price(safe_float(cost)),
                weight=safe_float(weight),
                weight_unit=weight_unit,
                updated_at=parse_iso_datetime(v.get("updatedAt")),
            ))

        except Exception as e:
            logger.error(
                f"Variant parse failed (product={product_id}, variant={v.get('id')}): {e}",
                exc_info=True
            )

    return variants