from dataclasses import dataclass
from datetime import datetime
from typing import Optional

# ─────────────────────────────────────────────
# Webami
# ─────────────────────────────────────────────

@dataclass
class WebamiOrderDTO:
    guid: str
    order_number: Optional[str]
    order_name: Optional[str]
    order_date: Optional[datetime]
    number_of_products: int
    synced_at: Optional[datetime]

@dataclass
class WebamiOrderItemDTO:
    id: int
    order_guid: str
    upc: str
    title: Optional[str]
    format: Optional[str]
    cost: Optional[float]
    quantity_ordered: int
    quantity_received: int
    received_at: Optional[datetime]

@dataclass
class WebamiProductDTO:
    upc: str
    title: str
    artist: Optional[str]
    brand: Optional[str]
    image_urls: Optional[list[str]]
    features: Optional[list[str]]
    genres: Optional[list[str]]
    weight_grams: Optional[float]
    cost: Optional[float]
    format: Optional[str]
    last_scraped: Optional[datetime]
    price_synced_at: Optional[datetime]

# ─────────────────────────────────────────────
# Shopify
# ─────────────────────────────────────────────

@dataclass
class ShopifyVariantDTO:
    variant_id: str
    product_id: str
    inventory_quantity: int
    taxable: bool
    cost: float
    price: float
    weight: float
    weight_unit: str
    updated_at: Optional[datetime]
    last_synced: Optional[datetime]

@dataclass
class ShopifyProductDTO:
    product_id: str
    upc: Optional[str]
    title: str
    vendor: str
    status: str
    tags: Optional[list[str]]
    product_type: Optional[str]
    image_urls: Optional[list[str]]
    music_genres: Optional[list[str]]
    updated_at: Optional[datetime]
    last_synced: Optional[datetime]

# ─────────────────────────────────────────────
# Sync
# ─────────────────────────────────────────────

@dataclass
class SyncStateDTO:
    key: str
    last_sync: Optional[datetime]
    cursor: Optional[str]
    extra: Optional[dict]