"""packaging overhead profiles

Revision ID: 56c0a1b2c3d4
Revises: 56b0f1a2b3c4
Create Date: 2026-06-19 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "56c0a1b2c3d4"
down_revision = "56b0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "packaging_profiles",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("profile_code", sa.String(length=50), nullable=False),
        sa.Column("profile_name", sa.String(length=150), nullable=False),
        sa.Column("cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "profile_name", name="uq_packaging_profiles_branch_name"),
        sa.UniqueConstraint("profile_code"),
    )
    op.create_index(op.f("ix_packaging_profiles_branch_id"), "packaging_profiles", ["branch_id"], unique=False)

    op.create_table(
        "overhead_profiles",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("profile_code", sa.String(length=50), nullable=False),
        sa.Column("profile_name", sa.String(length=150), nullable=False),
        sa.Column("gas_cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("electricity_cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("water_cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("labor_cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("spices_cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("other_cost_per_portion", sa.Float(), nullable=False, server_default="0"),
        sa.Column("overhead_percentage", sa.Float(), nullable=False, server_default="0"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "profile_name", name="uq_overhead_profiles_branch_name"),
        sa.UniqueConstraint("profile_code"),
    )
    op.create_index(op.f("ix_overhead_profiles_branch_id"), "overhead_profiles", ["branch_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_overhead_profiles_branch_id"), table_name="overhead_profiles")
    op.drop_table("overhead_profiles")
    op.drop_index(op.f("ix_packaging_profiles_branch_id"), table_name="packaging_profiles")
    op.drop_table("packaging_profiles")
