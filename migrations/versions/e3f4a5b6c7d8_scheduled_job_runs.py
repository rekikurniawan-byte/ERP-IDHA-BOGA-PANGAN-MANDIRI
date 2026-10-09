"""Add scheduled_job_runs table for scheduler engine.

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-10-08
"""
from alembic import op
import sqlalchemy as sa


revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("scheduled_job_runs",)


def upgrade():
    op.create_table(
        "scheduled_job_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("job_key", sa.String(length=80), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=True),
        sa.Column("period_key", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="RUNNING"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.UniqueConstraint("job_key", "branch_id", "period_key", name="uq_scheduled_job_runs_job_branch_period"),
    )
    op.create_index(
        "ix_scheduled_job_runs_job_key",
        "scheduled_job_runs",
        ["job_key"],
    )
    op.create_index(
        "ix_scheduled_job_runs_branch_id",
        "scheduled_job_runs",
        ["branch_id"],
    )
    op.create_index(
        "ix_scheduled_job_runs_period_key",
        "scheduled_job_runs",
        ["period_key"],
    )
    op.create_index(
        "ix_scheduled_job_runs_status",
        "scheduled_job_runs",
        ["status"],
    )
    op.create_index(
        "ix_scheduled_job_runs_started_at",
        "scheduled_job_runs",
        ["started_at"],
    )
    op.create_index(
        "uq_scheduled_job_runs_null_branch",
        "scheduled_job_runs",
        ["job_key", "period_key"],
        unique=True,
        postgresql_where=sa.text("branch_id IS NULL"),
    )


def downgrade():
    op.drop_index("uq_scheduled_job_runs_null_branch", table_name="scheduled_job_runs")
    op.drop_index("ix_scheduled_job_runs_started_at", table_name="scheduled_job_runs")
    op.drop_index("ix_scheduled_job_runs_status", table_name="scheduled_job_runs")
    op.drop_index("ix_scheduled_job_runs_period_key", table_name="scheduled_job_runs")
    op.drop_index("ix_scheduled_job_runs_branch_id", table_name="scheduled_job_runs")
    op.drop_index("ix_scheduled_job_runs_job_key", table_name="scheduled_job_runs")
    op.drop_table("scheduled_job_runs")
