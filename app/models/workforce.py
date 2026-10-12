"""Modul Tenaga Kerja: kontrak kerja, izin keluar lokasi, mangkir, denda/ganti rugi, dan keluar.

Keputusan owner 2026-10-11 (lihat RENCANA_PENGEMBANGAN_ERP.md):
- kontrak PKWT/PKWTT ditandatangani karyawan di layar HP + foto KTP, lalu owner;
- apel harian oleh admin (tanpa GPS, semua karyawan tinggal di lokasi);
- denda tertulis -> Pendapatan Lain-lain; ganti rugi sisa kontrak (Pasal 62 UU 13/2003)
  dipotong bertahap maks 50% upah per periode, sisanya piutang karyawan.
"""
from app.extensions import db
from app.models.base import BaseModel


CONTRACT_PKWT = "PKWT"
CONTRACT_PKWTT = "PKWTT"
CONTRACT_TYPES = (CONTRACT_PKWT, CONTRACT_PKWTT)

CONTRACT_DRAFT = "DRAFT"
CONTRACT_WAITING_EMPLOYER = "MENUNGGU_TTD_PERUSAHAAN"
CONTRACT_ACTIVE = "AKTIF"
CONTRACT_ENDED = "BERAKHIR"
CONTRACT_CANCELLED = "BATAL"

ATTENDANCE_STATUSES = ("HADIR", "IZIN", "SAKIT", "CUTI", "ALPA")

LEAVE_TYPES = ("IZIN_KELUAR", "PULANG_KAMPUNG", "CUTI", "SAKIT")
LEAVE_SUBMITTED = "DIAJUKAN"
LEAVE_APPROVED = "DISETUJUI"
LEAVE_REJECTED = "DITOLAK"
LEAVE_RETURNED = "KEMBALI"

CASE_OPEN = "TERBUKA"
CASE_SUMMONS_1 = "PANGGILAN_1"
CASE_SUMMONS_2 = "PANGGILAN_2"
CASE_RETURNED = "KEMBALI"
CASE_DEEMED_RESIGNED = "MENGUNDURKAN_DIRI"
CASE_OPEN_STATUSES = (CASE_OPEN, CASE_SUMMONS_1, CASE_SUMMONS_2)

CHARGE_FINE = "DENDA"
CHARGE_DAMAGES = "GANTI_RUGI"
CHARGE_ADVANCE = "KASBON"
CHARGE_PROPOSED = "DIUSULKAN"
CHARGE_ACTIVE = "AKTIF"
CHARGE_PAID = "LUNAS"
CHARGE_CANCELLED = "BATAL"

EXIT_RESIGN = "RESIGN"
EXIT_CONTRACT_END = "HABIS_KONTRAK"
EXIT_ABSCONDED = "MANGKIR"
EXIT_DISMISSED = "DIBERHENTIKAN"
EXIT_SUBMITTED = "DIAJUKAN"
EXIT_APPROVED = "DISETUJUI"
EXIT_DONE = "SELESAI"
EXIT_CANCELLED = "BATAL"


class EmploymentContract(BaseModel):
    __tablename__ = "employment_contracts"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    contract_number = db.Column(db.String(60), nullable=False, unique=True)
    contract_type = db.Column(db.String(10), nullable=False)
    position = db.Column(db.String(100), nullable=False)
    work_location = db.Column(db.String(200), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=True)
    probation_months = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    monthly_salary = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    notice_days = db.Column(db.Integer, nullable=False, default=30, server_default="30")
    fine_absent_per_day = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    fine_leave_site = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    fine_late_return_per_day = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    fine_short_notice = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    max_deduction_percent = db.Column(db.Integer, nullable=False, default=50, server_default="50")
    # Aturan potong upah hari tidak bekerja, dikunci per kontrak saat dibuat.
    unpaid_statuses = db.Column(db.String(60), nullable=False, default="ALPA", server_default="ALPA")
    daily_wage_divisor = db.Column(db.String(10), nullable=False, default="KALENDER", server_default="KALENDER")
    status = db.Column(db.String(30), nullable=False, default=CONTRACT_DRAFT, index=True)
    html_snapshot = db.Column(db.Text, nullable=True)
    employee_signature_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    ktp_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    employee_signed_at = db.Column(db.DateTime, nullable=True)
    employer_signature_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    employer_signed_at = db.Column(db.DateTime, nullable=True)
    employer_signed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    employer_signer_name = db.Column(db.String(150), nullable=True)
    employer_signer_position = db.Column(db.String(100), nullable=True)
    disnaker_registered_at = db.Column(db.Date, nullable=True)
    disnaker_reference = db.Column(db.String(100), nullable=True)
    ended_at = db.Column(db.Date, nullable=True)
    end_reason = db.Column(db.String(40), nullable=True)
    end_compensation_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    employee = db.relationship("Employee", lazy=True, backref=db.backref("contracts", lazy=True))

    __table_args__ = (
        db.CheckConstraint("contract_type IN ('PKWT', 'PKWTT')", name="ck_employment_contracts_type"),
        db.CheckConstraint(
            "status IN ('DRAFT', 'MENUNGGU_TTD_PERUSAHAAN', 'AKTIF', 'BERAKHIR', 'BATAL')",
            name="ck_employment_contracts_status",
        ),
        db.CheckConstraint("probation_months >= 0 AND probation_months <= 3", name="ck_employment_contracts_probation"),
        db.CheckConstraint("max_deduction_percent >= 0 AND max_deduction_percent <= 50", name="ck_employment_contracts_max_deduction"),
    )


class EmployeeLeave(BaseModel):
    """Izin keluar lokasi / pulang kampung / cuti / sakit dengan tanggal berangkat & kembali."""

    __tablename__ = "employee_leaves"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    leave_type = db.Column(db.String(20), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    expected_return_date = db.Column(db.Date, nullable=False)
    actual_return_date = db.Column(db.Date, nullable=True)
    reason = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default=LEAVE_SUBMITTED, index=True)
    decided_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    decided_at = db.Column(db.DateTime, nullable=True)
    decision_notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    employee = db.relationship("Employee", lazy=True)

    __table_args__ = (
        db.CheckConstraint(
            "leave_type IN ('IZIN_KELUAR', 'PULANG_KAMPUNG', 'CUTI', 'SAKIT')",
            name="ck_employee_leaves_type",
        ),
        db.CheckConstraint(
            "status IN ('DIAJUKAN', 'DISETUJUI', 'DITOLAK', 'KEMBALI')",
            name="ck_employee_leaves_status",
        ),
        db.CheckConstraint("expected_return_date >= start_date", name="ck_employee_leaves_dates"),
    )


class EmployeeAbsenceCase(BaseModel):
    """Meninggalkan lokasi / tidak masuk tanpa izin (mangkir) sampai kembali atau dikualifikasikan mengundurkan diri."""

    __tablename__ = "employee_absence_cases"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("employment_contracts.id"), nullable=True)
    leave_id = db.Column(db.Integer, db.ForeignKey("employee_leaves.id"), nullable=True)
    start_date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(30), nullable=False, default=CASE_OPEN, index=True)
    summons_1_date = db.Column(db.Date, nullable=True)
    summons_1_number = db.Column(db.String(60), nullable=True)
    summons_2_date = db.Column(db.Date, nullable=True)
    summons_2_number = db.Column(db.String(60), nullable=True)
    returned_date = db.Column(db.Date, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    resolution_notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    employee = db.relationship("Employee", lazy=True)
    contract = db.relationship("EmploymentContract", lazy=True)
    leave = db.relationship("EmployeeLeave", lazy=True)

    __table_args__ = (
        db.CheckConstraint(
            "status IN ('TERBUKA', 'PANGGILAN_1', 'PANGGILAN_2', 'KEMBALI', 'MENGUNDURKAN_DIRI')",
            name="ck_employee_absence_cases_status",
        ),
    )


class EmployeeCharge(BaseModel):
    """Denda tertulis atau ganti rugi yang menjadi piutang karyawan sampai lunas dipotong upah."""

    __tablename__ = "employee_charges"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("employment_contracts.id"), nullable=True)
    charge_type = db.Column(db.String(20), nullable=False)
    source_type = db.Column(db.String(30), nullable=False, default="MANUAL")
    source_id = db.Column(db.Integer, nullable=True)
    clause = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    deducted_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    cancelled_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    status = db.Column(db.String(20), nullable=False, default=CHARGE_PROPOSED, index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    cancelled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    cancelled_at = db.Column(db.DateTime, nullable=True)
    cancel_reason = db.Column(db.Text, nullable=True)
    # Kasbon: cicilan per gaji, kas/bank pencairan, tanda tangan persetujuan potong gaji.
    installment_amount = db.Column(db.Numeric(18, 2), nullable=True)
    cash_account_type = db.Column(db.String(10), nullable=True)
    bank_account_id = db.Column(db.Integer, db.ForeignKey("bank_accounts.id"), nullable=True)
    cash_bank_transaction_id = db.Column(db.Integer, db.ForeignKey("cash_bank_transactions.id"), nullable=True)
    signature_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    disbursed_on = db.Column(db.Date, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    employee = db.relationship("Employee", lazy=True)
    contract = db.relationship("EmploymentContract", lazy=True)

    __table_args__ = (
        db.CheckConstraint("charge_type IN ('DENDA', 'GANTI_RUGI', 'KASBON')", name="ck_employee_charges_type"),
        db.CheckConstraint("status IN ('DIUSULKAN', 'AKTIF', 'LUNAS', 'BATAL')", name="ck_employee_charges_status"),
        db.CheckConstraint("amount > 0", name="ck_employee_charges_amount_positive"),
        db.CheckConstraint(
            "deducted_amount >= 0 AND cancelled_amount >= 0 AND deducted_amount + cancelled_amount <= amount",
            name="ck_employee_charges_settled_within_amount",
        ),
    )


class PayrollDeductionItem(BaseModel):
    """Bagian denda/ganti rugi yang dipotong pada satu baris penggajian."""

    __tablename__ = "payroll_deduction_items"

    payroll_id = db.Column(db.Integer, db.ForeignKey("payrolls.id"), nullable=False, index=True)
    payroll_detail_id = db.Column(db.Integer, db.ForeignKey("payroll_details.id"), nullable=False, index=True)
    charge_id = db.Column(db.Integer, db.ForeignKey("employee_charges.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)

    charge = db.relationship("EmployeeCharge", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("payroll_detail_id", "charge_id", name="uq_payroll_deduction_items_detail_charge"),
        db.CheckConstraint("amount > 0", name="ck_payroll_deduction_items_amount_positive"),
    )


class EmployeeExit(BaseModel):
    """Pengunduran diri / habis kontrak / mangkir / diberhentikan beserta penyelesaian akhirnya."""

    __tablename__ = "employee_exits"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False, index=True)
    contract_id = db.Column(db.Integer, db.ForeignKey("employment_contracts.id"), nullable=True)
    absence_case_id = db.Column(db.Integer, db.ForeignKey("employee_absence_cases.id"), nullable=True)
    exit_type = db.Column(db.String(20), nullable=False)
    reason_code = db.Column(db.String(30), nullable=False)
    reason_notes = db.Column(db.Text, nullable=True)
    notice_date = db.Column(db.Date, nullable=False)
    effective_date = db.Column(db.Date, nullable=False)
    last_work_date = db.Column(db.Date, nullable=False)
    short_notice_days = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    handover_notes = db.Column(db.Text, nullable=True)
    handover_done = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    end_compensation = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    status = db.Column(db.String(20), nullable=False, default=EXIT_SUBMITTED, index=True)
    payroll_detail_id = db.Column(db.Integer, db.ForeignKey("payroll_details.id"), nullable=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)

    employee = db.relationship("Employee", lazy=True)
    contract = db.relationship("EmploymentContract", lazy=True)

    __table_args__ = (
        db.CheckConstraint(
            "exit_type IN ('RESIGN', 'HABIS_KONTRAK', 'MANGKIR', 'DIBERHENTIKAN')",
            name="ck_employee_exits_type",
        ),
        db.CheckConstraint("status IN ('DIAJUKAN', 'DISETUJUI', 'SELESAI', 'BATAL')", name="ck_employee_exits_status"),
        db.CheckConstraint("effective_date >= notice_date", name="ck_employee_exits_dates"),
    )


RECEIPT_DIGITAL = "DIGITAL"
RECEIPT_MANUAL = "MANUAL"


class PayrollReceipt(BaseModel):
    """Kwitansi tanda terima gaji per karyawan per periode (gores di HP atau TTD basah)."""

    __tablename__ = "payroll_receipts"

    payroll_id = db.Column(db.Integer, db.ForeignKey("payrolls.id"), nullable=False, index=True)
    payroll_detail_id = db.Column(db.Integer, db.ForeignKey("payroll_details.id"), nullable=False, unique=True)
    receipt_number = db.Column(db.String(60), nullable=False, unique=True)
    method = db.Column(db.String(20), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    received_by_name = db.Column(db.String(150), nullable=False)
    signature_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    scan_attachment_id = db.Column(db.Integer, db.ForeignKey("digital_attachments.id"), nullable=True)
    signed_at = db.Column(db.DateTime, nullable=False)
    handed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    handed_by_name = db.Column(db.String(150), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    __table_args__ = (
        db.CheckConstraint("method IN ('DIGITAL', 'MANUAL')", name="ck_payroll_receipts_method"),
        db.CheckConstraint("amount >= 0", name="ck_payroll_receipts_amount"),
    )
