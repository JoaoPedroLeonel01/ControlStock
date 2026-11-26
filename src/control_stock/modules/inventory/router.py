"""HTTP layer for PIX reservations and stock lookups (FR-07, FR-08, FR-09).

Thin by design: validation lives in the schemas, rules and transactions in the
service; domain errors become JSON responses via the handler in main.py.
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from src.control_stock.core.database import get_db
from src.control_stock.modules.inventory import service
from src.control_stock.modules.inventory.schemas import (
    ConfirmRequest,
    ExpireOut,
    OrderReservationsOut,
    ReservationCreate,
    StockOut,
    order_out,
)

router = APIRouter(prefix="/api/v1")


@router.post(
    "/reservations",
    status_code=status.HTTP_201_CREATED,
    response_model=OrderReservationsOut,
    tags=["Reservations"],
    summary="Reserve the items of a PIX checkout for 10 minutes (all or nothing)",
)
def create_reservations(
    data: ReservationCreate, db: Session = Depends(get_db)
) -> OrderReservationsOut:
    rows = service.create_reservations(db, data)
    return order_out(data.order_reference, rows)


# Declared before the "/{order_reference}" routes on purpose.
@router.post(
    "/reservations/expire",
    response_model=ExpireOut,
    tags=["Reservations"],
    summary="Release every expired reservation (global sweep)",
)
def expire_reservations(db: Session = Depends(get_db)) -> ExpireOut:
    return ExpireOut(released=service.expire_all(db))


@router.get(
    "/reservations/{order_reference}",
    response_model=OrderReservationsOut,
    tags=["Reservations"],
    summary="Reservations of an order",
)
def get_order(
    order_reference: str, db: Session = Depends(get_db)
) -> OrderReservationsOut:
    return order_out(order_reference, service.get_order(db, order_reference))


@router.post(
    "/reservations/{order_reference}/confirm",
    response_model=OrderReservationsOut,
    tags=["Reservations"],
    summary="PIX paid: turn the reservations into a sale (idempotent)",
)
def confirm_order(
    order_reference: str,
    body: ConfirmRequest | None = None,
    db: Session = Depends(get_db),
) -> OrderReservationsOut:
    prices = body.prices if body else []
    return order_out(
        order_reference, service.confirm_order(db, order_reference, prices)
    )


@router.post(
    "/reservations/{order_reference}/cancel",
    response_model=OrderReservationsOut,
    tags=["Reservations"],
    summary="Cancel the checkout and release the reserved stock",
)
def cancel_order(
    order_reference: str, db: Session = Depends(get_db)
) -> OrderReservationsOut:
    return order_out(order_reference, service.cancel_order(db, order_reference))


@router.get(
    "/stock/{sku}",
    response_model=StockOut,
    tags=["Stock"],
    summary="Physical, reserved and available quantities of a SKU",
)
def get_stock(sku: str, db: Session = Depends(get_db)) -> StockOut:
    return service.get_stock(db, sku)
