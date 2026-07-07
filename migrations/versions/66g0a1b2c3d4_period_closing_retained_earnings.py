"""PRODUCTION period closing retained earnings

Revision ID: 66g0a1b2c3d4
Revises: 66f0a1b2c3d4
Create Date: 2026-06-21
"""

from alembic import op
import sqlalchemy as sa


revision = "66g0a1b2c3d4"
down_revision = "66f0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "period_closings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("closing_number", sa.String(length=50), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("closing_date", sa.Date(), nullable=False),
        sa.Column("revenue_total", sa.Float(), nullable=False),
        sa.Column("expense_total", sa.Float(), nullable=False),
        sa.Column("net_income", sa.Float(), nullable=False),
        sa.Column("retained_earnings_account_code", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("journal_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["journal_id"], ["journals.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("closing_number"),
        sa.UniqueConstraint("branch_id", "period_year", "period_month", name="uq_period_closing_branch_period"),
    )
    op.create_index("ix_period_closings_branch_id", "period_closings", ["branch_id"])
    op.create_index("ix_period_closings_closing_number", "period_closings", ["closing_number"])
    op.create_index("ix_period_closings_period_year", "period_closings", ["period_year"])
    op.create_index("ix_period_closings_period_month", "period_closings", ["period_month"])
    op.create_index("ix_period_closings_period_start", "period_closings", ["period_start"])
    op.create_index("ix_period_closings_period_end", "period_closings", ["period_end"])
    op.create_index("ix_period_closings_closing_date", "period_closings", ["closing_date"])
    op.create_index("ix_period_closings_status", "period_closings", ["status"])


def downgrade():
    op.drop_index("ix_period_closings_status", table_name="period_closings")
    op.drop_index("ix_period_closings_closing_date", table_name="period_closings")
    op.drop_index("ix_period_closings_period_end", table_name="period_closings")
    op.drop_index("ix_period_closings_period_start", table_name="period_closings")
    op.drop_index("ix_period_closings_period_month", table_name="period_closings")
    op.drop_index("ix_period_closings_period_year", table_name="period_closings")
    op.drop_index("ix_period_closings_closing_number", table_name="period_closings")
    op.drop_index("ix_period_closings_branch_id", table_name="period_closings")
    op.drop_table("period_closings")
