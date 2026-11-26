"""Single registry of all ORM models.

Importing this module registers every table on ``Base.metadata``; Alembic
(``migrations/env.py``) and tests rely on it.
"""

from src.control_stock.modules.inventory.models import (
    InventoryMovement,
    StockLevel,
    StockReservation,
)
from src.control_stock.modules.products.models import (
    Category,
    PriceTier,
    Product,
    SizeGrid,
    SizeGridSize,
    TierPrice,
)
from src.control_stock.modules.variants.models import Variant

__all__ = [
    "Category",
    "InventoryMovement",
    "PriceTier",
    "Product",
    "SizeGrid",
    "SizeGridSize",
    "StockLevel",
    "StockReservation",
    "TierPrice",
    "Variant",
]
