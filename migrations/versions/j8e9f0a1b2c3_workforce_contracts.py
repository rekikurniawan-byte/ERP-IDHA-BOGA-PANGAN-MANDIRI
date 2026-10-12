"""Modul Tenaga Kerja: kontrak kerja PKWT/PKWTT, izin, mangkir, denda/ganti rugi, keluar.

Revision ID: j8e9f0a1b2c3
Revises: i7d8e9f0a1b2
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa


revision = "j8e9f0a1b2c3"
down_revision = "i7d8e9f0a1b2"
branch_labels = None
depends_on = None

MONEY_COLUMNS = {
    "employment_contracts": (
        "monthly_salary", "fine_absent_per_day", "fine_leave_site", "fine_late_return_per_day",
        "fine_short_notice", "end_compensation_amount",
    ),
    "employee_charges": ("amount", "deducted_amount", "cancelled_amount"),
    "payroll_deduction_items": ("amount",),
    "employee_exits": ("end_compensation",),
    "payroll_details": ("charge_deduction", "exit_compensation"),
}
QUANTITY_COLUMNS = {}
RATIO_COLUMNS = {}
VERSIONED_TABLES = (
    "employment_contracts", "employee_leaves", "employee_absence_cases",
    "employee_charges", "payroll_deduction_items", "employee_exits",
)


def _base_columns():
    return [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
    ]


def _money(name, nullable=False, default=True):
    if default:
        return sa.Column(name, sa.Numeric(18, 2), nullable=nullable, server_default="0")
    return sa.Column(name, sa.Numeric(18, 2), nullable=nullable)


def upgrade():
    with op.batch_alter_table("employees") as batch:
        batch.add_column(sa.Column("nik", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("address", sa.Text(), nullable=True))
        batch.add_column(sa.Column("position", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("employee_type", sa.String(length=20), nullable=False, server_default="KARYAWAN"))
        batch.add_column(sa.Column("emergency_contact_name", sa.String(length=150), nullable=True))
        batch.add_column(sa.Column("emergency_contact_phone", sa.String(length=30), nullable=True))
        batch.add_column(sa.Column("exit_date", sa.Date(), nullable=True))
        batch.add_column(sa.Column("exit_reason", sa.String(length=40), nullable=True))
        batch.create_check_constraint("ck_employees_employee_type", "employee_type IN ('KARYAWAN', 'CADANGAN')")

    with op.batch_alter_table("payroll_details") as batch:
        batch.add_column(_money("charge_deduction"))
        batch.add_column(_money("exit_compensation"))
        batch.add_column(sa.Column("unpaid_absence_days", sa.Integer(), nullable=False, server_default="0"))

    op.create_table(
        "employment_contracts",
        *_base_columns(),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("contract_number", sa.String(length=60), nullable=False, unique=True),
        sa.Column("contract_type", sa.String(length=10), nullable=False),
        sa.Column("position", sa.String(length=100), nullable=False),
        sa.Column("work_location", sa.String(length=200), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("probation_months", sa.Integer(), nullable=False, server_default="0"),
        _money("monthly_salary"),
        sa.Column("notice_days", sa.Integer(), nullable=False, server_default="30"),
        _money("fine_absent_per_day"),
        _money("fine_leave_site"),
        _money("fine_late_return_per_day"),
        _money("fine_short_notice"),
        sa.Column("max_deduction_percent", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="DRAFT"),
        sa.Column("html_snapshot", sa.Text(), nullable=True),
        sa.Column("employee_signature_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("ktp_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("employee_signed_at", sa.DateTime(), nullable=True),
        sa.Column("employer_signature_attachment_id", sa.Integer(), sa.ForeignKey("digital_attachments.id"), nullable=True),
        sa.Column("employer_signed_at", sa.DateTime(), nullable=True),
        sa.Column("employer_signed_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("employer_signer_name", sa.String(length=150), nullable=True),
        sa.Column("employer_signer_position", sa.String(length=100), nullable=True),
        sa.Column("disnaker_registered_at", sa.Date(), nullable=True),
        sa.Column("disnaker_reference", sa.String(length=100), nullable=True),
        sa.Column("ended_at", sa.Date(), nullable=True),
        sa.Column("end_reason", sa.String(length=40), nullable=True),
        _money("end_compensation_amount"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("contract_type IN ('PKWT', 'PKWTT')", name="ck_employment_contracts_type"),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'MENUNGGU_TTD_PERUSAHAAN', 'AKTIF', 'BERAKHIR', 'BATAL')",
            name="ck_employment_contracts_status",
        ),
        sa.CheckConstraint("probation_months >= 0 AND probation_months <= 3", name="ck_employment_contracts_probation"),
        sa.CheckConstraint("max_deduction_percent >= 0 AND max_deduction_percent <= 50", name="ck_employment_contracts_max_deduction"),
    )
    op.create_index("ix_employment_contracts_branch_id", "employment_contracts", ["branch_id"])
    op.create_index("ix_employment_contracts_employee_id", "employment_contracts", ["employee_id"])
    op.create_index("ix_employment_contracts_status", "employment_contracts", ["status"])

    op.create_table(
        "employee_leaves",
        *_base_columns(),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("leave_type", sa.String(length=20), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("expected_return_date", sa.Date(), nullable=False),
        sa.Column("actual_return_date", sa.Date(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DIAJUKAN"),
        sa.Column("decided_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("decision_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint(
            "leave_type IN ('IZIN_KELUAR', 'PULANG_KAMPUNG', 'CUTI', 'SAKIT')",
            name="ck_employee_leaves_type",
        ),
        sa.CheckConstraint(
            "status IN ('DIAJUKAN', 'DISETUJUI', 'DITOLAK', 'KEMBALI')",
            name="ck_employee_leaves_status",
        ),
        sa.CheckConstraint("expected_return_date >= start_date", name="ck_employee_leaves_dates"),
    )
    op.create_index("ix_employee_leaves_branch_id", "employee_leaves", ["branch_id"])
    op.create_index("ix_employee_leaves_employee_id", "employee_leaves", ["employee_id"])
    op.create_index("ix_employee_leaves_status", "employee_leaves", ["status"])

    op.create_table(
        "employee_absence_cases",
        *_base_columns(),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("employment_contracts.id"), nullable=True),
        sa.Column("leave_id", sa.Integer(), sa.ForeignKey("employee_leaves.id"), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="TERBUKA"),
        sa.Column("summons_1_date", sa.Date(), nullable=True),
        sa.Column("summons_1_number", sa.String(length=60), nullable=True),
        sa.Column("summons_2_date", sa.Date(), nullable=True),
        sa.Column("summons_2_number", sa.String(length=60), nullable=True),
        sa.Column("returned_date", sa.Date(), nullable=True),
        sa.Column("closed_at", sa.DateTime(), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint(
            "status IN ('TERBUKA', 'PANGGILAN_1', 'PANGGILAN_2', 'KEMBALI', 'MENGUNDURKAN_DIRI')",
            name="ck_employee_absence_cases_status",
        ),
    )
    op.create_index("ix_employee_absence_cases_branch_id", "employee_absence_cases", ["branch_id"])
    op.create_index("ix_employee_absence_cases_employee_id", "employee_absence_cases", ["employee_id"])
    op.create_index("ix_employee_absence_cases_status", "employee_absence_cases", ["status"])

    op.create_table(
        "employee_charges",
        *_base_columns(),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("employment_contracts.id"), nullable=True),
        sa.Column("charge_type", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="MANUAL"),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("clause", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        _money("amount", default=False),
        _money("deducted_amount"),
        _money("cancelled_amount"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DIUSULKAN"),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_reason", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint("charge_type IN ('DENDA', 'GANTI_RUGI')", name="ck_employee_charges_type"),
        sa.CheckConstraint("status IN ('DIUSULKAN', 'AKTIF', 'LUNAS', 'BATAL')", name="ck_employee_charges_status"),
        sa.CheckConstraint("amount > 0", name="ck_employee_charges_amount_positive"),
        sa.CheckConstraint(
            "deducted_amount >= 0 AND cancelled_amount >= 0 AND deducted_amount + cancelled_amount <= amount",
            name="ck_employee_charges_settled_within_amount",
        ),
    )
    op.create_index("ix_employee_charges_branch_id", "employee_charges", ["branch_id"])
    op.create_index("ix_employee_charges_employee_id", "employee_charges", ["employee_id"])
    op.create_index("ix_employee_charges_status", "employee_charges", ["status"])

    op.create_table(
        "payroll_deduction_items",
        *_base_columns(),
        sa.Column("payroll_id", sa.Integer(), sa.ForeignKey("payrolls.id"), nullable=False),
        sa.Column("payroll_detail_id", sa.Integer(), sa.ForeignKey("payroll_details.id"), nullable=False),
        sa.Column("charge_id", sa.Integer(), sa.ForeignKey("employee_charges.id"), nullable=False),
        _money("amount", default=False),
        sa.UniqueConstraint("payroll_detail_id", "charge_id", name="uq_payroll_deduction_items_detail_charge"),
        sa.CheckConstraint("amount > 0", name="ck_payroll_deduction_items_amount_positive"),
    )
    op.create_index("ix_payroll_deduction_items_payroll_id", "payroll_deduction_items", ["payroll_id"])
    op.create_index("ix_payroll_deduction_items_payroll_detail_id", "payroll_deduction_items", ["payroll_detail_id"])
    op.create_index("ix_payroll_deduction_items_charge_id", "payroll_deduction_items", ["charge_id"])

    op.create_table(
        "employee_exits",
        *_base_columns(),
        sa.Column("branch_id", sa.Integer(), sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("employee_id", sa.Integer(), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("contract_id", sa.Integer(), sa.ForeignKey("employment_contracts.id"), nullable=True),
        sa.Column("absence_case_id", sa.Integer(), sa.ForeignKey("employee_absence_cases.id"), nullable=True),
        sa.Column("exit_type", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=30), nullable=False),
        sa.Column("reason_notes", sa.Text(), nullable=True),
        sa.Column("notice_date", sa.Date(), nullable=False),
        sa.Column("effective_date", sa.Date(), nullable=False),
        sa.Column("last_work_date", sa.Date(), nullable=False),
        sa.Column("short_notice_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("handover_notes", sa.Text(), nullable=True),
        sa.Column("handover_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        _money("end_compensation"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="DIAJUKAN"),
        sa.Column("payroll_detail_id", sa.Integer(), sa.ForeignKey("payroll_details.id"), nullable=True),
        sa.Column("approved_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.CheckConstraint(
            "exit_type IN ('RESIGN', 'HABIS_KONTRAK', 'MANGKIR', 'DIBERHENTIKAN')",
            name="ck_employee_exits_type",
        ),
        sa.CheckConstraint("status IN ('DIAJUKAN', 'DISETUJUI', 'SELESAI', 'BATAL')", name="ck_employee_exits_status"),
        sa.CheckConstraint("effective_date >= notice_date", name="ck_employee_exits_dates"),
    )
    op.create_index("ix_employee_exits_branch_id", "employee_exits", ["branch_id"])
    op.create_index("ix_employee_exits_employee_id", "employee_exits", ["employee_id"])
    op.create_index("ix_employee_exits_status", "employee_exits", ["status"])


def downgrade():
    for table, columns in (
        ("employee_exits", ("status", "employee_id", "branch_id")),
        ("payroll_deduction_items", ("charge_id", "payroll_detail_id", "payroll_id")),
        ("employee_charges", ("status", "employee_id", "branch_id")),
        ("employee_absence_cases", ("status", "employee_id", "branch_id")),
        ("employee_leaves", ("status", "employee_id", "branch_id")),
        ("employment_contracts", ("status", "employee_id", "branch_id")),
    ):
        for column in columns:
            op.drop_index(f"ix_{table}_{column}", table_name=table)
        op.drop_table(table)

    with op.batch_alter_table("payroll_details") as batch:
        batch.drop_column("unpaid_absence_days")
        batch.drop_column("exit_compensation")
        batch.drop_column("charge_deduction")

    with op.batch_alter_table("employees") as batch:
        batch.drop_constraint("ck_employees_employee_type", type_="check")
        for column in (
            "exit_reason", "exit_date", "emergency_contact_phone", "emergency_contact_name",
            "employee_type", "position", "address", "nik",
        ):
            batch.drop_column(column)
