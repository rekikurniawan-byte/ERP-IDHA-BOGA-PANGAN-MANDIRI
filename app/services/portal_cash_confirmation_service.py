from __future__ import annotations

from app.models.finance import CashBankTransaction, Payment
from app.services.business_logic_guard_service import decimal_money


CUSTOMER_PAYMENT_REFERENCE_TYPE = "PAYMENT"


def build_customer_payment_cash_confirmation(*, payment_id: int, branch_id: int | None) -> dict:
    payment = Payment.query.filter(Payment.id == payment_id, Payment.branch_id == branch_id).first()
    if not payment:
        return {
            "found": False,
            "payment_id": payment_id,
            "checks": [],
            "is_valid": False,
        }

    ledgers = CashBankTransaction.query.filter_by(
        reference_type=CUSTOMER_PAYMENT_REFERENCE_TYPE,
        reference_id=payment.id,
    ).order_by(CashBankTransaction.id.asc()).all()
    expected_account_type = "BANK" if str(payment.payment_method or "").upper() == "TRANSFER" else "CASH"
    expected_bank_account_id = payment.bank_account_id if expected_account_type == "BANK" else None

    checks = [
        _check("ledger_exists", len(ledgers) == 1, expected=1, actual=len(ledgers), message="Payment harus punya tepat satu ledger kas/bank."),
    ]

    ledger = ledgers[0] if len(ledgers) == 1 else None
    if ledger:
        checks.extend(
            [
                _check(
                    "ledger_amount_matches_payment",
                    decimal_money(ledger.amount) == decimal_money(payment.amount),
                    expected=decimal_money(payment.amount),
                    actual=decimal_money(ledger.amount),
                    message="Nominal ledger harus sama dengan nominal payment.",
                ),
                _check(
                    "ledger_type_is_in",
                    str(ledger.transaction_type or "").upper() == "IN",
                    expected="IN",
                    actual=ledger.transaction_type,
                    message="Customer payment harus masuk sebagai transaksi kas/bank IN.",
                ),
                _check(
                    "ledger_account_type_matches_method",
                    str(ledger.account_type or "").upper() == expected_account_type,
                    expected=expected_account_type,
                    actual=ledger.account_type,
                    message="Account type ledger harus sesuai metode payment.",
                ),
                _check(
                    "ledger_bank_account_matches_payment",
                    ledger.bank_account_id == expected_bank_account_id,
                    expected=expected_bank_account_id,
                    actual=ledger.bank_account_id,
                    message="Bank account ledger harus sama dengan payment transfer.",
                ),
            ]
        )

    return {
        "found": True,
        "payment_id": payment.id,
        "payment_number": payment.payment_number,
        "payment_method": payment.payment_method,
        "payment_amount": decimal_money(payment.amount),
        "ledger_count": len(ledgers),
        "ledger_ids": [ledger.id for ledger in ledgers],
        "checks": checks,
        "is_valid": all(row["status"] == "PASS" for row in checks),
    }


def build_branch_cash_confirmation_recap(*, branch_id: int) -> dict:
    payments = Payment.query.filter_by(branch_id=branch_id).order_by(Payment.payment_date.asc(), Payment.id.asc()).all()
    rows = [build_customer_payment_cash_confirmation(payment_id=payment.id, branch_id=branch_id) for payment in payments]
    invalid_rows = [row for row in rows if not row["is_valid"]]
    return {
        "branch_id": branch_id,
        "payment_count": len(rows),
        "invalid_count": len(invalid_rows),
        "is_valid": not invalid_rows,
        "rows": rows,
    }


def _check(name: str, ok: bool, *, expected, actual, message: str) -> dict:
    return {
        "name": name,
        "status": "PASS" if ok else "FAIL",
        "expected": expected,
        "actual": actual,
        "message": message,
    }
