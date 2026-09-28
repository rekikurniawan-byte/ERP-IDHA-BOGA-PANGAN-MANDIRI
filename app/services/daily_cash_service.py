"""
Daily Cash Service — Tutup Kas Harian Warung.

Melengkapi tabel `cash_daily` yang sebelumnya hanya dibaca oleh
daily_closing_service (laporan tutup harian) tapi belum punya form input.

Fungsi utama:
- list/get record kas harian
- upsert (create/update) rekap kas harian per (branch_id, cash_date)
- hitung otomatis saldo akhir (closing_balance) dan selisih kas (cash_difference)
- angka referensi dari data warung aktual untuk bantu pengisian

Catatan integrasi:
- Record ini adalah REKAP/REKONSILIASI kas warung harian, bukan sumber ledger.
  Ia sengaja TIDAK memposting jurnal/ledger supaya tidak double-count dengan
  transaksi warung (CanteenSale) yang sudah tercatat sendiri. daily_closing_service
  membaca record ini untuk audit tutup harian.
"""

from app.extensions import db
from app.models.canteen import CashDaily, CanteenSale, DebtPayment, WorkerDebt


VALID_STATUSES = ("OPEN", "CLOSED")


def _f(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def compute_closing_balance(opening_balance, cash_sales, debt_payments, other_income, expenses):
    """Saldo akhir = saldo awal + penjualan tunai + bayar hutang + pemasukan lain - pengeluaran."""
    return (
        _f(opening_balance)
        + _f(cash_sales)
        + _f(debt_payments)
        + _f(other_income)
        - _f(expenses)
    )


def compute_cash_difference(actual_cash, closing_balance):
    """Selisih kas = kas fisik aktual - saldo akhir seharusnya."""
    return _f(actual_cash) - _f(closing_balance)


def list_daily_cash(branch_id):
    return (
        CashDaily.query.filter_by(branch_id=branch_id)
        .order_by(CashDaily.cash_date.desc(), CashDaily.id.desc())
        .all()
    )


def get_daily_cash(branch_id, cash_id):
    record = CashDaily.query.get(cash_id)
    if not record or record.branch_id != branch_id:
        return None
    return record


def get_daily_cash_by_date(branch_id, cash_date):
    return CashDaily.query.filter_by(branch_id=branch_id, cash_date=cash_date).first()


def get_last_closing_balance(branch_id, before_date):
    """Saldo fisik akhir hari sebelumnya, untuk saran saldo awal hari ini."""
    record = (
        CashDaily.query.filter(
            CashDaily.branch_id == branch_id,
            CashDaily.cash_date < before_date,
        )
        .order_by(CashDaily.cash_date.desc(), CashDaily.id.desc())
        .first()
    )
    if record:
        return _f(record.actual_cash) or _f(record.closing_balance)
    return 0.0


def build_reference_totals(branch_id, cash_date):
    """Angka referensi dari data warung aktual pada tanggal tsb (hanya bantu isi, tidak mengikat)."""
    sales = CanteenSale.query.filter_by(branch_id=branch_id, sale_date=cash_date).all()

    cash_sales_total = sum(
        _f(sale.total_amount) for sale in sales if str(sale.sale_type or "").upper() == "CASH"
    )
    debt_sales_total = sum(
        _f(sale.total_amount) for sale in sales if str(sale.sale_type or "").upper() == "DEBT"
    )

    debt_payments = (
        DebtPayment.query.join(WorkerDebt, DebtPayment.worker_debt_id == WorkerDebt.id)
        .filter(
            WorkerDebt.branch_id == branch_id,
            DebtPayment.payment_date == cash_date,
        )
        .all()
    )
    debt_payment_total = sum(_f(payment.amount) for payment in debt_payments)

    return {
        "cash_sales_total": cash_sales_total,
        "debt_sales_total": debt_sales_total,
        "debt_payment_total": debt_payment_total,
        "sales_count": len(sales),
    }


def save_daily_cash(
    branch_id,
    created_by,
    cash_date,
    opening_balance,
    cash_sales,
    debt_payments,
    other_income,
    expenses,
    actual_cash,
    status,
    notes,
):
    """Upsert rekap kas harian untuk (branch_id, cash_date).

    Menghormati unique constraint uq_cash_daily_branch_date: jika sudah ada
    record untuk tanggal itu, record di-update; jika belum, dibuat baru.
    Saldo akhir & selisih dihitung otomatis di server.
    """
    status = (status or "OPEN").strip().upper()
    if status not in VALID_STATUSES:
        status = "OPEN"

    closing_balance = compute_closing_balance(
        opening_balance, cash_sales, debt_payments, other_income, expenses
    )
    cash_difference = compute_cash_difference(actual_cash, closing_balance)

    record = get_daily_cash_by_date(branch_id, cash_date)
    is_new = record is None

    if is_new:
        record = CashDaily(branch_id=branch_id, cash_date=cash_date, created_by=created_by)
        db.session.add(record)

    record.status = status
    record.opening_balance = _f(opening_balance)
    record.cash_sales = _f(cash_sales)
    record.debt_payments = _f(debt_payments)
    record.other_income = _f(other_income)
    record.expenses = _f(expenses)
    record.closing_balance = closing_balance
    record.actual_cash = _f(actual_cash)
    record.cash_difference = cash_difference
    record.notes = notes

    db.session.commit()
    return record, is_new
