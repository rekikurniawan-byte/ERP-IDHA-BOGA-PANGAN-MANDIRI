from app.extensions import db
from app.models.base import BaseModel


class EmployeeAttendance(BaseModel):
    __tablename__ = "employee_attendance"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    attendance_date = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    # Sakit dengan surat keterangan dokter tetap dibayar (UU 13/2003 Ps. 93 ayat 2a).
    medical_note = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    created_by = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("employee_id", "attendance_date", name="uq_employee_attendance_employee_date"),
    )


class EmployeeAssignment(BaseModel):
    __tablename__ = "employee_assignments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    assignment_date = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    assignment_area = db.Column(db.String(50), nullable=False)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)


class Payroll(BaseModel):
    __tablename__ = "payrolls"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    period_month = db.Column(db.Integer, nullable=False)
    period_year = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="DRAFT")
    created_by = db.Column(db.Integer, nullable=False)

    details = db.relationship("PayrollDetail", backref="payroll", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "period_month", "period_year", name="uq_payroll_branch_period"),
    )


class PayrollDetail(BaseModel):
    __tablename__ = "payroll_details"

    payroll_id = db.Column(db.Integer, db.ForeignKey("payrolls.id"), nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    base_salary = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    bonus = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    deduction = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    # Potongan denda/ganti rugi (maks 50% upah per periode, PP 36/2021) dan
    # kompensasi akhir PKWT. final = base + bonus + kompensasi - deduction - charge_deduction.
    charge_deduction = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    exit_compensation = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    unpaid_absence_days = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    final_salary = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    # Snapshot PPh 21 (dihitung modul pajak saat penggajian masih konsep).
    # final = bruto dibayar - pph21 (bila ditanggung KARYAWAN) - charge_deduction.
    # pph21_amount boleh negatif di masa terakhir (lebih potong dikembalikan).
    tax_bruto = db.Column(db.Numeric(18, 2), nullable=True)
    pph21_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    pph21_method = db.Column(db.String(10), nullable=True)  # TER / TAHUNAN
    ter_category = db.Column(db.String(1), nullable=True)  # A / B / C
    ter_rate = db.Column(db.Numeric(8, 4), nullable=True)  # persen
    pph21_borne_by = db.Column(db.String(12), nullable=True)  # KARYAWAN / PERUSAHAAN
    ptkp_status = db.Column(db.String(5), nullable=True)  # status PTKP yang dipakai
    pph21_note = db.Column(db.Text, nullable=True)
    # Kunci rahasia link slip gaji yang dikirim lewat WhatsApp (dibuka dengan PIN NIK).
    slip_token = db.Column(db.String(64), nullable=True, unique=True)

    # SDM2D_PAYROLL_DETAIL_EMPLOYEE_RELATION
    employee = db.relationship("Employee", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("payroll_id", "employee_id", name="uq_payroll_detail_payroll_employee"),
    )


class EmployeeSalaryHistory(BaseModel):
    __tablename__ = "employee_salary_history"

    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    effective_date = db.Column(db.Date, nullable=False)
    salary_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
