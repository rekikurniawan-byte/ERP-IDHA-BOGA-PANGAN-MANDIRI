from app.extensions import db
from app.models.base import BaseModel


class Account(BaseModel):
    __tablename__ = "accounts"

    account_code = db.Column(db.String(50), nullable=False, unique=True)
    account_name = db.Column(db.String(150), nullable=False)
    account_type = db.Column(db.String(50), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    journal_details = db.relationship("JournalDetail", backref="account", lazy=True)


class Journal(BaseModel):
    __tablename__ = "journals"

    journal_number = db.Column(db.String(50), nullable=False, unique=True)
    journal_date = db.Column(db.Date, nullable=False, index=True)
    reference_type = db.Column(db.String(50), nullable=False)
    reference_id = db.Column(db.Integer, nullable=False)
    description = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, nullable=False)

    details = db.relationship("JournalDetail", backref="journal", lazy=True)

    # ANTI_DOUBLE_1B_JOURNAL_REFERENCE_UNIQUE_MODEL
    __table_args__ = (
        db.UniqueConstraint("reference_type", "reference_id", name="uq_journals_reference_type_id"),
    )


class JournalDetail(BaseModel):
    __tablename__ = "journal_details"

    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey("accounts.id"), nullable=False)
    debit = db.Column(db.Float, nullable=False, default=0)
    credit = db.Column(db.Float, nullable=False, default=0)


class FixedAsset(BaseModel):
    __tablename__ = "fixed_assets"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    asset_code = db.Column(db.String(50), nullable=False, unique=True)
    asset_name = db.Column(db.String(150), nullable=False)
    asset_category = db.Column(db.String(50), nullable=False)
    purchase_date = db.Column(db.Date, nullable=False)
    purchase_value = db.Column(db.Float, nullable=False, default=0)
    useful_life_years = db.Column(db.Integer, nullable=False, default=0)
    residual_value = db.Column(db.Float, nullable=False, default=0)
    accumulated_depreciation = db.Column(db.Float, nullable=False, default=0)
    book_value = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE")
    notes = db.Column(db.Text, nullable=True)

class FixedAssetPurchase(BaseModel):
    __tablename__ = "fixed_asset_purchases"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    purchase_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    purchase_date = db.Column(db.Date, nullable=False, index=True)
    fixed_asset_id = db.Column(db.Integer, db.ForeignKey("fixed_assets.id"), nullable=False, index=True)
    asset_account_code = db.Column(db.String(50), nullable=False)
    payment_method = db.Column(db.String(30), nullable=False)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    vendor_name = db.Column(db.String(150), nullable=True)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    fixed_asset = db.relationship(
        "FixedAsset",
        foreign_keys=[fixed_asset_id],
        backref=db.backref("purchase_transactions", lazy=True),
        lazy=True,
    )
    bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[bank_account_id],
        lazy=True,
    )
    cash_bank_transaction = db.relationship(
        "CashBankTransaction",
        foreign_keys=[cash_bank_transaction_id],
        lazy=True,
    )
    journal = db.relationship(
        "Journal",
        foreign_keys=[journal_id],
        lazy=True,
    )

    __table_args__ = (
        db.UniqueConstraint("fixed_asset_id", name="uq_fixed_asset_purchases_asset_once"),
    )

# === PRODUCTION_OPTIONAL_FIXED_ASSET_DEPRECIATION_ENGINE_MODELS ===
class FixedAssetDepreciationConfig(BaseModel):
    __tablename__ = "fixed_asset_depreciation_configs"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    fixed_asset_id = db.Column(db.Integer, db.ForeignKey("fixed_assets.id"), nullable=False, unique=True, index=True)
    depreciation_start_date = db.Column(db.Date, nullable=False, index=True)
    useful_life_months = db.Column(db.Integer, nullable=False)
    residual_value = db.Column(db.Float, nullable=False, default=0)
    depreciation_method = db.Column(db.String(30), nullable=False, default="STRAIGHT_LINE")
    accumulated_account_code = db.Column(db.String(50), nullable=False)
    expense_account_code = db.Column(db.String(50), nullable=False, default="5012")
    status = db.Column(db.String(30), nullable=False, default="CONFIGURED", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    fixed_asset = db.relationship(
        "FixedAsset",
        foreign_keys=[fixed_asset_id],
        backref=db.backref("depreciation_config", uselist=False, lazy=True),
        lazy=True,
    )


class FixedAssetDepreciation(BaseModel):
    __tablename__ = "fixed_asset_depreciations"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    depreciation_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    fixed_asset_id = db.Column(db.Integer, db.ForeignKey("fixed_assets.id"), nullable=False, index=True)
    period_year = db.Column(db.Integer, nullable=False, index=True)
    period_month = db.Column(db.Integer, nullable=False, index=True)
    depreciation_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    accumulated_depreciation_after = db.Column(db.Float, nullable=False, default=0)
    book_value_after = db.Column(db.Float, nullable=False, default=0)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="POSTED", index=True)
    created_by = db.Column(db.Integer, nullable=False)

    fixed_asset = db.relationship(
        "FixedAsset",
        foreign_keys=[fixed_asset_id],
        backref=db.backref("depreciation_entries", lazy=True),
        lazy=True,
    )
    journal = db.relationship(
        "Journal",
        foreign_keys=[journal_id],
        lazy=True,
    )

    __table_args__ = (
        db.UniqueConstraint("fixed_asset_id", "period_year", "period_month", name="uq_fixed_asset_depreciation_asset_period"),
    )



# === PRODUCTION_ASSET_VEHICLE_INSTALLMENT_FOUNDATION ===
class AssetFinancingContract(BaseModel):
    __tablename__ = "asset_financing_contracts"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    contract_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    contract_date = db.Column(db.Date, nullable=False, index=True)
    fixed_asset_id = db.Column(db.Integer, db.ForeignKey("fixed_assets.id"), nullable=False, index=True)
    asset_account_code = db.Column(db.String(50), nullable=False)
    liability_account_code = db.Column(db.String(50), nullable=False, default="2001")
    interest_expense_account_code = db.Column(db.String(50), nullable=False, default="5008")
    admin_expense_account_code = db.Column(db.String(50), nullable=False, default="5008")
    vendor_name = db.Column(db.String(150), nullable=True)
    financing_provider = db.Column(db.String(150), nullable=True)
    principal_amount = db.Column(db.Float, nullable=False, default=0)
    total_interest_amount = db.Column(db.Float, nullable=False, default=0)
    total_admin_amount = db.Column(db.Float, nullable=False, default=0)
    total_contract_amount = db.Column(db.Float, nullable=False, default=0)
    installment_count = db.Column(db.Integer, nullable=False, default=1)
    installment_frequency = db.Column(db.String(30), nullable=False, default="MONTHLY")
    first_due_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", index=True)
    acquisition_journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    fixed_asset = db.relationship(
        "FixedAsset",
        foreign_keys=[fixed_asset_id],
        backref=db.backref("financing_contracts", lazy=True),
        lazy=True,
    )
    acquisition_journal = db.relationship(
        "Journal",
        foreign_keys=[acquisition_journal_id],
        lazy=True,
    )
    schedules = db.relationship(
        "AssetInstallmentSchedule",
        backref="contract",
        lazy=True,
        cascade="all, delete-orphan",
        order_by="AssetInstallmentSchedule.installment_no",
    )
    payments = db.relationship(
        "AssetInstallmentPayment",
        backref="contract",
        lazy=True
    )


class AssetInstallmentSchedule(BaseModel):
    __tablename__ = "asset_installment_schedules"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("asset_financing_contracts.id"), nullable=False, index=True)
    installment_no = db.Column(db.Integer, nullable=False)
    due_date = db.Column(db.Date, nullable=False, index=True)
    principal_amount = db.Column(db.Float, nullable=False, default=0)
    interest_amount = db.Column(db.Float, nullable=False, default=0)
    admin_amount = db.Column(db.Float, nullable=False, default=0)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    paid_amount = db.Column(db.Float, nullable=False, default=0)
    remaining_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="UNPAID", index=True)

    payments = db.relationship(
        "AssetInstallmentPayment",
        backref="schedule",
        lazy=True
    )

    __table_args__ = (
        db.UniqueConstraint("contract_id", "installment_no", name="uq_asset_installment_contract_no"),
    )


class AssetInstallmentPayment(BaseModel):
    __tablename__ = "asset_installment_payments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    payment_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("asset_financing_contracts.id"), nullable=False, index=True)
    schedule_id = db.Column(db.Integer, db.ForeignKey("asset_installment_schedules.id"), nullable=False, index=True)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    principal_paid = db.Column(db.Float, nullable=False, default=0)
    interest_paid = db.Column(db.Float, nullable=False, default=0)
    admin_paid = db.Column(db.Float, nullable=False, default=0)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[bank_account_id],
        lazy=True,
    )
    cash_bank_transaction = db.relationship(
        "CashBankTransaction",
        foreign_keys=[cash_bank_transaction_id],
        lazy=True,
    )
    journal = db.relationship(
        "Journal",
        foreign_keys=[journal_id],
        lazy=True,
    )



# === PRODUCTION_PERIOD_CLOSING_RETAINED_EARNINGS ===
class PeriodClosing(BaseModel):
    """Period closing event that moves net income/loss to retained earnings (3002).

    This table is event-based and idempotent per branch/month:
    no row means no period closing has happened.
    """
    __tablename__ = "period_closings"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    closing_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    period_year = db.Column(db.Integer, nullable=False, index=True)
    period_month = db.Column(db.Integer, nullable=False, index=True)
    period_start = db.Column(db.Date, nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False, index=True)
    closing_date = db.Column(db.Date, nullable=False, index=True)
    revenue_total = db.Column(db.Float, nullable=False, default=0)
    expense_total = db.Column(db.Float, nullable=False, default=0)
    net_income = db.Column(db.Float, nullable=False, default=0)
    retained_earnings_account_code = db.Column(db.String(50), nullable=False, default="3002")
    status = db.Column(db.String(30), nullable=False, default="POSTED", index=True)
    notes = db.Column(db.Text, nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    journal = db.relationship("Journal", foreign_keys=[journal_id], lazy=True)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "period_year", "period_month", name="uq_period_closing_branch_period"),
    )
