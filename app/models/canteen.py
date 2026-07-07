from app.extensions import db
from app.models.base import BaseModel


class CanteenSale(BaseModel):
    __tablename__ = "canteen_sales"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    sale_date = db.Column(db.Date, nullable=False, index=True)
    sale_type = db.Column(db.String(20), nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0)

    # PRODUCTION — payment method + buyer foundation.
    # sale_type tetap dipertahankan untuk kompatibilitas laporan lama:
    # - CASH = transaksi sudah lunas (cash/QRIS/transfer)
    # - DEBT = transaksi hutang (pekerja internal / buyer eksternal)
    payment_method = db.Column(db.String(30), nullable=False, default="CASH", index=True)
    buyer_type = db.Column(db.String(40), nullable=False, default="GENERAL_BUYER", index=True)
    buyer_name = db.Column(db.String(150), nullable=True)
    buyer_company = db.Column(db.String(150), nullable=True)
    buyer_phone = db.Column(db.String(50), nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True)
    cash_bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    is_external_debt = db.Column(db.Boolean, nullable=False, default=False, index=True)

    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    items = db.relationship("CanteenSaleItem", backref="sale", lazy=True)
    worker_debt = db.relationship("WorkerDebt", backref="sale", lazy=True, uselist=False)
    external_receivable = db.relationship("CanteenExternalReceivable", backref="sale", lazy=True, uselist=False)
    cash_bank_account = db.relationship("BankAccount", foreign_keys=[cash_bank_account_id], lazy=True)


class CanteenSaleItem(BaseModel):
    __tablename__ = "canteen_sale_items"

    sale_id = db.Column(db.Integer, db.ForeignKey("canteen_sales.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    qty = db.Column(db.Integer, nullable=False, default=0)
    price = db.Column(db.Float, nullable=False, default=0)
    subtotal = db.Column(db.Float, nullable=False, default=0)

    item = db.relationship("Item", lazy=True)


class WorkerDebt(BaseModel):
    __tablename__ = "worker_debts"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    worker_id = db.Column(db.Integer, db.ForeignKey("workers.id"), nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey("canteen_sales.id"), nullable=False)
    debt_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="UNPAID")

    worker = db.relationship("Worker", lazy=True)
    payments = db.relationship("DebtPayment", backref="worker_debt", lazy=True)


class DebtPayment(BaseModel):
    __tablename__ = "debt_payments"

    worker_debt_id = db.Column(db.Integer, db.ForeignKey("worker_debts.id"), nullable=False)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    payment_method = db.Column(db.String(30), nullable=False, default="CASH", index=True)
    cash_bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    cash_bank_account = db.relationship("BankAccount", foreign_keys=[cash_bank_account_id], lazy=True)


class CanteenExternalReceivable(BaseModel):
    __tablename__ = "canteen_external_receivables"
    __table_args__ = (
        db.UniqueConstraint("sale_id", name="uq_canteen_external_receivable_sale"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    sale_id = db.Column(db.Integer, db.ForeignKey("canteen_sales.id"), nullable=False)
    buyer_name = db.Column(db.String(150), nullable=False)
    buyer_company = db.Column(db.String(150), nullable=True)
    buyer_phone = db.Column(db.String(50), nullable=True)
    receivable_amount = db.Column(db.Float, nullable=False, default=0)
    paid_amount = db.Column(db.Float, nullable=False, default=0)
    remaining_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, default="UNPAID", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    payments = db.relationship("CanteenExternalReceivablePayment", backref="external_receivable", lazy=True)


class CanteenExternalReceivablePayment(BaseModel):
    __tablename__ = "canteen_external_receivable_payments"

    receivable_id = db.Column(db.Integer, db.ForeignKey("canteen_external_receivables.id"), nullable=False)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    payment_method = db.Column(db.String(30), nullable=False, default="CASH", index=True)
    cash_bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    payment_reference = db.Column(db.String(120), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    cash_bank_account = db.relationship("BankAccount", foreign_keys=[cash_bank_account_id], lazy=True)


class CashDaily(BaseModel):
    __tablename__ = "cash_daily"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    cash_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default="OPEN")
    opening_balance = db.Column(db.Float, nullable=False, default=0)
    cash_sales = db.Column(db.Float, nullable=False, default=0)
    debt_payments = db.Column(db.Float, nullable=False, default=0)
    other_income = db.Column(db.Float, nullable=False, default=0)
    expenses = db.Column(db.Float, nullable=False, default=0)
    closing_balance = db.Column(db.Float, nullable=False, default=0)
    actual_cash = db.Column(db.Float, nullable=False, default=0)
    cash_difference = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "cash_date", name="uq_cash_daily_branch_date"),
    )


class CashExpense(BaseModel):
    __tablename__ = "cash_expenses"

    cash_daily_id = db.Column(db.Integer, db.ForeignKey("cash_daily.id"), nullable=False)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    expense_category = db.Column(db.String(50), nullable=False)
    amount = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)

    cash_daily = db.relationship("CashDaily", lazy=True)
