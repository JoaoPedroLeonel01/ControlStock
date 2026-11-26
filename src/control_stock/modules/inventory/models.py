"""Inventory models.

``stock_levels`` is maintained exclusively by database triggers (see the
inventory migration): the application only INSERTs ``inventory_movements``;
it never writes to ``stock_levels`` and never updates/deletes movements.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.control_stock.core.database import Base

if TYPE_CHECKING:
    from src.control_stock.modules.variants.models import Variant


class MovementType(enum.StrEnum):
    INBOUND_PURCHASE = "INBOUND_PURCHASE"
    OUTBOUND_SALE = "OUTBOUND_SALE"
    STOCK_RESERVE = "STOCK_RESERVE"
    STOCK_RELEASE = "STOCK_RELEASE"
    CUSTOMER_RETURN = "CUSTOMER_RETURN"
    LOSS_DEFECT = "LOSS_DEFECT"
    INVENTORY_ADJUSTMENT = "INVENTORY_ADJUSTMENT"


class ReturnReason(enum.StrEnum):
    WRONG_SIZE = "WRONG_SIZE"
    FABRIC_DEFECT = "FABRIC_DEFECT"
    NOT_AS_PICTURED = "NOT_AS_PICTURED"
    CUSTOMER_REGRET = "CUSTOMER_REGRET"


class ReservationStatus(enum.StrEnum):
    ACTIVE = "ACTIVE"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


def _str_enum(enum_cls: type[enum.StrEnum], name: str, length: int) -> Enum:
    """VARCHAR + named CHECK instead of a native PostgreSQL ENUM type."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=length,
        values_callable=lambda e: [m.value for m in e],
    )


class StockLevel(Base):
    """Physical/reserved quantities of one variant (one row per SKU)."""

    __tablename__ = "stock_levels"
    __table_args__ = (
        CheckConstraint("physical_qty >= 0", name="physical_non_negative"),
        CheckConstraint("reserved_qty >= 0", name="reserved_non_negative"),
        CheckConstraint("reserved_qty <= physical_qty", name="reserved_lte_physical"),
    )

    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("variants.id", ondelete="CASCADE"), primary_key=True
    )
    physical_qty: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    reserved_qty: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    available_qty: Mapped[int] = mapped_column(
        Integer, Computed("physical_qty - reserved_qty", persisted=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    variant: Mapped[Variant] = relationship(viewonly=True)


class StockReservation(Base):
    """PIX checkout hold of one item; one order may have several rows."""

    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "(status = 'ACTIVE') = (resolved_at IS NULL)",
            name="resolved_when_not_active",
        ),
        Index("ix_stock_reservations_status_expires_at", "status", "expires_at"),
        # Target of the composite FK on inventory_movements.
        UniqueConstraint(
            "id", "variant_id", name="uq_stock_reservations_id_variant_id"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("variants.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    status: Mapped[ReservationStatus] = mapped_column(
        _str_enum(ReservationStatus, "status", 20),
        server_default=text("'ACTIVE'"),
    )
    order_reference: Mapped[str] = mapped_column(String(100), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    variant: Mapped[Variant] = relationship()


_TYPES_NEEDING_ORDER = "('STOCK_RESERVE', 'STOCK_RELEASE', 'OUTBOUND_SALE')"


class InventoryMovement(Base):
    """Immutable ledger entry; inserting one updates stock_levels (trigger)."""

    __tablename__ = "inventory_movements"
    __table_args__ = (
        CheckConstraint(
            "((movement_type = 'INBOUND_PURCHASE') = (purchase_unit_cost IS NOT NULL))"
            " AND (purchase_unit_cost IS NULL OR purchase_unit_cost >= 0)",
            name="purchase_cost_rule",
        ),
        CheckConstraint(
            "((movement_type = 'OUTBOUND_SALE') = (sale_unit_price IS NOT NULL))"
            " AND (sale_unit_price IS NULL OR sale_unit_price >= 0)",
            name="sale_price_rule",
        ),
        CheckConstraint(
            "(movement_type = 'CUSTOMER_RETURN') = (return_reason IS NOT NULL)",
            name="return_reason_rule",
        ),
        CheckConstraint(
            "movement_type NOT IN ('LOSS_DEFECT', 'INVENTORY_ADJUSTMENT')"
            " OR (note IS NOT NULL AND btrim(note) <> '')",
            name="note_rule",
        ),
        CheckConstraint(
            "CASE movement_type"
            " WHEN 'INBOUND_PURCHASE' THEN physical_delta > 0 AND reserved_delta = 0"
            " WHEN 'OUTBOUND_SALE' THEN physical_delta < 0"
            "  AND (reserved_delta = 0 OR reserved_delta = physical_delta)"
            " WHEN 'STOCK_RESERVE' THEN physical_delta = 0 AND reserved_delta > 0"
            " WHEN 'STOCK_RELEASE' THEN physical_delta = 0 AND reserved_delta < 0"
            " WHEN 'CUSTOMER_RETURN' THEN physical_delta > 0 AND reserved_delta = 0"
            " WHEN 'LOSS_DEFECT' THEN physical_delta < 0 AND reserved_delta = 0"
            " WHEN 'INVENTORY_ADJUSTMENT' THEN physical_delta <> 0"
            "  AND reserved_delta = 0"
            " ELSE false END",
            name="delta_rule",
        ),
        CheckConstraint(
            "(reservation_id IS NOT NULL) ="
            " (movement_type IN ('STOCK_RESERVE', 'STOCK_RELEASE')"
            "  OR (movement_type = 'OUTBOUND_SALE' AND reserved_delta <> 0))",
            name="reservation_rule",
        ),
        CheckConstraint(
            f"movement_type NOT IN {_TYPES_NEEDING_ORDER}"
            " OR order_reference IS NOT NULL",
            name="order_reference_rule",
        ),
        # A movement's reservation must be for the same variant.
        ForeignKeyConstraint(
            ["reservation_id", "variant_id"],
            ["stock_reservations.id", "stock_reservations.variant_id"],
            name="fk_inventory_movements_reservation_variant",
            ondelete="RESTRICT",
        ),
        Index("ix_inventory_movements_variant_created", "variant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    # Indexed by ix_inventory_movements_variant_created (leading column).
    variant_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("variants.id", ondelete="RESTRICT")
    )
    movement_type: Mapped[MovementType] = mapped_column(
        _str_enum(MovementType, "movement_type", 30)
    )
    physical_delta: Mapped[int] = mapped_column(Integer)
    reserved_delta: Mapped[int] = mapped_column(Integer)
    purchase_unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    sale_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    return_reason: Mapped[ReturnReason | None] = mapped_column(
        _str_enum(ReturnReason, "return_reason", 30)
    )
    note: Mapped[str | None] = mapped_column(Text)
    reservation_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    order_reference: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    variant: Mapped[Variant] = relationship(foreign_keys=[variant_id])
    reservation: Mapped[StockReservation | None] = relationship(
        primaryjoin="InventoryMovement.reservation_id == StockReservation.id",
        foreign_keys=[reservation_id],
    )
