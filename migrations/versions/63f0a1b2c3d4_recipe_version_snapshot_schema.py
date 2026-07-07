"""recipe version snapshot schema

Revision ID: 63f0a1b2c3d4
Revises: 63b0a1b2c3d4
Create Date: 2026-06-20 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa


revision = "63f0a1b2c3d4"
down_revision = "63b0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "recipe_versions",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("menu_id", sa.Integer(), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("version_label", sa.String(length=50), nullable=False, server_default="v1"),
        sa.Column("version_note", sa.Text(), nullable=True),
        sa.Column("recipe_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("menu_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column("menu_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("base_portion", sa.Float(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="FINAL"),
        sa.Column("finalized_at", sa.DateTime(), nullable=True),
        sa.Column("finalized_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe_headers.id"]),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"]),
        sa.ForeignKeyConstraint(["finalized_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "recipe_id", "version_number", name="uq_recipe_versions_branch_recipe_number"),
    )
    op.create_index(op.f("ix_recipe_versions_branch_id"), "recipe_versions", ["branch_id"], unique=False)
    op.create_index(op.f("ix_recipe_versions_recipe_id"), "recipe_versions", ["recipe_id"], unique=False)
    op.create_index(op.f("ix_recipe_versions_menu_id"), "recipe_versions", ["menu_id"], unique=False)

    op.create_table(
        "recipe_version_items",
        sa.Column("recipe_version_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("item_code_snapshot", sa.String(length=50), nullable=True),
        sa.Column("item_name_snapshot", sa.String(length=150), nullable=False),
        sa.Column("item_category_snapshot", sa.String(length=50), nullable=True),
        sa.Column("qty_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["recipe_version_id"], ["recipe_versions.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_recipe_version_items_recipe_version_id"), "recipe_version_items", ["recipe_version_id"], unique=False)
    op.create_index(op.f("ix_recipe_version_items_item_id"), "recipe_version_items", ["item_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_recipe_version_items_item_id"), table_name="recipe_version_items")
    op.drop_index(op.f("ix_recipe_version_items_recipe_version_id"), table_name="recipe_version_items")
    op.drop_table("recipe_version_items")
    op.drop_index(op.f("ix_recipe_versions_menu_id"), table_name="recipe_versions")
    op.drop_index(op.f("ix_recipe_versions_recipe_id"), table_name="recipe_versions")
    op.drop_index(op.f("ix_recipe_versions_branch_id"), table_name="recipe_versions")
    op.drop_table("recipe_versions")
