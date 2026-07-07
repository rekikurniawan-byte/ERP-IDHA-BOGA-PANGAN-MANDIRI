"""Centralized business logic guard helpers for production readiness.

This module keeps critical status, payment, and stock rules in one place so
routes/services do not silently drift into different validation behavior.
It intentionally stays lightweight and does not commit database sessions.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable


class BusinessRuleError(ValueError):
    """Raised when a business transaction violates a production guard."""


MONEY_QUANT = Decimal("0.01")

INVOICE_STATUSES = ("DRAFT", "PARTIAL", "PAID", "CANCELLED", "CANCELED")
INVOICE_CANCELLED_STATUSES = ("CANCELLED", "CANCELED")
CUSTOMER_PAYMENT_METHODS = ("CASH", "TRANSFER")

SUPPLIER_BILL_STATUSES = ("OPEN", "PARTIAL", "PAID", "CANCELLED")
SUPPLIER_PAYMENT_METHODS = ("CASH", "TRANSFER")

PAYROLL_STATUSES = ("DRAFT", "FINAL", "POSTED", "PAID", "CANCELLED")
JOURNAL_STATUSES = ("DRAFT", "POSTED", "REVERSED")
PROCUREMENT_TYPES = ("CASH", "CREDIT")
DELIVERY_STATUSES = ("PREPARING", "ON_THE_WAY", "DELIVERED", "CANCELLED")
PRODUCTION_STATUSES = ("DRAFT", "IN_PROGRESS", "COMPLETED", "CANCELLED")
ITEM_REQUEST_STATUSES = ("PENDING", "APPROVED", "REJECTED", "FULFILLED")

STOCK_IN_TYPES = ("IN", "ADJUSTMENT_IN")
STOCK_OUT_TYPES = ("OUT", "ADJUSTMENT_OUT", "DAMAGED", "WASTE")
STOCK_NEUTRAL_TYPES = ("AUDIT_OK",)
STOCK_MOVEMENT_TYPES = STOCK_IN_TYPES + STOCK_OUT_TYPES + STOCK_NEUTRAL_TYPES


def normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def validate_choice(value: object, allowed: Iterable[str], label: str) -> str:
    normalized = normalize_code(value)
    allowed_tuple = tuple(allowed)
    if normalized not in allowed_tuple:
        allowed_text = ", ".join(allowed_tuple)
        raise BusinessRuleError(f"{label} tidak valid. Pilihan yang boleh: {allowed_text}.")
    return normalized


def decimal_money(value: object, label: str = "Nominal") -> Decimal:
    try:
        if isinstance(value, Decimal):
            raw = value
        else:
            text = str(value or "0").strip().replace("Rp", "").replace(" ", "")
            if "," in text and "." in text:
                # Input Indonesia: 1.000,50
                text = text.replace(".", "").replace(",", ".")
            elif "," in text and "." not in text:
                text = text.replace(",", ".")
            elif text.count(".") > 1:
                # Input Indonesia: 1.000.000
                text = text.replace(".", "")
            elif text.count(".") == 1:
                left, right = text.split(".")
                if left and right.isdigit() and len(right) == 3:
                    text = text.replace(".", "")
            raw = Decimal(text or "0")
    except (InvalidOperation, ValueError):
        raise BusinessRuleError(f"{label} tidak valid.")

    return raw.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


def float_money(value: object, label: str = "Nominal") -> float:
    return float(decimal_money(value, label=label))


def assert_positive_amount(amount: object, label: str = "Nominal") -> float:
    normalized = float_money(amount, label=label)
    if normalized <= 0:
        raise BusinessRuleError(f"{label} harus lebih dari 0.")
    return normalized


def assert_payment_amount_not_over_remaining(amount: object, remaining: object, label: str = "Nominal pembayaran") -> float:
    normalized_amount = assert_positive_amount(amount, label=label)
    normalized_remaining = float_money(remaining, label="Sisa tagihan")
    if normalized_remaining <= 0:
        raise BusinessRuleError("Tagihan ini sudah lunas.")
    if normalized_amount > normalized_remaining:
        raise BusinessRuleError(f"{label} tidak boleh lebih dari sisa tagihan.")
    return normalized_amount


def assert_not_future_date(transaction_date: date, today: date, label: str = "Tanggal transaksi") -> None:
    if transaction_date > today:
        raise BusinessRuleError(f"{label} tidak boleh lebih dari hari ini.")


def assert_date_not_before(transaction_date: date, reference_date: date, label: str = "Tanggal transaksi", reference_label: str = "tanggal referensi") -> None:
    if transaction_date < reference_date:
        raise BusinessRuleError(f"{label} tidak boleh lebih awal dari {reference_label}.")


def resolve_invoice_status_after_payment(total_amount: object, paid_amount: object) -> str:
    total = float_money(total_amount, label="Total invoice")
    paid = float_money(paid_amount, label="Total pembayaran")
    remaining = total - paid
    if remaining <= 0:
        return "PAID"
    if paid > 0:
        return "PARTIAL"
    return "DRAFT"


def resolve_supplier_bill_status_after_payment(total_amount: object, paid_amount: object) -> str:
    total = float_money(total_amount, label="Total hutang supplier")
    paid = float_money(paid_amount, label="Total pembayaran supplier")
    remaining = total - paid
    if remaining <= 0:
        return "PAID"
    if paid > 0:
        return "PARTIAL"
    return "OPEN"


def validate_stock_movement_guard(
    movement_type: object,
    qty: object,
    *,
    current_stock: object | None = None,
    item_unit: str | None = None,
    is_integer_unit: bool = False,
    allow_zero: bool = False,
    allow_audit_ok: bool = False,
) -> float:
    """Validate stock movement before inserting StockMovement rows.

    OUT-like movements are blocked when they would make stock negative.
    AUDIT_OK can be zero only when explicitly allowed by audit flows.
    """
    normalized_type = normalize_code(movement_type)
    allowed = STOCK_MOVEMENT_TYPES if allow_audit_ok else STOCK_IN_TYPES + STOCK_OUT_TYPES
    if normalized_type not in allowed:
        raise BusinessRuleError("Tipe pergerakan stok tidak valid.")

    try:
        normalized_qty = float(qty or 0)
    except (TypeError, ValueError):
        raise BusinessRuleError("Jumlah stok tidak valid.")

    if normalized_type in STOCK_NEUTRAL_TYPES:
        if not allow_zero or normalized_qty != 0:
            raise BusinessRuleError("Audit stok tanpa selisih hanya boleh menyimpan qty 0.")
        return normalized_qty

    if normalized_qty <= 0 and not allow_zero:
        raise BusinessRuleError("Jumlah stok wajib lebih dari 0.")

    if is_integer_unit and not float(normalized_qty).is_integer():
        unit_label = item_unit or "item ini"
        raise BusinessRuleError(f"Untuk satuan {unit_label}, jumlah stok harus angka bulat.")

    if normalized_type in STOCK_OUT_TYPES:
        if current_stock is None:
            raise BusinessRuleError("Validasi stok keluar wajib membaca stok saat ini.")
        current = float(current_stock or 0)
        if normalized_qty > current:
            unit_suffix = f" {item_unit}" if item_unit else ""
            raise BusinessRuleError(f"Stok tidak cukup. Stok saat ini {current:g}{unit_suffix}.")

    return normalized_qty
