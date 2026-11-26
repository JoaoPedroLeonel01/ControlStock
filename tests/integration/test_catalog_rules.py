"""Catalog integrity enforced by the database."""

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from src.control_stock.modules.products.models import TierPrice
from tests.integration.factories import make_variant

pytestmark = pytest.mark.integration


def test_only_one_current_price_per_tier(db_session: Session) -> None:
    variant = make_variant(db_session, "CAT-PRICE")
    for retail in (Decimal("59.90"), Decimal("69.90")):
        db_session.add(
            TierPrice(
                price_tier_id=variant.price_tier_id,
                cost_price=Decimal("20.00"),
                retail_price=retail,
            )
        )
    with pytest.raises(DBAPIError) as exc:
        db_session.flush()
    assert exc.value.orig.diag.constraint_name == "uq_tier_prices_current"


def test_category_with_products_cannot_be_deleted(db_session: Session) -> None:
    variant = make_variant(db_session, "CAT-DELETE")
    category_id = variant.product.category_id
    with pytest.raises(DBAPIError) as exc:
        db_session.execute(
            text("DELETE FROM categories WHERE id = :id"), {"id": category_id}
        )
    assert exc.value.orig.diag.constraint_name == "fk_products_category_id_categories"
