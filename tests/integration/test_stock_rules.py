"""Stock rules enforced by the database (triggers + CHECK constraints).

Tests 1-7 of the manual sandbox checklist ("ControlStock — SQL do Banco"),
automated against PostgreSQL with the schema built by the migrations.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.control_stock.modules.inventory.models import (
    MovementType,
    StockReservation,
)
from src.control_stock.modules.variants.models import Variant
from tests.integration.factories import make_variant, movement, stock

pytestmark = pytest.mark.integration

GUARD_MESSAGE = "stock_levels can only be changed through inventory_movements"
DIRECT_UPDATE_SKU = "RULE-DIRECT-UPD"


def constraint_name(exc: pytest.ExceptionInfo[DBAPIError]) -> str | None:
    return exc.value.orig.diag.constraint_name


def test_alembic_targets_test_database(db_session: Session) -> None:
    assert (
        db_session.execute(text("SELECT current_database()"))
        .scalar_one()
        .endswith("_test")
    )
    version = db_session.execute(text("SELECT version_num FROM alembic_version"))
    assert version.scalar_one() == "0cdb374b5ab3"


def test_new_variant_gets_zeroed_stock_level(db_session: Session) -> None:
    variant = make_variant(db_session, "RULE-NEW")
    assert stock(db_session, variant) == (0, 0, 0)


def test_direct_update_of_stock_levels_is_rejected(db_session: Session) -> None:
    make_variant(db_session, DIRECT_UPDATE_SKU)
    with pytest.raises(DBAPIError, match=GUARD_MESSAGE):
        db_session.execute(text("UPDATE stock_levels SET physical_qty = 50"))


def test_stock_levels_truncate_is_rejected(db_session: Session) -> None:
    with pytest.raises(DBAPIError, match=GUARD_MESSAGE):
        db_session.execute(text("TRUNCATE stock_levels"))


def test_inbound_purchase_updates_stock(db_session: Session) -> None:
    variant = make_variant(db_session, "RULE-INBOUND")
    movement(
        db_session,
        variant,
        MovementType.INBOUND_PURCHASE,
        10,
        0,
        purchase_unit_cost=Decimal("20.00"),
    )
    assert stock(db_session, variant) == (10, 0, 10)


def test_loss_beyond_stock_is_rejected(db_session: Session) -> None:
    variant = make_variant(db_session, "RULE-LOSS")
    movement(
        db_session,
        variant,
        MovementType.INBOUND_PURCHASE,
        10,
        0,
        purchase_unit_cost=Decimal("20.00"),
    )
    with pytest.raises(DBAPIError) as exc:
        movement(
            db_session,
            variant,
            MovementType.LOSS_DEFECT,
            -11,
            0,
            note="peça rasgada",
        )
    assert constraint_name(exc) == "ck_stock_levels_physical_non_negative"


def _reserve(session: Session, variant: Variant, qty: int, order: str) -> None:
    reservation = StockReservation(
        variant_id=variant.id,
        quantity=qty,
        order_reference=order,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    session.add(reservation)
    session.flush()
    movement(
        session,
        variant,
        MovementType.STOCK_RESERVE,
        0,
        qty,
        reservation_id=reservation.id,
        order_reference=order,
    )


def test_reservation_beyond_physical_is_rejected(db_session: Session) -> None:
    variant = make_variant(db_session, "RULE-RES-OVER")
    movement(
        db_session,
        variant,
        MovementType.INBOUND_PURCHASE,
        1,
        0,
        purchase_unit_cost=Decimal("20.00"),
    )
    with pytest.raises(DBAPIError) as exc:
        _reserve(db_session, variant, 2, "PED-OVER")
    assert constraint_name(exc) == "ck_stock_levels_reserved_lte_physical"


def test_reserve_release_and_sale_flow(db_session: Session) -> None:
    variant = make_variant(db_session, "RULE-FLOW")
    movement(
        db_session,
        variant,
        MovementType.INBOUND_PURCHASE,
        10,
        0,
        purchase_unit_cost=Decimal("20.00"),
    )
    reservation = StockReservation(
        variant_id=variant.id,
        quantity=3,
        order_reference="PED-FLOW",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(reservation)
    db_session.flush()
    linked = {"reservation_id": reservation.id, "order_reference": "PED-FLOW"}

    movement(db_session, variant, MovementType.STOCK_RESERVE, 0, 3, **linked)
    assert stock(db_session, variant) == (10, 3, 7)

    movement(db_session, variant, MovementType.STOCK_RELEASE, 0, -1, **linked)
    assert stock(db_session, variant) == (10, 2, 8)

    movement(
        db_session,
        variant,
        MovementType.OUTBOUND_SALE,
        -2,
        -2,
        sale_unit_price=Decimal("59.90"),
        **linked,
    )
    assert stock(db_session, variant) == (8, 0, 8)
