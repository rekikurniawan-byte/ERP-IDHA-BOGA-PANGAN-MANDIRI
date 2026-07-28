"""Add customer corrections.

Revision ID: 95a0a1b2c3d4
Revises: 94a0a1b2c3d4
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa


revision = "95a0a1b2c3d4"
down_revision = "94a0a1b2c3d4"
branch_labels = None
depends_on = None
VERSIONED_TABLES = ("customer_corrections",)
MONEY_COLUMNS = {"customer_corrections": ("correction_amount",)}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name):
    return _inspector().has_table(table_name)


def upgrade():
    if _table_exists("customer_corrections"):
        return

    op.create_table(
        "customer_corrections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("correction_number", sa.String(length=60), nullable=False),
        sa.Column("correction_type", sa.String(length=30), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("complaint_id", sa.Integer(), nullable=True),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("delivery_id", sa.Integer(), nullable=True),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("mandor_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("proposed_action", sa.Text(), nullable=False),
        sa.Column("correction_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("stock_effect", sa.String(length=30), nullable=False, server_default="NONE"),
        sa.Column("financial_effect", sa.String(length=30), nullable=False, server_default="NONE"),
        sa.Column("approval_request_id", sa.Integer(), nullable=True),
        sa.Column("submitted_by", sa.Integer(), nullable=False),
        sa.Column("approved_by", sa.Integer(), nullable=True),
        sa.Column("closed_by", sa.Integer(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "correction_type IN ('RETURN', 'CORRECTION', 'COMPENSATION')",
            name="ck_customer_corrections_type",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CLOSED', 'CANCELLED')",
            name="ck_customer_corrections_status",
        ),
        sa.CheckConstraint(
            "stock_effect IN ('NONE', 'PENDING', 'POSTED', 'NOT_APPLICABLE')",
            name="ck_customer_corrections_stock_effect",
        ),
        sa.CheckConstraint(
            "financial_effect IN ('NONE', 'PENDING', 'POSTED', 'NOT_APPLICABLE')",
            name="ck_customer_corrections_financial_effect",
        ),
        sa.CheckConstraint("correction_amount >= 0", name="ck_customer_corrections_amount_nonnegative"),
        sa.ForeignKeyConstraint(["approval_request_id"], ["approval_requests.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["complaint_id"], ["customer_complaints.id"]),
        sa.ForeignKeyConstraint(["delivery_id"], ["deliveries.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.ForeignKeyConstraint(["mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["daily_orders.id"]),
        sa.ForeignKeyConstraint(["submitted_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("correction_number"),
    )
    for column_name in (
        "branch_id",
        "correction_number",
        "correction_type",
        "status",
        "complaint_id",
        "order_id",
        "delivery_id",
        "invoice_id",
        "client_id",
        "mandor_id",
        "stock_effect",
        "financial_effect",
        "approval_request_id",
        "submitted_by",
        "approved_by",
        "closed_by",
    ):
        op.create_index(op.f(f"ix_customer_corrections_{column_name}"), "customer_corrections", [column_name], unique=False)
    op.create_index("ix_customer_corrections_branch_status", "customer_corrections", ["branch_id", "status"], unique=False)
    op.create_index("ix_customer_corrections_complaint_status", "customer_corrections", ["complaint_id", "status"], unique=False)
    op.create_index("ix_customer_corrections_reference", "customer_corrections", ["order_id", "delivery_id", "invoice_id"], unique=False)


def downgrade():
    if not _table_exists("customer_corrections"):
        return

    op.drop_index("ix_customer_corrections_reference", table_name="customer_corrections")
    op.drop_index("ix_customer_corrections_complaint_status", table_name="customer_corrections")
    op.drop_index("ix_customer_corrections_branch_status", table_name="customer_corrections")
    for column_name in (
        "closed_by",
        "approved_by",
        "submitted_by",
        "approval_request_id",
        "financial_effect",
        "stock_effect",
        "mandor_id",
        "client_id",
        "invoice_id",
        "delivery_id",
        "order_id",
        "complaint_id",
        "status",
        "correction_type",
        "correction_number",
        "branch_id",
    ):
        op.drop_index(op.f(f"ix_customer_corrections_{column_name}"), table_name="customer_corrections")
    op.drop_table("customer_corrections")
