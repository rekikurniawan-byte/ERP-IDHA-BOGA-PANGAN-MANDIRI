"""Kontrol kredit per pihak tertagih.

Sebelum ini syarat kredit hanya ada di customer_contracts, dan kontrak milik
CLIENT. Sub client (mandor) yang ditagih langsung -- karena PT pemilik proyek
tidak mau menjamin pembayarannya -- jadi tidak punya limit, tidak punya termin,
dan tidak punya gerbang sama sekali.

CreditAccount memindahkan syarat kredit ke pihak yang benar-benar ditagih, yang
bisa CLIENT maupun MANDOR. Lihat BLUEPRINT_V2_KONTROL_KREDIT.md.
"""
from datetime import datetime

from app.extensions import db
from app.models.base import BaseModel


PARTY_CLIENT = "CLIENT"
PARTY_MANDOR = "MANDOR"

# Ditagih ke PT pemilik proyek / ditagih langsung ke mandor (kredit) / bayar di muka.
BILLING_VIA_CLIENT = "VIA_CLIENT"
BILLING_DIRECT = "DIRECT"
BILLING_CASH = "CASH"

# Tangga eskalasi. Urutannya bermakna: naik otomatis, turun tidak pernah
# otomatis -- hanya OWNER yang boleh menurunkan.
STATUS_ACTIVE = "AKTIF"
STATUS_WATCH = "PANTAU"
STATUS_HOLD = "TAHAN"
STATUS_BLOCKED = "BLOKIR"
STATUS_WRITE_OFF = "HAPUS_BUKU"

CREDIT_STATUS_ORDER = (
    STATUS_ACTIVE,
    STATUS_WATCH,
    STATUS_HOLD,
    STATUS_BLOCKED,
    STATUS_WRITE_OFF,
)


class CreditAccount(BaseModel):
    """Syarat kredit satu pihak tertagih. Satu baris per (cabang, pihak)."""

    __tablename__ = "credit_accounts"
    __table_args__ = (
        db.UniqueConstraint(
            "branch_id", "party_type", "party_id",
            name="uq_credit_accounts_party",
        ),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    party_type = db.Column(db.String(20), nullable=False)
    party_id = db.Column(db.Integer, nullable=False)

    # Baris hanya ada untuk pihak yang kreditnya disetel owner. Pihak tanpa
    # baris dinilai sama dengan baris bawaan ini: VIA_CLIENT, limit 0, AKTIF.
    billing_mode = db.Column(
        db.String(20), nullable=False, default=BILLING_VIA_CLIENT,
        server_default=BILLING_VIA_CLIENT,
    )

    credit_limit = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    payment_terms_days = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    # Syarat deposit, sebagai persen dari limit. Jumlah deposit yang SUDAH
    # diterima sengaja tidak disimpan di sini: dihitung dari transaksi deposit
    # di buku besar (advance_transactions, akun 2007), supaya angka di layar
    # kredit tidak mungkin berbeda dengan jurnalnya.
    deposit_percent = db.Column(db.Numeric(8, 4), nullable=False, default=20, server_default="20")

    status = db.Column(
        db.String(20), nullable=False, default=STATUS_ACTIVE,
        server_default=STATUS_ACTIVE, index=True,
    )
    status_reason = db.Column(db.Text, nullable=True)
    status_changed_at = db.Column(db.DateTime, nullable=True)
    status_changed_by = db.Column(db.Integer, nullable=True)
    # Pelepasan sementara oleh OWNER, misalnya sampai tanggal komitmen bayar
    # tertulis. Sampai tanggal ini gerbang memakai status yang disetel OWNER;
    # sesudahnya hitungan otomatis berlaku lagi. Tanpa ini, OWNER tidak bisa
    # membuka mandor yang diblokir selama tunggakannya masih tua.
    release_until = db.Column(db.Date, nullable=True)

    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True, server_default="true")

    # Kelonggaran (QS Al-Baqarah 280) untuk pihak yang benar-benar tidak
    # mampu, dicatat OWNER. Sampai tanggal ini utang lama ditangguhkan: status
    # tidak naik melewati TAHAN dan tidak ada usulan ta'zir, tetapi pesanan
    # baru tetap wajib bayar di muka (TAHAN).
    grace_until = db.Column(db.Date, nullable=True)
    grace_reason = db.Column(db.Text, nullable=True)
    grace_set_by = db.Column(db.Integer, nullable=True)
    grace_set_at = db.Column(db.DateTime, nullable=True)

    def grace_active(self, on_date):
        return bool(self.grace_until and on_date and on_date <= self.grace_until)

    @property
    def required_deposit(self):
        """Deposit yang harus sudah diterima sebelum kredit menyala."""
        limit = self.credit_limit or 0
        percent = self.deposit_percent or 0
        return limit * percent / 100


class CreditStatusEvent(BaseModel):
    """Jejak tiap perpindahan status. Append-only, tidak pernah di-update.

    Ada supaya waktu mandor kabur lalu bilang "saya tidak pernah diperingatkan",
    tanggal dan angkanya bisa ditunjukkan.
    """

    __tablename__ = "credit_status_events"

    branch_id = db.Column(db.Integer, nullable=False, index=True)
    credit_account_id = db.Column(
        db.Integer, db.ForeignKey("credit_accounts.id"), nullable=False, index=True,
    )

    from_status = db.Column(db.String(20), nullable=True)
    to_status = db.Column(db.String(20), nullable=False)
    # SWEEP untuk penyapu harian, MANUAL kalau digerakkan orang.
    trigger = db.Column(db.String(30), nullable=False)
    reason = db.Column(db.Text, nullable=False)

    # Angka pada saat perpindahan, dibekukan supaya jejaknya tetap terbaca
    # walaupun invoice-nya berubah belakangan.
    exposure_amount = db.Column(db.Numeric(18, 2), nullable=True)
    credit_limit = db.Column(db.Numeric(18, 2), nullable=True)
    oldest_days_overdue = db.Column(db.Integer, nullable=True)

    changed_by = db.Column(db.Integer, nullable=True)
    changed_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


# Ta'zir: sanksi nominal tetap per kejadian untuk yang mampu tapi menunda,
# masuk Dana Sosial (bukan pendapatan). Ta'widh: ganti biaya penagihan riil
# yang ada buktinya. Keduanya diputuskan OWNER dan ditagih terpisah dari
# invoice makanan (fatwa DSN-MUI No. 17/2000 dan No. 43/2004).
CHARGE_TAZIR = "TAZIR"
CHARGE_TAWIDH = "TAWIDH"
CHARGE_TYPES = (CHARGE_TAZIR, CHARGE_TAWIDH)

CHARGE_PROPOSED = "PROPOSED"
CHARGE_IMPOSED = "IMPOSED"
CHARGE_DECLINED = "DECLINED"

TRIGGER_BROKEN_PROMISE = "BROKEN_PROMISE"
TRIGGER_BLOCKED = "BLOCKED"
TRIGGER_MANUAL = "MANUAL"


class CreditCharge(BaseModel):
    """Usulan/keputusan ta'zir atau ta'widh untuk satu pihak tertagih."""

    __tablename__ = "credit_charges"
    __table_args__ = (
        # Satu kejadian (janji meleset tertentu / satu kali masuk BLOKIR) hanya
        # boleh diusulkan sekali, walaupun penyapu jalan berkali-kali.
        db.UniqueConstraint("credit_account_id", "charge_type", "trigger_key", name="uq_credit_charges_trigger"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    credit_account_id = db.Column(db.Integer, db.ForeignKey("credit_accounts.id"), nullable=False, index=True)
    charge_type = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=CHARGE_PROPOSED, server_default=CHARGE_PROPOSED, index=True)
    trigger = db.Column(db.String(30), nullable=False)
    trigger_key = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    reason = db.Column(db.Text, nullable=False)
    contract_id = db.Column(db.Integer, db.ForeignKey("customer_contracts.id"), nullable=True)
    evidence_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True, index=True)
    decided_by = db.Column(db.Integer, nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    decision_note = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=True)

    account = db.relationship("CreditAccount", foreign_keys=[credit_account_id], lazy=True)
    invoice = db.relationship("Invoice", foreign_keys=[invoice_id], lazy=True)


class SocialFundDisbursement(BaseModel):
    """Penyaluran Dana Sosial (akun 2009), hanya dicatat OWNER, dengan bukti."""

    __tablename__ = "social_fund_disbursements"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    disbursed_on = db.Column(db.Date, nullable=False, index=True)
    recipient = db.Column(db.String(200), nullable=False)
    purpose = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    account_type = db.Column(db.String(10), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    evidence_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)
