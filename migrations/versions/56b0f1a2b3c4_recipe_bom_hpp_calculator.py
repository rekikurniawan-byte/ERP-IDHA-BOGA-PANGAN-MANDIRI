"""recipe bom hpp calculator

Revision ID: 56b0f1a2b3c4
Revises: 56a0e1f2a3b4
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "56b0f1a2b3c4"
down_revision = "56a0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "menus",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("menu_code", sa.String(length=50), nullable=False),
        sa.Column("menu_name", sa.String(length=150), nullable=False),
        sa.Column("menu_type", sa.String(length=50), nullable=False, server_default="CATERING"),
        sa.Column("default_selling_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "menu_name", name="uq_menus_branch_name"),
        sa.UniqueConstraint("menu_code"),
    )
    op.create_index(op.f("ix_menus_branch_id"), "menus", ["branch_id"], unique=False)

    op.create_table(
        "recipe_headers",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("menu_id", sa.Integer(), nullable=False),
        sa.Column("recipe_name", sa.String(length=150), nullable=False),
        sa.Column("base_portion", sa.Float(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["menu_id"], ["menus.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("menu_id"),
    )
    op.create_index(op.f("ix_recipe_headers_branch_id"), "recipe_headers", ["branch_id"], unique=False)
    op.create_index(op.f("ix_recipe_headers_menu_id"), "recipe_headers", ["menu_id"], unique=False)

    op.create_table(
        "recipe_items",
        sa.Column("recipe_id", sa.Integer(), nullable=False),
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("qty_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["recipe_id"], ["recipe_headers.id"]),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("recipe_id", "item_id", "unit", name="uq_recipe_items_recipe_item_unit"),
    )
    op.create_index(op.f("ix_recipe_items_recipe_id"), "recipe_items", ["recipe_id"], unique=False)
    op.create_index(op.f("ix_recipe_items_item_id"), "recipe_items", ["item_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_recipe_items_item_id"), table_name="recipe_items")
    op.drop_index(op.f("ix_recipe_items_recipe_id"), table_name="recipe_items")
    op.drop_table("recipe_items")
    op.drop_index(op.f("ix_recipe_headers_menu_id"), table_name="recipe_headers")
    op.drop_index(op.f("ix_recipe_headers_branch_id"), table_name="recipe_headers")
    op.drop_table("recipe_headers")
    op.drop_index(op.f("ix_menus_branch_id"), table_name="menus")
    op.drop_table("menus")
