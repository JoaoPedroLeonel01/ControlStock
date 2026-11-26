"""Reserving stock for a PIX checkout, with lazy release of expired holds."""

import threading
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from src.control_stock.modules.inventory import service
from src.control_stock.modules.inventory.errors import (
    InsufficientStock,
    OrderReferenceUsed,
    SkuNotFound,
)
from src.control_stock.modules.inventory.models import (
    MovementType,
    ReservationStatus,
)
from tests.integration.factories import (
    count_movements,
    deactivate,
    expire_now,
    order,
    rows_of,
    stock,
    stocked,
)

pytestmark = pytest.mark.integration


def test_reserve_holds_stock_for_ten_minutes(db_session: Session) -> None:
    variant = stocked(db_session, "SVC-HOLD", 5)

    rows = service.create_reservations(db_session, order("PED-HOLD", ("SVC-HOLD", 2)))

    assert stock(db_session, variant) == (5, 2, 3)
    assert len(rows) == 1
    assert rows[0].status == ReservationStatus.ACTIVE
    assert rows[0].expires_at - rows[0].created_at == timedelta(minutes=10)
    assert count_movements(db_session, variant, MovementType.STOCK_RESERVE) == 1


def test_reserve_is_all_or_nothing(db_session: Session) -> None:
    a = stocked(db_session, "SVC-ALL-A", 5)
    b = stocked(db_session, "SVC-ALL-B", 1)

    with pytest.raises(InsufficientStock) as exc:
        service.create_reservations(
            db_session, order("PED-ALL", ("SVC-ALL-A", 2), ("SVC-ALL-B", 3))
        )

    assert exc.value.extra["items"] == [
        {"sku": "SVC-ALL-B", "requested": 3, "available": 1}
    ]
    assert stock(db_session, a) == (5, 0, 5)
    assert stock(db_session, b) == (1, 0, 1)
    assert rows_of(db_session, "PED-ALL") == []


def test_unknown_sku_lists_all_missing(db_session: Session) -> None:
    with pytest.raises(SkuNotFound) as exc:
        service.create_reservations(
            db_session, order("PED-NOPE", ("NOPE-2", 1), ("NOPE-1", 1))
        )
    assert exc.value.extra["skus"] == ["NOPE-1", "NOPE-2"]


@pytest.mark.parametrize("level", ["variant", "product", "category"])
def test_inactive_product_is_not_reservable(db_session: Session, level: str) -> None:
    sku = f"SVC-OFF-{level.upper()}"
    variant = stocked(db_session, sku, 5)
    deactivate(db_session, variant, level)
    db_session.commit()

    with pytest.raises(SkuNotFound) as exc:
        service.create_reservations(db_session, order(f"PED-OFF-{level}", (sku, 1)))
    assert exc.value.extra["skus"] == [sku]


def test_order_reference_is_single_use(db_session: Session) -> None:
    stocked(db_session, "SVC-ONCE-A", 5)
    stocked(db_session, "SVC-ONCE-B", 5)
    service.create_reservations(db_session, order("PED-ONCE", ("SVC-ONCE-A", 1)))

    with pytest.raises(OrderReferenceUsed):
        service.create_reservations(db_session, order("PED-ONCE", ("SVC-ONCE-B", 1)))


def test_reserve_releases_expired_holds_of_same_sku_first(db_session: Session) -> None:
    variant = stocked(db_session, "SVC-LAZY", 1)
    service.create_reservations(db_session, order("PED-LAZY-1", ("SVC-LAZY", 1)))
    expire_now(db_session, "PED-LAZY-1")

    service.create_reservations(db_session, order("PED-LAZY-2", ("SVC-LAZY", 1)))

    (old,) = rows_of(db_session, "PED-LAZY-1")
    db_session.refresh(old)
    assert old.status == ReservationStatus.RELEASED
    assert old.resolved_at is not None
    assert stock(db_session, variant) == (1, 1, 0)
    assert count_movements(db_session, variant, MovementType.STOCK_RELEASE) == 1


def test_get_stock_discounts_expired(db_session: Session) -> None:
    stocked(db_session, "SVC-STOCK", 3)
    service.create_reservations(db_session, order("PED-STOCK", ("SVC-STOCK", 2)))
    expire_now(db_session, "PED-STOCK")

    result = service.get_stock(db_session, "SVC-STOCK")

    assert (result.physical_qty, result.reserved_qty, result.available_qty) == (3, 0, 3)


def test_get_stock_unknown_sku(db_session: Session) -> None:
    with pytest.raises(SkuNotFound):
        service.get_stock(db_session, "NOPE-STOCK")


def test_expire_all_counts_released(db_session: Session) -> None:
    stocked(db_session, "SVC-SWEEP", 10)
    for ref in ("PED-SWEEP-1", "PED-SWEEP-2", "PED-SWEEP-3"):
        service.create_reservations(db_session, order(ref, ("SVC-SWEEP", 1)))
    expire_now(db_session, "PED-SWEEP-1")
    expire_now(db_session, "PED-SWEEP-2")

    assert service.expire_all(db_session) == 2

    (third,) = rows_of(db_session, "PED-SWEEP-3")
    assert third.status == ReservationStatus.ACTIVE


def test_concurrent_same_order_reference_creates_once(migrated_engine: Engine) -> None:
    suffix = uuid4().hex[:8].upper()
    sku, ref = f"SVC-RACE-{suffix}", f"PED-RACE-{suffix}"
    with Session(migrated_engine) as seed:
        stocked(seed, sku, 5)
        seed.commit()

    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt() -> None:
        with Session(migrated_engine) as session:
            barrier.wait()
            try:
                service.create_reservations(session, order(ref, (sku, 1)))
                outcomes.append("created")
            except OrderReferenceUsed:
                outcomes.append("rejected")

    threads = [threading.Thread(target=attempt, daemon=True) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert sorted(outcomes) == ["created", "rejected"]
    with Session(migrated_engine) as check:
        assert len(rows_of(check, ref)) == 1
