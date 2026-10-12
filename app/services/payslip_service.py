"""Slip gaji dan kwitansi tanda terima gaji (keputusan owner 2026-10-11).

- Slip memuat identitas & kontrak, rekap apel bulan itu, pendapatan, potongan
  (prorata, hari tanpa keterangan, tiap denda/ganti rugi beserta dasar pasalnya),
  sisa piutang yang dibawa ke bulan berikutnya, gaji bersih + terbilang, dan kode verifikasi.
- Slip bisa dikirim lewat link WhatsApp; link dibuka dengan PIN 4 angka terakhir NIK.
- Kwitansi: karyawan menggores tanda tangan di HP saat menerima gaji, atau TTD basah
  di kertas lalu admin menandai (boleh lampirkan foto/scan).
Service tidak commit; route membungkus dengan atomic_business_action.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote

from flask import current_app

from app.extensions import db
from app.models.accounting import Account, Journal
from app.models.hr import EmployeeAttendance, PayrollDetail
from app.models.workforce import (
    CHARGE_ACTIVE,
    RECEIPT_DIGITAL,
    RECEIPT_MANUAL,
    EmployeeCharge,
    EmployeeExit,
    PayrollDeductionItem,
    PayrollReceipt,
)
from app.services.employee_charge_service import CHARGE_TYPE_LABELS, charge_remaining
from app.services.workforce_payroll_service import (
    absence_deduction,
    divisor_days,
    pay_rules,
    period_bounds,
    unpaid_days_by_status,
)
from app.services.workforce_service import (
    CONTRACT_TYPE_LABELS,
    WorkforceError,
    active_contract_for,
    latest_signed_contract,
    money,
    signature_file,
)
from app.utils.terbilang import terbilang

RECEIPT_ALLOWED_STATUSES = ("POSTED", "PAID")
MONTHS_ID = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
             "September", "Oktober", "November", "Desember"]


def period_label(payroll) -> str:
    return f"{MONTHS_ID[payroll.period_month]} {payroll.period_year}"


def slip_number(detail: PayrollDetail) -> str:
    return f"SG/{detail.payroll.period_year}{detail.payroll.period_month:02d}/{detail.id:05d}"


def receipt_number(detail: PayrollDetail) -> str:
    return f"KW-GJ/{detail.payroll.period_year}{detail.payroll.period_month:02d}/{detail.id:05d}"


def verification_code(detail: PayrollDetail) -> str:
    """Kode pendek untuk mencocokkan slip cetak dengan data sistem."""
    secret = str(current_app.config.get("SECRET_KEY") or "").encode()
    message = f"{detail.id}|{detail.payroll_id}|{money(detail.final_salary)}|{money(detail.charge_deduction)}".encode()
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()[:12].upper()
    return "-".join(digest[i:i + 4] for i in range(0, 12, 4))


def _payment_info(payroll) -> dict | None:
    journal = Journal.query.filter_by(reference_type="PAYROLL_PAYMENT", reference_id=payroll.id).first()
    if not journal:
        return None
    method = "Transfer bank"
    for line in journal.details:
        if money(line.credit) > 0:
            account = db.session.get(Account, line.account_id)
            if account and account.account_code == "1001":
                method = "Tunai"
            break
    return {"date": journal.journal_date, "method": method, "journal_number": journal.journal_number}


def build_payslip(detail: PayrollDetail) -> dict:
    from app.services.company_settings_service import get_company_settings

    payroll = detail.payroll
    employee = detail.employee
    period_start, period_end = period_bounds(payroll)
    days_in_month = (period_end - period_start).days + 1
    exit_row = EmployeeExit.query.filter_by(payroll_detail_id=detail.id).first()
    work_start = max(period_start, employee.join_date) if employee.join_date else period_start
    work_end = min(period_end, exit_row.last_work_date) if exit_row else period_end
    contract = active_contract_for(employee.id, min(work_end, period_end)) or latest_signed_contract(employee.id)

    attendance = {code: 0 for code in ("HADIR", "IZIN", "SAKIT", "CUTI", "ALPA")}
    if work_end >= work_start:
        rows = EmployeeAttendance.query.filter(
            EmployeeAttendance.employee_id == employee.id,
            EmployeeAttendance.attendance_date >= work_start,
            EmployeeAttendance.attendance_date <= work_end,
        ).all()
        for row in rows:
            attendance[row.status] = attendance.get(row.status, 0) + 1
    recorded_days = sum(attendance.values())
    counted_days = max(0, (work_end - work_start).days + 1)

    base = money(detail.base_salary)
    bonus = money(detail.bonus)
    compensation = money(detail.exit_compensation)
    deduction = money(detail.deduction)
    rules = pay_rules(employee.id, payroll.branch_id, work_end)
    unpaid_by_status = unpaid_days_by_status(employee.id, work_start, work_end, rules["statuses"])
    alpa_days = int(detail.unpaid_absence_days or 0)
    day_divisor = divisor_days(rules["divisor"], days_in_month)
    alpa_amount = min(deduction, absence_deduction(base, alpa_days, day_divisor))
    other_deduction = deduction - alpa_amount

    earnings = [{"label": "Gaji pokok", "note": f"Upah bulanan sesuai kontrak {contract.contract_number}" if contract else "Upah bulanan", "amount": base}]
    if bonus > 0:
        earnings.append({"label": "Bonus / insentif", "note": "", "amount": bonus})
    if compensation > 0:
        earnings.append({"label": "Kompensasi akhir hubungan kerja", "note": "PP 35/2021 (PKWT) / ganti rugi dari perusahaan", "amount": compensation})

    deductions = []
    if other_deduction > 0:
        if exit_row:
            note = f"Upah dihitung sampai hari kerja terakhir {exit_row.last_work_date:%d-%m-%Y}"
        elif employee.join_date and employee.join_date > period_start:
            note = f"Mulai kerja {employee.join_date:%d-%m-%Y}, dihitung {counted_days} dari {days_in_month} hari"
        else:
            note = "Penyesuaian upah periode ini"
        deductions.append({"label": "Prorata hari kerja", "note": note, "amount": other_deduction})
    if alpa_amount > 0:
        names = {"IZIN": "izin", "SAKIT": "sakit tanpa surat dokter", "CUTI": "cuti di luar jatah", "ALPA": "tanpa ket."}
        parts = ", ".join(f"{names[code]} {count}" for code, count in unpaid_by_status.items() if count)
        clause = f"Pasal Upah kontrak {rules['contract'].contract_number}" if rules["contract"] else "Aturan Gaji & Potongan"
        deductions.append({
            "label": f"Hari tidak bekerja · {alpa_days} hari ({parts})",
            "note": f"{clause}: upah harian = gaji ÷ {day_divisor} = {money(base / Decimal(day_divisor)):,.0f}".replace(",", "."),
            "amount": alpa_amount,
        })

    charge_lines = []
    for item in PayrollDeductionItem.query.filter_by(payroll_detail_id=detail.id).order_by(PayrollDeductionItem.id.asc()).all():
        charge = item.charge
        charge_lines.append({
            "label": f"{CHARGE_TYPE_LABELS[charge.charge_type]} · {charge.description}",
            "note": charge.clause,
            "amount": money(item.amount),
            "total": money(charge.amount),
        })
    deductions.extend({"label": line["label"], "note": line["note"], "amount": line["amount"]} for line in charge_lines)

    # PPh 21 karyawan (Fase 8)
    pph21_amount = money(getattr(detail, "pph21_amount", 0) or 0)
    pph21_borne_by = getattr(detail, "pph21_borne_by", None)
    ptkp_display = getattr(detail, "ptkp_status", None) or "TK/0"
    pph21_info = None

    if pph21_borne_by == "KARYAWAN":
        if pph21_amount > 0:
            if getattr(detail, "pph21_method", None) == "TAHUNAN":
                p_label = "PPh 21 (perhitungan tahunan)"
            else:
                ter_cat = getattr(detail, "ter_category", "") or "A"
                ter_rt = getattr(detail, "ter_rate", 0) or 0
                p_label = f"PPh 21 (TER kategori {ter_cat}, {ter_rt}%)"
            deductions.append({
                "label": p_label,
                "note": f"Status PTKP {ptkp_display}",
                "amount": pph21_amount,
            })
        elif pph21_amount < 0:
            earnings.append({
                "label": "Pengembalian lebih bayar PPh 21 (perhitungan tahunan)",
                "note": f"Status PTKP {ptkp_display}",
                "amount": abs(pph21_amount),
            })
    elif pph21_borne_by == "PERUSAHAAN" and pph21_amount > 0:
        pph21_info = {
            "label": "PPh 21 ditanggung perusahaan",
            "amount": pph21_amount,
            "ptkp_status": ptkp_display,
            "method": getattr(detail, "pph21_method", None),
            "ter_category": getattr(detail, "ter_category", None),
            "ter_rate": getattr(detail, "ter_rate", None),
        }

    posted = payroll.status in RECEIPT_ALLOWED_STATUSES
    open_charges = EmployeeCharge.query.filter_by(employee_id=employee.id, status=CHARGE_ACTIVE).all()
    outstanding = sum((charge_remaining(c) for c in open_charges), Decimal("0"))
    if not posted:
        outstanding -= sum((line["amount"] for line in charge_lines), Decimal("0"))
    outstanding = max(Decimal("0"), outstanding)

    gross = sum((row["amount"] for row in earnings), Decimal("0"))
    total_deduction = sum((line["amount"] for line in deductions), Decimal("0"))
    net = money(detail.final_salary)
    return {
        "detail": detail,
        "payroll": payroll,
        "employee": employee,
        "company": get_company_settings(payroll.branch_id),
        "contract": contract,
        "contract_label": CONTRACT_TYPE_LABELS.get(contract.contract_type) if contract else None,
        "exit": exit_row,
        "number": slip_number(detail),
        "period": period_label(payroll),
        "period_start": period_start,
        "period_end": period_end,
        "work_start": work_start,
        "work_end": work_end,
        "days_in_month": days_in_month,
        "counted_days": counted_days,
        "attendance": attendance,
        "recorded_days": recorded_days,
        "earnings": earnings,
        "deductions": deductions,
        "charge_lines": charge_lines,
        "gross": gross,
        "total_deduction": total_deduction,
        "net": net,
        "net_words": terbilang(net),
        "outstanding": outstanding,
        "payment": _payment_info(payroll),
        "receipt": PayrollReceipt.query.filter_by(payroll_detail_id=detail.id).first(),
        "pph21_info": pph21_info,
        "is_draft": payroll.status == "DRAFT",
        "verification": verification_code(detail),
    }


# ---------------------------------------------------------------- link WhatsApp


def ensure_slip_token(detail: PayrollDetail) -> str:
    if detail.payroll.status == "DRAFT":
        raise WorkforceError("Slip baru bisa dikirim setelah penggajian dikunci.")
    if not detail.slip_token:
        detail.slip_token = secrets.token_urlsafe(24)
    return detail.slip_token


def slip_pin(employee) -> str | None:
    """PIN pembuka slip = 4 angka terakhir NIK (atau No. HP bila NIK kosong)."""
    for raw in (employee.nik, employee.phone):
        digits = re.sub(r"\D", "", raw or "")
        if len(digits) >= 4:
            return digits[-4:]
    return None


def pin_matches(employee, pin: str) -> bool:
    expected = slip_pin(employee)
    return bool(expected) and hmac.compare_digest(expected, re.sub(r"\D", "", pin or ""))


def whatsapp_url(employee, slip_url: str, payroll) -> str | None:
    digits = re.sub(r"\D", "", employee.phone or "")
    if not digits:
        return None
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    pin_source = "NIK" if re.sub(r"\D", "", employee.nik or "") else "No. HP"
    text = (
        f"Halo {employee.full_name}, slip gaji {period_label(payroll)} sudah tersedia: {slip_url}\n"
        f"Buka dengan PIN 4 angka terakhir {pin_source} Anda. Jangan bagikan link ini."
    )
    return f"https://wa.me/{digits}?text={quote(text)}"


def detail_by_token(token: str) -> PayrollDetail | None:
    if not token or len(token) < 20:
        return None
    detail = PayrollDetail.query.filter_by(slip_token=token).first()
    if not detail or detail.payroll.status == "DRAFT":
        return None
    return detail


# ---------------------------------------------------------------- kwitansi


def _check_receipt_allowed(detail: PayrollDetail) -> None:
    if detail.payroll.status not in RECEIPT_ALLOWED_STATUSES:
        raise WorkforceError("Kwitansi baru bisa dibuat setelah hutang gaji dicatat (penggajian terkunci & dijurnal).")
    if PayrollReceipt.query.filter_by(payroll_detail_id=detail.id).first():
        raise WorkforceError("Kwitansi gaji karyawan ini sudah ditandatangani.")
    if money(detail.final_salary) <= 0:
        raise WorkforceError("Gaji bersih karyawan ini Rp 0, tidak ada yang diserahkan sehingga tidak perlu kwitansi.")


def _stage(detail, file_storage, attachment_type, user_id, notes):
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment

    try:
        return stage_digital_attachment(
            file_storage=file_storage,
            module="HR_PAYROLL",
            reference_type="PAYROLL_RECEIPT",
            reference_id=detail.id,
            attachment_type=attachment_type,
            branch_id=detail.payroll.branch_id,
            uploaded_by=user_id,
            notes=notes,
        )
    except AttachmentValidationError as error:
        raise WorkforceError(str(error)) from error


def sign_receipt(detail: PayrollDetail, *, typed_name: str, signature_data: str, user) -> tuple[PayrollReceipt, list]:
    """Karyawan menggores tanda tangan di HP saat menerima gaji."""
    _check_receipt_allowed(detail)
    expected = " ".join(str(detail.employee.full_name or "").lower().split())
    if " ".join(str(typed_name or "").lower().split()) != expected:
        raise WorkforceError("Nama yang diketik harus sama dengan nama karyawan.")
    attachment = _stage(detail, signature_file(signature_data, "ttd_terima_gaji"), "TTD_TERIMA_GAJI", user.id, "Tanda tangan terima gaji")
    db.session.flush()
    receipt = PayrollReceipt(
        payroll_id=detail.payroll_id,
        payroll_detail_id=detail.id,
        receipt_number=receipt_number(detail),
        method=RECEIPT_DIGITAL,
        amount=money(detail.final_salary),
        received_by_name=detail.employee.full_name,
        signature_attachment_id=attachment.id,
        signed_at=datetime.utcnow(),
        handed_by=user.id,
        handed_by_name=user.full_name,
    )
    db.session.add(receipt)
    db.session.flush()
    return receipt, [attachment]


def record_manual_receipt(detail: PayrollDetail, *, user, scan_file=None, notes: str | None = None) -> tuple[PayrollReceipt, list]:
    """Kwitansi kertas sudah ditandatangani basah; boleh lampirkan foto/scan."""
    _check_receipt_allowed(detail)
    attachments = []
    scan_id = None
    if scan_file is not None and getattr(scan_file, "filename", ""):
        scan = _stage(detail, scan_file, "SCAN_KWITANSI_GAJI", user.id, "Scan kwitansi gaji TTD basah")
        db.session.flush()
        attachments.append(scan)
        scan_id = scan.id
    receipt = PayrollReceipt(
        payroll_id=detail.payroll_id,
        payroll_detail_id=detail.id,
        receipt_number=receipt_number(detail),
        method=RECEIPT_MANUAL,
        amount=money(detail.final_salary),
        received_by_name=detail.employee.full_name,
        scan_attachment_id=scan_id,
        signed_at=datetime.utcnow(),
        handed_by=user.id,
        handed_by_name=user.full_name,
        notes=(notes or "").strip() or None,
    )
    db.session.add(receipt)
    db.session.flush()
    return receipt, attachments


def build_receipt(detail: PayrollDetail) -> dict:
    from app.services.company_settings_service import get_company_settings
    from app.services.workforce_service import attachment_data_url

    receipt = PayrollReceipt.query.filter_by(payroll_detail_id=detail.id).first()
    amount = money(receipt.amount) if receipt else money(detail.final_salary)
    return {
        "detail": detail,
        "payroll": detail.payroll,
        "employee": detail.employee,
        "company": get_company_settings(detail.payroll.branch_id),
        "receipt": receipt,
        "number": receipt_number(detail),
        "slip_number": slip_number(detail),
        "period": period_label(detail.payroll),
        "amount": amount,
        "amount_words": terbilang(amount),
        "payment": _payment_info(detail.payroll),
        "signature": attachment_data_url(receipt.signature_attachment_id) if receipt else None,
        "verification": verification_code(detail),
    }
