"""order hpp snapshot manual

Revision ID: 56e0b1c2d3e4
Revises: 56c0a1b2c3d4
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa


revision = "56e0b1c2d3e4"
down_revision = "56c0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "order_hpp_snapshots",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("daily_order_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_number", sa.String(length=50), nullable=False),
        sa.Column("snapshot_date", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="LOCKED"),
        sa.Column("total_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("food_cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("packaging_cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overhead_cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hpp_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hpp_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("revenue_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_margin_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_margin_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("target_margin_percentage", sa.Float(), nullable=False, server_default="30"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["daily_order_id"], ["daily_orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_number"),
    )
    op.create_index(op.f("ix_order_hpp_snapshots_branch_id"), "order_hpp_snapshots", ["branch_id"], unique=False)
    op.create_index(op.f("ix_order_hpp_snapshots_daily_order_id"), "order_hpp_snapshots", ["daily_order_id"], unique=False)

    op.create_table(
        "order_hpp_snapshot_lines",
        sa.Column("snapshot_id", sa.Integer(), nullable=False),
        sa.Column("meal_type", sa.String(length=30), nullable=False),
        sa.Column("menu_id", sa.Integer(), nullable=True),
        sa.Column("menu_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column("menu_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("recipe_id", sa.Integer(), nullable=True),
        sa.Column("recipe_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("packaging_profile_id", sa.Integer(), nullable=True),
        sa.Column("packaging_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("overhead_profile_id", sa.Integer(), nullable=True),
        sa.Column("overhead_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("portion_qty", sa.Float(), nullable=False, server_default="0"),
        sa.Column("selling_price_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("food_cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("packaging_cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overhead_cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hpp_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("hpp_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("revenue_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_margin_amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("gross_margin_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("calculation_status", sa.String(length=30), nullable=False, server_default="COMPLETE"),
        sa.Column("warning_text", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"]),
        sa.ForeignKeyConstraint(["overhead_profile_id"], ["overhead_profiles.id"]),
        sa.ForeignKeyConstraint(["packaging_profile_id"], ["packaging_profiles.id"]),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe_headers.id"]),
        sa.ForeignKeyConstraint(["snapshot_id"], ["order_hpp_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_hpp_snapshot_lines_snapshot_id"), "order_hpp_snapshot_lines", ["snapshot_id"], unique=False)

    op.create_table(
        "order_hpp_snapshot_components",
        sa.Column("snapshot_line_id", sa.Integer(), nullable=False),
        sa.Column("component_type", sa.String(length=30), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("item_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column("item_name_snapshot", sa.String(length=150), nullable=True),
        sa.Column("qty_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("recipe_unit", sa.String(length=30), nullable=True),
        sa.Column("base_unit", sa.String(length=30), nullable=True),
        sa.Column("conversion_multiplier", sa.Float(), nullable=True),
        sa.Column("base_qty_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("base_qty_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_per_base_unit_snapshot", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("source_profile_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["snapshot_line_id"], ["order_hpp_snapshot_lines.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_order_hpp_snapshot_components_snapshot_line_id"), "order_hpp_snapshot_components", ["snapshot_line_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_order_hpp_snapshot_components_snapshot_line_id"), table_name="order_hpp_snapshot_components")
    op.drop_table("order_hpp_snapshot_components")
    op.drop_index(op.f("ix_order_hpp_snapshot_lines_snapshot_id"), table_name="order_hpp_snapshot_lines")
    op.drop_table("order_hpp_snapshot_lines")
    op.drop_index(op.f("ix_order_hpp_snapshots_daily_order_id"), table_name="order_hpp_snapshots")
    op.drop_index(op.f("ix_order_hpp_snapshots_branch_id"), table_name="order_hpp_snapshots")
    op.drop_table("order_hpp_snapshots")
