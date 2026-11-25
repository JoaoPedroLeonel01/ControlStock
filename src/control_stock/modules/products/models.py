"""Catalog models: categories, size grids, products, price tiers and prices."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.control_stock.core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from src.control_stock.modules.variants.models import Variant


class Category(TimestampMixin, Base):
    """Product category (e.g. T-Shirts, Shorts)."""

    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    slug: Mapped[str] = mapped_column(String(120), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    # RESTRICT in the DB: never let the ORM null category_id on delete.
    products: Mapped[list[Product]] = relationship(
        back_populates="category", passive_deletes="all"
    )


class SizeGrid(TimestampMixin, Base):
    """Reusable size grid (e.g. "Letras P–G5", "Numérica 38+")."""

    __tablename__ = "size_grids"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    sizes: Mapped[list[SizeGridSize]] = relationship(
        back_populates="size_grid",
        order_by="SizeGridSize.sort_order",
        cascade="all, delete-orphan",
    )


class SizeGridSize(Base):
    """One size of a grid, in display order, with its default price tier."""

    __tablename__ = "size_grid_sizes"
    __table_args__ = (
        UniqueConstraint("size_grid_id", "label", name="uq_size_grid_sizes_grid_label"),
        UniqueConstraint(
            "size_grid_id", "sort_order", name="uq_size_grid_sizes_grid_order"
        ),
        CheckConstraint("sort_order >= 0", name="sort_order_non_negative"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Indexed by uq_size_grid_sizes_grid_label (leading column).
    size_grid_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("size_grids.id", ondelete="CASCADE")
    )
    label: Mapped[str] = mapped_column(String(10))
    sort_order: Mapped[int] = mapped_column(SmallInteger)
    default_tier_name: Mapped[str] = mapped_column(String(50))

    size_grid: Mapped[SizeGrid] = relationship(back_populates="sizes")


class Product(TimestampMixin, Base):
    """Parent product (garment line); sellable units are its variants."""

    __tablename__ = "products"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    category_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    size_grid_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("size_grids.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(150))
    slug: Mapped[str] = mapped_column(String(160), unique=True)
    description: Mapped[str | None] = mapped_column(Text)
    brand: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    category: Mapped[Category] = relationship(back_populates="products")
    size_grid: Mapped[SizeGrid] = relationship()
    # passive_deletes: let ON DELETE CASCADE/RESTRICT in the DB do the work.
    # No delete-orphan: removing a tier from the list must not erase history.
    price_tiers: Mapped[list[PriceTier]] = relationship(
        back_populates="product", cascade="all", passive_deletes=True
    )
    variants: Mapped[list[Variant]] = relationship(
        back_populates="product", cascade="all", passive_deletes=True
    )


class PriceTier(Base):
    """Price tier of a product (e.g. Normal, Especial)."""

    __tablename__ = "price_tiers"
    __table_args__ = (
        UniqueConstraint("product_id", "name", name="uq_price_tiers_product_id_name"),
        # Target of the composite FK on variants (tier must belong to the product).
        UniqueConstraint("id", "product_id", name="uq_price_tiers_id_product_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Indexed by uq_price_tiers_product_id_name (leading column).
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(50))

    product: Mapped[Product] = relationship(back_populates="price_tiers")
    prices: Mapped[list[TierPrice]] = relationship(
        back_populates="price_tier",
        order_by="TierPrice.valid_from",
        # Price history rows are never deleted by the ORM (no delete-orphan).
        cascade="all",
        passive_deletes=True,
    )


class TierPrice(Base):
    """Price history of a tier; the current price has valid_to IS NULL."""

    __tablename__ = "tier_prices"
    __table_args__ = (
        CheckConstraint("cost_price >= 0", name="cost_price_non_negative"),
        CheckConstraint("retail_price >= 0", name="retail_price_non_negative"),
        CheckConstraint(
            "valid_to IS NULL OR valid_to > valid_from", name="valid_range"
        ),
        Index(
            "uq_tier_prices_current",
            "price_tier_id",
            unique=True,
            postgresql_where=text("valid_to IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    price_tier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("price_tiers.id", ondelete="CASCADE"), index=True
    )
    cost_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    retail_price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    price_tier: Mapped[PriceTier] = relationship(back_populates="prices")
