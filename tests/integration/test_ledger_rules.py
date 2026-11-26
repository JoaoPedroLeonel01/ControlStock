"""The inventory ledger is append-only and each movement type has strict rules."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.control_stock.modules.inventory.models import MovementType, StockReservation
from tests.integration.factories import make_variant, movement

pytestmark = pytest.mark.integration


def _with_one_movement(session: Session, sku: str) -> None:
    variant = make_variant(session, sku)
    movement(
        session,
        variant,
        MovementType.INBOUND_PURCHASE,
        10,
        0,
        purchase_unit_cost=Decimal("20.00"),
    )


def test_ledger_delete_is_rejected(db_session: Session) -> None:
    _with_one_movement(db_session, "LEDGER-DEL")
    with pytest.raises(
        DBAPIError, match="inventory_movements is immutable: DELETE is not allowed"
    ):
        db_session.execute(text("DELETE FROM inventory_movements"))


def test_ledger_update_is_rejected(db_session: Session) -> None:
    _with_one_movement(db_session, "LEDGER-UPD")
    with pytest.raises(
        DBAPIError, match="inventory_movements is immutable: UPDATE is not allowed"
    ):
        db_session.execute(text("UPDATE inventory_movements SET physical_delta = 99"))


def test_ledger_truncate_is_rejected(db_session: Session) -> None:
    with pytest.raises(
        DBAPIError, match="inventory_movements is immutable: TRUNCATE is not allowed"
    ):
        db_session.execute(text("TRUNCATE inventory_movements"))


def test_delta_rule_rejects_negative_purchase(db_session: Session) -> None:
    variant = make_variant(db_session, "LEDGER-NEG-IN")
    with pytest.raises(DBAPIError) as exc:
        movement(
            db_session,
            variant,
            MovementType.INBOUND_PURCHASE,
            -1,
            0,
            purchase_unit_cost=Decimal("20.00"),
        )
    assert exc.value.orig.diag.constraint_name == "ck_inventory_movements_delta_rule"


def test_movement_reservation_must_match_variant(db_session: Session) -> None:
    variant_a = make_variant(db_session, "LEDGER-RES-A")
    variant_b = make_variant(db_session, "LEDGER-RES-B")
    movement(
        db_session,
        variant_b,
        MovementType.INBOUND_PURCHASE,
        5,
        0,
        purchase_unit_cost=Decimal("20.00"),
    )
    reservation_of_a = StockReservation(
        variant_id=variant_a.id,
        quantity=1,
        order_reference="PED-MISMATCH",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db_session.add(reservation_of_a)
    db_session.flush()
    with pytest.raises(DBAPIError) as exc:
        movement(
            db_session,
            variant_b,
            MovementType.STOCK_RESERVE,
            0,
            1,
            reservation_id=reservation_of_a.id,
            order_reference="PED-MISMATCH",
        )
    assert (
        exc.value.orig.diag.constraint_name
        == "fk_inventory_movements_reservation_variant"
    )
