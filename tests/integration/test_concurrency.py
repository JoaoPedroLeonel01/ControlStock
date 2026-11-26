"""Concurrent reservations of the same SKU (NFR-01 / NFR-02).

Two real connections reserve at the same time. The movement trigger's UPDATE on
stock_levels takes a row lock, so the second reservation waits for the first
to commit and is then checked against the updated quantities:

* with 1 unit left, exactly one reservation wins and stock never goes negative;
* with enough units, both succeed one after the other (serialized, not refused).

These tests commit data (two connections cannot share a rolled-back
transaction), so each one uses its own unique SKU; the next session's schema
reset removes it.
"""

import threading
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.control_stock.modules.inventory.models import (
    InventoryMovement,
    MovementType,
    StockReservation,
)
from src.control_stock.modules.variants.models import Variant
from tests.integration.factories import make_variant, movement, stock

pytestmark = pytest.mark.integration


def _seed(engine: Engine, units: int) -> Variant:
    with Session(engine, expire_on_commit=False) as session:
        variant = make_variant(session, f"CONC-{uuid4().hex[:8].upper()}")
        movement(
            session,
            variant,
            MovementType.INBOUND_PURCHASE,
            units,
            0,
            purchase_unit_cost=Decimal("20.00"),
        )
        session.commit()
        return variant


def _reserve_one(session: Session, variant: Variant, order: str) -> None:
    reservation = StockReservation(
        variant_id=variant.id,
        quantity=1,
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
        1,
        reservation_id=reservation.id,
        order_reference=order,
    )


def _race(engine: Engine, variant: Variant) -> dict[str, object]:
    """A reserves and holds its transaction open; B tries meanwhile."""
    result: dict[str, object] = {}

    def run_b() -> None:
        with Session(engine) as session_b:
            result["b_pid"] = session_b.execute(
                text("SELECT pg_backend_pid()")
            ).scalar_one()
            try:
                _reserve_one(session_b, variant, "PED-B")
                session_b.commit()
                result["b"] = "committed"
            except DBAPIError as exc:
                session_b.rollback()
                result["b"] = exc.orig.diag.constraint_name

    with Session(engine) as session_a:
        _reserve_one(session_a, variant, "PED-A")  # holds the stock_levels lock
        thread_b = threading.Thread(target=run_b)
        thread_b.start()
        result["b_waited_on_lock"] = _saw_waiting_on_lock(session_a, result)
        session_a.commit()

    thread_b.join(timeout=10)
    result["b_finished"] = not thread_b.is_alive()
    return result


def _saw_waiting_on_lock(observer: Session, result: dict[str, object]) -> bool:
    """Poll until B's backend is waiting on a lock (bounded to ~5 s)."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        pid = result.get("b_pid")
        if pid is not None:
            waiting = (
                observer.connection()
                .exec_driver_sql(
                    "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %(pid)s",
                    {"pid": pid},
                )
                .scalar()
            )
            if waiting == "Lock":
                return True
        time.sleep(0.05)
    return False


def _reserve_movements(engine: Engine, variant: Variant) -> int:
    with Session(engine) as session:
        return session.scalar(
            select(func.count())
            .select_from(InventoryMovement)
            .where(
                InventoryMovement.variant_id == variant.id,
                InventoryMovement.movement_type == MovementType.STOCK_RESERVE,
            )
        )


def _final_stock(engine: Engine, variant: Variant) -> tuple[int, int, int]:
    with Session(engine) as session:
        return stock(session, variant)


def test_concurrent_reservations_of_last_unit(migrated_engine: Engine) -> None:
    variant = _seed(migrated_engine, units=1)

    result = _race(migrated_engine, variant)

    assert result["b_waited_on_lock"] is True
    assert result["b_finished"] is True
    assert result["b"] == "ck_stock_levels_reserved_lte_physical"
    assert _final_stock(migrated_engine, variant) == (1, 1, 0)
    assert _reserve_movements(migrated_engine, variant) == 1


def test_concurrent_reservations_with_enough_stock_both_succeed(
    migrated_engine: Engine,
) -> None:
    variant = _seed(migrated_engine, units=2)

    result = _race(migrated_engine, variant)

    assert result["b_waited_on_lock"] is True
    assert result["b_finished"] is True
    assert result["b"] == "committed"
    assert _final_stock(migrated_engine, variant) == (2, 2, 0)
    assert _reserve_movements(migrated_engine, variant) == 2
