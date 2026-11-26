import pytest
from pydantic import ValidationError

from src.control_stock.modules.inventory.schemas import (
    ReservationCreate,
    SalePriceIn,
)


def _order(items: list[dict], ref: str = "PED-1") -> ReservationCreate:
    return ReservationCreate(order_reference=ref, items=items)


def test_duplicate_skus_are_summed() -> None:
    order = _order(
        [
            {"sku": "A", "quantity": 2},
            {"sku": "B", "quantity": 1},
            {"sku": "A", "quantity": 3},
        ]
    )
    assert [(i.sku, i.quantity) for i in order.items] == [("A", 5), ("B", 1)]


@pytest.mark.parametrize("quantity", [0, -1])
def test_quantity_must_be_positive(quantity: int) -> None:
    with pytest.raises(ValidationError):
        _order([{"sku": "A", "quantity": quantity}])


def test_items_cannot_be_empty() -> None:
    with pytest.raises(ValidationError):
        _order([])


def test_order_reference_is_stripped_and_bounded() -> None:
    assert _order([{"sku": "A", "quantity": 1}], "  PED-1 ").order_reference == "PED-1"
    for bad in ["", "   ", "X" * 101]:
        with pytest.raises(ValidationError):
            _order([{"sku": "A", "quantity": 1}], bad)


def test_sku_is_stripped() -> None:
    assert _order([{"sku": " A ", "quantity": 1}]).items[0].sku == "A"


@pytest.mark.parametrize("price", ["-1", "10.999"])
def test_sale_price_rejects_negative_and_three_decimals(price: str) -> None:
    with pytest.raises(ValidationError):
        SalePriceIn(sku="A", sale_unit_price=price)
