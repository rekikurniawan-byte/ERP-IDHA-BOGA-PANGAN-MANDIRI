import importlib

from sqlalchemy import Numeric

import app.models  # noqa: F401
from app.extensions import db


numeric_wave_83 = importlib.import_module(
    "migrations.versions.83a0a1b2c3d4_finance_accounting_numeric_wave"
)
numeric_wave_84 = importlib.import_module(
    "migrations.versions.84a0a1b2c3d4_remaining_numeric_wave"
)
numeric_wave_86 = importlib.import_module(
    "migrations.versions.86a0a1b2c3d4_stock_opening_balance"
)
customer_contracts_93 = importlib.import_module(
    "migrations.versions.93a0a1b2c3d4_customer_contracts"
)
customer_corrections_95 = importlib.import_module(
    "migrations.versions.95a0a1b2c3d4_customer_corrections"
)
credit_control_a0 = importlib.import_module(
    "migrations.versions.a0b1c2d3e4f5_add_credit_control"
)
pricing_c4 = importlib.import_module(
    "migrations.versions.c4d5e6f7a8b9_customer_path_and_portion_prices"
)
delivery_d5 = importlib.import_module(
    "migrations.versions.d5e6f7a8b9c0_delivery_zones_and_fees"
)
opening_c0 = importlib.import_module(
    "migrations.versions.c0d1e2f3a4b5_opening_balance_single_door"
)
gps_d1 = importlib.import_module(
    "migrations.versions.d1e2f3a4b5c6_gps_locations_partnership_requests"
)
claims_a7 = importlib.import_module(
    "migrations.versions.a7b8c9d0e1f2_payment_proof_claims_unique_code"
)
contract_settings_d2 = importlib.import_module(
    "migrations.versions.d2e3f4a5b6c7_contract_settings_and_driver_user"
)


def _migration_columns(module):
    columns = {}
    for table_name, column_names in module.MONEY_COLUMNS.items():
        for column_name in column_names:
            columns[(table_name, column_name)] = (18, 2)
    for table_name, column_names in module.QUANTITY_COLUMNS.items():
        for column_name in column_names:
            columns[(table_name, column_name)] = (18, 4)
    for table_name, column_names in module.RATIO_COLUMNS.items():
        for column_name in column_names:
            columns[(table_name, column_name)] = (8, 4)
    for table_name, column_names in getattr(module, "COORDINATE_COLUMNS", {}).items():
        for column_name in column_names:
            columns[(table_name, column_name)] = (10, 7)
    return columns


def _model_numeric_columns():
    columns = {}
    for table_name, table in db.metadata.tables.items():
        for column in table.columns:
            if isinstance(column.type, Numeric):
                columns[(table_name, column.name)] = (column.type.precision, column.type.scale)
    return columns


def test_numeric_migration_columns_exist_in_models_and_match_scale():
    model_columns = _model_numeric_columns()
    migration_columns = {
        **_migration_columns(numeric_wave_83),
        **_migration_columns(numeric_wave_84),
        **_migration_columns(numeric_wave_86),
        **_migration_columns(customer_contracts_93),
        **_migration_columns(customer_corrections_95),
        **_migration_columns(credit_control_a0),
        **_migration_columns(pricing_c4),
        **_migration_columns(delivery_d5),
        **_migration_columns(opening_c0),
        **_migration_columns(gps_d1),
        **_migration_columns(claims_a7),
        **_migration_columns(contract_settings_d2),
    }

    assert migration_columns
    assert migration_columns == model_columns


def test_numeric_migration_nullable_columns_match_models():
    for table_name, column_name in numeric_wave_84.NULLABLE_COLUMNS:
        column = db.metadata.tables[table_name].columns[column_name]
        assert column.nullable is True
