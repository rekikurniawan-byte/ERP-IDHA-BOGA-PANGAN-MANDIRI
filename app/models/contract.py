from datetime import time

from app.extensions import db
from app.models.base import BaseModel


COURT_PANGKALAN_BALAI = "PN_PANGKALAN_BALAI"
COURT_KAYUAGUNG = "PN_KAYUAGUNG"
DISPUTE_COURTS = (COURT_PANGKALAN_BALAI, COURT_KAYUAGUNG)

DISPUTE_COURT_LABELS = {
    COURT_PANGKALAN_BALAI: "PN Pangkalan Balai (alamat PT, Kab. Banyuasin)",
    COURT_KAYUAGUNG: "PN Kayuagung (lokasi OKI)",
}

BILLING_CYCLE_WEEKLY = "WEEKLY"
BILLING_CYCLE_BIWEEKLY = "BIWEEKLY"
BILLING_CYCLE_MONTHLY = "MONTHLY"
BILLING_CYCLES = (BILLING_CYCLE_WEEKLY, BILLING_CYCLE_BIWEEKLY, BILLING_CYCLE_MONTHLY)

BILLING_CYCLE_LABELS = {
    BILLING_CYCLE_WEEKLY: "Mingguan",
    BILLING_CYCLE_BIWEEKLY: "14 Hari (Dua Mingguan)",
    BILLING_CYCLE_MONTHLY: "Bulanan",
}


class CustomerContract(BaseModel):
    __tablename__ = "customer_contracts"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'EXPIRED', 'TERMINATED', 'SUPERSEDED')",
            name="ck_customer_contracts_status",
        ),
        db.CheckConstraint("version_no > 0", name="ck_customer_contracts_version_positive"),
        db.CheckConstraint("end_date >= start_date", name="ck_customer_contracts_date_range"),
        db.CheckConstraint("due_days >= 1", name="ck_customer_contracts_due_days_positive"),
        db.CheckConstraint("tazir_amount >= 0", name="ck_customer_contracts_tazir_nonnegative"),
        db.CheckConstraint(
            "default_billing_mode IN ('VIA_CLIENT', 'DIRECT', 'CASH')",
            name="ck_customer_contracts_billing_mode",
        ),
        db.CheckConstraint(
            "billing_cycle IN ('WEEKLY', 'BIWEEKLY', 'MONTHLY')",
            name="ck_customer_contracts_billing_cycle",
        ),
        db.CheckConstraint(
            "dispute_court IN ('PN_PANGKALAN_BALAI', 'PN_KAYUAGUNG')",
            name="ck_customer_contracts_dispute_court",
        ),
        db.Index("ix_customer_contracts_client_status", "client_id", "status"),
        db.Index("ix_customer_contracts_branch_end_date", "branch_id", "end_date"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    client_pic_id = db.Column(db.Integer, db.ForeignKey("client_pics.id"), nullable=True, index=True)
    parent_contract_id = db.Column(db.Integer, db.ForeignKey("customer_contracts.id"), nullable=True, index=True)
    contract_number = db.Column(db.String(60), nullable=False, unique=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    payment_terms = db.Column(db.String(120), nullable=False)
    credit_limit = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="DRAFT", index=True)
    version_no = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    # Fase 3 — Pengaturan kontrak (fondasi)
    lunch_lock_time = db.Column(db.Time, nullable=False, default=time(10, 0))
    dinner_lock_time = db.Column(db.Time, nullable=False, default=time(15, 0))
    weekly_holidays = db.Column(db.String(20), nullable=True, default="")
    default_billing_mode = db.Column(db.String(20), nullable=False, default="VIA_CLIENT")
    billing_cycle = db.Column(db.String(20), nullable=False, default="BIWEEKLY")
    billing_anchor_date = db.Column(db.Date, nullable=True)
    due_days = db.Column(db.Integer, nullable=False, default=7)
    dispute_court = db.Column(db.String(40), nullable=False, default=COURT_PANGKALAN_BALAI)
    tazir_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    client = db.relationship("Client", foreign_keys=[client_id], lazy="joined")
    client_pic = db.relationship("ClientPic", foreign_keys=[client_pic_id], lazy="joined")
    parent_contract = db.relationship("CustomerContract", remote_side="CustomerContract.id", lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = db.relationship("User", foreign_keys=[updated_by], lazy="joined")

    holidays = db.relationship(
        "ContractHoliday",
        backref="contract",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="ContractHoliday.holiday_date",
    )
    documents = db.relationship(
        "ContractDocument",
        back_populates="contract",
        cascade="all, delete-orphan",
        lazy="select",
        order_by="ContractDocument.version_no.desc(), ContractDocument.id.desc()",
    )


DOC_TYPE_CONTRACT = "KONTRAK"
DOC_TYPE_ADDENDUM = "ADENDUM"
DOC_TYPES = (DOC_TYPE_CONTRACT, DOC_TYPE_ADDENDUM)

DOC_STATUS_DRAFT = "DRAFT"
DOC_STATUS_PENDING = "MENUNGGU_TTD"
DOC_STATUS_SIGNED = "DITANDATANGANI"
DOC_STATUSES = (DOC_STATUS_DRAFT, DOC_STATUS_PENDING, DOC_STATUS_SIGNED)

SIGNING_METHOD_WET = "WET_STAMP"
SIGNING_METHOD_OTP = "PORTAL_EMAIL_OTP"
SIGNING_METHODS = (SIGNING_METHOD_WET, SIGNING_METHOD_OTP)


class ContractDocument(BaseModel):
    """Snapshot dokumen surat kontrak dan adendum resmi."""

    __tablename__ = "contract_documents"
    __table_args__ = (
        db.CheckConstraint(
            "document_type IN ('KONTRAK', 'ADENDUM')",
            name="ck_contract_documents_type",
        ),
        db.CheckConstraint(
            "status IN ('DRAFT', 'MENUNGGU_TTD', 'DITANDATANGANI')",
            name="ck_contract_documents_status",
        ),
        db.CheckConstraint(
            "signing_method IS NULL OR signing_method IN ('WET_STAMP', 'PORTAL_EMAIL_OTP')",
            name="ck_contract_documents_signing_method",
        ),
        db.Index("ix_contract_documents_contract_status", "contract_id", "status"),
        db.Index("ix_contract_documents_branch_id", "branch_id"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("customer_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    document_number = db.Column(db.String(80), nullable=False, unique=True, index=True)
    document_type = db.Column(db.String(30), nullable=False, default=DOC_TYPE_CONTRACT)
    version_no = db.Column(db.Integer, nullable=False, default=1)
    title = db.Column(db.String(200), nullable=False)
    html_snapshot = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default=DOC_STATUS_PENDING, index=True)
    signing_method = db.Column(db.String(30), nullable=True)
    scan_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    signed_at = db.Column(db.DateTime, nullable=True)
    signed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    signed_by_name = db.Column(db.String(120), nullable=True)
    portal_signed_at = db.Column(db.DateTime, nullable=True)
    portal_signed_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    otp_code_hash = db.Column(db.String(128), nullable=True)
    otp_expires_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    contract = db.relationship("CustomerContract", foreign_keys=[contract_id], back_populates="documents", lazy="joined")
    scan_attachment = db.relationship("DigitalAttachment", foreign_keys=[scan_attachment_id], lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
    signed_by_user = db.relationship("User", foreign_keys=[signed_by_user_id], lazy="joined")
    portal_signed_by_user = db.relationship("User", foreign_keys=[portal_signed_by_user_id], lazy="joined")


class ContractHoliday(BaseModel):
    """Hari libur khusus per kontrak (mis. libur bersama, tanggal tertentu)."""

    __tablename__ = "contract_holidays"
    __table_args__ = (
        db.UniqueConstraint("contract_id", "holiday_date", name="uq_contract_holidays_contract_date"),
        db.Index("ix_contract_holidays_contract_id", "contract_id"),
        db.Index("ix_contract_holidays_holiday_date", "holiday_date"),
    )

    contract_id = db.Column(db.Integer, db.ForeignKey("customer_contracts.id", ondelete="CASCADE"), nullable=False)
    holiday_date = db.Column(db.Date, nullable=False)
    note = db.Column(db.String(200), nullable=True)

