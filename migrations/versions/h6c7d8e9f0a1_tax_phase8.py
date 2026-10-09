"""Fase 8: potongan pajak pelanggan, setoran pajak, dokumen pajak, akun pajak.

Revision ID: h6c7d8e9f0a1
Revises: g5b6c7d8e9f0
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa


revision = "h6c7d8e9f0a1"
down_revision = "g5b6c7d8e9f0"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "tax_withholdings": ("base_amount", "amount"),
    "tax_payments": ("amount",),
}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {"tax_withholdings": ("rate_percent",)}
VERSIONED_TABLES = ("tax_withholdings", "tax_payments", "tax_documents")

TAX_ACCOUNTS = (
    ("1009", "Pajak Dibayar di Muka (PPh 23/25)", "ASSET"),
    ("2010", "Hutang PBJT", "LIABILITY"),
    ("5014", "Beban PPh Final", "EXPENSE"),
)


def _base_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
    ]


def upgrade():
    op.create_table(
        "tax_withholdings",
        *_base_columns(),
        sa.Column("invoice_id", sa.Integer(), sa.ForeignKey("invoices.id"), nullable=False),
        sa.Column("withholding_type", sa.String(length=20), nullable=False),
        sa.Column("withheld_on", sa.Date(), nullable=False),
        sa.Column("base_amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("rate_percent", sa.Numeric(8, 4), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("certificate_number", sa.String(length=100), nullable=False),
        sa.Column("attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("journal_id", sa.Integer(), sa.ForeignKey("journals.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
    )
    op.create_index("ix_tax_withholdings_branch_id", "tax_withholdings", ["branch_id"])
    op.create_index("ix_tax_withholdings_invoice_id", "tax_withholdings", ["invoice_id"])
    op.create_index("ix_tax_withholdings_withheld_on", "tax_withholdings", ["withheld_on"])

    op.create_table(
        "tax_payments",
        *_base_columns(),
        sa.Column("tax_type", sa.String(length=20), nullable=False),
        sa.Column("period_year", sa.Integer(), nullable=False),
        sa.Column("period_month", sa.Integer(), nullable=False),
        sa.Column("paid_on", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 2), nullable=False),
        sa.Column("reference_number", sa.String(length=100), nullable=False),
        sa.Column("account_type", sa.String(length=10), nullable=False),
        sa.Column("bank_account_id", sa.Integer(), sa.ForeignKey("bank_accounts.id"), nullable=True),
        sa.Column("cash_bank_transaction_id", sa.Integer(), sa.ForeignKey("cash_bank_transactions.id"), nullable=True),
        sa.Column("attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
    )
    op.create_index("ix_tax_payments_branch_id", "tax_payments", ["branch_id"])
    op.create_index("ix_tax_payments_tax_type", "tax_payments", ["tax_type"])
    op.create_index("ix_tax_payments_paid_on", "tax_payments", ["paid_on"])

    op.create_table(
        "tax_documents",
        *_base_columns(),
        sa.Column("doc_type", sa.String(length=40), nullable=False),
        sa.Column("doc_number", sa.String(length=150), nullable=True),
        sa.Column("issued_on", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_tax_documents_branch_id", "tax_documents", ["branch_id"])
    op.create_index("ix_tax_documents_valid_until", "tax_documents", ["valid_until"])

    for code, name, kind in TAX_ACCOUNTS:
        op.execute(
            sa.text(
                "INSERT INTO accounts (account_code, account_name, account_type, is_active, created_at, version_id) "
                "SELECT :code, :name, :kind, true, now(), 1 "
                "WHERE NOT EXISTS (SELECT 1 FROM accounts WHERE account_code = :code)"
            ).bindparams(code=code, name=name, kind=kind)
        )


def downgrade():
    op.drop_index("ix_tax_documents_valid_until", table_name="tax_documents")
    op.drop_index("ix_tax_documents_branch_id", table_name="tax_documents")
    op.drop_table("tax_documents")
    op.drop_index("ix_tax_payments_paid_on", table_name="tax_payments")
    op.drop_index("ix_tax_payments_tax_type", table_name="tax_payments")
    op.drop_index("ix_tax_payments_branch_id", table_name="tax_payments")
    op.drop_table("tax_payments")
    op.drop_index("ix_tax_withholdings_withheld_on", table_name="tax_withholdings")
    op.drop_index("ix_tax_withholdings_invoice_id", table_name="tax_withholdings")
    op.drop_index("ix_tax_withholdings_branch_id", table_name="tax_withholdings")
    op.drop_table("tax_withholdings")
