import importlib

import app.models  # noqa: F401
from app.extensions import db


locking_migration = importlib.import_module(
    "migrations.versions.85a0a1b2c3d4_base_model_optimistic_locking"
)
stock_opening_migration = importlib.import_module(
    "migrations.versions.86a0a1b2c3d4_stock_opening_balance"
)
idempotency_migration = importlib.import_module(
    "migrations.versions.87a0a1b2c3d4_idempotency_keys"
)
approval_migration = importlib.import_module(
    "migrations.versions.88a0a1b2c3d4_approval_requests"
)
portal_mapping_migration = importlib.import_module(
    "migrations.versions.91a0a1b2c3d4_portal_user_mappings"
)
portal_order_draft_migration = importlib.import_module(
    "migrations.versions.92a0a1b2c3d4_portal_order_drafts"
)


def _versioned_model_tables():
    return {
        table_name
        for table_name, table in db.metadata.tables.items()
        if "version_id" in table.columns
    }


def test_all_base_model_tables_have_version_id_mapper():
    for table_name, table in db.metadata.tables.items():
        if table_name == "invoice_collection_logs":
            assert "version_id" not in table.columns
            continue
        assert "version_id" in table.columns, table_name
        assert table.columns["version_id"].nullable is False


def test_optimistic_locking_migration_covers_all_versioned_tables():
    migration_tables = set(locking_migration.VERSIONED_TABLES)
    migration_tables.update(stock_opening_migration.VERSIONED_TABLES)
    migration_tables.update(idempotency_migration.VERSIONED_TABLES)
    migration_tables.update(approval_migration.VERSIONED_TABLES)
    migration_tables.update(portal_mapping_migration.VERSIONED_TABLES)
    migration_tables.update(portal_order_draft_migration.VERSIONED_TABLES)

    assert migration_tables == _versioned_model_tables()


def test_representative_models_use_sqlalchemy_version_id_col():
    from app.models.finance import Invoice, Payment
    from app.models.accounting import Journal
    from app.models.logistics import StockMovement
    from app.models.master import Item

    for model in (Invoice, Payment, Journal, StockMovement, Item):
        assert model.__mapper__.version_id_col is model.__table__.c.version_id
