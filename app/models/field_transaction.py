from app.extensions import db
from app.models.base import BaseModel


FIELD_TRANSACTION_DIRECTIONS = ("IN", "OUT")
FIELD_TRANSACTION_CHANNELS = (
    "MANUAL",
    "BACKDATE",
    "RECAP_HARIAN",
    "RECAP_MINGGUAN",
    "RECAP_BULANAN",
    "SYSTEM",
)
FIELD_TRANSACTION_PAYMENT_STATUSES = (
    "UNSPECIFIED",
    "UNPAID",
    "PARTIAL",
    "PAID",
)
FIELD_TRANSACTION_REVIEW_STATUSES = (
    "DRAFT",
    "RECORDED",
    "WAITING_EVIDENCE",
    "WAITING_CLASSIFICATION",
    "IN_REVIEW",
    "WAITING_APPROVAL",
    "READY_TO_POST",
    "POSTED",
    "REJECTED",
    "VOID",
    "RECONCILED",
)
FIELD_TRANSACTION_POSTING_STATUSES = (
    "NOT_POSTED",
    "POSTED",
    "PARTIALLY_POSTED",
    "VOIDED",
)
FIELD_TRANSACTION_EVIDENCE_STATUSES = (
    "NONE",
    "PENDING",
    "ATTACHED",
    "VERIFIED",
)
FIELD_TRANSACTION_COUNTERPARTY_TYPES = (
    "CLIENT_FORMAL",
    "MANDOR_NON_PT",
    "PEMBELI_UMUM",
    "PEKERJA_LAPANGAN",
    "BUYER_EKSTERNAL",
    "VENDOR_NONFORMAL",
    "SUPPLIER_FORMAL",
    "LAINNYA",
)


class FieldCounterparty(BaseModel):
    __tablename__ = "field_counterparties"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    counterparty_type = db.Column(db.String(40), nullable=False, index=True)
    name = db.Column(db.String(150), nullable=False)
    company_name = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(50), nullable=True)
    site_location = db.Column(db.String(150), nullable=True, index=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, index=True)
    linked_client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True, index=True)
    linked_supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True, index=True)
    linked_mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy=True)
    linked_client = db.relationship("Client", foreign_keys=[linked_client_id], lazy=True)
    linked_supplier = db.relationship("Supplier", foreign_keys=[linked_supplier_id], lazy=True)
    linked_mandor = db.relationship("Mandor", foreign_keys=[linked_mandor_id], lazy=True)
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)


class FieldTransaction(BaseModel):
    __tablename__ = "field_transactions"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    transaction_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    transaction_date = db.Column(db.Date, nullable=False, index=True)
    entry_date = db.Column(db.Date, nullable=False, index=True)
    transaction_direction = db.Column(db.String(10), nullable=False, index=True)
    business_event_type = db.Column(db.String(80), nullable=False, index=True)
    field_channel = db.Column(db.String(30), nullable=False, default="MANUAL", index=True)
    counterparty_id = db.Column(db.Integer, db.ForeignKey("field_counterparties.id"), nullable=True, index=True)
    counterparty_type_snapshot = db.Column(db.String(40), nullable=True, index=True)
    party_snapshot_name = db.Column(db.String(150), nullable=True)
    party_snapshot_company = db.Column(db.String(150), nullable=True)
    party_snapshot_phone = db.Column(db.String(50), nullable=True)
    site_location = db.Column(db.String(150), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    payment_status = db.Column(db.String(20), nullable=False, default="UNSPECIFIED", index=True)
    payment_method = db.Column(db.String(30), nullable=True, index=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True, index=True)
    review_status = db.Column(db.String(30), nullable=False, default="DRAFT", index=True)
    posting_status = db.Column(db.String(30), nullable=False, default="NOT_POSTED", index=True)
    evidence_status = db.Column(db.String(20), nullable=False, default="NONE", index=True)
    is_manual = db.Column(db.Boolean, nullable=False, default=True, index=True)
    needs_follow_up = db.Column(db.Boolean, nullable=False, default=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    source_context_json = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    posted_at = db.Column(db.DateTime, nullable=True)
    posted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy=True)
    counterparty = db.relationship("FieldCounterparty", foreign_keys=[counterparty_id], lazy=True)
    bank_account = db.relationship("BankAccount", foreign_keys=[bank_account_id], lazy=True)
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)
    reviewer = db.relationship("User", foreign_keys=[reviewed_by], lazy=True)
    poster = db.relationship("User", foreign_keys=[posted_by], lazy=True)
    attachments = db.relationship("FieldTransactionAttachment", backref="field_transaction", lazy=True)
    review_logs = db.relationship("FieldTransactionReviewLog", backref="field_transaction", lazy=True)
    links = db.relationship("FieldTransactionLink", backref="field_transaction", lazy=True)
    settlements = db.relationship("FieldTransactionSettlement", backref="field_transaction", lazy=True)


class FieldTransactionAttachment(BaseModel):
    __tablename__ = "field_transaction_attachments"

    field_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("field_transactions.id"),
        nullable=False,
        index=True,
    )
    digital_attachment_id = db.Column(
        db.Integer,
        db.ForeignKey("digital_attachments.id"),
        nullable=True,
        index=True,
    )
    attachment_role = db.Column(db.String(40), nullable=False, default="EVIDENCE", index=True)
    status = db.Column(db.String(20), nullable=False, default="ATTACHED", index=True)
    notes = db.Column(db.Text, nullable=True)
    verified_at = db.Column(db.DateTime, nullable=True)
    verified_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    digital_attachment = db.relationship("DigitalAttachment", foreign_keys=[digital_attachment_id], lazy=True)
    verifier = db.relationship("User", foreign_keys=[verified_by], lazy=True)
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)


class FieldTransactionReviewLog(BaseModel):
    __tablename__ = "field_transaction_review_logs"

    field_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("field_transactions.id"),
        nullable=False,
        index=True,
    )
    from_review_status = db.Column(db.String(30), nullable=True, index=True)
    to_review_status = db.Column(db.String(30), nullable=False, index=True)
    action_type = db.Column(db.String(40), nullable=False, default="STATUS_CHANGE", index=True)
    note = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    acted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    actor = db.relationship("User", foreign_keys=[acted_by], lazy=True)


class FieldTransactionLink(BaseModel):
    __tablename__ = "field_transaction_links"
    __table_args__ = (
        db.UniqueConstraint(
            "field_transaction_id",
            "link_role",
            "reference_type",
            "reference_id",
            name="uq_field_transaction_link_unique",
        ),
    )

    field_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("field_transactions.id"),
        nullable=False,
        index=True,
    )
    link_role = db.Column(db.String(40), nullable=False, index=True)
    reference_type = db.Column(db.String(80), nullable=False, index=True)
    reference_id = db.Column(db.Integer, nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)


class FieldTransactionSettlement(BaseModel):
    __tablename__ = "field_transaction_settlements"

    field_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("field_transactions.id"),
        nullable=False,
        index=True,
    )
    settlement_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    settlement_date = db.Column(db.Date, nullable=False, index=True)
    settlement_type = db.Column(db.String(40), nullable=False, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    reference_type = db.Column(db.String(80), nullable=True, index=True)
    reference_id = db.Column(db.Integer, nullable=True, index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)


class ManualReceivable(BaseModel):
    __tablename__ = "manual_receivables"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    receivable_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    field_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("field_transactions.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    counterparty_id = db.Column(db.Integer, db.ForeignKey("field_counterparties.id"), nullable=True, index=True)
    receivable_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    party_name = db.Column(db.String(150), nullable=False)
    party_company = db.Column(db.String(150), nullable=True)
    party_phone = db.Column(db.String(50), nullable=True)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    paid_amount = db.Column(db.Float, nullable=False, default=0)
    remaining_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="OPEN", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy=True)
    field_transaction = db.relationship("FieldTransaction", foreign_keys=[field_transaction_id], lazy=True)
    counterparty = db.relationship("FieldCounterparty", foreign_keys=[counterparty_id], lazy=True)
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)


class ManualReceivablePayment(BaseModel):
    __tablename__ = "manual_receivable_payments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    payment_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    manual_receivable_id = db.Column(
        db.Integer,
        db.ForeignKey("manual_receivables.id"),
        nullable=False,
        index=True,
    )
    payment_date = db.Column(db.Date, nullable=False, index=True)
    payment_method = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True, index=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True, index=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    paid_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy=True)
    manual_receivable = db.relationship(
        "ManualReceivable",
        foreign_keys=[manual_receivable_id],
        backref=db.backref("payments", lazy=True),
        lazy=True,
    )
    bank_account = db.relationship("BankAccount", foreign_keys=[bank_account_id], lazy=True)
    cash_bank_transaction = db.relationship("CashBankTransaction", foreign_keys=[cash_bank_transaction_id], lazy=True)
    journal = db.relationship("Journal", foreign_keys=[journal_id], lazy=True)
    payer = db.relationship("User", foreign_keys=[paid_by], lazy=True)


class ManualPayable(BaseModel):
    __tablename__ = "manual_payables"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    payable_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    field_transaction_id = db.Column(
        db.Integer,
        db.ForeignKey("field_transactions.id"),
        nullable=False,
        unique=True,
        index=True,
    )
    counterparty_id = db.Column(db.Integer, db.ForeignKey("field_counterparties.id"), nullable=True, index=True)
    payable_date = db.Column(db.Date, nullable=False, index=True)
    due_date = db.Column(db.Date, nullable=False, index=True)
    party_name = db.Column(db.String(150), nullable=False)
    party_company = db.Column(db.String(150), nullable=True)
    party_phone = db.Column(db.String(50), nullable=True)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    paid_amount = db.Column(db.Float, nullable=False, default=0)
    remaining_amount = db.Column(db.Float, nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="OPEN", index=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy=True)
    field_transaction = db.relationship("FieldTransaction", foreign_keys=[field_transaction_id], lazy=True)
    counterparty = db.relationship("FieldCounterparty", foreign_keys=[counterparty_id], lazy=True)
    creator = db.relationship("User", foreign_keys=[created_by], lazy=True)


class ManualPayablePayment(BaseModel):
    __tablename__ = "manual_payable_payments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    payment_number = db.Column(db.String(50), nullable=False, unique=True, index=True)
    manual_payable_id = db.Column(
        db.Integer,
        db.ForeignKey("manual_payables.id"),
        nullable=False,
        index=True,
    )
    payment_date = db.Column(db.Date, nullable=False, index=True)
    payment_method = db.Column(db.String(30), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True, index=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True, index=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True, index=True)
    amount = db.Column(db.Float, nullable=False, default=0)
    reference_number = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    paid_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy=True)
    manual_payable = db.relationship(
        "ManualPayable",
        foreign_keys=[manual_payable_id],
        backref=db.backref("payments", lazy=True),
        lazy=True,
    )
    bank_account = db.relationship("BankAccount", foreign_keys=[bank_account_id], lazy=True)
    cash_bank_transaction = db.relationship("CashBankTransaction", foreign_keys=[cash_bank_transaction_id], lazy=True)
    journal = db.relationship("Journal", foreign_keys=[journal_id], lazy=True)
    payer = db.relationship("User", foreign_keys=[paid_by], lazy=True)
