"""Field transaction foundation tables.

Revision ID: 75a0a1b2c3d4
Revises: 74a0a1b2c3d4
Create Date: 2026-07-03
"""
from alembic import op
import sqlalchemy as sa


revision = "75a0a1b2c3d4"
down_revision = "74a0a1b2c3d4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "field_counterparties",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("counterparty_type", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("company_name", sa.String(length=150), nullable=True),
        sa.Column("phone", sa.String(length=50), nullable=True),
        sa.Column("site_location", sa.String(length=150), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("linked_client_id", sa.Integer(), nullable=True),
        sa.Column("linked_supplier_id", sa.Integer(), nullable=True),
        sa.Column("linked_mandor_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["linked_client_id"], ["clients.id"]),
        sa.ForeignKeyConstraint(["linked_mandor_id"], ["mandors.id"]),
        sa.ForeignKeyConstraint(["linked_supplier_id"], ["suppliers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_field_counterparties_branch_id", "field_counterparties", ["branch_id"])
    op.create_index("ix_field_counterparties_counterparty_type", "field_counterparties", ["counterparty_type"])
    op.create_index("ix_field_counterparties_site_location", "field_counterparties", ["site_location"])
    op.create_index("ix_field_counterparties_is_active", "field_counterparties", ["is_active"])
    op.create_index("ix_field_counterparties_linked_client_id", "field_counterparties", ["linked_client_id"])
    op.create_index("ix_field_counterparties_linked_supplier_id", "field_counterparties", ["linked_supplier_id"])
    op.create_index("ix_field_counterparties_linked_mandor_id", "field_counterparties", ["linked_mandor_id"])
    op.create_index("ix_field_counterparties_created_by", "field_counterparties", ["created_by"])

    op.create_table(
        "field_transactions",
        sa.Column("branch_id", sa.Integer(), nullable=False),
        sa.Column("transaction_number", sa.String(length=50), nullable=False),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("entry_date", sa.Date(), nullable=False),
        sa.Column("transaction_direction", sa.String(length=10), nullable=False),
        sa.Column("business_event_type", sa.String(length=80), nullable=False),
        sa.Column("field_channel", sa.String(length=30), nullable=False, server_default="MANUAL"),
        sa.Column("counterparty_id", sa.Integer(), nullable=True),
        sa.Column("counterparty_type_snapshot", sa.String(length=40), nullable=True),
        sa.Column("party_snapshot_name", sa.String(length=150), nullable=True),
        sa.Column("party_snapshot_company", sa.String(length=150), nullable=True),
        sa.Column("party_snapshot_phone", sa.String(length=50), nullable=True),
        sa.Column("site_location", sa.String(length=150), nullable=True),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("payment_status", sa.String(length=20), nullable=False, server_default="UNSPECIFIED"),
        sa.Column("payment_method", sa.String(length=30), nullable=True),
        sa.Column("bank_account_id", sa.Integer(), nullable=True),
        sa.Column("review_status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("posting_status", sa.String(length=30), nullable=False, server_default="NOT_POSTED"),
        sa.Column("evidence_status", sa.String(length=20), nullable=False, server_default="NONE"),
        sa.Column("is_manual", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("needs_follow_up", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_context_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("posted_at", sa.DateTime(), nullable=True),
        sa.Column("posted_by", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["bank_account_id"], ["bank_accounts.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["counterparty_id"], ["field_counterparties.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["posted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("transaction_number", name="uq_field_transactions_transaction_number"),
    )
    op.create_index("ix_field_transactions_branch_id", "field_transactions", ["branch_id"])
    op.create_index("ix_field_transactions_transaction_date", "field_transactions", ["transaction_date"])
    op.create_index("ix_field_transactions_entry_date", "field_transactions", ["entry_date"])
    op.create_index("ix_field_transactions_transaction_direction", "field_transactions", ["transaction_direction"])
    op.create_index("ix_field_transactions_business_event_type", "field_transactions", ["business_event_type"])
    op.create_index("ix_field_transactions_field_channel", "field_transactions", ["field_channel"])
    op.create_index("ix_field_transactions_counterparty_id", "field_transactions", ["counterparty_id"])
    op.create_index("ix_field_transactions_counterparty_type_snapshot", "field_transactions", ["counterparty_type_snapshot"])
    op.create_index("ix_field_transactions_site_location", "field_transactions", ["site_location"])
    op.create_index("ix_field_transactions_payment_status", "field_transactions", ["payment_status"])
    op.create_index("ix_field_transactions_payment_method", "field_transactions", ["payment_method"])
    op.create_index("ix_field_transactions_bank_account_id", "field_transactions", ["bank_account_id"])
    op.create_index("ix_field_transactions_review_status", "field_transactions", ["review_status"])
    op.create_index("ix_field_transactions_posting_status", "field_transactions", ["posting_status"])
    op.create_index("ix_field_transactions_evidence_status", "field_transactions", ["evidence_status"])
    op.create_index("ix_field_transactions_is_manual", "field_transactions", ["is_manual"])
    op.create_index("ix_field_transactions_needs_follow_up", "field_transactions", ["needs_follow_up"])
    op.create_index("ix_field_transactions_reviewed_by", "field_transactions", ["reviewed_by"])
    op.create_index("ix_field_transactions_posted_by", "field_transactions", ["posted_by"])
    op.create_index("ix_field_transactions_created_by", "field_transactions", ["created_by"])

    op.create_table(
        "field_transaction_attachments",
        sa.Column("field_transaction_id", sa.Integer(), nullable=False),
        sa.Column("digital_attachment_id", sa.Integer(), nullable=True),
        sa.Column("attachment_role", sa.String(length=40), nullable=False, server_default="EVIDENCE"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="ATTACHED"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["digital_attachment_id"], ["digital_attachments.id"]),
        sa.ForeignKeyConstraint(["field_transaction_id"], ["field_transactions.id"]),
        sa.ForeignKeyConstraint(["verified_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_field_transaction_attachments_field_transaction_id", "field_transaction_attachments", ["field_transaction_id"])
    op.create_index("ix_field_transaction_attachments_digital_attachment_id", "field_transaction_attachments", ["digital_attachment_id"])
    op.create_index("ix_field_transaction_attachments_attachment_role", "field_transaction_attachments", ["attachment_role"])
    op.create_index("ix_field_transaction_attachments_status", "field_transaction_attachments", ["status"])
    op.create_index("ix_field_transaction_attachments_verified_by", "field_transaction_attachments", ["verified_by"])
    op.create_index("ix_field_transaction_attachments_created_by", "field_transaction_attachments", ["created_by"])

    op.create_table(
        "field_transaction_review_logs",
        sa.Column("field_transaction_id", sa.Integer(), nullable=False),
        sa.Column("from_review_status", sa.String(length=30), nullable=True),
        sa.Column("to_review_status", sa.String(length=30), nullable=False),
        sa.Column("action_type", sa.String(length=40), nullable=False, server_default="STATUS_CHANGE"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("acted_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["acted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["field_transaction_id"], ["field_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_field_transaction_review_logs_field_transaction_id", "field_transaction_review_logs", ["field_transaction_id"])
    op.create_index("ix_field_transaction_review_logs_from_review_status", "field_transaction_review_logs", ["from_review_status"])
    op.create_index("ix_field_transaction_review_logs_to_review_status", "field_transaction_review_logs", ["to_review_status"])
    op.create_index("ix_field_transaction_review_logs_action_type", "field_transaction_review_logs", ["action_type"])
    op.create_index("ix_field_transaction_review_logs_acted_by", "field_transaction_review_logs", ["acted_by"])

    op.create_table(
        "field_transaction_links",
        sa.Column("field_transaction_id", sa.Integer(), nullable=False),
        sa.Column("link_role", sa.String(length=40), nullable=False),
        sa.Column("reference_type", sa.String(length=80), nullable=False),
        sa.Column("reference_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["field_transaction_id"], ["field_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "field_transaction_id",
            "link_role",
            "reference_type",
            "reference_id",
            name="uq_field_transaction_link_unique",
        ),
    )
    op.create_index("ix_field_transaction_links_field_transaction_id", "field_transaction_links", ["field_transaction_id"])
    op.create_index("ix_field_transaction_links_link_role", "field_transaction_links", ["link_role"])
    op.create_index("ix_field_transaction_links_reference_type", "field_transaction_links", ["reference_type"])
    op.create_index("ix_field_transaction_links_reference_id", "field_transaction_links", ["reference_id"])
    op.create_index("ix_field_transaction_links_created_by", "field_transaction_links", ["created_by"])

    op.create_table(
        "field_transaction_settlements",
        sa.Column("field_transaction_id", sa.Integer(), nullable=False),
        sa.Column("settlement_number", sa.String(length=50), nullable=False),
        sa.Column("settlement_date", sa.Date(), nullable=False),
        sa.Column("settlement_type", sa.String(length=40), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False, server_default="0"),
        sa.Column("reference_type", sa.String(length=80), nullable=True),
        sa.Column("reference_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["field_transaction_id"], ["field_transactions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("settlement_number", name="uq_field_transaction_settlements_settlement_number"),
    )
    op.create_index("ix_field_transaction_settlements_field_transaction_id", "field_transaction_settlements", ["field_transaction_id"])
    op.create_index("ix_field_transaction_settlements_settlement_number", "field_transaction_settlements", ["settlement_number"])
    op.create_index("ix_field_transaction_settlements_settlement_date", "field_transaction_settlements", ["settlement_date"])
    op.create_index("ix_field_transaction_settlements_settlement_type", "field_transaction_settlements", ["settlement_type"])
    op.create_index("ix_field_transaction_settlements_reference_type", "field_transaction_settlements", ["reference_type"])
    op.create_index("ix_field_transaction_settlements_reference_id", "field_transaction_settlements", ["reference_id"])
    op.create_index("ix_field_transaction_settlements_created_by", "field_transaction_settlements", ["created_by"])


def downgrade():
    op.drop_index("ix_field_transaction_settlements_created_by", table_name="field_transaction_settlements")
    op.drop_index("ix_field_transaction_settlements_reference_id", table_name="field_transaction_settlements")
    op.drop_index("ix_field_transaction_settlements_reference_type", table_name="field_transaction_settlements")
    op.drop_index("ix_field_transaction_settlements_settlement_type", table_name="field_transaction_settlements")
    op.drop_index("ix_field_transaction_settlements_settlement_date", table_name="field_transaction_settlements")
    op.drop_index("ix_field_transaction_settlements_settlement_number", table_name="field_transaction_settlements")
    op.drop_index("ix_field_transaction_settlements_field_transaction_id", table_name="field_transaction_settlements")
    op.drop_table("field_transaction_settlements")

    op.drop_index("ix_field_transaction_links_created_by", table_name="field_transaction_links")
    op.drop_index("ix_field_transaction_links_reference_id", table_name="field_transaction_links")
    op.drop_index("ix_field_transaction_links_reference_type", table_name="field_transaction_links")
    op.drop_index("ix_field_transaction_links_link_role", table_name="field_transaction_links")
    op.drop_index("ix_field_transaction_links_field_transaction_id", table_name="field_transaction_links")
    op.drop_table("field_transaction_links")

    op.drop_index("ix_field_transaction_review_logs_acted_by", table_name="field_transaction_review_logs")
    op.drop_index("ix_field_transaction_review_logs_action_type", table_name="field_transaction_review_logs")
    op.drop_index("ix_field_transaction_review_logs_to_review_status", table_name="field_transaction_review_logs")
    op.drop_index("ix_field_transaction_review_logs_from_review_status", table_name="field_transaction_review_logs")
    op.drop_index("ix_field_transaction_review_logs_field_transaction_id", table_name="field_transaction_review_logs")
    op.drop_table("field_transaction_review_logs")

    op.drop_index("ix_field_transaction_attachments_created_by", table_name="field_transaction_attachments")
    op.drop_index("ix_field_transaction_attachments_verified_by", table_name="field_transaction_attachments")
    op.drop_index("ix_field_transaction_attachments_status", table_name="field_transaction_attachments")
    op.drop_index("ix_field_transaction_attachments_attachment_role", table_name="field_transaction_attachments")
    op.drop_index("ix_field_transaction_attachments_digital_attachment_id", table_name="field_transaction_attachments")
    op.drop_index("ix_field_transaction_attachments_field_transaction_id", table_name="field_transaction_attachments")
    op.drop_table("field_transaction_attachments")

    op.drop_index("ix_field_transactions_created_by", table_name="field_transactions")
    op.drop_index("ix_field_transactions_posted_by", table_name="field_transactions")
    op.drop_index("ix_field_transactions_reviewed_by", table_name="field_transactions")
    op.drop_index("ix_field_transactions_needs_follow_up", table_name="field_transactions")
    op.drop_index("ix_field_transactions_is_manual", table_name="field_transactions")
    op.drop_index("ix_field_transactions_evidence_status", table_name="field_transactions")
    op.drop_index("ix_field_transactions_posting_status", table_name="field_transactions")
    op.drop_index("ix_field_transactions_review_status", table_name="field_transactions")
    op.drop_index("ix_field_transactions_bank_account_id", table_name="field_transactions")
    op.drop_index("ix_field_transactions_payment_method", table_name="field_transactions")
    op.drop_index("ix_field_transactions_payment_status", table_name="field_transactions")
    op.drop_index("ix_field_transactions_site_location", table_name="field_transactions")
    op.drop_index("ix_field_transactions_counterparty_type_snapshot", table_name="field_transactions")
    op.drop_index("ix_field_transactions_counterparty_id", table_name="field_transactions")
    op.drop_index("ix_field_transactions_field_channel", table_name="field_transactions")
    op.drop_index("ix_field_transactions_business_event_type", table_name="field_transactions")
    op.drop_index("ix_field_transactions_transaction_direction", table_name="field_transactions")
    op.drop_index("ix_field_transactions_entry_date", table_name="field_transactions")
    op.drop_index("ix_field_transactions_transaction_date", table_name="field_transactions")
    op.drop_index("ix_field_transactions_branch_id", table_name="field_transactions")
    op.drop_table("field_transactions")

    op.drop_index("ix_field_counterparties_created_by", table_name="field_counterparties")
    op.drop_index("ix_field_counterparties_linked_mandor_id", table_name="field_counterparties")
    op.drop_index("ix_field_counterparties_linked_supplier_id", table_name="field_counterparties")
    op.drop_index("ix_field_counterparties_linked_client_id", table_name="field_counterparties")
    op.drop_index("ix_field_counterparties_is_active", table_name="field_counterparties")
    op.drop_index("ix_field_counterparties_site_location", table_name="field_counterparties")
    op.drop_index("ix_field_counterparties_counterparty_type", table_name="field_counterparties")
    op.drop_index("ix_field_counterparties_branch_id", table_name="field_counterparties")
    op.drop_table("field_counterparties")
