"""Request and response models for PIX reservations and stock lookups."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, model_validator

from src.control_stock.modules.inventory.models import (
    ReservationStatus,
    StockReservation,
)

Sku = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)
]
OrderReference = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)
]


class ReservationItemIn(BaseModel):
    sku: Sku
    quantity: int = Field(gt=0)


class ReservationCreate(BaseModel):
    """A PIX checkout: every item is reserved for 10 minutes, or none is."""

    order_reference: OrderReference
    items: list[ReservationItemIn] = Field(min_length=1)

    @model_validator(mode="after")
    def merge_duplicate_skus(self) -> "ReservationCreate":
        totals: dict[str, int] = {}
        for item in self.items:
            totals[item.sku] = totals.get(item.sku, 0) + item.quantity
        self.items = [
            ReservationItemIn(sku=sku, quantity=qty) for sku, qty in totals.items()
        ]
        return self


class SalePriceIn(BaseModel):
    sku: Sku
    sale_unit_price: Decimal = Field(ge=0, decimal_places=2, max_digits=12)


class ConfirmRequest(BaseModel):
    """Optional per-SKU sale prices (e.g. discounts); default is the tier price."""

    prices: list[SalePriceIn] = []


class ReservationOut(BaseModel):
    id: int
    sku: str
    quantity: int
    status: ReservationStatus
    expires_at: datetime
    created_at: datetime
    resolved_at: datetime | None


class OrderReservationsOut(BaseModel):
    order_reference: str
    reservations: list[ReservationOut]


class ExpireOut(BaseModel):
    released: int


class StockOut(BaseModel):
    sku: str
    physical_qty: int
    reserved_qty: int
    available_qty: int


def order_out(
    order_reference: str, rows: Sequence[StockReservation]
) -> OrderReservationsOut:
    return OrderReservationsOut(
        order_reference=order_reference,
        reservations=[
            ReservationOut(
                id=row.id,
                sku=row.variant.sku,
                quantity=row.quantity,
                status=row.status,
                expires_at=row.expires_at,
                created_at=row.created_at,
                resolved_at=row.resolved_at,
            )
            for row in rows
        ],
    )
