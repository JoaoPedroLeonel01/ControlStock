"""HTTP contract of the reservation and stock endpoints."""

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tests.integration.factories import expire_now, set_price, stocked

pytestmark = pytest.mark.integration

API = "/api/v1"


def seed(session: Session, sku: str, units: int = 5, price: bool = True) -> None:
    variant = stocked(session, sku, units)
    if price:
        set_price(session, variant, Decimal("59.90"))
        session.commit()


def reserve(client: TestClient, ref: str, sku: str, qty: int = 2):
    return client.post(
        f"{API}/reservations",
        json={"order_reference": ref, "items": [{"sku": sku, "quantity": qty}]},
    )


def test_post_reservation_returns_201_with_expiry(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session, "API-NEW")

    response = reserve(client, "PED-API-NEW", "API-NEW")

    assert response.status_code == 201
    body = response.json()
    assert body["order_reference"] == "PED-API-NEW"
    (item,) = body["reservations"]
    assert item["sku"] == "API-NEW"
    assert item["quantity"] == 2
    assert item["status"] == "ACTIVE"
    assert item["expires_at"] and item["resolved_at"] is None


def test_post_insufficient_returns_409_with_items(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session, "API-SHORT", units=1)

    response = reserve(client, "PED-API-SHORT", "API-SHORT", qty=3)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["code"] == "insufficient_stock"
    assert detail["items"] == [{"sku": "API-SHORT", "requested": 3, "available": 1}]


def test_post_unknown_sku_returns_404(client: TestClient) -> None:
    response = reserve(client, "PED-API-404", "API-NOPE")
    assert response.status_code == 404
    assert response.json()["detail"]["skus"] == ["API-NOPE"]


def test_post_validation_returns_422(client: TestClient) -> None:
    response = reserve(client, "PED-API-422", "API-X", qty=0)
    assert response.status_code == 422


def test_post_reused_reference_returns_409(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session, "API-REUSE")
    reserve(client, "PED-API-REUSE", "API-REUSE", qty=1)

    response = reserve(client, "PED-API-REUSE", "API-REUSE", qty=1)

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "order_reference_used"


def test_get_order_and_404(client: TestClient, db_session: Session) -> None:
    seed(db_session, "API-GET")
    reserve(client, "PED-API-GET", "API-GET")

    assert client.get(f"{API}/reservations/PED-API-GET").status_code == 200
    missing = client.get(f"{API}/reservations/PED-API-NONE")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "order_not_found"


def test_confirm_returns_200_and_repeat_200(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session, "API-PAY")
    reserve(client, "PED-API-PAY", "API-PAY")

    first = client.post(f"{API}/reservations/PED-API-PAY/confirm")
    second = client.post(f"{API}/reservations/PED-API-PAY/confirm")

    assert first.status_code == 200
    assert first.json()["reservations"][0]["status"] == "CONFIRMED"
    assert second.status_code == 200
    assert second.json() == first.json()
    stock = client.get(f"{API}/stock/API-PAY").json()
    assert (stock["physical_qty"], stock["reserved_qty"]) == (3, 0)


def test_confirm_with_price_override(client: TestClient, db_session: Session) -> None:
    seed(db_session, "API-DISC")
    reserve(client, "PED-API-DISC", "API-DISC")

    response = client.post(
        f"{API}/reservations/PED-API-DISC/confirm",
        json={"prices": [{"sku": "API-DISC", "sale_unit_price": "49.90"}]},
    )

    assert response.status_code == 200


def test_confirm_late_returns_410(client: TestClient, db_session: Session) -> None:
    seed(db_session, "API-LATE")
    reserve(client, "PED-API-LATE", "API-LATE")
    expire_now(db_session, "PED-API-LATE")
    db_session.commit()

    response = client.post(f"{API}/reservations/PED-API-LATE/confirm")

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "payment_too_late"


def test_confirm_cancelled_returns_409(client: TestClient, db_session: Session) -> None:
    seed(db_session, "API-CANC")
    reserve(client, "PED-API-CANC", "API-CANC")
    client.post(f"{API}/reservations/PED-API-CANC/cancel")

    response = client.post(f"{API}/reservations/PED-API-CANC/confirm")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "order_cancelled"


def test_cancel_returns_200(client: TestClient, db_session: Session) -> None:
    seed(db_session, "API-STOP")
    reserve(client, "PED-API-STOP", "API-STOP")

    response = client.post(f"{API}/reservations/PED-API-STOP/cancel")

    assert response.status_code == 200
    assert response.json()["reservations"][0]["status"] == "RELEASED"


def test_expire_returns_released_count(client: TestClient, db_session: Session) -> None:
    seed(db_session, "API-SWEEP")
    reserve(client, "PED-API-SWEEP", "API-SWEEP")
    expire_now(db_session, "PED-API-SWEEP")
    db_session.commit()

    response = client.post(f"{API}/reservations/expire")

    assert response.status_code == 200
    assert response.json()["released"] >= 1


def test_stock_returns_quantities_and_404(
    client: TestClient, db_session: Session
) -> None:
    seed(db_session, "API-STOCK", units=4)
    reserve(client, "PED-API-STOCK", "API-STOCK", qty=1)

    response = client.get(f"{API}/stock/API-STOCK")

    assert response.status_code == 200
    assert response.json() == {
        "sku": "API-STOCK",
        "physical_qty": 4,
        "reserved_qty": 1,
        "available_qty": 3,
    }
    assert client.get(f"{API}/stock/API-NOPE").status_code == 404


def test_openapi_lists_reservation_routes(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    for path in [
        f"{API}/reservations",
        f"{API}/reservations/{{order_reference}}",
        f"{API}/reservations/{{order_reference}}/confirm",
        f"{API}/reservations/{{order_reference}}/cancel",
        f"{API}/reservations/expire",
        f"{API}/stock/{{sku}}",
    ]:
        assert path in paths
