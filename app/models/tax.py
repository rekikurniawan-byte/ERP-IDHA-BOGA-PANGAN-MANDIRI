"""Pajak (Fase 8): potongan pajak oleh pelanggan, setoran pajak, dokumen pajak.

Pengaturan pajak (rezim PPh, Surat Keterangan PP 55, PBJT) disimpan di
branch_settings lewat tax_service; tabel di sini mencatat kejadiannya.
"""
from datetime import datetime

from app.extensions import db
from app.models.base import BaseModel

# Potongan PPh oleh pelanggan saat membayar invoice.
WITHHOLDING_PPH_FINAL = "PPH_FINAL_05"   # PP 55: 0,5% final
WITHHOLDING_PPH23 = "PPH23"              # tarif normal: PPh 23 2%, kredit pajak
WITHHOLDING_TYPES = (WITHHOLDING_PPH_FINAL, WITHHOLDING_PPH23)

# Setoran pajak yang dibayar PT sendiri.
TAX_PAYMENT_PPH_FINAL = "PPH_FINAL"
TAX_PAYMENT_PBJT = "PBJT"
TAX_PAYMENT_PPH25 = "PPH25"
TAX_PAYMENT_PPH29 = "PPH29"
TAX_PAYMENT_PPH21 = "PPH21"  # PPh 21 karyawan yang dipotong/ditanggung lewat penggajian
TAX_PAYMENT_TYPES = (TAX_PAYMENT_PPH_FINAL, TAX_PAYMENT_PBJT, TAX_PAYMENT_PPH25, TAX_PAYMENT_PPH29, TAX_PAYMENT_PPH21)


class TaxWithholding(BaseModel):
    """Potongan pajak pelanggan atas satu invoice (bukti potong). Mengurangi sisa invoice."""

    __tablename__ = "tax_withholdings"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=False, index=True)
    withholding_type = db.Column(db.String(20), nullable=False)
    withheld_on = db.Column(db.Date, nullable=False, index=True)
    base_amount = db.Column(db.Numeric(18, 2), nullable=False)
    rate_percent = db.Column(db.Numeric(8, 4), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    certificate_number = db.Column(db.String(100), nullable=False)
    attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journals.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    invoice = db.relationship("Invoice", foreign_keys=[invoice_id], lazy=True)


class TaxPayment(BaseModel):
    """Setoran pajak (PPh final, PBJT, angsuran) dengan NTPN dan bukti."""

    __tablename__ = "tax_payments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    tax_type = db.Column(db.String(20), nullable=False, index=True)
    period_year = db.Column(db.Integer, nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    paid_on = db.Column(db.Date, nullable=False, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    reference_number = db.Column(db.String(100), nullable=False)  # NTPN / nomor bukti setor daerah
    account_type = db.Column(db.String(10), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)


class TaxDocument(BaseModel):
    """Dokumen pajak/legal perusahaan (SKT, Surat Keterangan PP 55, NPWPD, akta) + masa berlaku."""

    __tablename__ = "tax_documents"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    doc_type = db.Column(db.String(40), nullable=False)
    doc_number = db.Column(db.String(150), nullable=True)
    issued_on = db.Column(db.Date, nullable=True)
    valid_until = db.Column(db.Date, nullable=True, index=True)
    attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="true")
    created_by = db.Column(db.Integer, nullable=False)
    updated_at = db.Column(db.DateTime, nullable=True, default=datetime.utcnow)
