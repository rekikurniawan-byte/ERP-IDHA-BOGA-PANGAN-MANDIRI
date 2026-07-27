"""Align clean-install schema with active ORM models.

Revision ID: 90a0a1b2c3d4
Revises: 89a0a1b2c3d4
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = "90a0a1b2c3d4"
down_revision = "89a0a1b2c3d4"
branch_labels = None
depends_on = None


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name):
    return _inspector().has_table(table_name)


def _column_exists(table_name, column_name):
    if not _table_exists(table_name):
        return False
    return column_name in {column["name"] for column in _inspector().get_columns(table_name)}


def _unique_constraint_exists(table_name, constraint_name):
    if not _table_exists(table_name):
        return False
    return constraint_name in {constraint["name"] for constraint in _inspector().get_unique_constraints(table_name)}


def _add_column_if_missing(table_name, column):
    if _table_exists(table_name) and not _column_exists(table_name, column.name):
        op.add_column(table_name, column)


def upgrade():
    _add_column_if_missing("item_requests", sa.Column("request_number", sa.String(length=50), nullable=True))
    if _column_exists("item_requests", "request_number"):
        op.execute("UPDATE item_requests SET request_number = 'REQ-MIG-' || id::text WHERE request_number IS NULL")
        op.alter_column("item_requests", "request_number", nullable=False)
        if not _unique_constraint_exists("item_requests", "uq_item_requests_request_number"):
            op.create_unique_constraint("uq_item_requests_request_number", "item_requests", ["request_number"])

    _add_column_if_missing(
        "item_requests",
        sa.Column("purpose", sa.String(length=100), nullable=False, server_default="Kebutuhan produksi dapur"),
    )
    if _column_exists("item_requests", "purpose"):
        op.alter_column("item_requests", "purpose", server_default=None)

    _add_column_if_missing(
        "item_request_details",
        sa.Column("requested_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "item_request_details",
        sa.Column("approved_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        "item_request_details",
        sa.Column("fulfilled_qty", sa.Numeric(18, 4), nullable=False, server_default="0"),
    )
    for column_name in ("requested_qty", "approved_qty", "fulfilled_qty"):
        if _column_exists("item_request_details", column_name):
            op.alter_column("item_request_details", column_name, server_default=None)

    _add_column_if_missing(
        "procurements",
        sa.Column("purchase_place", sa.String(length=150), nullable=False, server_default="Pembelian sendiri"),
    )
    if _column_exists("procurements", "purchase_place"):
        op.alter_column("procurements", "purchase_place", server_default=None)

    _add_column_if_missing(
        "order_revisions",
        sa.Column("price_per_portion", sa.Numeric(18, 2), nullable=True),
    )

    if not _table_exists("invoice_collection_logs"):
        op.create_table(
            "invoice_collection_logs",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("branch_id", sa.Integer(), nullable=False),
            sa.Column("invoice_id", sa.Integer(), nullable=False),
            sa.Column("follow_up_date", sa.Date(), nullable=False),
            sa.Column("channel", sa.String(length=30), nullable=False),
            sa.Column("contact_person", sa.String(length=150), nullable=True),
            sa.Column("response_note", sa.Text(), nullable=True),
            sa.Column("promise_date", sa.Date(), nullable=True),
            sa.Column("next_action", sa.String(length=100), nullable=True),
            sa.Column("collection_status", sa.String(length=30), nullable=False),
            sa.Column("created_by", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index(op.f("ix_invoice_collection_logs_invoice_id"), "invoice_collection_logs", ["invoice_id"], unique=False)
        op.create_index(op.f("ix_invoice_collection_logs_branch_id"), "invoice_collection_logs", ["branch_id"], unique=False)
        op.create_index(op.f("ix_invoice_collection_logs_follow_up_date"), "invoice_collection_logs", ["follow_up_date"], unique=False)


def downgrade():
    # Non-destructive by design. This migration aligns databases that may already
    # contain these columns/tables through manual or historical patches.
    pass
