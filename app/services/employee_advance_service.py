"""Kasbon karyawan (keputusan owner 2026-10-12).

Alur:
1. Admin mengajukan kasbon; karyawan mengetik nama + menggores tanda tangan persetujuan
   bahwa kasbon dicicil dari gaji (PP 36/2021: potongan utang wajib ada persetujuan tertulis).
2. OWNER menyetujui (boleh menurunkan nominal): uang keluar dari kas/bank → buku kas +
   jurnal Dr 1005 Piutang Karyawan / Cr Kas-Bank.
3. Cicilan dipotong otomatis di penggajian (ikut batas 50% upah), sisa terakhir terpotong saat keluar.
4. Pelunasan tunai: Dr Kas-Bank / Cr 1005. Hapus sisa (owner): Dr 5013 / Cr 1005.
Maksimal kasbon berjalan = 1x gaji bulanan. Service tidak commit.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.extensions import db
from app.models.workforce import CHARGE_ACTIVE, CHARGE_PAID, CHARGE_PROPOSED, EmployeeCharge
from app.services.workforce_service import WorkforceError, latest_signed_contract, money, signature_file
from app.utils.clock import today_wib

ADVANCE = "KASBON"
DISBURSE_JOURNAL = "EMPLOYEE_ADVANCE"
REPAY_JOURNAL = "EMPLOYEE_ADVANCE_REPAY"


def advance_number(charge: EmployeeCharge) -> str:
    return f"KSB/{(charge.created_at or datetime.utcnow()):%Y%m}/{charge.id:05d}"


def monthly_salary(employee) -> Decimal:
    from app.services.hr_service import get_latest_salary

    contract = latest_signed_contract(employee.id)
    if contract and contract.status == "AKTIF":
        return money(contract.monthly_salary)
    return money(get_latest_salary(employee.id))


def open_advance_total(employee_id: int) -> Decimal:
    """Kasbon yang masih berjalan atau menunggu persetujuan."""
    from app.services.employee_charge_service import charge_remaining

    rows = EmployeeCharge.query.filter(
        EmployeeCharge.employee_id == employee_id,
        EmployeeCharge.charge_type == ADVANCE,
        EmployeeCharge.status.in_((CHARGE_PROPOSED, CHARGE_ACTIVE)),
    ).all()
    return sum((money(r.amount) if r.status == CHARGE_PROPOSED else charge_remaining(r) for r in rows), Decimal("0"))


def _cash_bank(branch_id, account_type, bank_account_id):
    from app.services.cash_bank_service import normalize_cash_bank_account

    try:
        account_type, bank_account_id, _ = normalize_cash_bank_account(account_type, bank_account_id or None, branch_id=branch_id)
    except Exception as error:  # pesan validasi kas/bank untuk pengguna
        raise WorkforceError(str(error)) from error
    return account_type, bank_account_id


def request_advance(employee, *, amount, installment, reason, account_type, bank_account_id, typed_name, signature_data, user):
    """Pengajuan kasbon + persetujuan tertulis karyawan. Mengembalikan (kasbon, lampiran)."""
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment

    if employee.status != "ACTIVE" or employee.employee_type != "KARYAWAN":
        raise WorkforceError("Kasbon hanya untuk karyawan aktif (bukan tenaga cadangan).")
    amount = money(amount)
    installment = money(installment)
    reason = (reason or "").strip()
    if amount <= 0:
        raise WorkforceError("Nominal kasbon harus lebih dari 0.")
    if installment <= 0 or installment > amount:
        raise WorkforceError("Cicilan per gaji harus lebih dari 0 dan tidak melebihi nominal kasbon.")
    if not reason:
        raise WorkforceError("Keperluan kasbon wajib diisi.")
    salary = monthly_salary(employee)
    if salary <= 0:
        raise WorkforceError("Gaji karyawan belum diatur, kasbon tidak bisa dihitung batasnya.")
    limit = salary - open_advance_total(employee.id)
    if amount > limit:
        raise WorkforceError(f"Kasbon melebihi batas 1x gaji. Sisa batas kasbon karyawan ini Rp {limit:,.0f}.".replace(",", "."))
    expected = " ".join(str(employee.full_name or "").lower().split())
    if " ".join(str(typed_name or "").lower().split()) != expected:
        raise WorkforceError("Karyawan harus mengetik namanya persis sebagai persetujuan potong gaji.")
    account_type, bank_account_id = _cash_bank(employee.branch_id, account_type, bank_account_id)

    charge = EmployeeCharge(
        branch_id=employee.branch_id,
        employee_id=employee.id,
        contract_id=getattr(latest_signed_contract(employee.id), "id", None),
        charge_type=ADVANCE,
        source_type="MANUAL",
        clause="Surat pernyataan kasbon (persetujuan potong gaji, PP 36/2021)",
        description=reason,
        amount=amount,
        installment_amount=installment,
        cash_account_type=account_type,
        bank_account_id=bank_account_id,
        status=CHARGE_PROPOSED,
        created_by=user.id,
    )
    db.session.add(charge)
    db.session.flush()
    charge.clause = f"Surat pernyataan kasbon {advance_number(charge)} (persetujuan potong gaji, PP 36/2021)"
    try:
        attachment = stage_digital_attachment(
            file_storage=signature_file(signature_data, "ttd_kasbon"),
            module="HR_PAYROLL",
            reference_type="EMPLOYEE_ADVANCE",
            reference_id=charge.id,
            attachment_type="TTD_KASBON",
            branch_id=employee.branch_id,
            uploaded_by=user.id,
            notes="Tanda tangan persetujuan kasbon",
        )
    except AttachmentValidationError as error:
        raise WorkforceError(str(error)) from error
    db.session.flush()
    charge.signature_attachment_id = attachment.id

    from app.services.notification_service import create_or_update_notification
    from app.services.workforce_service import _safe_url

    create_or_update_notification(
        branch_id=employee.branch_id,
        notification_type="HR_WORKFORCE",
        title=f"Kasbon {employee.full_name} menunggu persetujuan",
        message=f"Rp {amount:,.0f}, dicicil Rp {installment:,.0f}/gaji: {reason[:100]}".replace(",", "."),
        target_role="OWNER",
        priority="WARNING",
        action_url=_safe_url("workforce.advances"),
        generated_key=f"hr-advance-{charge.id}",
        commit=False,
    )
    return charge, [attachment]


def disburse_advance(charge: EmployeeCharge, user) -> None:
    """Dipanggil dari approve_charge: uang keluar dari kas/bank + jurnal."""
    from app.models.finance import BankAccount, CashBankTransaction
    from app.services.cash_bank_service import (
        calculate_account_balance,
        cash_bank_coa_code,
        get_account_label,
        post_cash_bank_journal,
    )

    amount = money(charge.amount)
    if amount > money(monthly_salary(charge.employee)) - (open_advance_total(charge.employee_id) - money(charge.amount)):
        raise WorkforceError("Kasbon melebihi batas 1x gaji karyawan.")
    balance = Decimal(str(calculate_account_balance(charge.branch_id, charge.cash_account_type, charge.bank_account_id)))
    if amount > balance:
        raise WorkforceError(f"Saldo kas/bank tidak cukup. Saldo tersedia Rp {balance:,.0f}.".replace(",", "."))
    today = today_wib()
    bank = db.session.get(BankAccount, charge.bank_account_id) if charge.bank_account_id else None
    ledger = CashBankTransaction(
        branch_id=charge.branch_id,
        transaction_date=today,
        account_type=charge.cash_account_type,
        bank_account_id=charge.bank_account_id,
        transaction_type="OUT",
        amount=float(amount),
        description=f"Kasbon {charge.employee.full_name} {advance_number(charge)} ({get_account_label(charge.cash_account_type, bank)})",
        reference_type=DISBURSE_JOURNAL,
        reference_id=charge.id,
        created_by=user.id,
    )
    db.session.add(ledger)
    db.session.flush()
    charge.cash_bank_transaction_id = ledger.id
    charge.disbursed_on = today
    try:
        post_cash_bank_journal(
            journal_date=today,
            reference_type=DISBURSE_JOURNAL,
            reference_id=charge.id,
            description=f"Kasbon karyawan {charge.employee.full_name} {advance_number(charge)}",
            debit_code="1005",
            credit_code=cash_bank_coa_code(charge.cash_account_type, charge.bank_account_id),
            amount=float(amount),
            created_by=user.id,
        )
    except Exception as error:  # akun COA belum ada -> pesan yang bisa dibaca
        raise WorkforceError(f"Jurnal kasbon gagal dibuat: {error}") from error


def repay_advance_cash(charge: EmployeeCharge, *, amount, account_type, bank_account_id, user):
    """Karyawan melunasi sebagian/seluruh kasbon secara tunai/transfer."""
    from app.models.finance import BankAccount, CashBankTransaction
    from app.services.cash_bank_service import cash_bank_coa_code, get_account_label, post_cash_bank_journal
    from app.services.employee_charge_service import charge_remaining, charge_reserved
    from app.services.workforce_attendance_service import can_approve_leave

    if not can_approve_leave(user):
        raise WorkforceError("Hanya ADMIN/OWNER yang mencatat pelunasan kasbon.")
    if charge.charge_type != ADVANCE or charge.status != CHARGE_ACTIVE:
        raise WorkforceError("Hanya kasbon yang sedang berjalan yang bisa dilunasi.")
    amount = money(amount)
    available = charge_remaining(charge) - charge_reserved(charge)
    if amount <= 0 or amount > available:
        raise WorkforceError(f"Nominal pelunasan harus 1 s/d Rp {available:,.0f} (sisa di luar cicilan penggajian yang belum dijurnal).".replace(",", "."))
    account_type, bank_account_id = _cash_bank(charge.branch_id, account_type, bank_account_id)
    today = today_wib()
    bank = db.session.get(BankAccount, bank_account_id) if bank_account_id else None
    ledger = CashBankTransaction(
        branch_id=charge.branch_id,
        transaction_date=today,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type="IN",
        amount=float(amount),
        description=f"Pelunasan kasbon {charge.employee.full_name} {advance_number(charge)} ({get_account_label(account_type, bank)})",
        reference_type=REPAY_JOURNAL,
        reference_id=charge.id,
        created_by=user.id,
    )
    db.session.add(ledger)
    db.session.flush()
    try:
        post_cash_bank_journal(
            journal_date=today,
            reference_type=REPAY_JOURNAL,
            reference_id=ledger.id,
            description=f"Pelunasan kasbon {charge.employee.full_name} {advance_number(charge)}",
            debit_code=cash_bank_coa_code(account_type, bank_account_id),
            credit_code="1005",
            amount=float(amount),
            created_by=user.id,
        )
    except Exception as error:  # akun COA belum ada -> pesan yang bisa dibaca
        raise WorkforceError(f"Jurnal pelunasan kasbon gagal dibuat: {error}") from error
    charge.deducted_amount = money(charge.deducted_amount) + amount
    if charge_remaining(charge) <= 0:
        charge.status = CHARGE_PAID
    return ledger
