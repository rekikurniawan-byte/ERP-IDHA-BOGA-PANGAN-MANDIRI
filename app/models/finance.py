from app.extensions import db
from app.models.base import BaseModel



class Invoice(BaseModel):
    __tablename__ = "invoices"
    __table_args__ = (
        db.UniqueConstraint(
            "source_type", "source_order_id", "mandor_id",
            name="uq_invoices_source_order_mandor",
        ),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    invoice_number = db.Column(db.String(50), nullable=False, unique=True)
    invoice_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)

    # Periode tagihan invoice
    period_start = db.Column(db.Date, nullable=True, index=True)
    period_end = db.Column(db.Date, nullable=True, index=True)

    bill_to_type = db.Column(db.String(30), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=True)
    client_pic_id = db.Column(db.Integer, db.ForeignKey("client_pics.id"), nullable=True, index=True)

    # PRODUCTION official invoice snapshots. These keep printed invoices stable even
    # when master client/PIC or company payment settings are updated later.
    client_name_snapshot = db.Column(db.String(150), nullable=True)
    client_code_snapshot = db.Column(db.String(50), nullable=True)
    client_pic_name_snapshot = db.Column(db.String(150), nullable=True)
    client_pic_position_snapshot = db.Column(db.String(100), nullable=True)
    client_pic_phone_snapshot = db.Column(db.String(50), nullable=True)
    client_pic_email_snapshot = db.Column(db.String(150), nullable=True)
    company_bank_name_snapshot = db.Column(db.String(100), nullable=True)
    company_bank_account_number_snapshot = db.Column(db.String(100), nullable=True)
    company_bank_account_name_snapshot = db.Column(db.String(150), nullable=True)

    expected_payment_percent = db.Column(db.Numeric(8, 4), nullable=False, default=100)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    paid_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    remaining_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="DRAFT", index=True)
    notes = db.Column(db.Text, nullable=True)

    # Source invoice untuk cegah invoice dobel
    source_type = db.Column(db.String(50), nullable=True, index=True)
    source_order_id = db.Column(db.Integer, nullable=True, index=True)

    # Cara data masuk ke sistem: REALTIME atau MANUAL_BACKFILL.
    # Dipisahkan dari source_type agar invoice tahu jalur input bisnisnya.
    input_source = db.Column(db.String(30), nullable=False, default="REALTIME", server_default="REALTIME", index=True)

    created_by = db.Column(db.Integer, nullable=False)

    client = db.relationship("Client", foreign_keys=[client_id], lazy=True)
    mandor = db.relationship("Mandor", foreign_keys=[mandor_id], lazy=True)
    client_pic = db.relationship("ClientPic", foreign_keys=[client_pic_id], lazy=True)
    items = db.relationship("InvoiceItem", backref="invoice", lazy=True)
    payments = db.relationship("Payment", backref="invoice", lazy=True)


class InvoiceItem(BaseModel):
    __tablename__ = "invoice_items"

    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    item_type = db.Column(db.String(30), nullable=False)
    description = db.Column(db.Text, nullable=False)
    qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    unit_price = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    # Sumber item invoice untuk mencegah dobel tagih
    source_type = db.Column(db.String(50), nullable=True, index=True)
    source_id = db.Column(db.Integer, nullable=True, index=True)
    input_source = db.Column(db.String(30), nullable=False, default="REALTIME", server_default="REALTIME", index=True)


class ManualBillingBatch(BaseModel):
    __tablename__ = "manual_billing_batches"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    batch_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    period_start = db.Column(db.Date, nullable=False, index=True)
    period_end = db.Column(db.Date, nullable=False, index=True)
    bill_to_type = db.Column(db.String(30), nullable=False, default="CLIENT", index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True, index=True)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=True, index=True)
    client_pic_id = db.Column(db.Integer, db.ForeignKey("client_pics.id"), nullable=True, index=True)
    bill_to_name_snapshot = db.Column(db.String(150), nullable=True, index=True)
    bill_to_phone_snapshot = db.Column(db.String(50), nullable=True)
    bill_to_address_snapshot = db.Column(db.Text, nullable=True)
    bill_to_notes = db.Column(db.Text, nullable=True)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="DRAFT", index=True)
    input_source = db.Column(db.String(30), nullable=False, default="REALTIME", server_default="REALTIME", index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True, index=True)
    locked_at = db.Column(db.DateTime, nullable=True, index=True)
    locked_by = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    client = db.relationship("Client", foreign_keys=[client_id], lazy=True)
    mandor = db.relationship("Mandor", foreign_keys=[mandor_id], lazy=True)
    client_pic = db.relationship("ClientPic", foreign_keys=[client_pic_id], lazy=True)
    invoice = db.relationship("Invoice", foreign_keys=[invoice_id], lazy=True)
    items = db.relationship("ManualBillingBatchItem", backref="batch", lazy=True)


class ManualBillingBatchItem(BaseModel):
    __tablename__ = "manual_billing_batch_items"
    __table_args__ = (
        db.UniqueConstraint(
            "source_type",
            "source_id",
            name="uq_manual_billing_batch_item_source",
        ),
    )

    batch_id = db.Column(db.Integer, db.ForeignKey("manual_billing_batches.id"), nullable=False, index=True)
    item_type = db.Column(db.String(40), nullable=False, index=True)
    description = db.Column(db.Text, nullable=False)
    qty = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    unit_price = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    subtotal = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    source_type = db.Column(db.String(50), nullable=False, index=True)
    source_id = db.Column(db.Integer, nullable=False, index=True)
    source_date = db.Column(db.Date, nullable=True, index=True)
    input_source = db.Column(db.String(30), nullable=False, default="REALTIME", server_default="REALTIME", index=True)
    source_label = db.Column(db.String(150), nullable=True)


class Payment(BaseModel):
    __tablename__ = "payments"

    payment_number = db.Column(db.String(50), nullable=False, unique=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    payment_method = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    received_by = db.Column(db.Integer, nullable=False)

    bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[bank_account_id],
        lazy=True
    )


class BankAccount(BaseModel):
    __tablename__ = "bank_accounts"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    account_name = db.Column(db.String(150), nullable=False)
    bank_name = db.Column(db.String(100), nullable=False)
    account_number = db.Column(db.String(100), nullable=False, unique=True)
    coa_account_code = db.Column(db.String(50), nullable=True, index=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class CashBankTransaction(BaseModel):
    __tablename__ = "cash_bank_transactions"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    transaction_type = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    description = db.Column(db.Text, nullable=False)
    reference_type = db.Column(db.String(50), nullable=True)
    reference_id = db.Column(db.Integer, nullable=True)
    transfer_group_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transfers.id"), nullable=True, index=True)
    is_reconciled = db.Column(db.Boolean, nullable=False, default=False, index=True)
    reconciled_at = db.Column(db.DateTime, nullable=True)
    reconciled_by = db.Column(db.Integer, nullable=True)
    reconciliation_note = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[bank_account_id],
        lazy=True
    )


class CashBankOpeningBalance(BaseModel):
    __tablename__ = "cash_bank_opening_balances"
    __table_args__ = (
        db.UniqueConstraint("branch_id", "account_key", name="uq_cash_bank_opening_balance_account"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    account_key = db.Column(db.String(80), nullable=False, index=True)
    opening_date = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    ledger_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[bank_account_id],
        lazy=True
    )
    ledger_transaction = db.relationship(
        "CashBankTransaction",
        foreign_keys=[ledger_transaction_id],
        lazy=True
    )


class CashBankTransfer(BaseModel):
    __tablename__ = "cash_bank_transfers"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    transfer_number = db.Column(db.String(50), nullable=False, unique=True)
    transfer_date = db.Column(db.Date, nullable=False, index=True)
    from_account_type = db.Column(db.String(30), nullable=False)
    from_bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    to_account_type = db.Column(db.String(30), nullable=False)
    to_bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    from_bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[from_bank_account_id],
        lazy=True
    )
    to_bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[to_bank_account_id],
        lazy=True
    )
    ledger_transactions = db.relationship(
        "CashBankTransaction",
        foreign_keys="CashBankTransaction.transfer_group_id",
        lazy=True
    )


class CashBankAdjustment(BaseModel):
    __tablename__ = "cash_bank_adjustments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    adjustment_number = db.Column(db.String(50), nullable=False, unique=True)
    adjustment_date = db.Column(db.Date, nullable=False, index=True)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    account_key = db.Column(db.String(80), nullable=False, index=True)
    adjustment_type = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    reason = db.Column(db.String(150), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    ledger_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[bank_account_id],
        lazy=True
    )
    ledger_transaction = db.relationship(
        "CashBankTransaction",
        foreign_keys=[ledger_transaction_id],
        lazy=True
    )


class SupplierBill(BaseModel):
    __tablename__ = "supplier_bills"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    bill_number = db.Column(db.String(50), nullable=False, unique=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True, index=True)
    procurement_id = db.Column(db.Integer, db.ForeignKey("procurements.id"), nullable=False, unique=True, index=True)
    bill_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    supplier_name = db.Column(db.String(150), nullable=False)
    total_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    paid_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    remaining_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="OPEN", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    supplier = db.relationship(
        "Supplier",
        foreign_keys=[supplier_id],
        lazy=True
    )
    procurement = db.relationship(
        "Procurement",
        foreign_keys=[procurement_id],
        backref=db.backref("supplier_bill", uselist=False, lazy=True),
        lazy=True
    )


class SupplierPayment(BaseModel):
    __tablename__ = "supplier_payments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    payment_number = db.Column(db.String(50), nullable=False, unique=True)
    supplier_bill_id = db.Column(db.Integer, db.ForeignKey("supplier_bills.id"), nullable=False, index=True)
    payment_date = db.Column(db.Date, nullable=False, index=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    payment_method = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    paid_by = db.Column(db.Integer, nullable=False)

    supplier_bill = db.relationship(
        "SupplierBill",
        foreign_keys=[supplier_bill_id],
        backref=db.backref("payments", lazy=True),
        lazy=True
    )
    bank_account = db.relationship(
        "BankAccount",
        foreign_keys=[bank_account_id],
        lazy=True
    )


# === PATCH_COLLECTION_LOG_STEP12B1A ===
class InvoiceCollectionLog(db.Model):
    __tablename__ = "invoice_collection_logs"

    id = db.Column(db.Integer, primary_key=True)

    branch_id = db.Column(db.Integer, nullable=False)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False)

    follow_up_date = db.Column(db.Date, nullable=False)
    channel = db.Column(db.String(30), nullable=False)  # WHATSAPP / EMAIL / PHONE / VISIT / OTHER

    contact_person = db.Column(db.String(150), nullable=True)
    response_note = db.Column(db.Text, nullable=True)

    promise_date = db.Column(db.Date, nullable=True)
    next_action = db.Column(db.String(100), nullable=True)

    collection_status = db.Column(db.String(30), nullable=False, default="FOLLOW_UP")
    created_by = db.Column(db.Integer, nullable=False)

    created_at = db.Column(db.DateTime, nullable=False, default=db.func.now())

    invoice = db.relationship(
        "Invoice",
        backref=db.backref("collection_logs", lazy=True)
    )

    def __repr__(self):
        return f"<InvoiceCollectionLog invoice_id={self.invoice_id} status={self.collection_status}>"



# === PRODUCTION_OPTIONAL_ADVANCE_DP_FLOW ===
class AdvanceTransaction(BaseModel):
    """Optional DP / uang muka / panjar transaction.

    This table is intentionally optional and event-based:
    no advance row means no DP accounting event exists.
    """
    __tablename__ = "advance_transactions"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    advance_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    advance_date = db.Column(db.Date, nullable=False, index=True)
    advance_type = db.Column(db.String(50), nullable=False, index=True)
    party_type = db.Column(db.String(30), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True, index=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True, index=True)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=True, index=True)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    payment_method = db.Column(db.String(30), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    settled_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    remaining_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="OPEN", index=True)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    client = db.relationship("Client", foreign_keys=[client_id], lazy=True)
    supplier = db.relationship("Supplier", foreign_keys=[supplier_id], lazy=True)
    mandor = db.relationship("Mandor", foreign_keys=[mandor_id], lazy=True)
    bank_account = db.relationship("BankAccount", foreign_keys=[bank_account_id], lazy=True)
    cash_bank_transaction = db.relationship("CashBankTransaction", foreign_keys=[cash_bank_transaction_id], lazy=True)
    journal = db.relationship("Journal", foreign_keys=[journal_id], lazy=True)
    settlements = db.relationship("AdvanceSettlement", backref="advance", lazy=True)


class AdvanceSettlement(BaseModel):
    """Settlement / pemakaian advance ke invoice, supplier bill, or later expense proof."""
    __tablename__ = "advance_settlements"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    settlement_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    advance_id = db.Column(db.Integer, db.ForeignKey("advance_transactions.id"), nullable=False, index=True)
    settlement_date = db.Column(db.Date, nullable=False, index=True)
    settlement_type = db.Column(db.String(50), nullable=False, index=True)
    reference_type = db.Column(db.String(50), nullable=True, index=True)
    reference_id = db.Column(db.Integer, nullable=True, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    journal = db.relationship("Journal", foreign_keys=[journal_id], lazy=True)


# === PRODUCTION_TRANSPORT_VEHICLE_FUEL_EXPENSE_COA_MAPPING ===
class TransportVehicleExpense(BaseModel):
    """Transport / vehicle fuel expense that posts directly to COA 5003 or 5011.

    This is event-based: no row means no transport/fuel expense event exists.
    Vehicle master is not present in the active schema yet, so vehicle is stored as
    a safe label while driver and delivery can be linked to existing tables.
    """
    __tablename__ = "transport_vehicle_expenses"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    expense_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    expense_type = db.Column(db.String(50), nullable=False, index=True)
    account_code = db.Column(db.String(50), nullable=False, index=True)
    payment_method = db.Column(db.String(30), nullable=False)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    vehicle_label = db.Column(db.String(150), nullable=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=True, index=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("deliveries.id"), nullable=True, index=True)
    vendor_name = db.Column(db.String(150), nullable=True)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    bank_account = db.relationship("BankAccount", foreign_keys=[bank_account_id], lazy=True)
    driver = db.relationship("Driver", foreign_keys=[driver_id], lazy=True)
    delivery = db.relationship("Delivery", foreign_keys=[delivery_id], lazy=True)
    cash_bank_transaction = db.relationship("CashBankTransaction", foreign_keys=[cash_bank_transaction_id], lazy=True)
    journal = db.relationship("Journal", foreign_keys=[journal_id], lazy=True)


# === PRODUCTION_OPERATIONAL_EXPENSE_COA_MAPPING ===
class OperationalExpense(BaseModel):
    """Operational catering expense mapped directly to expense COA.

    This is event-based: no row means no operational expense event exists.
    PRODUCTION intentionally handles direct cash/bank operational expense posting.
    Supplier-credit operational AP is kept out of this table until AP can support
    non-procurement supplier bills safely without breaking existing procurement AP.
    """
    __tablename__ = "operational_expenses"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    expense_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    expense_date = db.Column(db.Date, nullable=False, index=True)
    expense_category = db.Column(db.String(50), nullable=False, index=True)
    account_code = db.Column(db.String(50), nullable=False, index=True)
    payment_method = db.Column(db.String(30), nullable=False)
    account_type = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True, index=True)
    vendor_name = db.Column(db.String(150), nullable=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    posting_status = db.Column(db.String(30), nullable=False, default="POSTED", index=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    bank_account = db.relationship("BankAccount", foreign_keys=[bank_account_id], lazy=True)
    supplier = db.relationship("Supplier", foreign_keys=[supplier_id], lazy=True)
    cash_bank_transaction = db.relationship("CashBankTransaction", foreign_keys=[cash_bank_transaction_id], lazy=True)
    journal = db.relationship("Journal", foreign_keys=[journal_id], lazy=True)
