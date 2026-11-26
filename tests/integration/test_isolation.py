"""The per-test session really discards what a test wrote."""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from src.control_stock.modules.variants.models import Variant
from tests.integration.factories import make_variant, rolled_back_session

pytestmark = pytest.mark.integration


def test_successful_writes_are_rolled_back(migrated_engine: Engine) -> None:
    sku = "ISOLATION-OK"
    with rolled_back_session(migrated_engine) as session:
        make_variant(session, sku)  # succeeds and is flushed
        assert session.scalars(select(Variant).where(Variant.sku == sku)).one()

    with Session(migrated_engine) as fresh:
        assert fresh.scalars(select(Variant).where(Variant.sku == sku)).first() is None
