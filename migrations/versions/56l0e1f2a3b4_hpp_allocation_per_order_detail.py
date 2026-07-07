"""hpp allocation per order detail mandor

Revision ID: 56l0e1f2a3b4
Revises: 56k0d1e2f3a4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "56l0e1f2a3b4"
down_revision = "56k0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_hpp_snapshot_allocations",
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_line_id", sa.Integer(), nullable=False),
        sa.Column("daily_order_detail_id", sa.Integer(), nullable=False),
        sa.Column("mandor_id", sa.Integer(), nullable=False),
        sa.Column("delivery_location_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="ORDER_DETAIL"),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(length=30), nullable=False),
        sa.Column("allocation_method", sa.String(length=50), nullable=False, server_default="PORTION_RATIO"),
        sa.Column("allocation_ratio", sa.Float(), nullable=False, server_default="0"),
        sa.Column("mandor_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("delivery_location_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("portion_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("selling_price_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("revenue_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("food_cost_allocated_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("packaging_cost_allocated_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overhead_cost_allocated_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hpp_allocated_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hpp_per_portion_snapshot", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_margin_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_margin_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["daily_order_detail_id"], ["daily_order_details.id"]),
        sa.ForeignKeyConstraint(["delivery_location_id"], ["delivery_locations.id"]),
        sa.ForeignKeyConstraint(["mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["order_hpp_snapshots.id"]),
        sa.ForeignKeyConstraint(["snapshot_line_id"], ["order_hpp_snapshot_lines.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_line_id", "daily_order_detail_id", "meal_type", name="uq_hpp_snapshot_allocation_line_detail_meal"),
    )
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_snapshot_id"), "order_hpp_snapshot_allocations", ["snapshot_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_snapshot_line_id"), "order_hpp_snapshot_allocations", ["snapshot_line_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_daily_order_detail_id"), "order_hpp_snapshot_allocations", ["daily_order_detail_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_mandor_id"), "order_hpp_snapshot_allocations", ["mandor_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_delivery_location_id"), "order_hpp_snapshot_allocations", ["delivery_location_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_source_type"), "order_hpp_snapshot_allocations", ["source_type"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_source_id"), "order_hpp_snapshot_allocations", ["source_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshot_allocations_meal_type"), "order_hpp_snapshot_allocations", ["meal_type"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_meal_type"), table_name="order_hpp_snapshot_allocations")
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_source_id"), table_name="order_hpp_snapshot_allocations")
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_source_type"), table_name="order_hpp_snapshot_allocations")
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_delivery_location_id"), table_name="order_hpp_snapshot_allocations")
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_mandor_id"), table_name="order_hpp_snapshot_allocations")
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_daily_order_detail_id"), table_name="order_hpp_snapshot_allocations")
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_snapshot_line_id"), table_name="order_hpp_snapshot_allocations")
    op.drop_index(op.f("ix_order_hpp_snapshot_allocations_snapshot_id"), table_name="order_hpp_snapshot_allocations")
    op.drop_table("order_hpp_snapshot_allocations")
