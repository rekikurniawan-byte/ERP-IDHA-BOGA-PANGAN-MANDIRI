"""Add maker-checker approval request foundation.

Revision ID: 88a0a1b2c3d4
Revises: 87a0a1b2c3d4
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "88a0a1b2c3d4"
down_revision = "87a0a1b2c3d4"
branch_labels = None
depends_on = None


VERSIONED_TABLES = ("approval_requests",)


def upgrade():
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), server_default="1", nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("action_key", sa.String(length=120), nullable=False),
        sa.Column("reference_type", sa.String(length=80), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("requested_by", sa.Integer(), nullable=False),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("requested_reason", sa.Text(), nullable=False),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_approval_requests_action_key"), "approval_requests", ["action_key"], unique=False)
    op.create_index("ix_approval_requests_action_status", "approval_requests", ["action_key", "status"], unique=False)
    op.create_index(op.f("ix_approval_requests_branch_id"), "approval_requests", ["branch_id"], unique=False)
    op.create_index(op.f("ix_approval_requests_reference_id"), "approval_requests", ["reference_id"], unique=False)
    op.create_index("ix_approval_requests_reference", "approval_requests", ["reference_type", "reference_id"], unique=False)
    op.create_index(op.f("ix_approval_requests_reference_type"), "approval_requests", ["reference_type"], unique=False)
    op.create_index(op.f("ix_approval_requests_requested_by"), "approval_requests", ["requested_by"], unique=False)
    op.create_index(op.f("ix_approval_requests_reviewed_by"), "approval_requests", ["reviewed_by"], unique=False)
    op.create_index(op.f("ix_approval_requests_status"), "approval_requests", ["status"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_approval_requests_status"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_reviewed_by"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_requested_by"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_reference_type"), table_name="approval_requests")
    op.drop_index("ix_approval_requests_reference", table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_reference_id"), table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_branch_id"), table_name="approval_requests")
    op.drop_index("ix_approval_requests_action_status", table_name="approval_requests")
    op.drop_index(op.f("ix_approval_requests_action_key"), table_name="approval_requests")
    op.drop_table("approval_requests")
