"""
Database layer (persistence only).

Rules:
- NO business logic
- Always return DTOs or None, never raw ORM objects
"""

import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, List, Optional

from sqlalchemy import Engine, create_engine, or_
from sqlalchemy.orm import Session, sessionmaker

import config
from db.models import (
    Base,
    ShopifyProduct,
    ShopifyVariant,
    SyncState,
    WebamiOrder,
    WebamiOrderItem,
    WebamiProduct,
    WebamiProductAlias
)
from objects.dtos import (
    ShopifyProductDTO,
    ShopifyVariantDTO,
    ShopifyProductVariantDTO,
    SyncStateDTO,
    WebamiOrderDTO,
    WebamiOrderItemDTO,
    WebamiProductDTO,
)

logger: logging.Logger = logging.getLogger(__name__)

engine: Engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)

# ─────────────────────────────────────────────
# Session
# ─────────────────────────────────────────────

@contextmanager
def get_db() -> Generator[Session, None, None]:
    db: Session = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    logger.info("Database initialised")

# ─────────────────────────────────────────────
# Mappers
# ─────────────────────────────────────────────

def _map_webami_order(o: WebamiOrder) -> WebamiOrderDTO:
    return WebamiOrderDTO(
        guid=o.guid,
        order_number=o.order_number,
        order_name=o.order_name,
        order_date=o.order_date,
        number_of_products=o.number_of_products,
        synced_at=o.synced_at,
    )

def _map_webami_order_item(i: WebamiOrderItem) -> WebamiOrderItemDTO:
    return WebamiOrderItemDTO(
        id=i.id,
        order_guid=i.order_guid,
        upc=i.upc,
        title=i.title,
        format=i.format,
        cost=i.cost,
        quantity_ordered=i.quantity_ordered,
        quantity_received=i.quantity_received,
        received_at=i.received_at,
    )

def _map_webami_product(p: WebamiProduct) -> WebamiProductDTO:
    return WebamiProductDTO(
        upc=p.upc,
        title=p.title,
        artist=p.artist,
        brand=p.brand,
        image_urls=p.image_urls,
        features=p.features,
        genres=p.genres,
        weight_grams=p.weight_grams,
        cost=p.cost,
        format=p.format,
        last_scraped=p.last_scraped,
        price_synced_at=p.price_synced_at,
    )

def _map_shopify_product(p: ShopifyProduct) -> ShopifyProductDTO:
    return ShopifyProductDTO(
        product_id=p.product_id,
        upc=p.upc,
        title=p.title,
        vendor=p.vendor,
        status=p.status,
        tags=p.tags,
        product_type=p.product_type,
        image_urls=p.image_urls,
        music_genres=p.music_genres,
        updated_at=p.updated_at,
        last_synced=p.last_synced,
    )

def _map_shopify_variant(v: ShopifyVariant) -> ShopifyVariantDTO:
    return ShopifyVariantDTO(
        variant_id=v.variant_id,
        product_id=v.product_id,
        inventory_quantity=v.inventory_quantity,
        taxable=v.taxable,
        cost=v.cost,
        price=v.price,
        weight=v.weight,
        weight_unit=v.weight_unit,
        updated_at=v.updated_at,
        last_synced=v.last_synced,
    )

def _map_shopify_product_variant(v: ShopifyVariant) -> ShopifyProductVariantDTO:
    return ShopifyProductVariantDTO(
        
    )

def _map_sync_state(s: SyncState) -> SyncStateDTO:
    return SyncStateDTO(
        key=s.key,
        last_sync=s.last_sync,
        cursor=s.cursor,
        extra=s.extra,
    )

# ─────────────────────────────────────────────
# Webami Orders
# ─────────────────────────────────────────────

def get_all_order_guids() -> set[str]:
    with get_db() as db:
        return {r.guid for r in db.query(WebamiOrder.guid).all()}

def get_order(guid: str) -> Optional[WebamiOrderDTO]:
    with get_db() as db:
        obj: WebamiOrder | None = db.get(WebamiOrder, guid)
        return _map_webami_order(obj) if obj else None

def upsert_order(order: WebamiOrder) -> None:
    with get_db() as db:
        existing: WebamiOrder | None = db.get(WebamiOrder, order.guid)
        if existing:
            existing.order_number = order.order_number
            existing.order_name = order.order_name
            existing.order_date = order.order_date
            existing.number_of_products = order.number_of_products
            existing.synced_at = datetime.now(timezone.utc)
        else:
            order.synced_at = datetime.now(timezone.utc)
            db.add(order)

def search_webami_orders(query: str) -> list[WebamiOrderDTO]:
    with get_db() as db:
        q: str = f"%{query}%"
        rows: List[WebamiOrder] = (
            db.query(WebamiOrder)
            .filter(
                or_(
                    WebamiOrder.order_number.ilike(q),
                    WebamiOrder.order_name.ilike(q),
                )
            )
            .all()
        )
        return [_map_webami_order(r) for r in rows]
    
def count_webami_orders() -> int:
    with get_db() as db:
        return db.query(WebamiOrder).count()

def delete_order(guid: str) -> None:
    with get_db() as db:
        obj: WebamiOrder | None = db.get(WebamiOrder, guid)
        if obj:
            db.delete(obj)

# ─────────────────────────────────────────────
# Webami Order Items
# ─────────────────────────────────────────────

def upsert_order_items(guid: str, items: list[dict]) -> None:
    with get_db() as db:
        existing: dict[str, WebamiOrderItem] = {
            r.upc: r for r in
            db.query(WebamiOrderItem)
            .filter(WebamiOrderItem.order_guid == guid)
            .all()
        }
        for item in items:
            upc = item["upc"]
            if upc in existing:
                existing[upc].quantity_ordered = item["quantity"]
                # don't overwrite cost/format — preserve original purchase data
            else:
                db.add(WebamiOrderItem(
                    order_guid=guid,
                    upc=upc,
                    title=item.get("title"),
                    format=item.get("format"),
                    cost=item.get("cost"),
                    quantity_ordered=item["quantity"],
                    quantity_received=0,
                ))

def get_order_items(guid: str) -> list[WebamiOrderItemDTO]:
    with get_db() as db:
        rows: List[WebamiOrderItem] = (
            db.query(WebamiOrderItem)
            .filter(WebamiOrderItem.order_guid == guid)
            .all()
        )
        return [_map_webami_order_item(r) for r in rows]

def mark_item_received(item_id: int, quantity_received: int) -> None:
    with get_db() as db:
        item: WebamiOrderItem | None = db.get(WebamiOrderItem, item_id)
        if not item:
            return
        item.quantity_received = max(0, min(quantity_received, item.quantity_ordered))
        item.received_at = datetime.now(timezone.utc) if item.quantity_received > 0 else None

# ─────────────────────────────────────────────
# Webami Products
# ─────────────────────────────────────────────

def upsert_product_alias(alias_upc: str, canonical_upc: str) -> None:
    with get_db() as db:
        existing = db.get(WebamiProductAlias, alias_upc)
        if not existing:
            db.add(WebamiProductAlias(
                alias_upc=alias_upc,
                canonical_upc=canonical_upc,
            ))

def resolve_upc(upc: str) -> str:
    """Follows alias chain up to a max depth to avoid infinite loops."""
    with get_db() as db:
        seen: set[str] = {upc}
        current: str = upc
        for _ in range(5):  # max chain depth
            alias: WebamiProductAlias | None = db.get(WebamiProductAlias, current)
            if not alias:
                break
            if alias.canonical_upc in seen:
                logger.warning(f"Circular alias detected for UPC {upc}")
                break
            seen.add(alias.canonical_upc)
            current = alias.canonical_upc
        return current

def get_all_upcs() -> set[str]:
    with get_db() as db:
        return {r.upc for r in db.query(WebamiProduct.upc).all()}

def get_webami_product(upc: str) -> Optional[WebamiProductDTO]:
    with get_db() as db:
        obj = db.get(WebamiProduct, resolve_upc(upc))
        return _map_webami_product(obj) if obj else None

def upsert_webami_product(p: WebamiProduct) -> None:
    with get_db() as db:
        existing: WebamiProduct | None = db.get(WebamiProduct, p.upc)
        if existing:
            existing.title = p.title
            existing.artist = p.artist
            existing.brand = p.brand
            existing.image_urls = p.image_urls
            existing.features = p.features
            existing.genres = p.genres
            existing.weight_grams = p.weight_grams
            existing.cost = p.cost
            existing.format = p.format
            existing.last_scraped = datetime.now(timezone.utc)
        else:
            p.last_scraped = datetime.now(timezone.utc)
            db.add(p)

def update_product_cost(upc: str, cost: float) -> None:
    with get_db() as db:
        obj: WebamiProduct | None = db.get(WebamiProduct, upc)
        if obj:
            obj.cost = cost
            obj.price_synced_at = datetime.now(timezone.utc)

def search_webami_products(query: str) -> list[WebamiProductDTO]:
    with get_db() as db:
        q: str = f"%{query}%"
        rows: List[WebamiProduct] = (
            db.query(WebamiProduct)
            .filter(
                or_(
                    WebamiProduct.title.ilike(q),
                    WebamiProduct.artist.ilike(q),
                    WebamiProduct.brand.ilike(q),
                    WebamiProduct.upc.ilike(q),
                )
            )
            .all()
        )
        return [_map_webami_product(r) for r in rows]

def count_webami_products() -> int:
    with get_db() as db:
        return db.query(WebamiProduct).count()

def search_webami_products_with_cost() -> list[WebamiProductDTO]:
    with get_db() as db:
        rows: List[WebamiProduct] = db.query(WebamiProduct).filter(WebamiProduct.cost.isnot(None)).all()
        return [_map_webami_product(r) for r in rows]

def delete_webami_product(upc: str) -> None:
    with get_db() as db:
        obj: WebamiProduct | None = db.get(WebamiProduct, upc)
        if obj:
            db.delete(obj)

# ─────────────────────────────────────────────
# Shopify Products
# ─────────────────────────────────────────────

def upsert_shopify_product(p: ShopifyProduct) -> None:
    with get_db() as db:
        existing: ShopifyProduct | None = db.get(ShopifyProduct, p.product_id)
        if existing:
            existing.title = p.title
            existing.vendor = p.vendor
            existing.status = p.status
            existing.product_type = p.product_type
            existing.tags = p.tags
            existing.image_urls = p.image_urls
            existing.music_genres = p.music_genres
            existing.upc = p.upc
            existing.updated_at = p.updated_at
            existing.last_synced = datetime.now(timezone.utc)
        else:
            p.last_synced = datetime.now(timezone.utc)
            db.add(p)

def get_shopify_product(product_id: str) -> Optional[ShopifyProductDTO]:
    with get_db() as db:
        obj: ShopifyProduct | None = db.get(ShopifyProduct, product_id)
        return _map_shopify_product(obj) if obj else None

def search_shopify_products(query: str) -> list[ShopifyProductVariantDTO]:
    with get_db() as db:
        q: str = f"%{query}%"
        rows: List[ShopifyProduct] = (
            db.query(ShopifyProduct)
            .filter(
                or_(
                    ShopifyProduct.title.ilike(q),
                    ShopifyProduct.vendor.ilike(q),
                    ShopifyProduct.upc.ilike(q),
                )
            )
            .all()
        )
        return [_map_shopify_product(r) for r in rows]
    
def search_shopify_variant_products(query: str) -> list[ShopifyProductVariantDTO]:
    return []
    
def count_shopify_products() -> int:
    with get_db() as db:
        return db.query(ShopifyProduct).count()

def delete_shopify_product_local(product_id: str) -> None:
    with get_db() as db:
        obj: ShopifyProduct | None = db.get(ShopifyProduct, product_id)
        if obj:
            db.delete(obj)

# ─────────────────────────────────────────────
# Shopify Variants
# ─────────────────────────────────────────────

def upsert_shopify_variant(v: ShopifyVariant) -> None:
    with get_db() as db:
        existing: ShopifyVariant | None = db.get(ShopifyVariant, v.variant_id)
        if existing:
            existing.product_id = v.product_id
            existing.inventory_quantity = v.inventory_quantity
            existing.taxable = v.taxable
            existing.cost = v.cost
            existing.price = v.price
            existing.weight = v.weight
            existing.weight_unit = v.weight_unit
            existing.updated_at = v.updated_at
            existing.last_synced = datetime.now(timezone.utc)
        else:
            v.last_synced = datetime.now(timezone.utc)
            db.add(v)

def get_shopify_variants(product_id: str) -> list[ShopifyVariantDTO]:
    with get_db() as db:
        rows: List[ShopifyVariant] = (
            db.query(ShopifyVariant)
            .filter(ShopifyVariant.product_id == product_id)
            .all()
        )
        return [_map_shopify_variant(r) for r in rows]

def delete_shopify_variants(product_id: str) -> None:
    with get_db() as db:
        db.query(ShopifyVariant).filter(
            ShopifyVariant.product_id == product_id
        ).delete()

# ─────────────────────────────────────────────
# Sync State
# ─────────────────────────────────────────────

def get_sync_state(key: str) -> Optional[SyncStateDTO]:
    with get_db() as db:
        obj: SyncState | None = db.get(SyncState, key)
        return _map_sync_state(obj) if obj else None

def set_sync_state(
    key: str,
    last_sync: datetime,
    cursor: Optional[str] = None,
    extra: Optional[dict] = None,
) -> None:
    with get_db() as db:
        obj: SyncState | None = db.get(SyncState, key)
        if obj:
            obj.last_sync = last_sync
            obj.cursor = cursor
            obj.extra = extra
        else:
            db.add(SyncState(
                key=key,
                last_sync=last_sync,
                cursor=cursor,
                extra=extra,
            ))