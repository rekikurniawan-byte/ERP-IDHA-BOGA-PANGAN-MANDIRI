"""Add idempotency key registry.

Revision ID: 87a0a1b2c3d4
Revises: 86a0a1b2c3d4
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "87a0a1b2c3d4"
down_revision = "86a0a1b2c3d4"
branch_labels = None
depends_on = None


VERSIONED_TABLES = ("idempotency_keys",)


def upgrade():
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("scope", sa.String(length=120), nullable=False),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("branch_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="STARTED"),
        sa.Column("reference_type", sa.String(length=80), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("response_payload_json", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
    )
    op.create_index(op.f("ix_idempotency_keys_branch_id"), "idempotency_keys", ["branch_id"], unique=False)
    op.create_index(op.f("ix_idempotency_keys_key"), "idempotency_keys", ["key"], unique=False)
    op.create_index(op.f("ix_idempotency_keys_reference_id"), "idempotency_keys", ["reference_id"], unique=False)
    op.create_index(op.f("ix_idempotency_keys_reference_type"), "idempotency_keys", ["reference_type"], unique=False)
    op.create_index(op.f("ix_idempotency_keys_request_hash"), "idempotency_keys", ["request_hash"], unique=False)
    op.create_index(op.f("ix_idempotency_keys_scope"), "idempotency_keys", ["scope"], unique=False)
    op.create_index(op.f("ix_idempotency_keys_status"), "idempotency_keys", ["status"], unique=False)
    op.create_index(op.f("ix_idempotency_keys_user_id"), "idempotency_keys", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_idempotency_keys_user_id"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_status"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_scope"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_request_hash"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_reference_type"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_reference_id"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_key"), table_name="idempotency_keys")
    op.drop_index(op.f("ix_idempotency_keys_branch_id"), table_name="idempotency_keys")
    op.drop_table("idempotency_keys")
