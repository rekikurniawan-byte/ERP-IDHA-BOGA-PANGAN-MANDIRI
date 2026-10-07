"""Add user profile fields, menu description, and menu schedules.

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa


revision = "c1d2e3f4a5b6"
down_revision = "b1c2d3e4f5a6"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("menu_schedules",)


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("phone", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch.add_column(sa.Column("avatar_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True))

    with op.batch_alter_table("menus") as batch:
        batch.add_column(sa.Column("description", sa.Text(), nullable=True))

    op.create_table(
        "menu_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("menu_date", sa.Date(), nullable=False),
        sa.Column("meal_type", sa.String(length=20), nullable=False),
        sa.Column("menu_id", sa.Integer(), sa.ForeignKey("menus.id"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.UniqueConstraint("branch_id", "menu_date", "meal_type", name="uq_menu_schedule_branch_date_meal"),
    )
    op.create_index(
        "ix_menu_schedules_branch_id",
        "menu_schedules",
        ["branch_id"],
    )
    op.create_index(
        "ix_menu_schedules_menu_date",
        "menu_schedules",
        ["menu_date"],
    )
    op.create_index(
        "ix_menu_schedules_menu_id",
        "menu_schedules",
        ["menu_id"],
    )


def downgrade():
    op.drop_index("ix_menu_schedules_menu_id", table_name="menu_schedules")
    op.drop_index("ix_menu_schedules_menu_date", table_name="menu_schedules")
    op.drop_index("ix_menu_schedules_branch_id", table_name="menu_schedules")
    op.drop_table("menu_schedules")

    with op.batch_alter_table("menus") as batch:
        batch.drop_column("description")

    with op.batch_alter_table("users") as batch:
        batch.drop_column("avatar_attachment_id")
        batch.drop_column("address")
        batch.drop_column("phone")
