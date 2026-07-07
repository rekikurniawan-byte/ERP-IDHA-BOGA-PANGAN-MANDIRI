"""hpp stock consumption commit

Revision ID: 56j0c1d2e3f4
Revises: 56e0b1c2d3e4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "56j0c1d2e3f4"
down_revision = "56e0b1c2d3e4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_hpp_stock_consumptions",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("daily_order_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("consumption_number", sa.String(length=50), nullable=False),
        sa.Column("consumption_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="COMMITTED"),
        sa.Column("total_item_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_required_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("committed_by", sa.Integer(), nullable=False),
        sa.Column("committed_at", sa.DateTime(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["daily_order_id"], ["daily_orders.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["order_hpp_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumption_number"),
        sa.UniqueConstraint("snapshot_id"),
    )
    op.create_index(op.f("ix_order_hpp_stock_consumptions_branch_id"), "order_hpp_stock_consumptions", ["branch_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_stock_consumptions_consumption_date"), "order_hpp_stock_consumptions", ["consumption_date"], unique=False)
    op.create_index(op.f("ix_order_hpp_stock_consumptions_daily_order_id"), "order_hpp_stock_consumptions", ["daily_order_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_stock_consumptions_snapshot_id"), "order_hpp_stock_consumptions", ["snapshot_id"], unique=False)

    op.create_table(
        "order_hpp_stock_consumption_lines",
        sa.Column("consumption_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("stock_movement_id", sa.Integer(), nullable=True),
        sa.Column("item_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column("item_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("stock_unit_snapshot", sa.String(length=30), nullable=True),
        sa.Column("required_stock_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stock_before_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("stock_after_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("component_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["consumption_id"], ["order_hpp_stock_consumptions.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["stock_movement_id"], ["stock_movements.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("consumption_id", "item_id", name="uq_hpp_stock_consumption_line_item"),
    )
    op.create_index(op.f("ix_order_hpp_stock_consumption_lines_consumption_id"), "order_hpp_stock_consumption_lines", ["consumption_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_stock_consumption_lines_item_id"), "order_hpp_stock_consumption_lines", ["item_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_stock_consumption_lines_stock_movement_id"), "order_hpp_stock_consumption_lines", ["stock_movement_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_order_hpp_stock_consumption_lines_stock_movement_id"), table_name="order_hpp_stock_consumption_lines")
    op.drop_index(op.f("ix_order_hpp_stock_consumption_lines_item_id"), table_name="order_hpp_stock_consumption_lines")
    op.drop_index(op.f("ix_order_hpp_stock_consumption_lines_consumption_id"), table_name="order_hpp_stock_consumption_lines")
    op.drop_table("order_hpp_stock_consumption_lines")
    op.drop_index(op.f("ix_order_hpp_stock_consumptions_snapshot_id"), table_name="order_hpp_stock_consumptions")
    op.drop_index(op.f("ix_order_hpp_stock_consumptions_daily_order_id"), table_name="order_hpp_stock_consumptions")
    op.drop_index(op.f("ix_order_hpp_stock_consumptions_consumption_date"), table_name="order_hpp_stock_consumptions")
    op.drop_index(op.f("ix_order_hpp_stock_consumptions_branch_id"), table_name="order_hpp_stock_consumptions")
    op.drop_table("order_hpp_stock_consumptions")
