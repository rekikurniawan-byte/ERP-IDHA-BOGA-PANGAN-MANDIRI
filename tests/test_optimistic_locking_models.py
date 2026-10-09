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
customer_contract_migration = importlib.import_module(
    "migrations.versions.93a0a1b2c3d4_customer_contracts"
)
customer_complaint_migration = importlib.import_module(
    "migrations.versions.94a0a1b2c3d4_customer_complaints"
)
customer_correction_migration = importlib.import_module(
    "migrations.versions.95a0a1b2c3d4_customer_corrections"
)
credit_control_migration = importlib.import_module(
    "migrations.versions.a0b1c2d3e4f5_add_credit_control"
)
pricing_migration = importlib.import_module(
    "migrations.versions.c4d5e6f7a8b9_customer_path_and_portion_prices"
)
delivery_migration = importlib.import_module(
    "migrations.versions.d5e6f7a8b9c0_delivery_zones_and_fees"
)
opening_balance_migration = importlib.import_module(
    "migrations.versions.c0d1e2f3a4b5_opening_balance_single_door"
)
gps_partnership_migration = importlib.import_module(
    "migrations.versions.d1e2f3a4b5c6_gps_locations_partnership_requests"
)
claims_migration = importlib.import_module(
    "migrations.versions.a7b8c9d0e1f2_payment_proof_claims_unique_code"
)
reset_tokens_migration = importlib.import_module(
    "migrations.versions.b1c2d3e4f5a6_add_password_reset_tokens"
)
user_menu_migration = importlib.import_module(
    "migrations.versions.c1d2e3f4a5b6_user_profile_and_menu_schedule"
)
contract_settings_migration = importlib.import_module(
    "migrations.versions.d2e3f4a5b6c7_contract_settings_and_driver_user"
)
scheduler_migration = importlib.import_module(
    "migrations.versions.e3f4a5b6c7d8_scheduled_job_runs"
)
auto_order_migration = importlib.import_module(
    "migrations.versions.f4a5b6c7d8e9_standing_orders_and_qty_changes"
)
sharia_credit_migration = importlib.import_module(
    "migrations.versions.g5b6c7d8e9f0_sharia_credit_tazir"
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
    migration_tables.update(customer_contract_migration.VERSIONED_TABLES)
    migration_tables.update(customer_complaint_migration.VERSIONED_TABLES)
    migration_tables.update(customer_correction_migration.VERSIONED_TABLES)
    migration_tables.update(credit_control_migration.VERSIONED_TABLES)
    migration_tables.update(pricing_migration.VERSIONED_TABLES)
    migration_tables.update(delivery_migration.VERSIONED_TABLES)
    migration_tables.update(opening_balance_migration.VERSIONED_TABLES)
    migration_tables.update(gps_partnership_migration.VERSIONED_TABLES)
    migration_tables.update(claims_migration.VERSIONED_TABLES)
    migration_tables.update(reset_tokens_migration.VERSIONED_TABLES)
    migration_tables.update(user_menu_migration.VERSIONED_TABLES)
    migration_tables.update(contract_settings_migration.VERSIONED_TABLES)
    migration_tables.update(scheduler_migration.VERSIONED_TABLES)
    migration_tables.update(auto_order_migration.VERSIONED_TABLES)
    migration_tables.update(sharia_credit_migration.VERSIONED_TABLES)

    assert migration_tables == _versioned_model_tables()


def test_representative_models_use_sqlalchemy_version_id_col():
    from app.models.finance import Invoice, Payment
    from app.models.accounting import Journal
    from app.models.logistics import StockMovement
    from app.models.master import Item

    for model in (Invoice, Payment, Journal, StockMovement, Item):
        assert model.__mapper__.version_id_col is model.__table__.c.version_id
