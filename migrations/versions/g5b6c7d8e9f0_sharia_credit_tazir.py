"""Fase 7: kelonggaran kredit, ta'zir/ta'widh, Dana Sosial.

Revision ID: g5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa


revision = "g5b6c7d8e9f0"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "credit_charges": ("amount",),
    "social_fund_disbursements": ("amount",),
}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("credit_charges", "social_fund_disbursements")

SOCIAL_FUND_ACCOUNT = ("2009", "Dana Sosial (Ta'zir)", "LIABILITY")


def upgrade():
    op.add_column("credit_accounts", sa.Column("grace_until", sa.Date(), nullable=True))
    op.add_column("credit_accounts", sa.Column("grace_reason", sa.Text(), nullable=True))
    op.add_column("credit_accounts", sa.Column("grace_set_by", sa.Integer(), nullable=True))
    op.add_column("credit_accounts", sa.Column("grace_set_at", sa.DateTime(), nullable=True))

    op.create_table(
        "credit_charges",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("credit_account_id", sa.Integer(), sa.ForeignKey("credit_accounts.id"), nullable=False),
        sa.Column("charge_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="PROPOSED"),
        sa.Column("trigger", sa.String(length=30), nullable=False),
        sa.Column("trigger_key", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("customer_contracts.id"), nullable=True),
        sa.Column("evidence_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.UniqueConstraint("credit_account_id", "charge_type", "trigger_key", name="uq_credit_charges_trigger"),
    )
    op.create_index("ix_credit_charges_branch_id", "credit_charges", ["branch_id"])
    op.create_index("ix_credit_charges_credit_account_id", "credit_charges", ["credit_account_id"])
    op.create_index("ix_credit_charges_status", "credit_charges", ["status"])
    op.create_index("ix_credit_charges_invoice_id", "credit_charges", ["invoice_id"])

    op.create_table(
        "social_fund_disbursements",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("disbursed_on", sa.Date(), nullable=False),
        sa.Column("recipient", sa.String(length=200), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("account_type", sa.String(length=10), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id"), nullable=True),
        sa.Column("cash_bank_transaction_id", sa.Integer(), sa.ForeignKey("cash_bank_transactions.id"), nullable=True),
        sa.Column("evidence_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
    )
    op.create_index("ix_social_fund_disbursements_branch_id", "social_fund_disbursements", ["branch_id"])
    op.create_index("ix_social_fund_disbursements_disbursed_on", "social_fund_disbursements", ["disbursed_on"])

    # Akun Dana Sosial: kewajiban, bukan pendapatan. Tidak menimpa akun yang sudah ada.
    code, name, kind = SOCIAL_FUND_ACCOUNT
    op.execute(
        sa.text(
            "INSERT INTO accounts (account_code, account_name, account_type, is_active, created_at, version_id) "
            "SELECT :code, :name, :kind, true, now(), 1 "
            "WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE account_code = :code)"
        ).bindparams(code=code, name=name, kind=kind)
    )


def downgrade():
    op.drop_index("ix_social_fund_disbursements_disbursed_on", table_name="social_fund_disbursements")
    op.drop_index("ix_social_fund_disbursements_branch_id", table_name="social_fund_disbursements")
    op.drop_table("social_fund_disbursements")
    op.drop_index("ix_credit_charges_invoice_id", table_name="credit_charges")
    op.drop_index("ix_credit_charges_status", table_name="credit_charges")
    op.drop_index("ix_credit_charges_credit_account_id", table_name="credit_charges")
    op.drop_index("ix_credit_charges_branch_id", table_name="credit_charges")
    op.drop_table("credit_charges")
    op.drop_column("credit_accounts", "grace_set_at")
    op.drop_column("credit_accounts", "grace_set_by")
    op.drop_column("credit_accounts", "grace_reason")
    op.drop_column("credit_accounts", "grace_until")
