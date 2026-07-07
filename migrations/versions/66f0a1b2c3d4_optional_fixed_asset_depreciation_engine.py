"""PRODUCTION optional fixed asset depreciation engine

Revision ID: 66f0a1b2c3d4
Revises: 66e0a1b2c3d4
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa


revision = "66f0a1b2c3d4"
down_revision = "66e0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "fixed_asset_depreciation_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("fixed_asset_id", sa.Integer(), nullable=False),
        sa.Column("depreciation_start_date", sa.Date(), nullable=False),
        sa.Column("useful_life_months", sa.Integer(), nullable=False),
        sa.Column("residual_value", sa.Float(), nullable=False),
        sa.Column("depreciation_method", sa.String(length=30), nullable=False),
        sa.Column("accumulated_account_code", sa.String(length=50), nullable=False),
        sa.Column("expense_account_code", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["fixed_asset_id"], ["fixed_assets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("fixed_asset_id"),
    )
    op.create_index("ix_fixed_asset_depreciation_configs_branch_id", "fixed_asset_depreciation_configs", ["branch_id"])
    op.create_index("ix_fixed_asset_depreciation_configs_fixed_asset_id", "fixed_asset_depreciation_configs", ["fixed_asset_id"])
    op.create_index("ix_fixed_asset_depreciation_configs_depreciation_start_date", "fixed_asset_depreciation_configs", ["depreciation_start_date"])
    op.create_index("ix_fixed_asset_depreciation_configs_status", "fixed_asset_depreciation_configs", ["status"])

    op.create_table(
        "fixed_asset_depreciations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("depreciation_number", sa.String(length=50), nullable=False),
        sa.Column("fixed_asset_id", sa.Integer(), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("depreciation_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("accumulated_depreciation_after", sa.Float(), nullable=False),
        sa.Column("book_value_after", sa.Float(), nullable=False),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["fixed_asset_id"], ["fixed_assets.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("depreciation_number"),
        sa.UniqueConstraint("fixed_asset_id", "period_year", "period_month", name="uq_fixed_asset_depreciation_asset_period"),
    )
    op.create_index("ix_fixed_asset_depreciations_branch_id", "fixed_asset_depreciations", ["branch_id"])
    op.create_index("ix_fixed_asset_depreciations_depreciation_number", "fixed_asset_depreciations", ["depreciation_number"])
    op.create_index("ix_fixed_asset_depreciations_fixed_asset_id", "fixed_asset_depreciations", ["fixed_asset_id"])
    op.create_index("ix_fixed_asset_depreciations_period_year", "fixed_asset_depreciations", ["period_year"])
    op.create_index("ix_fixed_asset_depreciations_period_month", "fixed_asset_depreciations", ["period_month"])
    op.create_index("ix_fixed_asset_depreciations_depreciation_date", "fixed_asset_depreciations", ["depreciation_date"])
    op.create_index("ix_fixed_asset_depreciations_status", "fixed_asset_depreciations", ["status"])


def downgrade():
    op.drop_index("ix_fixed_asset_depreciations_status", table_name="fixed_asset_depreciations")
    op.drop_index("ix_fixed_asset_depreciations_depreciation_date", table_name="fixed_asset_depreciations")
    op.drop_index("ix_fixed_asset_depreciations_period_month", table_name="fixed_asset_depreciations")
    op.drop_index("ix_fixed_asset_depreciations_period_year", table_name="fixed_asset_depreciations")
    op.drop_index("ix_fixed_asset_depreciations_fixed_asset_id", table_name="fixed_asset_depreciations")
    op.drop_index("ix_fixed_asset_depreciations_depreciation_number", table_name="fixed_asset_depreciations")
    op.drop_index("ix_fixed_asset_depreciations_branch_id", table_name="fixed_asset_depreciations")
    op.drop_table("fixed_asset_depreciations")

    op.drop_index("ix_fixed_asset_depreciation_configs_status", table_name="fixed_asset_depreciation_configs")
    op.drop_index("ix_fixed_asset_depreciation_configs_depreciation_start_date", table_name="fixed_asset_depreciation_configs")
    op.drop_index("ix_fixed_asset_depreciation_configs_fixed_asset_id", table_name="fixed_asset_depreciation_configs")
    op.drop_index("ix_fixed_asset_depreciation_configs_branch_id", table_name="fixed_asset_depreciation_configs")
    op.drop_table("fixed_asset_depreciation_configs")
