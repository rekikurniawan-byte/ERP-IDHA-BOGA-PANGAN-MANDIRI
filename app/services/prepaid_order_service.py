"""Jalur UMUM: pesanan pelanggan umum dibayar di muka.

Keputusan owner 2026-09-27:
1. Sistem menghitung total (harga terkunci × porsi + ongkir).
2. Pelanggan mengunggah bukti bayar; Finance memverifikasi dengan nominal dan
   rekening yang benar-benar diterima -> Uang Muka Pelanggan (2008) dengan
   jurnal otomatis (Dr Kas/Bank, Cr 2008), terhubung ke pesanan itu.
3. Pesanan baru boleh masuk dapur kalau uang muka >= total. OWNER boleh
   meloloskan; tercatat di audit log.
4. Setelah semua pengiriman pesanan diterima, invoice dibuat otomatis dan
   langsung dipotong uang mukanya (Dr 2008, Cr 1004) -> lunas.
5. Pesanan yang ditolak/dibatalkan setelah dibayar: uang muka dikembalikan atas
   keputusan OWNER (Dr 2008, Cr Kas/Bank).
6. Pesanan umum yang diinput admin langsung: pembayarannya dicatat saat input.

Semua jurnal lewat app/services/advance_service.py dan
app/services/accounting_service.py -- tidak ada jurnal yang ditulis di sini.
"""
from datetime import date
from decimal import Decimal

from app.models.finance import AdvanceTransaction
from app.services.advance_service import CLIENT_DP_RECEIVED, CLIENT_DP_REFUND, create_advance_settlement, create_advance_transaction
from app.services.audit_log_service import record_audit_log

ZERO = Decimal("0.00")


class PrepaymentError(ValueError):
    pass


def _money(value):
    return Decimal(str(value or 0)).quantize(Decimal("0.01"))


def rupiah(value):
    return f"Rp {_money(value):,.0f}".replace(",", ".")


def advance_method(payment_method):
    """Uang muka hanya mengenal CASH dan TRANSFER; QRIS masuk rekening = TRANSFER."""
    method = str(payment_method or "").strip().upper()
    if method == "QRIS":
        return "TRANSFER"
    if method not in {"CASH", "TRANSFER"}:
        raise PrepaymentError("Metode pembayaran harus tunai, transfer, atau QRIS.")
    return method


# --- berapa yang harus dan sudah dibayar ----------------------------------

def detail_total_amount(detail):
    """Total pesanan satu baris order: harga × porsi + ongkir siang/malam."""
    return (
        _money(detail.price_per_portion) * int(detail.total_qty or 0)
        + _money(detail.lunch_delivery_fee)
        + _money(detail.dinner_delivery_fee)
    )


def _prepayments(query_filter):
    return (
        AdvanceTransaction.query.filter(
            query_filter,
            AdvanceTransaction.advance_type == CLIENT_DP_RECEIVED,
        )
        .order_by(AdvanceTransaction.id.asc())
        .all()
    )


def draft_prepayments(draft):
    return _prepayments(AdvanceTransaction.portal_order_draft_id == draft.id)


def detail_prepayments(detail):
    return _prepayments(AdvanceTransaction.daily_order_detail_id == detail.id)


def available_amount(advances):
    """Uang muka yang masih bisa dipakai (belum dipotong ke invoice / dikembalikan)."""
    return sum((_money(advance.remaining_amount) for advance in advances), ZERO)


def draft_prepaid_amount(draft):
    return available_amount(draft_prepayments(draft))


def draft_requires_prepayment(draft):
    """Jalur UMUM, atau akun pelanggan umum (tidak pernah melonggarkan aturan lama)."""
    from app.services.pricing_service import is_general_client
    from app.services.user_management_service import ROLE_PORTAL_CUSTOMER

    role = getattr(getattr(draft, "user", None), "role", None)
    return is_general_client(getattr(draft, "client", None)) or role == ROLE_PORTAL_CUSTOMER


# --- 2. Finance: bukti bayar draft -> uang muka ---------------------------

def record_draft_prepayment(
    *,
    draft,
    amount,
    payment_method,
    created_by,
    payment_date=None,
    bank_account_id=None,
    reference_number=None,
    notes=None,
):
    """Catat uang muka untuk draft ini (jurnal otomatis). Tidak commit."""
    from app.services.portal_order_draft_service import draft_total_amount

    if draft.status in {"REJECTED", "CANCELLED"}:
        raise PrepaymentError("Draft yang ditolak/dibatalkan tidak menerima pembayaran.")
    total = draft_total_amount(draft)
    if total is None:
        raise PrepaymentError("Draft ini belum punya harga terkunci; total pembayaran tidak bisa dihitung.")
    amount = _money(amount)
    if amount <= 0:
        raise PrepaymentError("Nominal pembayaran harus lebih dari 0.")
    outstanding = total - draft_prepaid_amount(draft)
    if amount > outstanding:
        raise PrepaymentError(
            f"Nominal {rupiah(amount)} melebihi sisa yang harus dibayar {rupiah(max(outstanding, ZERO))}."
        )

    try:
        _, _, advance = create_advance_transaction(
            branch_id=draft.branch_id,
            advance_date=payment_date or date.today(),
            advance_type=CLIENT_DP_RECEIVED,
            payment_method=advance_method(payment_method),
            amount=float(amount),
            created_by=created_by,
            client_id=draft.client_id,
            bank_account_id=bank_account_id,
            reference_number=reference_number,
            notes=notes or f"Uang muka pesanan portal #{draft.id}",
            commit=False,
        )
    except PrepaymentError:
        raise
    except Exception as error:
        raise PrepaymentError(str(error)) from error

    advance.portal_order_draft_id = draft.id
    if draft.converted_daily_order_id:
        detail = converted_detail(draft)
        if detail is not None:
            advance.daily_order_detail_id = detail.id
    return advance


def converted_detail(draft):
    from app.models.operational import DailyOrderDetail

    if not draft.converted_daily_order_id:
        return None
    return DailyOrderDetail.query.filter_by(
        daily_order_id=draft.converted_daily_order_id,
        mandor_id=draft.mandor_id,
        delivery_location_id=draft.delivery_location_id,
    ).first()


def link_draft_prepayments_to_detail(draft, detail):
    """Saat draft menjadi baris order, uang mukanya ikut pindah ke baris itu."""
    for advance in draft_prepayments(draft):
        advance.daily_order_detail_id = detail.id


# --- 6. Admin: pesanan umum diinput langsung ------------------------------

def record_detail_prepayment(
    *,
    detail,
    amount,
    payment_method,
    created_by,
    payment_date=None,
    bank_account_id=None,
    reference_number=None,
):
    """Catat pembayaran untuk baris order umum yang diinput admin. Tidak commit."""
    amount = _money(amount)
    if amount <= 0:
        raise PrepaymentError("Nominal pembayaran harus lebih dari 0.")
    outstanding = detail_total_amount(detail) - available_amount(detail_prepayments(detail))
    if amount > outstanding:
        raise PrepaymentError(
            f"Nominal {rupiah(amount)} melebihi total pesanan yang belum dibayar {rupiah(max(outstanding, ZERO))}."
        )
    client_id = getattr(getattr(detail, "mandor", None), "client_id", None)
    try:
        _, _, advance = create_advance_transaction(
            branch_id=detail.daily_order.branch_id,
            advance_date=payment_date or date.today(),
            advance_type=CLIENT_DP_RECEIVED,
            payment_method=advance_method(payment_method),
            amount=float(amount),
            created_by=created_by,
            client_id=client_id,
            bank_account_id=bank_account_id,
            reference_number=reference_number,
            notes=f"Pembayaran pesanan {detail.daily_order.order_number} (input admin)",
            commit=False,
        )
    except Exception as error:
        raise PrepaymentError(str(error)) from error
    advance.daily_order_detail_id = detail.id
    return advance


# --- 4. Setelah terkirim: invoice otomatis + potong uang muka -------------

def _meal_fully_delivered(detail, delivery_type, ordered_qty):
    from app.models.delivery import Delivery, DeliveryDetail

    rows = (
        DeliveryDetail.query.join(Delivery, Delivery.id == DeliveryDetail.delivery_id)
        .filter(
            DeliveryDetail.daily_order_detail_id == detail.id,
            Delivery.notes.like(f"%delivery_type={delivery_type}%"),
            Delivery.status != "CANCELLED",
        )
        .all()
    )
    if not rows:
        return False
    planned = sum(int(row.planned_qty or 0) for row in rows)
    return planned >= int(ordered_qty or 0) and all(row.receipt is not None for row in rows)


def detail_fully_delivered(detail):
    """Semua pengiriman yang dipesan (siang/malam) sudah dikirim dan diterima."""
    for delivery_type, qty in (("LUNCH", detail.lunch_qty), ("DINNER", detail.dinner_qty)):
        if int(qty or 0) > 0 and not _meal_fully_delivered(detail, delivery_type, qty):
            return False
    return True


def invoice_prepaid_order(order, mandor, created_by):
    """Buat invoice pesanan umum yang sudah terkirim semua, lalu lunasi dari uang mukanya.

    Mengembalikan invoice, atau None kalau belum waktunya (bukan jalur UMUM,
    belum terkirim semua, atau invoice sudah ada). Tidak commit.
    """
    from app.services.order_invoice_service import create_order_invoice, find_order_invoice
    from app.services.pricing_service import is_general_client

    if not is_general_client(getattr(mandor, "client", None)):
        return None
    if order.status != "LOCKED" or find_order_invoice(order.branch_id, order.id, mandor.id):
        return None
    details = [detail for detail in order.details if int(detail.mandor_id) == int(mandor.id)]
    if not details or not all(detail_fully_delivered(detail) for detail in details):
        return None

    invoice = create_order_invoice(order, mandor, created_by=created_by, prepaid=True)
    today = date.today()
    for detail in details:
        for advance in detail_prepayments(detail):
            remaining_invoice = _money(invoice.remaining_amount)
            usable = min(_money(advance.remaining_amount), remaining_invoice)
            if usable <= 0:
                continue
            create_advance_settlement(
                advance=advance,
                settlement_date=max(today, advance.advance_date),
                settlement_type="CLIENT_INVOICE",
                amount=float(usable),
                created_by=created_by,
                reference_id=invoice.id,
                notes=f"Pelunasan otomatis invoice {invoice.invoice_number} dari uang muka pesanan.",
                commit=False,
            )
    record_audit_log(
        module="FINANCE",
        event_type="PREPAID_ORDER_INVOICED",
        action="CREATE",
        table_name="invoices",
        record_id=invoice.id,
        description=(
            f"Invoice {invoice.invoice_number} dibuat otomatis setelah pesanan {order.order_number} terkirim; "
            f"sisa tagihan {rupiah(invoice.remaining_amount)}."
        ),
        metadata={"order_id": order.id, "mandor_id": mandor.id, "status": invoice.status},
        user_id=created_by,
        branch_id=order.branch_id,
        commit=False,
    )
    return invoice


def invoice_after_delivery_receipt(delivery_detail, created_by):
    """Dipanggil setelah tanda terima pengiriman tersimpan. Commit sendiri.

    Kegagalan tidak membatalkan tanda terima: pesannya dikembalikan supaya
    Finance bisa membuat invoice manual.
    """
    from app.services.atomic_transaction_service import atomic_business_action

    order_detail = delivery_detail.daily_order_detail
    order = order_detail.daily_order
    try:
        with atomic_business_action(
            module="FINANCE",
            action="PREPAID_ORDER_INVOICE",
            description=f"Invoice otomatis pesanan umum {order.order_number} setelah pengiriman diterima.",
            reference_type="invoices",
            user_id=created_by,
            branch_id=order.branch_id,
            metadata={"order_id": order.id, "mandor_id": order_detail.mandor_id},
        ):
            invoice = invoice_prepaid_order(order, order_detail.mandor, created_by)
    except Exception as error:  # noqa: BLE001 - tanda terima sudah tersimpan
        return None, f"Invoice otomatis belum dibuat: {error}. Finance bisa membuatnya manual."
    return invoice, None


# --- 5. Pengembalian uang muka (OWNER) ------------------------------------

def refund_prepayments(*, advances, created_by, payment_method, bank_account_id=None, reason=None):
    """Kembalikan sisa uang muka ke pelanggan. Hanya OWNER (dicek advance_service). Tidak commit."""
    refunded = ZERO
    for advance in advances:
        amount = _money(advance.remaining_amount)
        if amount <= 0:
            continue
        try:
            create_advance_settlement(
                advance=advance,
                settlement_date=max(date.today(), advance.advance_date),
                settlement_type=CLIENT_DP_REFUND,
                amount=float(amount),
                created_by=created_by,
                notes=reason or "Pesanan ditolak/dibatalkan setelah dibayar.",
                commit=False,
                payment_method=advance_method(payment_method),
                bank_account_id=bank_account_id,
            )
        except Exception as error:
            raise PrepaymentError(str(error)) from error
        refunded += amount
    if refunded <= 0:
        raise PrepaymentError("Tidak ada uang muka yang bisa dikembalikan.")
    return refunded
