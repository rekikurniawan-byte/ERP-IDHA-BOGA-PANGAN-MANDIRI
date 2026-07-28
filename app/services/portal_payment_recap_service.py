from __future__ import annotations

from decimal import Decimal

from app.models.finance import Invoice, Payment
from app.services.business_logic_guard_service import INVOICE_CANCELLED_STATUSES, decimal_money


def build_invoice_payment_recap(*, invoice_id: int, branch_id: int | None) -> dict:
    """Read-only invoice/payment/receivable invariant recap."""
    invoice = Invoice.query.filter(Invoice.id == invoice_id, Invoice.branch_id == branch_id).first()
    if not invoice:
        return {
            "found": False,
            "invoice_id": invoice_id,
            "status": "NOT_FOUND",
            "checks": [],
            "is_valid": False,
        }

    payments = Payment.query.filter_by(invoice_id=invoice.id, branch_id=invoice.branch_id).order_by(Payment.payment_date.asc(), Payment.id.asc()).all()
    payment_total = _sum_money(payment.amount for payment in payments)
    invoice_total = decimal_money(invoice.total_amount, label="Total invoice")
    invoice_paid = decimal_money(invoice.paid_amount, label="Paid amount invoice")
    invoice_remaining = decimal_money(invoice.remaining_amount, label="Remaining amount invoice")
    expected_remaining = max(invoice_total - payment_total, Decimal("0.00"))
    status = str(invoice.status or "").upper()
    is_cancelled = status in INVOICE_CANCELLED_STATUSES
    active_receivable = not is_cancelled and expected_remaining > 0

    checks = [
        _check(
            "payment_sum_vs_invoice_paid",
            payment_total == invoice_paid,
            expected=payment_total,
            actual=invoice_paid,
            message="Total payment rows harus sama dengan paid_amount invoice.",
        ),
        _check(
            "remaining_vs_total_minus_payment",
            expected_remaining == invoice_remaining,
            expected=expected_remaining,
            actual=invoice_remaining,
            message="Remaining invoice harus total invoice dikurangi total payment rows.",
        ),
        _check(
            "payment_not_over_invoice_total",
            payment_total <= invoice_total,
            expected=f"<= {invoice_total}",
            actual=payment_total,
            message="Total payment rows tidak boleh melebihi total invoice.",
        ),
        _check(
            "cancelled_not_active_receivable",
            not (is_cancelled and invoice_remaining > 0),
            expected=Decimal("0.00") if is_cancelled else "not_cancelled",
            actual=invoice_remaining if is_cancelled else "not_cancelled",
            message="Invoice cancelled tidak boleh masuk piutang aktif.",
        ),
    ]

    return {
        "found": True,
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_status": invoice.status,
        "invoice_total": invoice_total,
        "invoice_paid": invoice_paid,
        "invoice_remaining": invoice_remaining,
        "payment_total": payment_total,
        "payment_count": len(payments),
        "expected_remaining": expected_remaining,
        "active_receivable": active_receivable,
        "over_allocated": payment_total > invoice_total,
        "checks": checks,
        "is_valid": all(row["status"] == "PASS" for row in checks),
    }


def build_branch_receivable_recap(*, branch_id: int) -> dict:
    invoices = Invoice.query.filter_by(branch_id=branch_id).order_by(Invoice.invoice_date.asc(), Invoice.id.asc()).all()
    rows = [build_invoice_payment_recap(invoice_id=invoice.id, branch_id=branch_id) for invoice in invoices]
    active_rows = [row for row in rows if row.get("active_receivable")]
    invalid_rows = [row for row in rows if not row.get("is_valid")]
    return {
        "branch_id": branch_id,
        "invoice_count": len(rows),
        "active_receivable_count": len(active_rows),
        "active_receivable_total": _sum_money(row["expected_remaining"] for row in active_rows),
        "invalid_count": len(invalid_rows),
        "is_valid": not invalid_rows,
        "rows": rows,
    }


def _sum_money(values) -> Decimal:
    total = Decimal("0.00")
    for value in values:
        total += decimal_money(value, label="Nominal")
    return total.quantize(Decimal("0.01"))


def _check(name: str, ok: bool, *, expected, actual, message: str) -> dict:
    return {
        "name": name,
        "status": "PASS" if ok else "FAIL",
        "expected": expected,
        "actual": actual,
        "message": message,
    }
