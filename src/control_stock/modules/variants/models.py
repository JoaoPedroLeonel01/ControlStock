"""Variant (SKU) model: one sellable color × size of a product."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.control_stock.core.database import Base, TimestampMixin

if TYPE_CHECKING:
    from src.control_stock.modules.products.models import (
        PriceTier,
        Product,
        SizeGridSize,
    )


class Variant(TimestampMixin, Base):
    """SKU. Prices come from its price tier (no price columns here)."""

    __tablename__ = "variants"
    __table_args__ = (
        # The price tier must belong to the same product as the variant.
        ForeignKeyConstraint(
            ["price_tier_id", "product_id"],
            ["price_tiers.id", "price_tiers.product_id"],
            name="fk_variants_price_tier_product",
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "product_id",
            "color_name",
            "size_grid_size_id",
            name="uq_variants_product_color_size",
        ),
        CheckConstraint("min_safety_stock >= 0", name="min_safety_stock_non_negative"),
        CheckConstraint(
            "color_hex IS NULL OR color_hex ~ '^#[0-9A-Fa-f]{6}$'",
            name="color_hex_format",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Indexed by uq_variants_product_color_size (leading column).
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE")
    )
    price_tier_id: Mapped[int] = mapped_column(BigInteger, index=True)
    size_grid_size_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("size_grid_sizes.id", ondelete="RESTRICT"), index=True
    )
    sku: Mapped[str] = mapped_column(String(64), unique=True)
    color_name: Mapped[str] = mapped_column(String(50))
    color_hex: Mapped[str | None] = mapped_column(CHAR(7))
    barcode: Mapped[str | None] = mapped_column(String(50), unique=True)
    image_url: Mapped[str | None] = mapped_column(String(500))
    min_safety_stock: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))

    product: Mapped[Product] = relationship(
        back_populates="variants", foreign_keys=[product_id]
    )
    # Read through price_tier_id only: product_id is owned by `product`.
    price_tier: Mapped[PriceTier] = relationship(
        primaryjoin="Variant.price_tier_id == PriceTier.id",
        foreign_keys=[price_tier_id],
    )
    size: Mapped[SizeGridSize] = relationship()
