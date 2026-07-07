"""item cost profile unit conversion

Revision ID: 56a0e1f2a3b4
Revises: 55g0d1e2f3a4
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "56a0e1f2a3b4"
down_revision = "55g0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "unit_conversions",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("unit_from", sa.String(length=30), nullable=False),
        sa.Column("unit_to", sa.String(length=30), nullable=False),
        sa.Column("multiplier", sa.Float(), nullable=False, server_default="1"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "unit_from", "unit_to", name="uq_unit_conversions_branch_units"),
    )
    op.create_index(op.f("ix_unit_conversions_branch_id"), "unit_conversions", ["branch_id"], unique=False)

    op.create_table(
        "item_cost_profiles",
        sa.Column("item_id", sa.Integer(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("purchase_unit", sa.String(length=30), nullable=False),
        sa.Column("purchase_qty", sa.Float(), nullable=False, server_default="1"),
        sa.Column("base_unit", sa.String(length=30), nullable=False),
        sa.Column("conversion_factor", sa.Float(), nullable=False, server_default="1"),
        sa.Column("yield_percentage", sa.Float(), nullable=False, server_default="100"),
        sa.Column("waste_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("standard_purchase_price", sa.Float(), nullable=False, server_default="0"),
        sa.Column("effective_cost_per_base_unit", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_source", sa.String(length=30), nullable=False, server_default="STANDARD"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["items.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("item_id"),
    )
    op.create_index(op.f("ix_item_cost_profiles_item_id"), "item_cost_profiles", ["item_id"], unique=False)
    op.create_index(op.f("ix_item_cost_profiles_branch_id"), "item_cost_profiles", ["branch_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_item_cost_profiles_branch_id"), table_name="item_cost_profiles")
    op.drop_index(op.f("ix_item_cost_profiles_item_id"), table_name="item_cost_profiles")
    op.drop_table("item_cost_profiles")
    op.drop_index(op.f("ix_unit_conversions_branch_id"), table_name="unit_conversions")
    op.drop_table("unit_conversions")
