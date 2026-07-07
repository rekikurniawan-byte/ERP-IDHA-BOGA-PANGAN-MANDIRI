"""PostgreSQL runtime invoice schema alignment

Revision ID: 72a0a1b2c3d4
Revises: 71f0a1b2c3d4
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa


revision = "72a0a1b2c3d4"
down_revision = "71f0a1b2c3d4"
branch_labels = None
depends_on = None


def _columns(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _indexes(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def _add_column_if_missing(table_name: str, column: sa.Column) -> None:
    if column.name in _columns(table_name):
        return
    with op.batch_alter_table(table_name) as batch_op:
        batch_op.add_column(column)


def _create_index_if_missing(index_name: str, table_name: str, columns: list[str]) -> None:
    if index_name in _indexes(table_name):
        return
    op.create_index(index_name, table_name, columns, unique=False)


def _drop_index_if_exists(index_name: str, table_name: str) -> None:
    if index_name not in _indexes(table_name):
        return
    op.drop_index(index_name, table_name=table_name)


def upgrade():
    # Columns added for invoice schema alignment. Fresh databases built from Alembic
    # history need these columns so runtime model queries do not fail.
    _add_column_if_missing("invoices", sa.Column("period_start", sa.Date(), nullable=True))
    _add_column_if_missing("invoices", sa.Column("period_end", sa.Date(), nullable=True))
    _add_column_if_missing("invoices", sa.Column("source_type", sa.String(length=50), nullable=True))
    _add_column_if_missing("invoices", sa.Column("source_order_id", sa.Integer(), nullable=True))

    _add_column_if_missing("invoice_items", sa.Column("source_type", sa.String(length=50), nullable=True))
    _add_column_if_missing("invoice_items", sa.Column("source_id", sa.Integer(), nullable=True))

    _create_index_if_missing("ix_invoices_period_start", "invoices", ["period_start"])
    _create_index_if_missing("ix_invoices_period_end", "invoices", ["period_end"])
    _create_index_if_missing("ix_invoices_source_type", "invoices", ["source_type"])
    _create_index_if_missing("ix_invoices_source_order_id", "invoices", ["source_order_id"])
    _create_index_if_missing("ix_invoice_items_source_type", "invoice_items", ["source_type"])
    _create_index_if_missing("ix_invoice_items_source_id", "invoice_items", ["source_id"])


def downgrade():
    _drop_index_if_exists("ix_invoice_items_source_id", "invoice_items")
    _drop_index_if_exists("ix_invoice_items_source_type", "invoice_items")
    _drop_index_if_exists("ix_invoices_source_order_id", "invoices")
    _drop_index_if_exists("ix_invoices_source_type", "invoices")
    _drop_index_if_exists("ix_invoices_period_end", "invoices")
    _drop_index_if_exists("ix_invoices_period_start", "invoices")

    invoice_item_columns = _columns("invoice_items")
    with op.batch_alter_table("invoice_items") as batch_op:
        if "source_id" in invoice_item_columns:
            batch_op.drop_column("source_id")
        if "source_type" in invoice_item_columns:
            batch_op.drop_column("source_type")

    invoice_columns = _columns("invoices")
    with op.batch_alter_table("invoices") as batch_op:
        if "source_order_id" in invoice_columns:
            batch_op.drop_column("source_order_id")
        if "source_type" in invoice_columns:
            batch_op.drop_column("source_type")
        if "period_end" in invoice_columns:
            batch_op.drop_column("period_end")
        if "period_start" in invoice_columns:
            batch_op.drop_column("period_start")
