"""Add customer contract rules, contract holidays, and driver user link.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
Create Date: 2026-10-07
"""
from alembic import op
import sqlalchemy as sa


revision = "d2e3f4a5b6c7"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {"customer_contracts": ["tazir_amount"]}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = ("contract_holidays",)


def upgrade():
    with op.batch_alter_table("customer_contracts") as batch:
        batch.add_column(sa.Column("lunch_lock_time", sa.Time(), nullable=False, server_default="10:00:00"))
        batch.add_column(sa.Column("dinner_lock_time", sa.Time(), nullable=False, server_default="15:00:00"))
        batch.add_column(sa.Column("weekly_holidays", sa.String(length=20), nullable=True, server_default=""))
        batch.add_column(sa.Column("default_billing_mode", sa.String(length=20), nullable=False, server_default="VIA_CLIENT"))
        batch.add_column(sa.Column("billing_cycle", sa.String(length=20), nullable=False, server_default="BIWEEKLY"))
        batch.add_column(sa.Column("billing_anchor_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("due_days", sa.Integer(), nullable=False, server_default="7"))
        batch.add_column(sa.Column("dispute_court", sa.String(length=40), nullable=False, server_default="PN_PANGKALAN_BALAI"))
        batch.add_column(sa.Column("tazir_amount", sa.Numeric(precision=18, scale=2), nullable=False, server_default="0"))
        batch.create_check_constraint("ck_customer_contracts_due_days_positive", "due_days >= 1")
        batch.create_check_constraint("ck_customer_contracts_tazir_nonnegative", "tazir_amount >= 0")
        batch.create_check_constraint(
            "ck_customer_contracts_billing_mode",
            "default_billing_mode IN ('VIA_CLIENT', 'DIRECT', 'CASH')",
        )
        batch.create_check_constraint(
            "ck_customer_contracts_billing_cycle",
            "billing_cycle IN ('WEEKLY', 'BIWEEKLY', 'MONTHLY')",
        )
        batch.create_check_constraint(
            "ck_customer_contracts_dispute_court",
            "dispute_court IN ('PN_PANGKALAN_BALAI', 'PN_KAYUAGUNG')",
        )

    op.execute("UPDATE customer_contracts SET billing_anchor_date = start_date WHERE billing_anchor_date IS NULL")
    # Kontrak lama tetap memakai termin yang sudah disepakati ("net 30" -> 30 hari).
    # Bawaan 7 hari hanya untuk kontrak yang termin teksnya tidak berisi angka,
    # sama seperti parse_terms_days() yang dulu dipakai resolve_due_date().
    op.execute(
        r"""
        UPDATE customer_contracts
        SET due_days = CAST(substring(payment_terms from '\d+') AS INTEGER)
        WHERE substring(payment_terms from '\d+') IS NOT NULL
          AND length(substring(payment_terms from '\d+')) <= 3
          AND CAST(substring(payment_terms from '\d+') AS INTEGER) BETWEEN 1 AND 365
        """
    )

    op.create_table(
        "contract_holidays",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("customer_contracts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.UniqueConstraint("contract_id", "holiday_date", name="uq_contract_holidays_contract_date"),
    )
    op.create_index(
        "ix_contract_holidays_contract_id",
        "contract_holidays",
        ["contract_id"],
    )
    op.create_index(
        "ix_contract_holidays_holiday_date",
        "contract_holidays",
        ["holiday_date"],
    )

    with op.batch_alter_table("drivers") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True))
        batch.create_index("ix_drivers_user_id", ["user_id"], unique=True)


def downgrade():
    with op.batch_alter_table("drivers") as batch:
        batch.drop_index("ix_drivers_user_id")
        batch.drop_column("user_id")

    op.drop_index("ix_contract_holidays_holiday_date", table_name="contract_holidays")
    op.drop_index("ix_contract_holidays_contract_id", table_name="contract_holidays")
    op.drop_table("contract_holidays")

    with op.batch_alter_table("customer_contracts") as batch:
        batch.drop_constraint("ck_customer_contracts_dispute_court", type_="check")
        batch.drop_constraint("ck_customer_contracts_billing_cycle", type_="check")
        batch.drop_constraint("ck_customer_contracts_billing_mode", type_="check")
        batch.drop_constraint("ck_customer_contracts_tazir_nonnegative", type_="check")
        batch.drop_constraint("ck_customer_contracts_due_days_positive", type_="check")
        batch.drop_column("tazir_amount")
        batch.drop_column("dispute_court")
        batch.drop_column("due_days")
        batch.drop_column("billing_anchor_date")
        batch.drop_column("billing_cycle")
        batch.drop_column("default_billing_mode")
        batch.drop_column("weekly_holidays")
        batch.drop_column("dinner_lock_time")
        batch.drop_column("lunch_lock_time")
