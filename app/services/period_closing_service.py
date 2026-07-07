from __future__ import annotations

from calendar import monthrange
from datetime import date
from typing import Any

from sqlalchemy import inspect

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail, PeriodClosing
from app.services.accounting_service import generate_journal_number
from app.services.audit_log_service import record_audit_log

PERIOD_CLOSING_REFERENCE_TYPE = "PERIOD_CLOSING"
RETAINED_EARNINGS_CODE = "3002"
REVENUE_ACCOUNT_TYPE = "REVENUE"
EXPENSE_ACCOUNT_TYPE = "EXPENSE"
POSTED_STATUS = "POSTED"
LOCKED_STATUS = "LOCKED"
CLOSED_STATUSES = {POSTED_STATUS, LOCKED_STATUS}


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _safe_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def is_period_closing_schema_ready() -> bool:
    try:
        inspector = inspect(db.engine)
        return inspector.has_table("period_closings")
    except Exception:
        return False


def get_period_bounds(year: Any, month: Any) -> tuple[int, int, date, date]:
    today = date.today()
    y = _safe_int(year, today.year)
    m = _safe_int(month, today.month)
    if y < 2000 or y > 2100:
        y = today.year
    if m < 1 or m > 12:
        m = today.month
    start = date(y, m, 1)
    end = date(y, m, monthrange(y, m)[1])
    return y, m, start, end


def generate_period_closing_number(closing_date: date) -> str:
    prefix = f"CLS-{closing_date.strftime('%Y%m%d')}"
    counter = PeriodClosing.query.filter(PeriodClosing.closing_number.like(f"{prefix}-%")).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not PeriodClosing.query.filter_by(closing_number=number).first():
            return number
        counter += 1


def _journal_totals_by_id(journal_id: int) -> tuple[float, float]:
    rows = JournalDetail.query.filter_by(journal_id=journal_id).all()
    debit = sum(_safe_float(row.debit) for row in rows)
    credit = sum(_safe_float(row.credit) for row in rows)
    return debit, credit


def _get_unbalanced_journals(start_date: date, end_date: date) -> list[dict[str, Any]]:
    journals = Journal.query.filter(
        Journal.journal_date >= start_date,
        Journal.journal_date <= end_date,
    ).order_by(Journal.journal_date.asc(), Journal.id.asc()).all()
    rows = []
    for journal in journals:
        debit, credit = _journal_totals_by_id(journal.id)
        if round(debit, 2) != round(credit, 2):
            rows.append({
                "journal": journal,
                "debit": debit,
                "credit": credit,
                "difference": round(debit - credit, 2),
            })
    return rows


def _account_period_balances(account_type: str, start_date: date, end_date: date) -> list[dict[str, Any]]:
    """Return natural positive balances for revenue/expense accounts in the period.

    Revenue balance = credit - debit.
    Expense balance = debit - credit.
    Existing PERIOD_CLOSING journals are excluded so preview remains stable.
    """
    accounts = Account.query.filter_by(account_type=account_type, is_active=True).order_by(Account.account_code.asc()).all()
    rows = []
    for account in accounts:
        debit, credit = db.session.query(
            db.func.coalesce(db.func.sum(JournalDetail.debit), 0),
            db.func.coalesce(db.func.sum(JournalDetail.credit), 0),
        ).join(Journal, Journal.id == JournalDetail.journal_id).filter(
            JournalDetail.account_id == account.id,
            Journal.journal_date >= start_date,
            Journal.journal_date <= end_date,
            Journal.reference_type != PERIOD_CLOSING_REFERENCE_TYPE,
        ).first()
        debit = _safe_float(debit)
        credit = _safe_float(credit)
        if account_type == REVENUE_ACCOUNT_TYPE:
            natural_balance = round(credit - debit, 2)
        else:
            natural_balance = round(debit - credit, 2)
        if abs(natural_balance) > 0.004:
            rows.append({
                "account": account,
                "account_code": account.account_code,
                "account_name": account.account_name,
                "debit": debit,
                "credit": credit,
                "balance": natural_balance,
                "is_negative": natural_balance < 0,
            })
    return rows


def get_period_closing_preview(branch_id: int, year: Any, month: Any) -> dict[str, Any]:
    y, m, start_date, end_date = get_period_bounds(year, month)
    schema_ready = is_period_closing_schema_ready()

    existing_closing = None
    closing_rows = []
    if schema_ready:
        existing_closing = PeriodClosing.query.filter_by(branch_id=branch_id, period_year=y, period_month=m).first()
        closing_rows = PeriodClosing.query.filter_by(branch_id=branch_id).order_by(
            PeriodClosing.period_year.desc(), PeriodClosing.period_month.desc(), PeriodClosing.id.desc()
        ).limit(12).all()

    revenue_rows = _account_period_balances(REVENUE_ACCOUNT_TYPE, start_date, end_date)
    expense_rows = _account_period_balances(EXPENSE_ACCOUNT_TYPE, start_date, end_date)
    negative_rows = [row for row in revenue_rows + expense_rows if row.get("is_negative")]

    revenue_total = round(sum(max(_safe_float(row["balance"]), 0) for row in revenue_rows), 2)
    expense_total = round(sum(max(_safe_float(row["balance"]), 0) for row in expense_rows), 2)
    net_income = round(revenue_total - expense_total, 2)
    unbalanced_journals = _get_unbalanced_journals(start_date, end_date)

    retained_account = Account.query.filter_by(account_code=RETAINED_EARNINGS_CODE, is_active=True).first()
    can_post = bool(
        schema_ready
        and retained_account
        and not existing_closing
        and not unbalanced_journals
        and not negative_rows
        and (revenue_total > 0 or expense_total > 0)
    )

    blockers = []
    if not schema_ready:
        blockers.append("Migration period_closings belum dijalankan.")
    if not retained_account:
        blockers.append("Akun 3002 Laba Ditahan belum tersedia atau tidak aktif.")
    if existing_closing:
        blockers.append("Periode ini sudah closing. Duplicate closing ditolak.")
    if unbalanced_journals:
        blockers.append("Masih ada jurnal tidak balance pada periode ini.")
    if negative_rows:
        blockers.append("Ada akun revenue/expense bersaldo negatif. Perlu review sebelum closing.")
    if revenue_total <= 0 and expense_total <= 0:
        blockers.append("Tidak ada saldo pendapatan/beban untuk ditutup pada periode ini.")

    return {
        "schema_ready": schema_ready,
        "year": y,
        "month": m,
        "period_start": start_date,
        "period_end": end_date,
        "period_label": start_date.strftime("%B %Y"),
        "existing_closing": existing_closing,
        "recent_closings": closing_rows,
        "retained_account": retained_account,
        "revenue_rows": revenue_rows,
        "expense_rows": expense_rows,
        "revenue_total": revenue_total,
        "expense_total": expense_total,
        "net_income": net_income,
        "net_status": "LABA" if net_income > 0 else ("RUGI" if net_income < 0 else "IMPAS"),
        "unbalanced_journals": unbalanced_journals,
        "negative_rows": negative_rows,
        "can_post": can_post,
        "blockers": blockers,
    }


def post_period_closing(
    *,
    branch_id: int,
    year: Any,
    month: Any,
    closing_date: date,
    notes: str | None,
    created_by: int,
    commit: bool = False,
) -> PeriodClosing:
    preview = get_period_closing_preview(branch_id, year, month)
    if not preview["schema_ready"]:
        raise Exception("Migration period closing belum dijalankan.")
    if preview["blockers"]:
        raise Exception("Closing belum boleh diposting: " + " | ".join(preview["blockers"]))
    if not closing_date:
        closing_date = preview["period_end"]
    if closing_date < preview["period_start"]:
        raise Exception("Tanggal closing tidak boleh sebelum awal periode.")

    retained_account = preview["retained_account"]
    if not retained_account:
        raise Exception("Akun 3002 Laba Ditahan belum tersedia.")

    closing = PeriodClosing(
        branch_id=branch_id,
        closing_number=generate_period_closing_number(closing_date),
        period_year=preview["year"],
        period_month=preview["month"],
        period_start=preview["period_start"],
        period_end=preview["period_end"],
        closing_date=closing_date,
        revenue_total=preview["revenue_total"],
        expense_total=preview["expense_total"],
        net_income=preview["net_income"],
        retained_earnings_account_code=RETAINED_EARNINGS_CODE,
        status=POSTED_STATUS,
        notes=notes or None,
        created_by=created_by,
    )
    db.session.add(closing)
    db.session.flush()

    journal = Journal(
        journal_number=generate_journal_number(closing_date),
        journal_date=closing_date,
        reference_type=PERIOD_CLOSING_REFERENCE_TYPE,
        reference_id=closing.id,
        description=(
            f"Closing periode {preview['period_start'].strftime('%d-%m-%Y')} s/d "
            f"{preview['period_end'].strftime('%d-%m-%Y')} - {preview['net_status']}"
        ),
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    # Tutup pendapatan: Dr Revenue, Cr 3002 Laba Ditahan.
    for row in preview["revenue_rows"]:
        amount = max(_safe_float(row["balance"]), 0)
        if amount <= 0:
            continue
        db.session.add(JournalDetail(journal_id=journal.id, account_id=row["account"].id, debit=amount, credit=0))
    if preview["revenue_total"] > 0:
        db.session.add(JournalDetail(journal_id=journal.id, account_id=retained_account.id, debit=0, credit=preview["revenue_total"]))

    # Tutup beban: Dr 3002 Laba Ditahan, Cr Expense.
    if preview["expense_total"] > 0:
        db.session.add(JournalDetail(journal_id=journal.id, account_id=retained_account.id, debit=preview["expense_total"], credit=0))
    for row in preview["expense_rows"]:
        amount = max(_safe_float(row["balance"]), 0)
        if amount <= 0:
            continue
        db.session.add(JournalDetail(journal_id=journal.id, account_id=row["account"].id, debit=0, credit=amount))

    closing.journal_id = journal.id

    record_audit_log(
        module="ACCOUNTING",
        event_type="PERIOD_CLOSING_POSTED",
        action="CREATE",
        table_name="period_closings",
        record_id=closing.id,
        description=f"Closing periode {preview['period_label']} diposting ke 3002 Laba Ditahan.",
        metadata={
            "closing_number": closing.closing_number,
            "period_year": closing.period_year,
            "period_month": closing.period_month,
            "revenue_total": closing.revenue_total,
            "expense_total": closing.expense_total,
            "net_income": closing.net_income,
            "journal_id": journal.id,
            "reference_type": PERIOD_CLOSING_REFERENCE_TYPE,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()
    return closing
