"""Add portal order drafts.

Revision ID: 92a0a1b2c3d4
Revises: 91a0a1b2c3d4
Create Date: 2026-07-27
"""
from alembic import op
import sqlalchemy as sa


revision = "92a0a1b2c3d4"
down_revision = "91a0a1b2c3d4"
branch_labels = None
depends_on = None
VERSIONED_TABLES = ("portal_order_drafts",)


def _inspector():
    return sa.inspect(op.get_bind())


def _table_exists(table_name):
    return _inspector().has_table(table_name)


def upgrade():
    if _table_exists("portal_order_drafts"):
        return

    op.create_table(
        "portal_order_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.Integer(), nullable=False),
        sa.Column("mandor_id", sa.Integer(), nullable=False),
        sa.Column("delivery_location_id", sa.Integer(), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=20), nullable=False),
        sa.Column("portion_qty", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=40), nullable=False, server_default="PENDING_ADMIN_CONFIRMATION"),
        sa.Column("idempotency_key", sa.String(length=120), nullable=False),
        sa.Column("submitted_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("converted_daily_order_id", sa.Integer(), nullable=True),
        sa.CheckConstraint("meal_type IN ('LUNCH', 'DINNER')", name="ck_portal_order_drafts_meal_type"),
        sa.CheckConstraint(
            "status IN ('PENDING_ADMIN_CONFIRMATION', 'CONFIRMED', 'REJECTED', 'CANCELLED')",
            name="ck_portal_order_drafts_status",
        ),
        sa.CheckConstraint("portion_qty > 0", name="ck_portal_order_drafts_portion_qty_positive"),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["converted_daily_order_id"], ["daily_orders.id"]),
        sa.ForeignKeyConstraint(["delivery_location_id"], ["delivery_locations.id"]),
        sa.ForeignKeyConstraint(["mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_portal_order_drafts_user_idempotency"),
    )
    for column_name in (
        "user_id",
        "branch_id",
        "client_id",
        "mandor_id",
        "delivery_location_id",
        "order_date",
        "meal_type",
        "status",
        "idempotency_key",
        "submitted_at",
        "reviewed_by",
        "converted_daily_order_id",
    ):
        op.create_index(op.f(f"ix_portal_order_drafts_{column_name}"), "portal_order_drafts", [column_name], unique=False)
    op.create_index("ix_portal_order_drafts_user_status", "portal_order_drafts", ["user_id", "status"], unique=False)
    op.create_index("ix_portal_order_drafts_branch_date", "portal_order_drafts", ["branch_id", "order_date"], unique=False)


def downgrade():
    if not _table_exists("portal_order_drafts"):
        return

    op.drop_index("ix_portal_order_drafts_branch_date", table_name="portal_order_drafts")
    op.drop_index("ix_portal_order_drafts_user_status", table_name="portal_order_drafts")
    for column_name in (
        "converted_daily_order_id",
        "reviewed_by",
        "submitted_at",
        "idempotency_key",
        "status",
        "meal_type",
        "order_date",
        "delivery_location_id",
        "mandor_id",
        "client_id",
        "branch_id",
        "user_id",
    ):
        op.drop_index(op.f(f"ix_portal_order_drafts_{column_name}"), table_name="portal_order_drafts")
    op.drop_table("portal_order_drafts")
