# """
# Database engine, session factory, and CRUD helpers.

# All read functions return plain dicts or lists of dicts — never live ORM
# objects. This avoids SQLAlchemy's DetachedInstanceError, which occurs when
# an ORM object is accessed after its session has been closed (the normal
# case when using the get_db() context manager).

# Write functions (upsert_*, update_*, delete_*) take either plain values
# or ORM objects constructed outside a session — that is safe because they
# only read from the object, they don't let SQLAlchemy track it across
# session boundaries.
# """

# import json
# import logging
# from contextlib import contextmanager
# from datetime import datetime, timezone
# from typing import Generator, Optional, Any

# from sqlalchemy import create_engine, or_
# from sqlalchemy.orm import Session, sessionmaker

# import config
# from db.models import Base, ShopifyProduct, ShopifyVariant, SyncState, WebamiOrder, WebamiProduct

# logger = logging.getLogger(__name__)

# engine = create_engine(
#     f"sqlite:///{config.DB_PATH}",
#     connect_args={"check_same_thread": False},
# )
# SessionLocal = sessionmaker(
#     bind=engine, 
#     expire_on_commit=False
# )


# def init_db() -> None:
#     """Create all tables if they don't exist."""
#     Base.metadata.create_all(bind=engine)
#     logger.info("Database initialised")


# @contextmanager
# def get_db() -> Generator[Session, None, None]:
#     db = SessionLocal()
#     try:
#         yield db
#         db.commit()
#     except Exception:
#         db.rollback()
#         raise
#     finally:
#         db.close()


# def _row(obj: Any, *cols: str) -> dict:
#     if obj is None:
#         return {}
#     return {c: getattr(obj, c) for c in cols}


# # ── Webami orders ────────────────────────────────────────────────────

# def get_all_order_guids() -> set[str]:
#     with get_db() as db:
#         return {r.guid for r in db.query(WebamiOrder.guid).all()}


# def upsert_order(order: WebamiOrder) -> None:
#     with get_db() as db:
#         existing = db.get(WebamiOrder, order.guid)
#         if existing:
#             existing.order_number       = order.order_number
#             existing.order_name         = order.order_name
#             existing.order_date         = order.order_date
#             existing.number_of_products = order.number_of_products
#             existing.synced_at          = datetime.now(timezone.utc)
#             existing.raw_upcs           = order.raw_upcs
#         else:
#             order.synced_at = datetime.now(timezone.utc)
#             db.add(order)


# def search_orders(query: str) -> list[dict]:
#     with get_db() as db:
#         rows = (
#             db.query(WebamiOrder)
#             .filter(WebamiOrder.raw_upcs.contains(query))
#             .all()
#         )
#         return [
#             _row(r, "guid", "order_date", "synced_at", "raw_upcs")
#             for r in rows
#         ]


# # ── Webami products ──────────────────────────────────────────────────

# def get_all_upcs() -> set[str]:
#     with get_db() as db:
#         return {r.upc for r in db.query(WebamiProduct.upc).all()}


# def upsert_webami_product(p: WebamiProduct) -> None:
#     with get_db() as db:
#         existing = db.get(WebamiProduct, p.upc)
#         if existing:
#             for col in ("album", "artist", "image_urls", "features",
#                         "weight_grams", "cost", "format"):
#                 setattr(existing, col, getattr(p, col))
#             existing.last_scraped = datetime.now(timezone.utc)
#         else:
#             p.last_scraped = datetime.now(timezone.utc)
#             db.add(p)


# def update_product_cost(upc: str, cost: float) -> None:
#     with get_db() as db:
#         p = db.get(WebamiProduct, upc)
#         if p:
#             p.cost = cost
#             p.price_synced_at = datetime.now(timezone.utc)


# def search_webami_products(query: str) -> list[dict]:
#     with get_db() as db:
#         q = f"%{query}%"
#         rows = (
#             db.query(WebamiProduct)
#             .filter(or_(
#                 WebamiProduct.album.ilike(q),
#                 WebamiProduct.artist.ilike(q),
#                 WebamiProduct.upc.ilike(q),
#             ))
#             .all()
#         )
#         return [
#             _row(r, "upc", "album", "artist", "image_urls", "features",
#                  "weight_grams", "cost", "format", "last_scraped",
#                  "price_synced_at")
#             for r in rows
#         ]


# # ── Shopify products ─────────────────────────────────────────────────

# _SHOPIFY_PRODUCT_COLS = (
#     "product_id", "upc", "title", "vendor", "status", "tags",
#     "image_urls", "product_type", "variants", "metafields",
#     "updated_at", "last_synced",
# )


# def upsert_shopify_product(p: ShopifyProduct) -> None:
#     with get_db() as db:
#         existing = db.get(ShopifyProduct, p.product_id)
#         if existing:
#             for col in ("title", "vendor", "status", "tags", "product_type",
#                         "image_urls", "upc", "music_genres", "updated_at"):
#                 setattr(existing, col, getattr(p, col))
#             existing.last_synced = datetime.now(timezone.utc)
#         else:
#             p.last_synced = datetime.now(timezone.utc)
#             db.add(p)


# def get_shopify_product(product_id: str) -> Optional[dict]:
#     with get_db() as db:
#         obj = db.get(ShopifyProduct, product_id)
#         return _row(obj, *_SHOPIFY_PRODUCT_COLS) if obj else None


# def delete_shopify_product_local(product_id: str) -> None:
#     with get_db() as db:
#         p = db.get(ShopifyProduct, product_id)
#         if p:
#             db.delete(p)


# def search_shopify_products(query: str) -> list[dict]:
#     with get_db() as db:
#         q = f"%{query}%"
#         rows = (
#             db.query(ShopifyProduct)
#             .filter(or_(
#                 ShopifyProduct.title.ilike(q),
#                 ShopifyProduct.vendor.ilike(q),
#                 ShopifyProduct.upc.ilike(q),
#             ))
#             .all()
#         )
#         return [_row(r, *_SHOPIFY_PRODUCT_COLS) for r in rows]


# # ── Shopify variants ─────────────────────────────────────────────────

# _SHOPIFY_VARIANT_COLS = (
#     "variant_id", "product_id", "inventory_quantity", "taxable", "cost",
#     "price", "weight", "weight_unit", "updated_at", "last_synced",
# )

# def upsert_shopify_variant(v: ShopifyVariant) -> None:
#     with get_db() as db:
#         existing = db.get(ShopifyVariant, v.variant_id)
#         if existing:
#             for col in ("product_id", "inventory_quantity", "taxable", "cost",
#                         "price", "weight", "weight_unit", "updated_at"):
#                 setattr(existing, col, getattr(v, col))
#             existing.last_synced = datetime.now(timezone.utc)
#         else:
#             v.last_synced = datetime.now(timezone.utc)
#             db.add(v)


# # ── Sync state ───────────────────────────────────────────────────────

# def get_sync_state(key: str) -> Optional[dict]:
#     """
#     Returns sync state as a plain dict, or None if not found.
#     Keys: key, last_sync, cursor, extra
#     """
#     with get_db() as db:
#         obj = db.get(SyncState, key)
#         if obj is None:
#             return None
#         return _row(obj, "key", "last_sync", "cursor", "extra")


# def set_sync_state(key: str, last_sync: datetime,
#                    cursor: Optional[str] = None,
#                    extra: Optional[dict] = None) -> None:
#     with get_db() as db:
#         existing = db.get(SyncState, key)
#         if existing:
#             existing.last_sync = last_sync
#             existing.cursor = cursor
#             existing.extra = json.dumps(extra) if extra else None
#         else:
#             db.add(SyncState(
#                 key=key,
#                 last_sync=last_sync,
#                 cursor=cursor,
#                 extra=json.dumps(extra) if extra else None,
#             ))


# def search_webami_products_with_cost() -> list[dict]:
#     """All Webami products that have a known cost value."""
#     with get_db() as db:
#         rows = (
#             db.query(WebamiProduct)
#             .filter(WebamiProduct.cost.isnot(None))
#             .all()
#         )
#         return [
#             _row(r, "upc", "album", "artist", "image_urls", "features",
#                  "weight_grams", "cost", "format", "last_scraped",
#                  "price_synced_at")
#             for r in rows
#         ]


"""
Database layer (persistence only).

Rules:
- NO business logic
- NO DTO transformations outside explicit mappers
- NO silent fallbacks
- Always return None or strict dict/list
"""

import json
import logging
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Generator, List, Optional, Any

from sqlalchemy import Engine, create_engine, or_
from sqlalchemy.orm import Session, sessionmaker

import config
from db.models import (
    Base,
    ShopifyProduct,
    ShopifyVariant,
    SyncState,
    WebamiOrder,
    WebamiProduct,
)

logger: logging.Logger = logging.getLogger(__name__)

engine: Engine = create_engine(
    f"sqlite:///{config.DB_PATH}",
    connect_args={"check_same_thread": False},
)

SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, expire_on_commit=False)


# ─────────────────────────────────────────────
# session
# ─────────────────────────────────────────────

@contextmanager
def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
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
# helpers
# ─────────────────────────────────────────────

def _dump_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value)


def _load_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


# ─────────────────────────────────────────────
# mappers (IMPORTANT NEW LAYER)
# ─────────────────────────────────────────────

def map_webami_product(p: WebamiProduct) -> dict:
    return {
        "upc": p.upc,
        "album": p.album,
        "artist": p.artist,
        "image_urls": p.image_urls,
        "features": p.features,
        "weight_grams": p.weight_grams,
        "cost": p.cost,
        "format": p.format,
        "last_scraped": p.last_scraped,
        "price_synced_at": p.price_synced_at,
    }


def map_shopify_product(p: ShopifyProduct) -> dict:
    return {
        "product_id": p.product_id,
        "upc": p.upc,
        "title": p.title,
        "vendor": p.vendor,
        "status": p.status,
        "tags": p.tags,
        "product_type": p.product_type,
        "image_urls": p.image_urls,
        "music_genres": p.music_genres,
        "updated_at": p.updated_at,
        "last_synced": p.last_synced,
    }


def map_sync_state(s: SyncState) -> dict:
    extra_val: Any = None

    if s.extra:
        try:
            extra_val = s.extra
        except Exception:
            extra_val = None

    return {
        "key": s.key,
        "last_sync": s.last_sync,
        "cursor": s.cursor,
        "extra": extra_val,
    }


# ─────────────────────────────────────────────
# Webami
# ─────────────────────────────────────────────

def search_webami_products(query: str) -> list[dict]:
    with get_db() as db:
        q: str = f"%{query}%"
        rows: List[WebamiProduct] = (
            db.query(WebamiProduct)
            .filter(
                or_(
                    WebamiProduct.album.ilike(q),
                    WebamiProduct.artist.ilike(q),
                    WebamiProduct.upc.ilike(q),
                )
            )
            .all()
        )
        return [map_webami_product(r) for r in rows]


def search_webami_products_with_cost() -> list[dict]:
    with get_db() as db:
        rows = db.query(WebamiProduct).filter(WebamiProduct.cost.isnot(None)).all()
        return [map_webami_product(r) for r in rows]


def get_all_upcs() -> set[str]:
    with get_db() as db:
        return {r.upc for r in db.query(WebamiProduct.upc).all()}


# ─────────────────────────────────────────────
# Shopify
# ─────────────────────────────────────────────

def upsert_shopify_product(p: ShopifyProduct) -> None:
    with get_db() as db:
        existing = db.get(ShopifyProduct, p.product_id)

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
            p.tags = p.tags
            p.image_urls = p.image_urls
            p.music_genres = p.music_genres
            p.last_synced = datetime.now(timezone.utc)

            db.add(p)

def search_shopify_products(query: str) -> list[dict]:
    with get_db() as db:
        q = f"%{query}%"
        rows = (
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
        return [map_shopify_product(r) for r in rows]


def get_shopify_product(product_id: str) -> Optional[dict]:
    with get_db() as db:
        obj = db.get(ShopifyProduct, product_id)
        return map_shopify_product(obj) if obj else None


def delete_shopify_product_local(product_id: str) -> None:
    with get_db() as db:
        obj = db.get(ShopifyProduct, product_id)
        if obj:
            db.delete(obj)


# ─────────────────────────────────────────────
# Sync state
# ─────────────────────────────────────────────

def get_sync_state(key: str) -> Optional[dict]:
    with get_db() as db:
        obj: SyncState | None = db.get(SyncState, key)
        return map_sync_state(obj) if obj else None


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
            db.add(
                SyncState(
                    key=key,
                    last_sync=last_sync,
                    cursor=cursor,
                    extra=json.dumps(extra) if extra else None,
                )
            )