"""PIX reservations: reserve for 10 minutes, release expired holds, confirm, cancel.

Rules every function follows:

* The database clock (now()) is the only clock.
* Stock only changes by inserting inventory_movements; the triggers apply them
  to stock_levels and the CHECK constraints are the final guarantee.
* Lock order is always: advisory lock on the order reference ->
  stock_reservations rows (by id) -> stock_levels rows (by variant_id, taken
  explicitly with FOR UPDATE *before* any movement is inserted, because the
  movement trigger would otherwise lock them in item order). Concurrent
  requests therefore queue instead of deadlocking.
* Public functions commit on success and roll back before re-raising.

Expired reservations are released lazily (approach A): before a SKU is
reserved or its stock is read, plus the global sweep in expire_all().
"""

from collections.abc import Sequence
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import exists, func, select, text
from sqlalchemy.orm import Session

from src.control_stock.modules.inventory.errors import (
    InsufficientStock,
    MissingSalePrice,
    OrderCancelled,
    OrderNotActive,
    OrderNotFound,
    OrderReferenceUsed,
    PaymentTooLate,
    PriceForUnknownSku,
    SkuNotFound,
)
from src.control_stock.modules.inventory.models import (
    InventoryMovement,
    MovementType,
    ReservationStatus,
    StockLevel,
    StockReservation,
)
from src.control_stock.modules.inventory.schemas import (
    ReservationCreate,
    SalePriceIn,
    StockOut,
)
from src.control_stock.modules.products.models import Category, Product, TierPrice
from src.control_stock.modules.variants.models import Variant

RESERVATION_TTL = timedelta(minutes=10)


def _lock_order_reference(db: Session, order_reference: str) -> None:
    """Serialize requests for the same order (no unique column to rely on)."""
    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:ref, 0))"),
        {"ref": order_reference},
    )


def _release(db: Session, reservation: StockReservation) -> None:
    reservation.status = ReservationStatus.RELEASED
    reservation.resolved_at = func.now()
    db.add(
        InventoryMovement(
            variant_id=reservation.variant_id,
            movement_type=MovementType.STOCK_RELEASE,
            physical_delta=0,
            reserved_delta=-reservation.quantity,
            reservation_id=reservation.id,
            order_reference=reservation.order_reference,
        )
    )
    db.flush()


def _lock_stock_levels(
    db: Session, variant_ids: Sequence[int]
) -> dict[int, StockLevel]:
    query = (
        select(StockLevel)
        .where(StockLevel.variant_id.in_(variant_ids))
        .order_by(StockLevel.variant_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return {level.variant_id: level for level in db.scalars(query)}


def release_expired(db: Session, variant_ids: Sequence[int] | None = None) -> int:
    """Release ACTIVE reservations past expires_at; the caller commits.

    FOR UPDATE makes a concurrent confirm/cancel/sweep wait; under READ
    COMMITTED the WHERE clause is re-checked after the wait, so rows resolved
    meanwhile are skipped and never released twice.
    """
    query = (
        select(StockReservation)
        .where(
            StockReservation.status == ReservationStatus.ACTIVE,
            StockReservation.expires_at <= func.now(),
        )
        .order_by(StockReservation.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if variant_ids is not None:
        query = query.where(StockReservation.variant_id.in_(variant_ids))
    rows = db.scalars(query).all()
    if rows:
        _lock_stock_levels(db, sorted({row.variant_id for row in rows}))
    for row in rows:
        _release(db, row)
    return len(rows)


def _reservable_variants(db: Session, skus: Sequence[str]) -> dict[str, Variant]:
    query = (
        select(Variant)
        .join(Variant.product)
        .join(Product.category)
        .where(
            Variant.sku.in_(skus),
            Variant.is_active,
            Product.is_active,
            Category.is_active,
        )
    )
    return {variant.sku: variant for variant in db.scalars(query)}


def create_reservations(db: Session, data: ReservationCreate) -> list[StockReservation]:
    """Reserve every item of the order for RESERVATION_TTL, or nothing."""
    ref = data.order_reference
    try:
        _lock_order_reference(db, ref)
        if db.scalar(select(exists().where(StockReservation.order_reference == ref))):
            raise OrderReferenceUsed(ref)

        skus = [item.sku for item in data.items]
        variants = _reservable_variants(db, skus)
        missing = sorted(set(skus) - set(variants))
        if missing:
            raise SkuNotFound(missing)

        variant_ids = [variants[sku].id for sku in skus]
        release_expired(db, variant_ids)
        levels = _lock_stock_levels(db, variant_ids)
        shortages = [
            {
                "sku": item.sku,
                "requested": item.quantity,
                "available": levels[variants[item.sku].id].available_qty,
            }
            for item in data.items
            if item.quantity > levels[variants[item.sku].id].available_qty
        ]
        if shortages:
            raise InsufficientStock(shortages)

        expires_at = func.now() + RESERVATION_TTL
        rows = []
        for item in data.items:
            reservation = StockReservation(
                variant_id=variants[item.sku].id,
                quantity=item.quantity,
                order_reference=ref,
                expires_at=expires_at,
            )
            db.add(reservation)
            db.flush()
            db.add(
                InventoryMovement(
                    variant_id=reservation.variant_id,
                    movement_type=MovementType.STOCK_RESERVE,
                    physical_delta=0,
                    reserved_delta=item.quantity,
                    reservation_id=reservation.id,
                    order_reference=ref,
                )
            )
            rows.append(reservation)
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return rows


def expire_all(db: Session) -> int:
    """Global sweep: release every expired reservation."""
    try:
        released = release_expired(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return released


def get_stock(db: Session, sku: str) -> StockOut:
    """Quantities of a SKU, after releasing its expired reservations."""
    try:
        variant = db.scalar(select(Variant).where(Variant.sku == sku))
        if variant is None:
            raise SkuNotFound([sku])
        release_expired(db, [variant.id])
        db.commit()
        level = db.scalar(
            select(StockLevel)
            .where(StockLevel.variant_id == variant.id)
            .execution_options(populate_existing=True)
        )
    except Exception:
        db.rollback()
        raise
    return StockOut(
        sku=sku,
        physical_qty=level.physical_qty,
        reserved_qty=level.reserved_qty,
        available_qty=level.available_qty,
    )


def _lock_order(db: Session, order_reference: str) -> list[StockReservation]:
    rows = list(
        db.scalars(
            select(StockReservation)
            .where(StockReservation.order_reference == order_reference)
            .order_by(StockReservation.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
    if not rows:
        raise OrderNotFound(order_reference)
    return rows


def get_order(db: Session, order_reference: str) -> list[StockReservation]:
    """All reservations of an order (any status), oldest first."""
    rows = list(
        db.scalars(
            select(StockReservation)
            .where(StockReservation.order_reference == order_reference)
            .order_by(StockReservation.id)
        )
    )
    if not rows:
        raise OrderNotFound(order_reference)
    return rows


def _current_retail_price(db: Session, variant: Variant) -> Decimal | None:
    return db.scalar(
        select(TierPrice.retail_price).where(
            TierPrice.price_tier_id == variant.price_tier_id,
            TierPrice.valid_to.is_(None),
        )
    )


def confirm_order(
    db: Session, order_reference: str, prices: Sequence[SalePriceIn] = ()
) -> list[StockReservation]:
    """PIX paid: turn the order's active reservations into a sale.

    * already confirmed -> same rows, nothing new (payment webhooks retry);
    * expired (still ACTIVE, or already released after expires_at) -> 410:
      the stock went back to the shelf and the payment must be refunded;
    * cancelled before expiring -> 409.
    """
    try:
        rows = _lock_order(db, order_reference)
        if all(r.status == ReservationStatus.CONFIRMED for r in rows):
            return rows
        _lock_stock_levels(db, sorted({r.variant_id for r in rows}))

        order_skus = {r.variant.sku for r in rows}
        overrides = {p.sku: p.sale_unit_price for p in prices}
        unknown = sorted(set(overrides) - order_skus)
        if unknown:
            raise PriceForUnknownSku(unknown)

        # Decide on the whole order before touching anything: if any item
        # expired (still ACTIVE, or already released after expires_at), the
        # payment is late for the whole order and every remaining hold goes back.
        now = db.scalar(select(func.now()))
        active = [r for r in rows if r.status == ReservationStatus.ACTIVE]
        released = [r for r in rows if r.status == ReservationStatus.RELEASED]
        late = any(r.expires_at <= now for r in active) or any(
            r.resolved_at >= r.expires_at for r in released
        )
        if late:
            for row in active:
                _release(db, row)
            db.commit()
            raise PaymentTooLate(order_reference)
        if released or not active:
            raise OrderCancelled(order_reference)

        unit_prices = {
            r.id: (
                overrides[r.variant.sku]
                if r.variant.sku in overrides
                else _current_retail_price(db, r.variant)
            )
            for r in active
        }
        missing = sorted({r.variant.sku for r in active if unit_prices[r.id] is None})
        if missing:
            raise MissingSalePrice(missing)

        for row in active:
            row.status = ReservationStatus.CONFIRMED
            row.resolved_at = func.now()
            db.add(
                InventoryMovement(
                    variant_id=row.variant_id,
                    movement_type=MovementType.OUTBOUND_SALE,
                    physical_delta=-row.quantity,
                    reserved_delta=-row.quantity,
                    sale_unit_price=unit_prices[row.id],
                    reservation_id=row.id,
                    order_reference=order_reference,
                )
            )
        db.flush()
        db.commit()
    except Exception:
        db.rollback()
        raise
    return rows


def cancel_order(db: Session, order_reference: str) -> list[StockReservation]:
    """Checkout abandoned before paying: release the order's active reservations."""
    try:
        rows = _lock_order(db, order_reference)
        active = [r for r in rows if r.status == ReservationStatus.ACTIVE]
        if not active:
            raise OrderNotActive(order_reference)
        _lock_stock_levels(db, sorted({r.variant_id for r in active}))
        for row in active:
            _release(db, row)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return rows
