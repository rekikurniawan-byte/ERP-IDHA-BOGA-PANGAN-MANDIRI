"""Add manual billing recap tables.

Revision ID: 79a0a1b2c3d4
Revises: 78a0a1b2c3d4
Create Date: 2026-07-04
"""
from alembic import op
import sqlalchemy as sa


revision = "79a0a1b2c3d4"
down_revision = "78a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "manual_billing_batches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("batch_number", sa.String(length=50), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("bill_to_type", sa.String(length=30), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=True),
        sa.Column("mandor_id", sa.Integer(), nullable=False),
        sa.Column("client_pic_id", sa.Integer(), nullable=True),
        sa.Column("total_amount", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("invoice_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["client_pic_id"], ["client_pics.id"]),
        sa.ForeignKeyConstraint(["invoice_id"], ["invoices.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("batch_number"),
    )
    op.create_index("ix_manual_billing_batches_branch_id", "manual_billing_batches", ["branch_id"])
    op.create_index("ix_manual_billing_batches_batch_number", "manual_billing_batches", ["batch_number"])
    op.create_index("ix_manual_billing_batches_period_start", "manual_billing_batches", ["period_start"])
    op.create_index("ix_manual_billing_batches_period_end", "manual_billing_batches", ["period_end"])
    op.create_index("ix_manual_billing_batches_bill_to_type", "manual_billing_batches", ["bill_to_type"])
    op.create_index("ix_manual_billing_batches_client_id", "manual_billing_batches", ["client_id"])
    op.create_index("ix_manual_billing_batches_mandor_id", "manual_billing_batches", ["mandor_id"])
    op.create_index("ix_manual_billing_batches_client_pic_id", "manual_billing_batches", ["client_pic_id"])
    op.create_index("ix_manual_billing_batches_status", "manual_billing_batches", ["status"])
    op.create_index("ix_manual_billing_batches_invoice_id", "manual_billing_batches", ["invoice_id"])

    op.create_table(
        "manual_billing_batch_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=40), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("unit_price", sa.Float(), nullable=False),
        sa.Column("subtotal", sa.Float(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=True),
        sa.Column("source_label", sa.String(length=150), nullable=True),
        sa.ForeignKeyConstraint(["batch_id"], ["manual_billing_batches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("source_type", "source_id", name="uq_manual_billing_batch_item_source"),
    )
    op.create_index("ix_manual_billing_batch_items_batch_id", "manual_billing_batch_items", ["batch_id"])
    op.create_index("ix_manual_billing_batch_items_item_type", "manual_billing_batch_items", ["item_type"])
    op.create_index("ix_manual_billing_batch_items_source_type", "manual_billing_batch_items", ["source_type"])
    op.create_index("ix_manual_billing_batch_items_source_id", "manual_billing_batch_items", ["source_id"])
    op.create_index("ix_manual_billing_batch_items_source_date", "manual_billing_batch_items", ["source_date"])


def downgrade():
    op.drop_index("ix_manual_billing_batch_items_source_date", table_name="manual_billing_batch_items")
    op.drop_index("ix_manual_billing_batch_items_source_id", table_name="manual_billing_batch_items")
    op.drop_index("ix_manual_billing_batch_items_source_type", table_name="manual_billing_batch_items")
    op.drop_index("ix_manual_billing_batch_items_item_type", table_name="manual_billing_batch_items")
    op.drop_index("ix_manual_billing_batch_items_batch_id", table_name="manual_billing_batch_items")
    op.drop_table("manual_billing_batch_items")

    op.drop_index("ix_manual_billing_batches_invoice_id", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_status", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_client_pic_id", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_mandor_id", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_client_id", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_bill_to_type", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_period_end", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_period_start", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_batch_number", table_name="manual_billing_batches")
    op.drop_index("ix_manual_billing_batches_branch_id", table_name="manual_billing_batches")
    op.drop_table("manual_billing_batches")
