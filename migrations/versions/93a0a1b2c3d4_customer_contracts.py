"""Add customer contracts.

Revision ID: 93a0a1b2c3d4
Revises: 92a0a1b2c3d4
Create Date: 2026-07-28
"""
from alembic import op
import sqlalchemy as sa


revision = "93a0a1b2c3d4"
down_revision = "92a0a1b2c3d4"
branch_labels = None
depends_on = None
VERSIONED_TABLES = ("customer_contracts",)
MONEY_COLUMNS = {"customer_contracts": ("credit_limit",)}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name):
    return _inspector().has_table(table_name)


def upgrade():
    if _table_exists("customer_contracts"):
        return

    op.create_table(
        "customer_contracts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("client_pic_id", sa.Integer(), nullable=True),
        sa.Column("parent_contract_id", sa.Integer(), nullable=True),
        sa.Column("contract_number", sa.String(length=60), nullable=False),
        sa.Column("title", sa.String(length=180), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("payment_terms", sa.String(length=120), nullable=False),
        sa.Column("credit_limit", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'EXPIRED', 'TERMINATED', 'SUPERSEDED')",
            name="ck_customer_contracts_status",
        ),
        sa.CheckConstraint("version_no > 0", name="ck_customer_contracts_version_positive"),
        sa.CheckConstraint("end_date >= start_date", name="ck_customer_contracts_date_range"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["client_pic_id"], ["client_pics.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["parent_contract_id"], ["customer_contracts.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("contract_number"),
    )
    for column_name in (
        "branch_id",
        "client_id",
        "client_pic_id",
        "parent_contract_id",
        "contract_number",
        "start_date",
        "end_date",
        "status",
        "created_by",
        "updated_by",
    ):
        op.create_index(op.f(f"ix_customer_contracts_{column_name}"), "customer_contracts", [column_name], unique=False)
    op.create_index("ix_customer_contracts_client_status", "customer_contracts", ["client_id", "status"], unique=False)
    op.create_index("ix_customer_contracts_branch_end_date", "customer_contracts", ["branch_id", "end_date"], unique=False)


def downgrade():
    if not _table_exists("customer_contracts"):
        return

    op.drop_index("ix_customer_contracts_branch_end_date", table_name="customer_contracts")
    op.drop_index("ix_customer_contracts_client_status", table_name="customer_contracts")
    for column_name in (
        "updated_by",
        "created_by",
        "status",
        "end_date",
        "start_date",
        "contract_number",
        "parent_contract_id",
        "client_pic_id",
        "client_id",
        "branch_id",
    ):
        op.drop_index(op.f(f"ix_customer_contracts_{column_name}"), table_name="customer_contracts")
    op.drop_table("customer_contracts")
