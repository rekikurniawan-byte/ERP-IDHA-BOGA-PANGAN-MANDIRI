"""supplier bill accounts payable

Revision ID: 55f0c1d2e3f4
Revises: 55b0b1c2d3e4
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "55f0c1d2e3f4"
down_revision = "55b0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "supplier_bills",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("bill_number", sa.String(length=50), nullable=False),
        sa.Column("supplier_id", sa.Integer(), nullable=True),
        sa.Column("procurement_id", sa.Integer(), nullable=False),
        sa.Column("bill_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("supplier_name", sa.String(length=150), nullable=False),
        sa.Column("total_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("paid_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("remaining_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="OPEN"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"]),
        sa.ForeignKeyConstraint(["procurement_id"], ["procurements.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bill_number"),
        sa.UniqueConstraint("procurement_id", name="uq_supplier_bills_procurement"),
    )
    op.create_index(op.f("ix_supplier_bills_bill_date"), "supplier_bills", ["bill_date"], unique=False)
    op.create_index(op.f("ix_supplier_bills_due_date"), "supplier_bills", ["due_date"], unique=False)
    op.create_index(op.f("ix_supplier_bills_procurement_id"), "supplier_bills", ["procurement_id"], unique=False)
    op.create_index(op.f("ix_supplier_bills_status"), "supplier_bills", ["status"], unique=False)
    op.create_index(op.f("ix_supplier_bills_supplier_id"), "supplier_bills", ["supplier_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_supplier_bills_supplier_id"), table_name="supplier_bills")
    op.drop_index(op.f("ix_supplier_bills_status"), table_name="supplier_bills")
    op.drop_index(op.f("ix_supplier_bills_procurement_id"), table_name="supplier_bills")
    op.drop_index(op.f("ix_supplier_bills_due_date"), table_name="supplier_bills")
    op.drop_index(op.f("ix_supplier_bills_bill_date"), table_name="supplier_bills")
    op.drop_table("supplier_bills")
