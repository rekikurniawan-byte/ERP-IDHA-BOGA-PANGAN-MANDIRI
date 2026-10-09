"""Fase 9: Surat kontrak otomatis, snapshot dokumen, dan adendum.

Revision ID: i7d8e9f0a1b2
Revises: h6c7d8e9f0a1
Create Date: 2026-10-09
"""
from alembic import op
import sqlalchemy as sa


revision = "i7d8e9f0a1b2"
down_revision = "h6c7d8e9f0a1"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("contract_documents",)


def _base_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
    ]


def upgrade():
    op.create_table(
        "contract_documents",
        *_base_columns(),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("customer_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_number", sa.String(length=80), nullable=False, unique=True),
        sa.Column("document_type", sa.String(length=30), nullable=False, server_default="KONTRAK"),
        sa.Column("version_no", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("html_snapshot", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="MENUNGGU_TTD"),
        sa.Column("signing_method", sa.String(length=30), nullable=True),
        sa.Column("scan_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("signed_at", sa.DateTime(), nullable=True),
        sa.Column("signed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("signed_by_name", sa.String(length=120), nullable=True),
        sa.Column("portal_signed_at", sa.DateTime(), nullable=True),
        sa.Column("portal_signed_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("otp_code_hash", sa.String(length=128), nullable=True),
        sa.Column("otp_expires_at", sa.DateTime(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint(
            "document_type IN ('KONTRAK', 'ADENDUM')",
            name="ck_contract_documents_type",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'MENUNGGU_TTD', 'DITANDATANGANI')",
            name="ck_contract_documents_status",
        ),
        sa.CheckConstraint(
            "signing_method IS NULL OR signing_method IN ('WET_STAMP', 'PORTAL_EMAIL_OTP')",
            name="ck_contract_documents_signing_method",
        ),
    )
    op.create_index("ix_contract_documents_branch_id", "contract_documents", ["branch_id"])
    op.create_index("ix_contract_documents_contract_id", "contract_documents", ["contract_id"])
    op.create_index("ix_contract_documents_document_number", "contract_documents", ["document_number"])
    op.create_index("ix_contract_documents_status", "contract_documents", ["status"])
    op.create_index("ix_contract_documents_contract_status", "contract_documents", ["contract_id", "status"])


def downgrade():
    op.drop_index("ix_contract_documents_contract_status", table_name="contract_documents")
    op.drop_index("ix_contract_documents_status", table_name="contract_documents")
    op.drop_index("ix_contract_documents_document_number", table_name="contract_documents")
    op.drop_index("ix_contract_documents_contract_id", table_name="contract_documents")
    op.drop_index("ix_contract_documents_branch_id", table_name="contract_documents")
    op.drop_table("contract_documents")
