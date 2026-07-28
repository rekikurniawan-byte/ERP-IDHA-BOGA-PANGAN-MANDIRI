"""Add customer complaints.

Revision ID: 94a0a1b2c3d4
Revises: 93a0a1b2c3d4
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa


revision = "94a0a1b2c3d4"
down_revision = "93a0a1b2c3d4"
branch_labels = None
depends_on = None
VERSIONED_TABLES = ("customer_complaints",)
MONEY_COLUMNS = {}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name):
    return _inspector().has_table(table_name)


def upgrade():
    if _table_exists("customer_complaints"):
        return

    op.create_table(
        "customer_complaints",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("complaint_number", sa.String(length=60), nullable=False),
        sa.Column("category", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("mandor_id", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("delivery_id", sa.Integer(), nullable=True),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("submitted_by", sa.Integer(), nullable=False),
        sa.Column("assigned_to", sa.Integer(), nullable=True),
        sa.Column("resolved_by", sa.Integer(), nullable=True),
        sa.Column("closed_by", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "category IN ('FOOD_SHORTAGE', 'DAMAGED_FOOD', 'WRONG_MENU', 'LATE_DELIVERY', 'PORTION_SHORTAGE', 'OTHER')",
            name="ck_customer_complaints_category",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')",
            name="ck_customer_complaints_status",
        ),
        sa.ForeignKeyConstraint(["assigned_to"], ["users.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["daily_orders.id"]),
        sa.ForeignKeyConstraint(["resolved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("complaint_number"),
    )
    for column_name in (
        "branch_id",
        "complaint_number",
        "category",
        "status",
        "client_id",
        "mandor_id",
        "order_id",
        "delivery_id",
        "invoice_id",
        "submitted_by",
        "assigned_to",
        "resolved_by",
        "closed_by",
    ):
        op.create_index(op.f(f"ix_customer_complaints_{column_name}"), "customer_complaints", [column_name], unique=False)
    op.create_index("ix_customer_complaints_branch_status", "customer_complaints", ["branch_id", "status"], unique=False)
    op.create_index("ix_customer_complaints_client_status", "customer_complaints", ["client_id", "status"], unique=False)
    op.create_index("ix_customer_complaints_reference", "customer_complaints", ["order_id", "delivery_id", "invoice_id"], unique=False)


def downgrade():
    if not _table_exists("customer_complaints"):
        return

    op.drop_index("ix_customer_complaints_reference", table_name="customer_complaints")
    op.drop_index("ix_customer_complaints_client_status", table_name="customer_complaints")
    op.drop_index("ix_customer_complaints_branch_status", table_name="customer_complaints")
    for column_name in (
        "closed_by",
        "resolved_by",
        "assigned_to",
        "submitted_by",
        "invoice_id",
        "delivery_id",
        "order_id",
        "mandor_id",
        "client_id",
        "status",
        "category",
        "complaint_number",
        "branch_id",
    ):
        op.drop_index(op.f(f"ix_customer_complaints_{column_name}"), table_name="customer_complaints")
    op.drop_table("customer_complaints")
