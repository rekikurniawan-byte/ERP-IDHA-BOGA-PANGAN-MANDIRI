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
    }

    assert migration_columns
    assert migration_columns == model_columns


def test_numeric_migration_nullable_columns_match_models():
    for table_name, column_name in numeric_wave_84.NULLABLE_COLUMNS:
        column = db.metadata.tables[table_name].columns[column_name]
        assert column.nullable is True
