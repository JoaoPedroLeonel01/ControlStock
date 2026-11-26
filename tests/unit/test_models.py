import warnings

from sqlalchemy.orm import configure_mappers

from src.control_stock import models  # noqa: F401
from src.control_stock.core.database import Base

CATALOG_TABLES = {
    "categories",
    "size_grids",
    "size_grid_sizes",
    "products",
    "price_tiers",
    "tier_prices",
    "variants",
}


def constraint_names(table: str) -> set[str]:
    t = Base.metadata.tables[table]
    return {c.name for c in t.constraints} | {i.name for i in t.indexes}


def test_catalog_tables_registered() -> None:
    assert CATALOG_TABLES <= set(Base.metadata.tables)


def test_catalog_named_constraints() -> None:
    assert {
        "uq_size_grid_sizes_grid_label",
        "uq_size_grid_sizes_grid_order",
    } <= constraint_names("size_grid_sizes")
    assert {
        "uq_price_tiers_product_id_name",
        "uq_price_tiers_id_product_id",
    } <= constraint_names("price_tiers")
    assert {
        "uq_tier_prices_current",
        "ck_tier_prices_cost_price_non_negative",
        "ck_tier_prices_retail_price_non_negative",
        "ck_tier_prices_valid_range",
    } <= constraint_names("tier_prices")
    assert {
        "fk_variants_price_tier_product",
        "uq_variants_product_color_size",
        "ck_variants_min_safety_stock_non_negative",
        "ck_variants_color_hex_format",
    } <= constraint_names("variants")


def test_variant_has_no_price_columns() -> None:
    cols = set(Base.metadata.tables["variants"].c.keys())
    assert not {"cost_price", "retail_price"} & cols


def test_current_price_index_is_partial_unique() -> None:
    idx = next(
        i
        for i in Base.metadata.tables["tier_prices"].indexes
        if i.name == "uq_tier_prices_current"
    )
    assert idx.unique
    assert "valid_to IS NULL" in str(idx.dialect_options["postgresql"]["where"])


def test_mappers_configure_without_warnings() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        configure_mappers()


def test_inventory_tables_registered() -> None:
    assert {"stock_levels", "stock_reservations", "inventory_movements"} <= set(
        Base.metadata.tables
    )


def test_enum_values() -> None:
    from src.control_stock.modules.inventory.models import (
        MovementType,
        ReservationStatus,
        ReturnReason,
    )

    assert [m.value for m in MovementType] == [
        "INBOUND_PURCHASE",
        "OUTBOUND_SALE",
        "STOCK_RESERVE",
        "STOCK_RELEASE",
        "CUSTOMER_RETURN",
        "LOSS_DEFECT",
        "INVENTORY_ADJUSTMENT",
    ]
    assert [m.value for m in ReturnReason] == [
        "WRONG_SIZE",
        "FABRIC_DEFECT",
        "NOT_AS_PICTURED",
        "CUSTOMER_REGRET",
    ]
    assert [m.value for m in ReservationStatus] == ["ACTIVE", "CONFIRMED", "RELEASED"]


def test_available_qty_is_computed() -> None:
    col = Base.metadata.tables["stock_levels"].c.available_qty
    assert col.computed is not None
    assert col.computed.persisted


def test_inventory_named_constraints() -> None:
    assert {
        "ck_stock_levels_physical_non_negative",
        "ck_stock_levels_reserved_non_negative",
        "ck_stock_levels_reserved_lte_physical",
    } <= constraint_names("stock_levels")
    assert {
        "ck_stock_reservations_quantity_positive",
        "ck_stock_reservations_resolved_when_not_active",
        "ix_stock_reservations_status_expires_at",
    } <= constraint_names("stock_reservations")
    assert {
        "ck_inventory_movements_purchase_cost_rule",
        "ck_inventory_movements_sale_price_rule",
        "ck_inventory_movements_return_reason_rule",
        "ck_inventory_movements_note_rule",
        "ck_inventory_movements_delta_rule",
        "ck_inventory_movements_reservation_rule",
        "ck_inventory_movements_order_reference_rule",
        "ix_inventory_movements_variant_created",
    } <= constraint_names("inventory_movements")


def _inventory_migration():
    import importlib.util
    from pathlib import Path

    path = next(Path("migrations/versions").glob("*_0cdb374b5ab3_*.py"))
    spec = importlib.util.spec_from_file_location("inventory_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_stock_levels_truncate_is_guarded() -> None:
    triggers = {(t[1], t[2]) for t in _inventory_migration().TRIGGERS}
    assert (
        "stock_levels",
        "BEFORE TRUNCATE ON stock_levels FOR EACH STATEMENT",
    ) in triggers


def test_db_cascades_are_passive_in_orm() -> None:
    from sqlalchemy import inspect

    from src.control_stock.models import Category, PriceTier, Product

    product = inspect(Product).relationships
    assert product["variants"].passive_deletes is True
    assert product["price_tiers"].passive_deletes is True
    assert inspect(PriceTier).relationships["prices"].passive_deletes is True
    # RESTRICT in the DB: the ORM must not null category_id first.
    assert inspect(Category).relationships["products"].passive_deletes == "all"


def test_price_history_is_never_orphan_deleted() -> None:
    from sqlalchemy import inspect

    from src.control_stock.models import PriceTier, Product

    assert not inspect(PriceTier).relationships["prices"].cascade.delete_orphan
    assert not inspect(Product).relationships["price_tiers"].cascade.delete_orphan


def test_movement_reservation_must_match_variant() -> None:
    assert "uq_stock_reservations_id_variant_id" in constraint_names(
        "stock_reservations"
    )
    fks = {
        fk.name: (
            [c.name for c in fk.columns],
            [e.target_fullname for e in fk.elements],
        )
        for fk in Base.metadata.tables["inventory_movements"].foreign_key_constraints
    }
    assert fks["fk_inventory_movements_reservation_variant"] == (
        ["reservation_id", "variant_id"],
        ["stock_reservations.id", "stock_reservations.variant_id"],
    )
    assert "fk_inventory_movements_reservation_id_stock_reservations" not in fks
