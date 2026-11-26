import pytest

from src.control_stock.modules.inventory.errors import (
    InsufficientStock,
    InventoryError,
    MissingSalePrice,
    OrderCancelled,
    OrderNotActive,
    OrderNotFound,
    OrderReferenceUsed,
    PaymentTooLate,
    PriceForUnknownSku,
    SkuNotFound,
    error_body,
)


@pytest.mark.parametrize(
    ("error", "status", "code"),
    [
        (SkuNotFound(["A"]), 404, "sku_not_found"),
        (InsufficientStock([]), 409, "insufficient_stock"),
        (OrderReferenceUsed("P"), 409, "order_reference_used"),
        (OrderNotFound("P"), 404, "order_not_found"),
        (OrderNotActive("P"), 409, "order_not_active"),
        (OrderCancelled("P"), 409, "order_cancelled"),
        (PaymentTooLate("P"), 410, "payment_too_late"),
        (MissingSalePrice(["A"]), 409, "missing_sale_price"),
        (PriceForUnknownSku(["A"]), 422, "price_for_unknown_sku"),
    ],
)
def test_error_body_and_status(error: InventoryError, status: int, code: str) -> None:
    assert error.status_code == status
    body = error_body(error)
    assert body["code"] == code
    assert isinstance(body["message"], str) and body["message"]


def test_insufficient_stock_lists_items() -> None:
    items = [{"sku": "A", "requested": 2, "available": 1}]
    assert error_body(InsufficientStock(items))["items"] == items


def test_sku_errors_list_skus() -> None:
    assert error_body(SkuNotFound(["A", "B"]))["skus"] == ["A", "B"]
    assert error_body(MissingSalePrice(["A"]))["skus"] == ["A"]
    assert error_body(PriceForUnknownSku(["X"]))["skus"] == ["X"]
