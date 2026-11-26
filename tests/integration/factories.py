"""Small builders for integration tests.

Every name and slug is derived from the SKU, so tests never collide with each
other (including the concurrency tests, whose data is committed).
"""

from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from typing import Literal

from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from src.control_stock.modules.inventory.models import (
    InventoryMovement,
    MovementType,
    StockLevel,
    StockReservation,
)
from src.control_stock.modules.inventory.schemas import ReservationCreate
from src.control_stock.modules.products.models import (
    Category,
    PriceTier,
    Product,
    SizeGrid,
    SizeGridSize,
    TierPrice,
)
from src.control_stock.modules.variants.models import Variant


@contextmanager
def rolled_back_session(engine: Engine) -> Iterator[Session]:
    """Session inside an outer transaction that is always rolled back.

    Flushes (and even session.commit(), via a SAVEPOINT) never reach the
    database for other connections.
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


def make_variant(session: Session, sku: str) -> Variant:
    """Create the minimal catalog for one variant (stock_levels row via trigger)."""
    slug = sku.lower()
    category = Category(name=f"Categoria {sku}", slug=f"cat-{slug}")
    grid = SizeGrid(name=f"Grade {sku}")
    size = SizeGridSize(
        size_grid=grid, label="P", sort_order=1, default_tier_name="Normal"
    )
    product = Product(
        category=category, size_grid=grid, name=f"Produto {sku}", slug=f"prod-{slug}"
    )
    tier = PriceTier(product=product, name="Normal")
    session.add_all([category, grid, size, product, tier])
    session.flush()
    variant = Variant(
        product_id=product.id,
        price_tier_id=tier.id,
        size_grid_size_id=size.id,
        sku=sku,
        color_name="Preta",
    )
    session.add(variant)
    session.flush()
    return variant


def movement(
    session: Session,
    variant: Variant,
    movement_type: MovementType,
    physical: int,
    reserved: int,
    **extra: object,
) -> InventoryMovement:
    """Insert one ledger row; the database applies it to stock_levels."""
    row = InventoryMovement(
        variant_id=variant.id,
        movement_type=movement_type,
        physical_delta=physical,
        reserved_delta=reserved,
        **extra,
    )
    session.add(row)
    session.flush()
    return row


def stock(session: Session, variant: Variant) -> tuple[int, int, int]:
    """(physical, reserved, available) read straight from the database."""
    row = session.execute(
        select(
            StockLevel.physical_qty, StockLevel.reserved_qty, StockLevel.available_qty
        ).where(StockLevel.variant_id == variant.id)
    ).one()
    return tuple(row)


def set_price(
    session: Session,
    variant: Variant,
    retail: Decimal,
    cost: Decimal = Decimal("20.00"),
) -> None:
    """Give the variant's price tier a current price."""
    session.add(
        TierPrice(
            price_tier_id=variant.price_tier_id, cost_price=cost, retail_price=retail
        )
    )
    session.flush()


def deactivate(
    session: Session, variant: Variant, level: Literal["variant", "product", "category"]
) -> None:
    target = {
        "variant": variant,
        "product": variant.product,
        "category": variant.product.category,
    }[level]
    target.is_active = False
    session.flush()


# --- Reservation test helpers -------------------------------------------


def stocked(session: Session, sku: str, units: int) -> Variant:
    variant = make_variant(session, sku)
    if units:
        movement(
            session,
            variant,
            MovementType.INBOUND_PURCHASE,
            units,
            0,
            purchase_unit_cost=Decimal("20.00"),
        )
    # In db_session this only releases a SAVEPOINT (the test is still rolled
    # back at the end); it keeps the seed when the service rolls back an error.
    session.commit()
    return variant


def order(ref: str, *items: tuple[str, int]) -> ReservationCreate:
    return ReservationCreate(
        order_reference=ref, items=[{"sku": s, "quantity": q} for s, q in items]
    )


def expire_now(session: Session, ref: str) -> None:
    session.execute(
        text(
            "UPDATE stock_reservations SET expires_at = now() - interval '1 minute'"
            " WHERE order_reference = :ref"
        ),
        {"ref": ref},
    )


def rows_of(session: Session, ref: str) -> list[StockReservation]:
    return list(
        session.scalars(
            select(StockReservation)
            .where(StockReservation.order_reference == ref)
            .order_by(StockReservation.id)
        )
    )


def count_movements(session: Session, variant: Variant, kind: MovementType) -> int:
    return session.scalar(
        select(func.count())
        .select_from(InventoryMovement)
        .where(
            InventoryMovement.variant_id == variant.id,
            InventoryMovement.movement_type == kind,
        )
    )
