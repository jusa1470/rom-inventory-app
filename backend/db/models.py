# """
# SQLAlchemy ORM models for all four tables.
# """

# from datetime import datetime, timezone
# from sqlalchemy import DateTime, Float, String, Text, JSON, ForeignKey, Integer, Boolean, ARRAY, func
# from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# class Base(DeclarativeBase):
#     pass


# class WebamiOrder(Base):
#     __tablename__ = "webami_orders"

#     guid: Mapped[str] = mapped_column(String, primary_key=True)
#     order_number: Mapped[str] = mapped_column(String)
#     order_name: Mapped[str | None] = mapped_column(String, nullable=True)
#     order_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
#     number_of_products: Mapped[int] = mapped_column(Integer)
#     synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())
#     raw_upcs: Mapped[list[str]] = mapped_column(JSON)

# class WebamiProduct(Base):
#     __tablename__ = "webami_products"

#     upc: Mapped[str] = mapped_column(String, primary_key=True)
#     album: Mapped[str | None] = mapped_column(String)
#     artist: Mapped[str | None] = mapped_column(String)
#     image_urls: Mapped[list[str]] = mapped_column(ARRAY(String))
#     features: Mapped[list[str]] = mapped_column(ARRAY(String))
#     weight_grams: Mapped[float | None] = mapped_column(Float)
#     cost: Mapped[float | None] = mapped_column(Float)
#     format: Mapped[str | None] = mapped_column(String)   # LP / CD / Cassette
#     last_scraped: Mapped[datetime | None] = mapped_column(DateTime)
#     price_synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())


# class ShopifyProduct(Base):
#     __tablename__ = "shopify_products"

#     product_id: Mapped[str] = mapped_column(String, primary_key=True)
#     title: Mapped[str] = mapped_column(String)
#     vendor: Mapped[str] = mapped_column(String)
#     status: Mapped[str] = mapped_column(String)                # ACTIVE / DRAFT / ARCHIVED
#     tags: Mapped[list[str]] = mapped_column(ARRAY(String))
#     product_type: Mapped[str | None] = mapped_column(String, nullable=True)
#     image_urls: Mapped[list[str]] = mapped_column(ARRAY(String))
#     upc: Mapped[str | None] = mapped_column(String, index=True)
#     music_genres: Mapped[list[str]] = mapped_column(ARRAY(String))
#     variants: Mapped[list["ShopifyVariant"]] = relationship(
#         "ShopifyVariant",
#         backref="product",
#         cascade="all, delete-orphan"
#     )
#     updated_at: Mapped[datetime | None] = mapped_column(DateTime)
#     last_synced: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())


# class ShopifyVariant(Base):
#     __tablename__ = "shopify_variants"

#     variant_id: Mapped[str] = mapped_column(String, primary_key=True)
#     product_id: Mapped[str] = mapped_column(ForeignKey("shopify_products.product_id"))
#     inventory_quantity: Mapped[int] = mapped_column(Integer)
#     taxable: Mapped[bool] = mapped_column(Boolean, default=True)
#     cost: Mapped[float] = mapped_column(Float)
#     price: Mapped[float] = mapped_column(Float)
#     weight: Mapped[float] = mapped_column(Float)
#     weight_unit: Mapped[str] = mapped_column(String)
#     updated_at: Mapped[datetime | None] = mapped_column(DateTime)
#     last_synced: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())


# class SyncState(Base):
#     __tablename__ = "sync_state"

#     key: Mapped[str] = mapped_column(String, primary_key=True)
#     last_sync: Mapped[datetime | None] = mapped_column(DateTime)
#     cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
#     extra: Mapped[str | None] = mapped_column(Text, nullable=True)


from datetime import datetime, timezone
from sqlalchemy import DateTime, Float, String, Text, Integer, Boolean, JSON, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────
# Webami
# ─────────────────────────────────────────────

class WebamiOrder(Base):
    __tablename__ = "webami_orders"

    guid: Mapped[str] = mapped_column(String, primary_key=True)
    order_number: Mapped[str] = mapped_column(String)
    order_name: Mapped[str | None] = mapped_column(String, nullable=True)
    order_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    number_of_products: Mapped[int] = mapped_column(Integer)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=datetime.now(timezone.utc))
    raw_upcs: Mapped[str] = mapped_column(Text)  # JSON string


class WebamiOrderItem(Base):
    __tablename__ = "webami_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_guid: Mapped[str] = mapped_column(String, index=True)
    upc: Mapped[str] = mapped_column(String, index=True)
    quantity_ordered: Mapped[int] = mapped_column(Integer, default=1)
    quantity_received: Mapped[int] = mapped_column(Integer, default=0)
    received_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class WebamiProduct(Base):
    __tablename__ = "webami_products"

    upc: Mapped[str] = mapped_column(String, primary_key=True)
    album: Mapped[str | None] = mapped_column(String)
    artist: Mapped[str | None] = mapped_column(String)
    image_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    features: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    weight_grams: Mapped[float | None] = mapped_column(Float)
    cost: Mapped[float | None] = mapped_column(Float)
    format: Mapped[str | None] = mapped_column(String)
    last_scraped: Mapped[datetime | None] = mapped_column(DateTime)
    price_synced_at: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())


# ─────────────────────────────────────────────
# Shopify
# ─────────────────────────────────────────────

class ShopifyProduct(Base):
    __tablename__ = "shopify_products"

    product_id: Mapped[str] = mapped_column(String, primary_key=True)
    title: Mapped[str] = mapped_column(String)
    vendor: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    image_urls: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    music_genres: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    product_type: Mapped[str | None] = mapped_column(String, nullable=True)
    upc: Mapped[str | None] = mapped_column(String, index=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_synced: Mapped[datetime | None] = mapped_column(DateTime, default=func.now())


class ShopifyVariant(Base):
    __tablename__ = "shopify_variants"

    variant_id: Mapped[str] = mapped_column(String, primary_key=True)
    product_id: Mapped[str] = mapped_column(String)
    inventory_quantity: Mapped[int] = mapped_column(Integer)
    taxable: Mapped[bool] = mapped_column(Boolean, default=True)
    cost: Mapped[float] = mapped_column(Float)
    price: Mapped[float] = mapped_column(Float)
    weight: Mapped[float] = mapped_column(Float)
    weight_unit: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_synced: Mapped[datetime | None] = mapped_column(DateTime)


# ─────────────────────────────────────────────
# Sync
# ─────────────────────────────────────────────

class SyncState(Base):
    __tablename__ = "sync_state"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime)
    cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)