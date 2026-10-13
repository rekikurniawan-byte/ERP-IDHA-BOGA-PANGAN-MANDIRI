"""Kontrak kerja karyawan (PKWT/PKWTT) dan pengaturan modul Tenaga Kerja.

Alur kontrak (keputusan owner 2026-10-11):
1. Admin membuat konsep kontrak dari angka bawaan Pengaturan Perusahaan.
2. Karyawan membaca, mengetik namanya, menggores tanda tangan di layar HP, dan
   memotret KTP. Saat itu isi surat dibekukan (snapshot) -- perubahan pengaturan
   sesudahnya tidak mengubah surat ini.
3. Owner menandatangani dengan goresan di layar. Kontrak AKTIF.
4. PKWT wajib dicatatkan ke Disnaker paling lambat 3 hari kerja sesudah ditandatangani.

Service tidak pernah commit; route membungkus dengan atomic_business_action.
"""
from __future__ import annotations

import base64
import binascii
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO

from flask import current_app
from werkzeug.datastructures import FileStorage

from app.extensions import db
from app.models.hr import EmployeeSalaryHistory
from app.models.master import Employee
from app.models.workforce import (
    CONTRACT_ACTIVE,
    CONTRACT_CANCELLED,
    CONTRACT_DRAFT,
    CONTRACT_ENDED,
    CONTRACT_PKWT,
    CONTRACT_PKWTT,
    CONTRACT_TYPES,
    CONTRACT_WAITING_EMPLOYER,
    EmploymentContract,
)
from app.utils.clock import today_wib


class WorkforceError(ValueError):
    """Aturan modul tenaga kerja dilanggar; pesannya aman ditampilkan ke pengguna."""


PKWT_MAX_DAYS = 5 * 365 + 1  # PP 35/2021 Pasal 8: PKWT paling lama 5 tahun termasuk perpanjangan.
CONTRACT_MODULE = "HR_CONTRACT"
CONTRACT_REFERENCE_TYPE = "EMPLOYMENT_CONTRACT"
CONTRACT_STATUS_LABELS = {
    CONTRACT_DRAFT: "Menunggu TTD Karyawan",
    CONTRACT_WAITING_EMPLOYER: "Menunggu TTD Perusahaan",
    CONTRACT_ACTIVE: "Aktif",
    CONTRACT_ENDED: "Berakhir",
    CONTRACT_CANCELLED: "Batal",
}
CONTRACT_TYPE_LABELS = {
    CONTRACT_PKWT: "PKWT (waktu tertentu)",
    CONTRACT_PKWTT: "PKWTT (tetap)",
}
EMPLOYEE_TYPE_LABELS = {"KARYAWAN": "Karyawan", "CADANGAN": "Cadangan (harian lepas)"}

_INT_SETTINGS = {
    "notice_days": ("hr.notice_days", 30),
    "max_deduction_percent": ("hr.max_deduction_percent", 50),
    "portions_per_worker": ("hr.portions_per_worker", 60),
    "deemed_resign_days": ("hr.deemed_resign_days", 5),
}
_MONEY_SETTINGS = {
    "fine_absent_per_day": ("hr.fine_absent_per_day", "50000"),
    "fine_leave_site": ("hr.fine_leave_site", "100000"),
    "fine_late_return_per_day": ("hr.fine_late_return_per_day", "50000"),
    "fine_short_notice": ("hr.fine_short_notice", "200000"),
}


def money(value) -> Decimal:
    return Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


UNPAID_STATUS_CHOICES = ("IZIN", "SAKIT", "CUTI", "ALPA")
DIVISOR_CHOICES = {"KALENDER": "Hari kalender bulan itu (28–31)", "30": "Tetap 30 hari", "26": "Tetap 26 hari kerja"}
HR_SETTING_DEFAULTS = {
    "hr.employer_signer_name": "",
    "hr.employer_signer_position": "Direktur",
    "hr.work_location": "",
    "hr.notice_days": "30",
    "hr.fine_absent_per_day": "50000",
    "hr.fine_leave_site": "100000",
    "hr.fine_late_return_per_day": "50000",
    "hr.fine_short_notice": "200000",
    "hr.max_deduction_percent": "50",
    "hr.portions_per_worker": "60",
    "hr.deemed_resign_days": "5",
    "hr.company_regulation_number": "",
    # Keputusan owner 2026-10-11: setiap hari tidak bekerja dipotong, apa pun alasannya.
    "hr.unpaid_statuses": "IZIN,SAKIT,CUTI,ALPA",
    "hr.daily_wage_divisor": "KALENDER",
    "hr.working_hours": "",
    "hr.fine_fund_usage": "",
}


def parse_statuses(raw) -> tuple:
    return tuple(code for code in UNPAID_STATUS_CHOICES if code in str(raw or "").upper().split(","))


def hr_raw_settings(branch_id: int) -> dict:
    from app.models.master import BranchSetting

    raw = dict(HR_SETTING_DEFAULTS)
    rows = BranchSetting.query.filter(
        BranchSetting.branch_id == branch_id,
        BranchSetting.setting_key.like("hr.%"),
    ).order_by(BranchSetting.id.asc()).all()
    for row in rows:
        if row.setting_key in raw and str(row.setting_value or "").strip() != "":
            raw[row.setting_key] = str(row.setting_value).strip()
    return raw


def save_hr_settings(branch_id: int, values: dict) -> None:
    """Disimpan dari halaman Aturan Gaji & Potongan (OWNER). Tidak commit."""
    from app.models.master import BranchSetting

    clean = {}
    for key in HR_SETTING_DEFAULTS:
        if key not in values:
            continue
        clean[key] = str(values.get(key) or "").strip()
    for key in ("hr.notice_days", "hr.max_deduction_percent", "hr.portions_per_worker", "hr.deemed_resign_days",
                "hr.fine_absent_per_day", "hr.fine_leave_site", "hr.fine_late_return_per_day", "hr.fine_short_notice"):
        if key in clean and clean[key] and not clean[key].isdigit():
            raise WorkforceError("Angka di aturan gaji harus bilangan bulat tanpa titik/koma.")
    if "hr.max_deduction_percent" in clean and clean["hr.max_deduction_percent"] and int(clean["hr.max_deduction_percent"]) > 50:
        raise WorkforceError("Batas potongan upah maksimal 50% per periode (PP 36/2021).")
    if "hr.deemed_resign_days" in clean and clean["hr.deemed_resign_days"] and int(clean["hr.deemed_resign_days"]) < 5:
        raise WorkforceError("Mangkir dikualifikasikan mengundurkan diri minimal 5 hari kerja.")
    if "hr.daily_wage_divisor" in clean and clean["hr.daily_wage_divisor"] not in DIVISOR_CHOICES:
        raise WorkforceError("Pembagi upah harian tidak dikenal.")
    if "hr.unpaid_statuses" in clean:
        # Sakit & cuti selalu mengikuti UU: dipotong kecuali surat dokter / jatah cuti tahunan.
        chosen = set(parse_statuses(clean["hr.unpaid_statuses"])) | {"SAKIT", "CUTI"}
        clean["hr.unpaid_statuses"] = ",".join(code for code in UNPAID_STATUS_CHOICES if code in chosen)
    for key, value in clean.items():
        row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=key).order_by(BranchSetting.id.asc()).first()
        if row:
            row.setting_value = value
        else:
            db.session.add(BranchSetting(branch_id=branch_id, setting_key=key, setting_value=value))


def hr_settings(branch_id: int) -> dict:
    """Angka modul tenaga kerja; isian kosong/rusak jatuh ke bawaan."""
    from app.services.company_settings_service import get_company_settings

    company = get_company_settings(branch_id)
    raw = hr_raw_settings(branch_id)
    result = {}
    for name, (key, fallback) in _INT_SETTINGS.items():
        try:
            result[name] = int(str(raw.get(key) or "").strip())
        except ValueError:
            result[name] = fallback
    for name, (key, fallback) in _MONEY_SETTINGS.items():
        try:
            result[name] = money(str(raw.get(key) or "").strip() or fallback)
        except ArithmeticError:
            result[name] = money(fallback)
    result["max_deduction_percent"] = max(0, min(50, result["max_deduction_percent"]))
    result["portions_per_worker"] = max(1, result["portions_per_worker"])
    result["deemed_resign_days"] = max(5, result["deemed_resign_days"])
    result["employer_signer_name"] = (raw.get("hr.employer_signer_name") or company.get("invoice_authorized_name") or "").strip()
    result["employer_signer_position"] = (raw.get("hr.employer_signer_position") or "Direktur").strip()
    result["work_location"] = (raw.get("hr.work_location") or company.get("company_address") or "").strip()
    result["company_regulation_number"] = (raw.get("hr.company_regulation_number") or "").strip()
    result["working_hours"] = (raw.get("hr.working_hours") or "").strip()
    result["fine_fund_usage"] = (raw.get("hr.fine_fund_usage") or "").strip()
    result["unpaid_statuses"] = parse_statuses(raw.get("hr.unpaid_statuses"))
    divisor = raw.get("hr.daily_wage_divisor") or "KALENDER"
    result["daily_wage_divisor"] = divisor if divisor in DIVISOR_CHOICES else "KALENDER"
    result["raw"] = raw
    result["company"] = company
    return result


def add_working_days(start: date, days: int) -> date:
    """Tambah hari kerja Senin-Jumat (dipakai untuk tenggat pencatatan PKWT ke Disnaker)."""
    current = start
    remaining = days
    while remaining > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def get_employee(employee_id: int, branch_id: int) -> Employee:
    employee = Employee.query.filter_by(id=employee_id, branch_id=branch_id).first()
    if not employee:
        raise WorkforceError("Karyawan tidak ditemukan.")
    return employee


def get_contract(contract_id: int, branch_id: int) -> EmploymentContract:
    contract = EmploymentContract.query.filter_by(id=contract_id, branch_id=branch_id).first()
    if not contract:
        raise WorkforceError("Kontrak kerja tidak ditemukan.")
    return contract


def contract_last_day(contract: EmploymentContract) -> date | None:
    """Hari terakhir kontrak berlaku: tanggal diakhiri lebih dulu, lalu tanggal selesai PKWT."""
    days = [d for d in (contract.ended_at, contract.end_date) if d]
    return min(days) if days else None


def contract_in_force(contract: EmploymentContract, on_date: date | None = None) -> bool:
    on_date = on_date or today_wib()
    if contract.status != CONTRACT_ACTIVE or contract.start_date > on_date:
        return False
    last_day = contract_last_day(contract)
    return last_day is None or on_date <= last_day


def active_contract_for(employee_id: int, on_date: date | None = None) -> EmploymentContract | None:
    on_date = on_date or today_wib()
    contracts = (
        EmploymentContract.query
        .filter_by(employee_id=employee_id, status=CONTRACT_ACTIVE)
        .order_by(EmploymentContract.start_date.desc())
        .all()
    )
    return next((contract for contract in contracts if contract_in_force(contract, on_date)), None)


def latest_signed_contract(employee_id: int) -> EmploymentContract | None:
    return (
        EmploymentContract.query
        .filter(
            EmploymentContract.employee_id == employee_id,
            EmploymentContract.status.in_((CONTRACT_ACTIVE, CONTRACT_ENDED)),
        )
        .order_by(EmploymentContract.start_date.desc(), EmploymentContract.id.desc())
        .first()
    )


def _next_contract_number(branch_id: int, contract_type: str, start_date: date) -> str:
    prefix = f"{contract_type}-{start_date.year}-"
    counter = EmploymentContract.query.filter(EmploymentContract.contract_number.like(f"{prefix}%")).count() + 1
    while True:
        number = f"{prefix}{counter:04d}"
        if not EmploymentContract.query.filter_by(contract_number=number).first():
            return number
        counter += 1


def _pkwt_days_used(employee_id: int, exclude_id: int | None = None) -> int:
    contracts = EmploymentContract.query.filter(
        EmploymentContract.employee_id == employee_id,
        EmploymentContract.contract_type == CONTRACT_PKWT,
        EmploymentContract.status.in_((CONTRACT_DRAFT, CONTRACT_WAITING_EMPLOYER, CONTRACT_ACTIVE, CONTRACT_ENDED)),
    ).all()
    total = 0
    for contract in contracts:
        if exclude_id and contract.id == exclude_id:
            continue
        last_day = contract_last_day(contract) or contract.start_date
        total += (last_day - contract.start_date).days + 1
    return total


@dataclass
class ContractInput:
    contract_type: str
    position: str
    start_date: date
    end_date: date | None
    probation_months: int
    monthly_salary: Decimal
    work_location: str | None = None
    notes: str | None = None
    notice_days: int | None = None
    fine_absent_per_day: Decimal | None = None
    fine_leave_site: Decimal | None = None
    fine_late_return_per_day: Decimal | None = None
    fine_short_notice: Decimal | None = None


def create_contract(employee: Employee, data: ContractInput, created_by: int) -> EmploymentContract:
    if employee.status != "ACTIVE":
        raise WorkforceError("Karyawan nonaktif tidak bisa dibuatkan kontrak.")
    contract_type = str(data.contract_type or "").upper()
    if contract_type not in CONTRACT_TYPES:
        raise WorkforceError("Jenis kontrak harus PKWT atau PKWTT.")
    position = (data.position or "").strip()
    if not position:
        raise WorkforceError("Jabatan wajib diisi.")
    salary = money(data.monthly_salary)
    if salary <= 0:
        raise WorkforceError("Upah per bulan wajib lebih dari 0.")

    probation = int(data.probation_months or 0)
    end_date = data.end_date
    if contract_type == CONTRACT_PKWT:
        if not end_date or end_date <= data.start_date:
            raise WorkforceError("PKWT wajib punya tanggal selesai setelah tanggal mulai.")
        if probation:
            raise WorkforceError("PKWT tidak boleh memakai masa percobaan (UU 13/2003 Pasal 58).")
        new_days = (end_date - data.start_date).days + 1
        if _pkwt_days_used(employee.id) + new_days > PKWT_MAX_DAYS:
            raise WorkforceError("Total PKWT karyawan ini melebihi 5 tahun (PP 35/2021). Gunakan PKWTT.")
    else:
        end_date = None
        if not 0 <= probation <= 3:
            raise WorkforceError("Masa percobaan PKWTT paling lama 3 bulan.")

    pending = EmploymentContract.query.filter(
        EmploymentContract.employee_id == employee.id,
        EmploymentContract.status.in_((CONTRACT_DRAFT, CONTRACT_WAITING_EMPLOYER)),
    ).first()
    if pending:
        raise WorkforceError(f"Masih ada kontrak {pending.contract_number} yang belum selesai ditandatangani.")

    current = active_contract_for(employee.id, data.start_date)
    if current:
        raise WorkforceError(
            f"Kontrak {current.contract_number} masih berlaku pada tanggal mulai. "
            "Kontrak baru harus mulai setelah kontrak lama berakhir."
        )

    settings = hr_settings(employee.branch_id)

    def _pick_money(value, key):
        return money(value) if value is not None else settings[key]

    notice_days = data.notice_days if data.notice_days is not None else settings["notice_days"]
    if notice_days < 0:
        raise WorkforceError("Masa pemberitahuan resign tidak boleh negatif.")
    fines = {
        key: _pick_money(getattr(data, key), key)
        for key in ("fine_absent_per_day", "fine_leave_site", "fine_late_return_per_day", "fine_short_notice")
    }
    if any(value < 0 for value in fines.values()):
        raise WorkforceError("Nominal denda tidak boleh negatif.")

    contract = EmploymentContract(
        branch_id=employee.branch_id,
        employee_id=employee.id,
        contract_number=_next_contract_number(employee.branch_id, contract_type, data.start_date),
        contract_type=contract_type,
        position=position,
        work_location=(data.work_location or settings["work_location"] or None),
        start_date=data.start_date,
        end_date=end_date,
        probation_months=probation,
        monthly_salary=salary,
        notice_days=notice_days,
        max_deduction_percent=settings["max_deduction_percent"],
        unpaid_statuses=",".join(settings["unpaid_statuses"]),
        daily_wage_divisor=settings["daily_wage_divisor"],
        status=CONTRACT_DRAFT,
        notes=(data.notes or "").strip() or None,
        created_by=created_by,
        **fines,
    )
    db.session.add(contract)
    db.session.flush()
    return contract


def cancel_contract(contract: EmploymentContract) -> EmploymentContract:
    if contract.status not in (CONTRACT_DRAFT, CONTRACT_WAITING_EMPLOYER):
        raise WorkforceError("Hanya kontrak yang belum aktif yang bisa dibatalkan.")
    contract.status = CONTRACT_CANCELLED
    return contract


def contract_document_context(contract: EmploymentContract) -> dict:
    settings = hr_settings(contract.branch_id)
    company = settings["company"]
    duration_months = None
    if contract.end_date:
        duration_months = round(((contract.end_date - contract.start_date).days + 1) / 30.4375, 1)
    return {
        "contract": contract,
        "employee": contract.employee,
        "company": company,
        "settings": settings,
        "type_label": CONTRACT_TYPE_LABELS.get(contract.contract_type, contract.contract_type),
        "duration_months": duration_months,
        "signer_name": contract.employer_signer_name or settings["employer_signer_name"] or company.get("company_name"),
        "signer_position": contract.employer_signer_position or settings["employer_signer_position"],
    }


def render_contract_body(contract: EmploymentContract) -> str:
    # Tanpa context processor: isi surat hanya bergantung pada data kontrak, bukan pada siapa yang membuka.
    template = current_app.jinja_env.get_template("workforce/contract_document.html")
    return template.render(**contract_document_context(contract))


def contract_body_html(contract: EmploymentContract) -> str:
    """Isi surat: snapshot bila sudah ditandatangani karyawan, pratinjau bila masih konsep."""
    return contract.html_snapshot or render_contract_body(contract)


def signature_file(data_url: str | None, label: str) -> FileStorage:
    """Ubah goresan kanvas (data URL PNG) menjadi file yang bisa disimpan sebagai lampiran."""
    prefix = "data:image/png;base64,"
    if not data_url or not data_url.startswith(prefix):
        raise WorkforceError("Tanda tangan belum digores.")
    try:
        raw = base64.b64decode(data_url[len(prefix):], validate=True)
    except (binascii.Error, ValueError) as error:
        raise WorkforceError("Data tanda tangan rusak. Gores ulang.") from error
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        raise WorkforceError("Data tanda tangan bukan gambar PNG.")
    if len(raw) < 600:
        raise WorkforceError("Tanda tangan terlalu pendek. Gores ulang dengan jelas.")
    if len(raw) > 500_000:
        raise WorkforceError("Gambar tanda tangan terlalu besar.")
    return FileStorage(stream=BytesIO(raw), filename=f"{label}.png", content_type="image/png")


def _stage(contract, file_storage, attachment_type, uploaded_by, notes):
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment

    try:
        return stage_digital_attachment(
            file_storage=file_storage,
            module=CONTRACT_MODULE,
            reference_type=CONTRACT_REFERENCE_TYPE,
            reference_id=contract.id,
            attachment_type=attachment_type,
            branch_id=contract.branch_id,
            uploaded_by=uploaded_by,
            notes=notes,
        )
    except AttachmentValidationError as error:
        raise WorkforceError(str(error)) from error


def sign_contract_employee(
    contract: EmploymentContract,
    *,
    typed_name: str,
    agreed: bool,
    signature_data: str,
    ktp_file: FileStorage | None,
    user_id: int,
) -> list:
    """Karyawan menandatangani. Mengembalikan lampiran yang dibuat (untuk dibersihkan bila rollback)."""
    if contract.status != CONTRACT_DRAFT:
        raise WorkforceError("Kontrak ini tidak sedang menunggu tanda tangan karyawan.")
    if not agreed:
        raise WorkforceError("Karyawan wajib mencentang pernyataan sudah membaca dan menyetujui isi kontrak.")
    expected = " ".join(str(contract.employee.full_name or "").lower().split())
    if " ".join(str(typed_name or "").lower().split()) != expected:
        raise WorkforceError("Nama yang diketik harus sama dengan nama karyawan di kontrak.")
    if not ktp_file or not getattr(ktp_file, "filename", ""):
        raise WorkforceError("Foto KTP karyawan wajib diunggah.")
    if not str(ktp_file.mimetype or "").startswith("image/"):
        raise WorkforceError("Foto KTP harus berupa gambar (JPG/PNG/WEBP).")

    signature = _stage(contract, signature_file(signature_data, "ttd_karyawan"), "TTD_KARYAWAN", user_id, "Tanda tangan karyawan")
    ktp = _stage(contract, ktp_file, "KTP", user_id, "Foto KTP karyawan")
    db.session.flush()

    # Isi surat dibekukan sekarang: angka denda, upah, dan pasal yang disetujui karyawan.
    contract.html_snapshot = render_contract_body(contract)
    contract.employee_signature_attachment_id = signature.id
    contract.ktp_attachment_id = ktp.id
    contract.employee_signed_at = datetime.utcnow()
    contract.status = CONTRACT_WAITING_EMPLOYER
    return [signature, ktp]


def sign_contract_employer(contract: EmploymentContract, *, signature_data: str, user) -> list:
    if contract.status != CONTRACT_WAITING_EMPLOYER:
        raise WorkforceError("Kontrak harus sudah ditandatangani karyawan lebih dulu.")
    if str(getattr(user, "role", "")).upper() != "OWNER":
        raise WorkforceError("Hanya OWNER yang menandatangani kontrak atas nama perusahaan.")

    settings = hr_settings(contract.branch_id)
    signature = _stage(contract, signature_file(signature_data, "ttd_perusahaan"), "TTD_PERUSAHAAN", user.id, "Tanda tangan perusahaan")
    db.session.flush()

    contract.employer_signature_attachment_id = signature.id
    contract.employer_signed_at = datetime.utcnow()
    contract.employer_signed_by = user.id
    contract.employer_signer_name = settings["employer_signer_name"] or user.full_name
    contract.employer_signer_position = settings["employer_signer_position"]
    contract.status = CONTRACT_ACTIVE
    _apply_contract_to_employee(contract)
    _notify_disnaker_due(contract)
    return [signature]


def _apply_contract_to_employee(contract: EmploymentContract) -> None:
    employee = contract.employee
    employee.position = contract.position
    if not employee.join_date or employee.join_date > contract.start_date:
        employee.join_date = contract.start_date
    latest = (
        EmployeeSalaryHistory.query
        .filter(
            EmployeeSalaryHistory.employee_id == employee.id,
            EmployeeSalaryHistory.effective_date <= contract.start_date,
        )
        .order_by(EmployeeSalaryHistory.effective_date.desc(), EmployeeSalaryHistory.id.desc())
        .first()
    )
    if not latest or money(latest.salary_amount) != money(contract.monthly_salary):
        db.session.add(EmployeeSalaryHistory(
            employee_id=employee.id,
            effective_date=contract.start_date,
            salary_amount=money(contract.monthly_salary),
            notes=f"Sesuai kontrak {contract.contract_number}",
        ))


def disnaker_due_date(contract: EmploymentContract) -> date | None:
    if contract.contract_type != CONTRACT_PKWT or not contract.employer_signed_at:
        return None
    signed_day = (contract.employer_signed_at + timedelta(hours=7)).date()
    return add_working_days(signed_day, 3)


def _notify_disnaker_due(contract: EmploymentContract) -> None:
    if contract.contract_type != CONTRACT_PKWT:
        return
    from app.services.notification_service import create_or_update_notification

    due = disnaker_due_date(contract)
    create_or_update_notification(
        branch_id=contract.branch_id,
        notification_type="HR_PKWT_DISNAKER",
        title="Catatkan PKWT ke Disnaker",
        message=(
            f"Kontrak {contract.contract_number} ({contract.employee.full_name}) sudah ditandatangani. "
            f"Catatkan ke Disnaker paling lambat {due:%d-%m-%Y} (3 hari kerja)."
        ),
        target_role="OWNER",
        priority="HIGH",
        reference_type=CONTRACT_REFERENCE_TYPE,
        reference_id=contract.id,
        action_url=_safe_url("workforce.contract_detail", contract_id=contract.id),
        due_date=due,
        generated_key=f"hr-disnaker-{contract.id}",
        commit=False,
    )


def record_disnaker(contract: EmploymentContract, *, registered_at: date, reference: str) -> EmploymentContract:
    if contract.contract_type != CONTRACT_PKWT:
        raise WorkforceError("Pencatatan Disnaker hanya untuk PKWT.")
    if contract.status not in (CONTRACT_ACTIVE, CONTRACT_ENDED):
        raise WorkforceError("Kontrak belum aktif.")
    reference = (reference or "").strip()
    if not reference:
        raise WorkforceError("Nomor/bukti pencatatan Disnaker wajib diisi.")
    if registered_at > today_wib():
        raise WorkforceError("Tanggal pencatatan tidak boleh di masa depan.")
    contract.disnaker_registered_at = registered_at
    contract.disnaker_reference = reference[:100]
    return contract


def _safe_url(endpoint: str, **kwargs) -> str | None:
    from flask import url_for

    try:
        return url_for(endpoint, **kwargs)
    except RuntimeError:
        return None


def contract_alerts(branch_id: int, today: date | None = None) -> dict:
    """Daftar yang perlu tindakan: tanpa kontrak, kontrak hampir habis, PKWT belum dicatat."""
    today = today or today_wib()
    employees = (
        Employee.query
        .filter_by(branch_id=branch_id, status="ACTIVE", employee_type="KARYAWAN")
        .order_by(Employee.full_name.asc())
        .all()
    )
    contracts = EmploymentContract.query.filter(
        EmploymentContract.branch_id == branch_id,
        EmploymentContract.status.in_((CONTRACT_DRAFT, CONTRACT_WAITING_EMPLOYER, CONTRACT_ACTIVE)),
    ).all()
    by_employee: dict[int, list] = {}
    for contract in contracts:
        by_employee.setdefault(contract.employee_id, []).append(contract)

    without_contract = []
    for employee in employees:
        rows = by_employee.get(employee.id, [])
        if not any(contract_in_force(c, today) for c in rows):
            pending = next((c for c in rows if c.status in (CONTRACT_DRAFT, CONTRACT_WAITING_EMPLOYER)), None)
            without_contract.append({"employee": employee, "pending": pending})

    ending_soon, expired, disnaker = [], [], []
    for contract in contracts:
        if contract.status != CONTRACT_ACTIVE:
            continue
        last_day = contract_last_day(contract)
        if last_day and last_day < today and contract.employee.status == "ACTIVE":
            expired.append(contract)
        elif last_day and (last_day - today).days <= 30:
            ending_soon.append({"contract": contract, "days_left": (last_day - today).days})
        if contract.contract_type == CONTRACT_PKWT and not contract.disnaker_registered_at:
            due = disnaker_due_date(contract)
            disnaker.append({"contract": contract, "due": due, "overdue": bool(due and due < today)})

    pending_employer = [c for c in contracts if c.status == CONTRACT_WAITING_EMPLOYER]
    return {
        "without_contract": without_contract,
        "ending_soon": sorted(ending_soon, key=lambda row: row["days_left"]),
        "expired": expired,
        "disnaker": disnaker,
        "pending_employer": pending_employer,
        "active_count": len(employees),
        "regulation_required": len(employees) >= 10,
    }


def attachment_data_url(attachment_id: int | None) -> str | None:
    """Gambar tanda tangan sebagai data URL untuk dicetak bersama surat."""
    if not attachment_id:
        return None
    from app.services.digital_attachment_service import get_attachment_file_path, get_attachment_or_none

    attachment = get_attachment_or_none(attachment_id)
    if not attachment:
        return None
    try:
        path = get_attachment_file_path(attachment)
    except FileNotFoundError:
        return None
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{attachment.mime_type or 'image/png'};base64,{encoded}"
