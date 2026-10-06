"""Portal payment proof claims and draft payment unique code.

Revision ID: a7b8c9d0e1f2
Revises: d1e2f3a4b5c6
Create Date: 2026-10-06
"""
from alembic import op
import sqlalchemy as sa


revision = "a7b8c9d0e1f2"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "portal_payment_proof_claims": ["claimed_amount"],
}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("portal_payment_proof_claims",)


def upgrade():
    with op.batch_alter_table("portal_order_drafts") as batch:
        batch.add_column(sa.Column("payment_unique_code", sa.Integer(), nullable=True))

    op.create_table(
        "portal_payment_proof_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=False),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("claimed_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("sender_name", sa.String(length=120), nullable=False),
        sa.Column("transfer_reference", sa.String(length=80), nullable=True),
    )
    op.create_index(
        "ix_portal_payment_proof_claims_attachment_id",
        "portal_payment_proof_claims",
        ["attachment_id"],
        unique=True,
    )
    op.create_index(
        "ix_portal_payment_proof_claims_branch_id",
        "portal_payment_proof_claims",
        ["branch_id"],
    )
    op.create_index(
        "ix_portal_payment_proof_claims_transfer_reference",
        "portal_payment_proof_claims",
        ["transfer_reference"],
    )


def downgrade():
    op.drop_index("ix_portal_payment_proof_claims_transfer_reference", table_name="portal_payment_proof_claims")
    op.drop_index("ix_portal_payment_proof_claims_branch_id", table_name="portal_payment_proof_claims")
    op.drop_index("ix_portal_payment_proof_claims_attachment_id", table_name="portal_payment_proof_claims")
    op.drop_table("portal_payment_proof_claims")
    with op.batch_alter_table("portal_order_drafts") as batch:
        batch.drop_column("payment_unique_code")
