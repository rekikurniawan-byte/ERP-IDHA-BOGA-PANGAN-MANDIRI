"""Denda tertulis & ganti rugi karyawan, jurnalnya, dan potongan upah per periode.

Akuntansi (keputusan owner 2026-10-11):
- Disetujui OWNER  : Dr 1005 Piutang Karyawan / Cr 4004 Pendapatan Lain-lain.
- Dipotong upah    : ikut jurnal penggajian (Dr 5004 bruto / Cr 2003 neto / Cr 1005 potongan).
- Sisa dibatalkan  : Dr 4004 / Cr 1005 sebesar sisa yang belum terpotong.
Potongan seluruhnya maksimal 50% upah per periode (PP 36/2021); sisanya tetap
piutang karyawan dan dipotong lagi di periode berikutnya.
"""
from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from app.extensions import db
from app.models.accounting import Journal, JournalDetail
from app.models.hr import Payroll, PayrollDetail
from app.models.workforce import (
    CHARGE_ACTIVE,
    CHARGE_CANCELLED,
    CHARGE_DAMAGES,
    CHARGE_FINE,
    CHARGE_PAID,
    CHARGE_PROPOSED,
    CONTRACT_PKWT,
    EmployeeCharge,
    PayrollDeductionItem,
)
from app.services.workforce_service import WorkforceError, latest_signed_contract, money
from app.utils.clock import today_wib

RECEIVABLE_ACCOUNT = "1005"
OTHER_INCOME_ACCOUNT = "4004"
CHARGE_JOURNAL = "EMPLOYEE_CHARGE"
CHARGE_CANCEL_JOURNAL = "EMPLOYEE_CHARGE_CANCEL"
UNPOSTED_PAYROLL_STATUSES = ("DRAFT", "FINAL")
WRITE_OFF_ACCOUNT = "5013"  # kasbon yang dihapuskan = beban piutang tak tertagih, bukan pendapatan
CHARGE_TYPE_LABELS = {CHARGE_FINE: "Denda", CHARGE_DAMAGES: "Ganti rugi", "KASBON": "Kasbon"}
CHARGE_STATUS_LABELS = {
    CHARGE_PROPOSED: "Menunggu persetujuan owner",
    CHARGE_ACTIVE: "Berjalan (dipotong upah)",
    CHARGE_PAID: "Lunas",
    CHARGE_CANCELLED: "Dibatalkan",
}


def charge_remaining(charge: EmployeeCharge) -> Decimal:
    return max(Decimal("0"), money(charge.amount) - money(charge.deducted_amount) - money(charge.cancelled_amount))


def charge_reserved(charge: EmployeeCharge, exclude_payroll_id: int | None = None) -> Decimal:
    """Bagian yang sudah dijadwalkan dipotong di penggajian yang belum dijurnal."""
    query = (
        db.session.query(db.func.coalesce(db.func.sum(PayrollDeductionItem.amount), 0))
        .join(Payroll, Payroll.id == PayrollDeductionItem.payroll_id)
        .filter(PayrollDeductionItem.charge_id == charge.id, Payroll.status.in_(UNPOSTED_PAYROLL_STATUSES))
    )
    if exclude_payroll_id:
        query = query.filter(PayrollDeductionItem.payroll_id != exclude_payroll_id)
    return money(query.scalar())


def create_charge(
    *,
    employee,
    charge_type: str,
    amount,
    clause: str,
    description: str,
    created_by: int,
    source_type: str = "MANUAL",
    source_id: int | None = None,
    contract=None,
) -> EmployeeCharge:
    charge_type = str(charge_type or "").upper()
    if charge_type not in (CHARGE_FINE, CHARGE_DAMAGES):
        raise WorkforceError("Jenis tagihan harus Denda atau Ganti rugi.")
    amount = money(amount)
    if amount <= 0:
        raise WorkforceError("Nominal denda/ganti rugi harus lebih dari 0.")
    clause = (clause or "").strip()
    description = (description or "").strip()
    if not clause:
        raise WorkforceError("Dasar pasal kontrak wajib diisi (denda hanya sah bila tertulis di kontrak).")
    if not description:
        raise WorkforceError("Uraian kejadian wajib diisi.")

    contract = contract or latest_signed_contract(employee.id)
    if not contract:
        raise WorkforceError("Karyawan belum punya kontrak yang ditandatangani, jadi denda/ganti rugi tidak punya dasar tertulis.")
    if charge_type == CHARGE_DAMAGES and contract.contract_type != CONTRACT_PKWT:
        raise WorkforceError("Ganti rugi sisa kontrak (Pasal 62 UU 13/2003) hanya berlaku untuk PKWT.")

    charge = EmployeeCharge(
        branch_id=employee.branch_id,
        employee_id=employee.id,
        contract_id=contract.id,
        charge_type=charge_type,
        source_type=source_type,
        source_id=source_id,
        clause=clause[:200],
        description=description,
        amount=amount,
        status=CHARGE_PROPOSED,
        created_by=created_by,
    )
    db.session.add(charge)
    db.session.flush()
    return charge


def _account(code: str):
    from app.services.accounting_service import get_active_account_by_code

    account = get_active_account_by_code(code)
    if not account:
        raise WorkforceError(f"Akun {code} belum aktif di daftar akun.")
    return account


def _post_journal(reference_type: str, reference_id: int, description: str, lines, created_by: int) -> Journal:
    from app.services.accounting_service import generate_journal_number

    if Journal.query.filter_by(reference_type=reference_type, reference_id=reference_id).first():
        raise WorkforceError("Jurnal untuk transaksi ini sudah ada.")
    journal_date = today_wib()
    journal = Journal(
        journal_number=generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()
    for code, debit, credit in lines:
        db.session.add(JournalDetail(journal_id=journal.id, account_id=_account(code).id, debit=debit, credit=credit))
    return journal


def _require_owner(user) -> None:
    if str(getattr(user, "role", "")).upper() != "OWNER":
        raise WorkforceError("Hanya OWNER yang boleh memutuskan denda/ganti rugi.")


def approve_charge(charge: EmployeeCharge, user, amount=None) -> EmployeeCharge:
    """OWNER menyetujui (boleh menurunkan nominal, tidak boleh menaikkan)."""
    _require_owner(user)
    if charge.status != CHARGE_PROPOSED:
        raise WorkforceError("Tagihan ini tidak sedang menunggu persetujuan.")
    if amount not in (None, ""):
        new_amount = money(amount)
        if new_amount <= 0 or new_amount > money(charge.amount):
            raise WorkforceError("Nominal disetujui harus lebih dari 0 dan tidak melebihi usulan.")
        charge.amount = new_amount
    if charge.charge_type == "KASBON":
        from app.services.employee_advance_service import disburse_advance

        disburse_advance(charge, user)
    charge.status = CHARGE_ACTIVE
    charge.approved_by = user.id
    charge.approved_at = datetime.utcnow()
    if charge.charge_type == "KASBON":
        return charge
    label = CHARGE_TYPE_LABELS[charge.charge_type]
    _post_journal(
        CHARGE_JOURNAL,
        charge.id,
        f"{label} karyawan {charge.employee.full_name}: {charge.description[:120]}",
        [(RECEIVABLE_ACCOUNT, money(charge.amount), 0), (OTHER_INCOME_ACCOUNT, 0, money(charge.amount))],
        user.id,
    )
    return charge


def cancel_charge(charge: EmployeeCharge, user, reason: str) -> EmployeeCharge:
    _require_owner(user)
    reason = (reason or "").strip()
    if not reason:
        raise WorkforceError("Alasan pembatalan wajib diisi.")
    if charge.status in (CHARGE_PAID, CHARGE_CANCELLED):
        raise WorkforceError("Tagihan sudah lunas/batal.")
    if charge.status == CHARGE_ACTIVE:
        if charge_reserved(charge) > 0:
            raise WorkforceError("Tagihan ini sedang dijadwalkan dipotong di penggajian yang belum dijurnal. Hitung ulang penggajian itu dulu.")
        remaining = charge_remaining(charge)
        if remaining > 0:
            # Denda/ganti rugi dibalik dari pendapatan; kasbon yang dihapuskan jadi beban piutang tak tertagih.
            debit_account = WRITE_OFF_ACCOUNT if charge.charge_type == "KASBON" else OTHER_INCOME_ACCOUNT
            verb = "Hapus sisa" if charge.charge_type == "KASBON" else "Batal sisa"
            _post_journal(
                CHARGE_CANCEL_JOURNAL,
                charge.id,
                f"{verb} {CHARGE_TYPE_LABELS[charge.charge_type].lower()} karyawan {charge.employee.full_name}: {reason[:120]}",
                [(debit_account, remaining, 0), (RECEIVABLE_ACCOUNT, 0, remaining)],
                user.id,
            )
        charge.cancelled_amount = money(charge.cancelled_amount) + remaining
    charge.status = CHARGE_CANCELLED
    charge.cancelled_by = user.id
    charge.cancelled_at = datetime.utcnow()
    charge.cancel_reason = reason
    return charge


def open_charges_for(employee_id: int) -> list[EmployeeCharge]:
    return (
        EmployeeCharge.query
        .filter_by(employee_id=employee_id, status=CHARGE_ACTIVE)
        .order_by(EmployeeCharge.approved_at.asc(), EmployeeCharge.id.asc())
        .all()
    )


def outstanding_for(employee_id: int) -> Decimal:
    return sum((charge_remaining(c) for c in open_charges_for(employee_id)), Decimal("0"))


def payroll_detail_gross(detail: PayrollDetail) -> Decimal:
    """Upah yang diterima periode ini sebelum potongan denda/ganti rugi."""
    gross = money(detail.base_salary) + money(detail.bonus) + money(detail.exit_compensation) - money(detail.deduction)
    return max(Decimal("0"), gross)


def payroll_detail_wage_after_tax(detail: PayrollDetail) -> Decimal:
    """Upah yang diterima setelah potongan PPh 21 (bila ditanggung KARYAWAN) sebelum potongan denda/ganti rugi."""
    gross = payroll_detail_gross(detail)
    borne_by = getattr(detail, "pph21_borne_by", None)
    pph21 = money(getattr(detail, "pph21_amount", 0) or 0)
    if borne_by == "KARYAWAN":
        return max(Decimal("0"), gross - pph21)
    return gross


def recalculate_detail(detail: PayrollDetail) -> PayrollDetail:
    # final = bruto dibayar - pph21 (bila KARYAWAN) - charge_deduction
    wage_after_tax = payroll_detail_wage_after_tax(detail)
    detail.final_salary = max(Decimal("0"), wage_after_tax - money(detail.charge_deduction))
    return detail


def allocate_detail_deductions(detail: PayrollDetail, max_percent: int) -> Decimal:
    """Potong denda/ganti rugi tertua dulu sampai batas persen upah periode ini (setelah PPh 21)."""
    PayrollDeductionItem.query.filter_by(payroll_detail_id=detail.id).delete(synchronize_session=False)
    # Batas 50% denda dihitung dari upah setelah PPh 21 (keputusan owner 2026-10-11).
    # Dibulatkan ke bawah supaya potongan tidak pernah melewati batas persen.
    cap = (payroll_detail_wage_after_tax(detail) * Decimal(max_percent) / Decimal(100)).quantize(Decimal("1"), rounding=ROUND_DOWN)
    used = Decimal("0")
    from app.models.workforce import EmployeeExit

    exiting = EmployeeExit.query.filter_by(payroll_detail_id=detail.id).first() is not None
    for charge in open_charges_for(detail.employee_id):
        available = charge_remaining(charge) - charge_reserved(charge, exclude_payroll_id=detail.payroll_id)
        if charge.charge_type == "KASBON" and charge.installment_amount and not exiting:
            # Kasbon dicicil sesuai kesepakatan; saat karyawan keluar dipotong sebanyak batas 50% mengizinkan.
            available = min(available, money(charge.installment_amount))
        take = min(available, cap - used)
        if take <= 0:
            continue
        db.session.add(PayrollDeductionItem(
            payroll_id=detail.payroll_id,
            payroll_detail_id=detail.id,
            charge_id=charge.id,
            amount=take,
        ))
        used += take
        if used >= cap:
            break
    detail.charge_deduction = used
    recalculate_detail(detail)
    return used


def apply_posted_payroll_deductions(payroll: Payroll) -> Decimal:
    """Dipanggil saat jurnal penggajian dibuat: potongan resmi mengurangi piutang karyawan."""
    total = Decimal("0")
    items = PayrollDeductionItem.query.filter_by(payroll_id=payroll.id).all()
    for item in items:
        charge = item.charge
        amount = money(item.amount)
        if charge.status != CHARGE_ACTIVE or amount > charge_remaining(charge):
            raise WorkforceError(
                f"Potongan {CHARGE_TYPE_LABELS[charge.charge_type].lower()} {charge.employee.full_name} sudah berubah. "
                "Hitung ulang penggajian sebelum dijurnal."
            )
        charge.deducted_amount = money(charge.deducted_amount) + amount
        if charge_remaining(charge) <= 0:
            charge.status = CHARGE_PAID
        total += amount
    return total
