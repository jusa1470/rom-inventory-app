from typing import TypedDict, Optional, List


# ── Webami ─────────────────────────────────────────────

class WebamiProductDTO(TypedDict):
    upc: str
    album: Optional[str]
    artist: Optional[str]
    image_urls: Optional[List[str]]
    features: Optional[List[str]]
    weight_grams: Optional[float]
    cost: Optional[float]
    format: Optional[str]


class WebamiOrderDTO(TypedDict):
    guid: str
    order_number: Optional[str]
    order_name: Optional[str]
    order_date: Optional[str]
    raw_upcs: List[str]


# ── Shopify ────────────────────────────────────────────

class ShopifyVariantDTO(TypedDict):
    id: str
    price: float
    inventoryQuantity: int


class ShopifyProductDTO(TypedDict):
    product_id: str
    upc: Optional[str]
    title: str
    vendor: Optional[str]
    status: Optional[str]
    tags: List[str]
    product_type: Optional[str]
    image_urls: Optional[List[str]]
    variants: List[ShopifyVariantDTO]
    updated_at: Optional[str]