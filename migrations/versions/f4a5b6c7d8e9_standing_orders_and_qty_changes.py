"""Add standing_order_states and order_qty_changes tables for Fase 5.

Revision ID: f4a5b6c7d8e9
Revises: e3f4a5b6c7d8
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa


revision = "f4a5b6c7d8e9"
down_revision = "e3f4a5b6c7d8"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("standing_order_states", "order_qty_changes")


def upgrade():
    op.create_table(
        "standing_order_states",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("mandor_id", sa.Integer(), sa.ForeignKey("mandors.id"), nullable=False),
        sa.Column("delivery_location_id", sa.Integer(), sa.ForeignKey("delivery_locations.id"), nullable=False),
        sa.Column("meal_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="ACTIVE"),
        sa.Column("resume_date", sa.Date(), nullable=True),
        sa.Column("last_nonzero_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.UniqueConstraint(
            "branch_id",
            "mandor_id",
            "delivery_location_id",
            "meal_type",
            name="uq_standing_order_states_scope",
        ),
    )
    op.create_index(
        "ix_standing_order_states_branch_id",
        "standing_order_states",
        ["branch_id"],
    )
    op.create_index(
        "ix_standing_order_states_mandor_id",
        "standing_order_states",
        ["mandor_id"],
    )
    op.create_index(
        "ix_standing_order_states_delivery_location_id",
        "standing_order_states",
        ["delivery_location_id"],
    )

    op.create_table(
        "order_qty_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("daily_order_detail_id", sa.Integer(), sa.ForeignKey("daily_order_details.id"), nullable=False),
        sa.Column("meal_type", sa.String(length=20), nullable=False),
        sa.Column("old_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_qty", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reason_code", sa.String(length=50), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="AUTO"),
        sa.Column("changed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_order_qty_changes_daily_order_detail_id",
        "order_qty_changes",
        ["daily_order_detail_id"],
    )
    op.create_index(
        "ix_order_qty_changes_branch_id",
        "order_qty_changes",
        ["branch_id"],
    )
    op.create_index(
        "ix_order_qty_changes_changed_at",
        "order_qty_changes",
        ["changed_at"],
    )
    op.create_index(
        "ix_order_qty_changes_source",
        "order_qty_changes",
        ["source"],
    )


def downgrade():
    op.drop_index("ix_order_qty_changes_source", table_name="order_qty_changes")
    op.drop_index("ix_order_qty_changes_changed_at", table_name="order_qty_changes")
    op.drop_index("ix_order_qty_changes_branch_id", table_name="order_qty_changes")
    op.drop_index("ix_order_qty_changes_daily_order_detail_id", table_name="order_qty_changes")
    op.drop_table("order_qty_changes")

    op.drop_index("ix_standing_order_states_delivery_location_id", table_name="standing_order_states")
    op.drop_index("ix_standing_order_states_mandor_id", table_name="standing_order_states")
    op.drop_index("ix_standing_order_states_branch_id", table_name="standing_order_states")
    op.drop_table("standing_order_states")
