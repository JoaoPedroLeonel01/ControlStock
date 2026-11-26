"""Confirming (PIX paid) and cancelling reservations, including late payments."""

import threading
import time
from collections.abc import Callable
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from src.control_stock.modules.inventory import service
from src.control_stock.modules.inventory.errors import (
    InventoryError,
    MissingSalePrice,
    OrderCancelled,
    OrderNotActive,
    OrderNotFound,
    PaymentTooLate,
    PriceForUnknownSku,
)
from src.control_stock.modules.inventory.models import (
    InventoryMovement,
    MovementType,
    ReservationStatus,
)
from src.control_stock.modules.inventory.schemas import SalePriceIn
from src.control_stock.modules.variants.models import Variant
from tests.integration.factories import (
    count_movements,
    expire_now,
    order,
    rows_of,
    set_price,
    stock,
    stocked,
)

pytestmark = pytest.mark.integration


def reserved(
    session: Session, sku: str, ref: str, *, units: int = 5, qty: int = 2, price=True
) -> Variant:
    variant = stocked(session, sku, units)
    if price:
        set_price(session, variant, Decimal("59.90"))
        session.commit()
    service.create_reservations(session, order(ref, (sku, qty)))
    return variant


def sale_prices(session: Session, variant: Variant) -> list[Decimal]:
    return list(
        session.scalars(
            select(InventoryMovement.sale_unit_price).where(
                InventoryMovement.variant_id == variant.id,
                InventoryMovement.movement_type == MovementType.OUTBOUND_SALE,
            )
        )
    )


def test_confirm_turns_reservation_into_sale(db_session: Session) -> None:
    variant = reserved(db_session, "LIFE-OK", "PED-OK")

    rows = service.confirm_order(db_session, "PED-OK")

    assert stock(db_session, variant) == (3, 0, 3)
    assert [r.status for r in rows] == [ReservationStatus.CONFIRMED]
    assert rows[0].resolved_at is not None
    assert sale_prices(db_session, variant) == [Decimal("59.90")]


def test_confirm_uses_price_override(db_session: Session) -> None:
    variant = reserved(db_session, "LIFE-DISC", "PED-DISC")

    service.confirm_order(
        db_session,
        "PED-DISC",
        [SalePriceIn(sku="LIFE-DISC", sale_unit_price=Decimal("49.90"))],
    )

    assert sale_prices(db_session, variant) == [Decimal("49.90")]


def test_confirm_twice_is_idempotent(db_session: Session) -> None:
    variant = reserved(db_session, "LIFE-TWICE", "PED-TWICE")
    first = service.confirm_order(db_session, "PED-TWICE")

    second = service.confirm_order(db_session, "PED-TWICE")

    assert [r.id for r in second] == [r.id for r in first]
    assert count_movements(db_session, variant, MovementType.OUTBOUND_SALE) == 1
    assert stock(db_session, variant) == (3, 0, 3)


def test_confirm_expired_active_releases_and_raises_too_late(
    db_session: Session,
) -> None:
    variant = reserved(db_session, "LIFE-LATE", "PED-LATE")
    expire_now(db_session, "PED-LATE")
    db_session.commit()

    with pytest.raises(PaymentTooLate):
        service.confirm_order(db_session, "PED-LATE")

    (row,) = rows_of(db_session, "PED-LATE")
    db_session.refresh(row)
    assert row.status == ReservationStatus.RELEASED
    assert stock(db_session, variant) == (5, 0, 5)
    assert count_movements(db_session, variant, MovementType.OUTBOUND_SALE) == 0


def test_confirm_after_sweep_is_too_late(db_session: Session) -> None:
    reserved(db_session, "LIFE-SWEPT", "PED-SWEPT")
    expire_now(db_session, "PED-SWEPT")
    service.expire_all(db_session)

    with pytest.raises(PaymentTooLate):
        service.confirm_order(db_session, "PED-SWEPT")


def test_confirm_after_cancel_is_conflict(db_session: Session) -> None:
    reserved(db_session, "LIFE-CANC", "PED-CANC")
    service.cancel_order(db_session, "PED-CANC")

    with pytest.raises(OrderCancelled):
        service.confirm_order(db_session, "PED-CANC")


def test_confirm_rejects_price_for_unknown_sku(db_session: Session) -> None:
    variant = reserved(db_session, "LIFE-UNK", "PED-UNK")

    with pytest.raises(PriceForUnknownSku) as exc:
        service.confirm_order(
            db_session,
            "PED-UNK",
            [SalePriceIn(sku="OTHER", sale_unit_price=Decimal("1.00"))],
        )

    assert exc.value.extra["skus"] == ["OTHER"]
    (row,) = rows_of(db_session, "PED-UNK")
    assert row.status == ReservationStatus.ACTIVE
    assert count_movements(db_session, variant, MovementType.OUTBOUND_SALE) == 0


def test_confirm_without_price_changes_nothing(db_session: Session) -> None:
    variant = reserved(db_session, "LIFE-NOPRICE", "PED-NOPRICE", price=False)

    with pytest.raises(MissingSalePrice) as exc:
        service.confirm_order(db_session, "PED-NOPRICE")

    assert exc.value.extra["skus"] == ["LIFE-NOPRICE"]
    (row,) = rows_of(db_session, "PED-NOPRICE")
    assert row.status == ReservationStatus.ACTIVE
    assert count_movements(db_session, variant, MovementType.OUTBOUND_SALE) == 0
    assert stock(db_session, variant) == (5, 2, 3)


def test_cancel_releases_and_second_cancel_conflicts(db_session: Session) -> None:
    variant = reserved(db_session, "LIFE-CANCEL", "PED-CANCEL")

    rows = service.cancel_order(db_session, "PED-CANCEL")

    assert stock(db_session, variant) == (5, 0, 5)
    assert rows[0].status == ReservationStatus.RELEASED
    assert rows[0].resolved_at < rows[0].expires_at
    with pytest.raises(OrderNotActive):
        service.cancel_order(db_session, "PED-CANCEL")


def test_get_order_returns_rows_and_unknown_raises(db_session: Session) -> None:
    reserved(db_session, "LIFE-GET", "PED-GET")
    assert [r.order_reference for r in service.get_order(db_session, "PED-GET")] == [
        "PED-GET"
    ]
    with pytest.raises(OrderNotFound):
        service.get_order(db_session, "PED-NOBODY")


def _run_both(
    engine: Engine,
    first: Callable[[Session], object],
    second: Callable[[Session], object],
) -> list[object]:
    barrier = threading.Barrier(2)
    results: list[object] = []

    def run(action: Callable[[Session], object]) -> None:
        with Session(engine) as session:
            barrier.wait()
            try:
                results.append(action(session))
            except InventoryError as exc:
                results.append(exc)

    threads = [
        threading.Thread(target=run, args=(action,), daemon=True)
        for action in (first, second)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
    assert not any(thread.is_alive() for thread in threads)
    return results


def _committed_order(engine: Engine, prefix: str) -> tuple[Variant, str]:
    suffix = uuid4().hex[:8].upper()
    sku, ref = f"{prefix}-{suffix}", f"PED-{prefix}-{suffix}"
    with Session(engine, expire_on_commit=False) as session:
        variant = reserved(session, sku, ref)
    return variant, ref


def test_confirm_and_sweep_race_release_once(migrated_engine: Engine) -> None:
    variant, ref = _committed_order(migrated_engine, "RACE-SWEEP")
    with Session(migrated_engine) as session:
        expire_now(session, ref)
        session.commit()

    results = _run_both(
        migrated_engine,
        lambda s: service.confirm_order(s, ref),
        service.expire_all,
    )

    assert any(isinstance(r, PaymentTooLate) for r in results)
    with Session(migrated_engine) as check:
        assert count_movements(check, variant, MovementType.STOCK_RELEASE) == 1
        assert count_movements(check, variant, MovementType.OUTBOUND_SALE) == 0
        assert [r.status for r in rows_of(check, ref)] == [ReservationStatus.RELEASED]


def test_confirm_and_cancel_race_one_effect(migrated_engine: Engine) -> None:
    variant, ref = _committed_order(migrated_engine, "RACE-CANCEL")

    results = _run_both(
        migrated_engine,
        lambda s: service.confirm_order(s, ref),
        lambda s: service.cancel_order(s, ref),
    )

    errors = [r for r in results if isinstance(r, InventoryError)]
    assert len(errors) == 1
    assert isinstance(errors[0], OrderCancelled | OrderNotActive)
    with Session(migrated_engine) as check:
        sales = count_movements(check, variant, MovementType.OUTBOUND_SALE)
        releases = count_movements(check, variant, MovementType.STOCK_RELEASE)
        assert sales + releases == 1


def test_confirm_accepts_zero_price_override(db_session: Session) -> None:
    variant = reserved(db_session, "LIFE-FREE", "PED-FREE")

    service.confirm_order(
        db_session,
        "PED-FREE",
        [SalePriceIn(sku="LIFE-FREE", sale_unit_price=Decimal("0.00"))],
    )

    assert sale_prices(db_session, variant) == [Decimal("0.00")]


def test_confirm_partially_released_order_is_too_late(db_session: Session) -> None:
    # Item A of the order was released by expiry (e.g. a stock lookup ran just
    # after expires_at) while B still looks active: the order is late as a whole.
    a = stocked(db_session, "LIFE-PART-A", 5)
    b = stocked(db_session, "LIFE-PART-B", 5)
    for variant in (a, b):
        set_price(db_session, variant, Decimal("59.90"))
    db_session.commit()
    service.create_reservations(
        db_session, order("PED-PART", ("LIFE-PART-A", 1), ("LIFE-PART-B", 1))
    )
    db_session.execute(
        text(
            "UPDATE stock_reservations SET expires_at = now() - interval '1 minute'"
            " WHERE order_reference = 'PED-PART' AND variant_id = :a"
        ),
        {"a": a.id},
    )
    service.release_expired(db_session, [a.id])
    db_session.commit()

    with pytest.raises(PaymentTooLate):
        service.confirm_order(db_session, "PED-PART")

    assert count_movements(db_session, b, MovementType.OUTBOUND_SALE) == 0
    assert [r.status for r in rows_of(db_session, "PED-PART")] == [
        ReservationStatus.RELEASED,
        ReservationStatus.RELEASED,
    ]
    assert stock(db_session, b) == (5, 0, 5)


def test_confirm_locks_stock_in_variant_order(migrated_engine: Engine) -> None:
    # Global lock order on stock_levels (by variant_id) is what prevents
    # deadlocks between orders holding the same SKUs in different orders.
    suffix = uuid4().hex[:8].upper()
    ref = f"PED-LOCK-{suffix}"
    with Session(migrated_engine, expire_on_commit=False) as session:
        low = stocked(session, f"LOCK-LOW-{suffix}", 5)
        high = stocked(session, f"LOCK-HIGH-{suffix}", 5)
        for variant in (low, high):
            set_price(session, variant, Decimal("59.90"))
        session.commit()
        # Item order [high, low]: the reservation of `high` gets the lower id.
        service.create_reservations(session, order(ref, (high.sku, 1), (low.sku, 1)))

    blocker = migrated_engine.connect()
    blocker_tx = blocker.begin()
    blocker.execute(
        text("SELECT 1 FROM stock_levels WHERE variant_id = :v FOR UPDATE"),
        {"v": high.id},
    )
    result: dict[str, object] = {}

    def confirm() -> None:
        with Session(migrated_engine) as session:
            result["pid"] = session.execute(text("SELECT pg_backend_pid()")).scalar()
            service.confirm_order(session, ref)

    thread = threading.Thread(target=confirm, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        waiting = False
        while time.monotonic() < deadline and not waiting:
            pid = result.get("pid")
            if pid is not None:
                waiting = (
                    blocker.execute(
                        text(
                            "SELECT wait_event_type FROM pg_stat_activity"
                            " WHERE pid = :p"
                        ),
                        {"p": pid},
                    ).scalar()
                    == "Lock"
                )
            time.sleep(0.05)
        assert waiting, "confirm never waited on the blocked stock row"

        # Confirm must already hold the LOWER variant's row (sorted locking).
        with migrated_engine.connect() as probe:
            with pytest.raises(OperationalError, match="could not obtain lock"):
                probe.execute(
                    text(
                        "SELECT 1 FROM stock_levels WHERE variant_id = :v"
                        " FOR UPDATE NOWAIT"
                    ),
                    {"v": low.id},
                )
    finally:
        blocker_tx.rollback()
        blocker.close()
        thread.join(timeout=10)
    assert not thread.is_alive()
