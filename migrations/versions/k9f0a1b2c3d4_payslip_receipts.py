"""Slip gaji (link WhatsApp) dan kwitansi tanda terima gaji.

Revision ID: k9f0a1b2c3d4
Revises: j8e9f0a1b2c3
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "k9f0a1b2c3d4"
down_revision = "j8e9f0a1b2c3"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {"payroll_receipts": ("amount",)}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("payroll_receipts",)


def upgrade():
    with op.batch_alter_table("payroll_details") as batch:
        batch.add_column(sa.Column("slip_token", sa.String(length=64), nullable=True))
        batch.create_unique_constraint("uq_payroll_details_slip_token", ["slip_token"])

    op.create_table(
        "payroll_receipts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("payroll_id", sa.Integer(), sa.ForeignKey("payrolls.id"), nullable=False),
        sa.Column("payroll_detail_id", sa.Integer(), sa.ForeignKey("payroll_details.id"), nullable=False, unique=True),
        sa.Column("receipt_number", sa.String(length=60), nullable=False, unique=True),
        sa.Column("method", sa.String(length=20), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("received_by_name", sa.String(length=150), nullable=False),
        sa.Column("signature_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("scan_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=False),
        sa.Column("handed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("handed_by_name", sa.String(length=150), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("method IN ('DIGITAL', 'MANUAL')", name="ck_payroll_receipts_method"),
        sa.CheckConstraint("amount >= 0", name="ck_payroll_receipts_amount"),
    )
    op.create_index("ix_payroll_receipts_payroll_id", "payroll_receipts", ["payroll_id"])


def downgrade():
    op.drop_index("ix_payroll_receipts_payroll_id", table_name="payroll_receipts")
    op.drop_table("payroll_receipts")
    with op.batch_alter_table("payroll_details") as batch:
        batch.drop_constraint("uq_payroll_details_slip_token", type_="unique")
        batch.drop_column("slip_token")
