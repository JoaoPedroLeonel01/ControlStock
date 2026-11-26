"""Domain errors of the inventory module and their HTTP representation."""

from typing import Any


class InventoryError(Exception):
    status_code: int = 400
    code: str = "inventory_error"

    def __init__(self, message: str, **extra: Any) -> None:
        super().__init__(message)
        self.message = message
        self.extra = extra


class SkuNotFound(InventoryError):
    status_code, code = 404, "sku_not_found"

    def __init__(self, skus: list[str]) -> None:
        super().__init__("SKU not found or not available for sale", skus=skus)


class InsufficientStock(InventoryError):
    status_code, code = 409, "insufficient_stock"

    def __init__(self, items: list[dict[str, Any]]) -> None:
        super().__init__(
            "Not enough available stock; nothing was reserved", items=items
        )


class OrderReferenceUsed(InventoryError):
    status_code, code = 409, "order_reference_used"

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            f"Order reference {order_reference!r} was already used; "
            "start a new checkout with a new reference"
        )


class OrderNotFound(InventoryError):
    status_code, code = 404, "order_not_found"

    def __init__(self, order_reference: str) -> None:
        super().__init__(f"No reservations for order {order_reference!r}")


class OrderNotActive(InventoryError):
    status_code, code = 409, "order_not_active"

    def __init__(self, order_reference: str) -> None:
        super().__init__(f"Order {order_reference!r} has no active reservations")


class OrderCancelled(InventoryError):
    status_code, code = 409, "order_cancelled"

    def __init__(self, order_reference: str) -> None:
        super().__init__(f"Order {order_reference!r} was cancelled")


class PaymentTooLate(InventoryError):
    status_code, code = 410, "payment_too_late"

    def __init__(self, order_reference: str) -> None:
        super().__init__(
            f"Reservations of order {order_reference!r} expired; "
            "the stock was released and the payment must be refunded"
        )


class MissingSalePrice(InventoryError):
    status_code, code = 409, "missing_sale_price"

    def __init__(self, skus: list[str]) -> None:
        super().__init__("No current price and no sale price informed", skus=skus)


class PriceForUnknownSku(InventoryError):
    status_code, code = 422, "price_for_unknown_sku"

    def __init__(self, skus: list[str]) -> None:
        super().__init__(
            "Sale price given for SKUs that are not in the order", skus=skus
        )


def error_body(error: InventoryError) -> dict[str, Any]:
    return {"code": error.code, "message": error.message, **error.extra}
