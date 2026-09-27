from __future__ import annotations

import json
from contextlib import nullcontext
from datetime import date, datetime

from app.extensions import db
from app.models.finance import BankAccount, Invoice, InvoiceCollectionLog, Payment
from app.models.system import DigitalAttachment
from app.services.accounting_service import create_payment_journal_for_payment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.business_logic_guard_service import (
    BusinessRuleError,
    CUSTOMER_PAYMENT_METHODS,
    INVOICE_CANCELLED_STATUSES,
    assert_date_not_before,
    assert_not_future_date,
    assert_payment_amount_not_over_remaining,
    decimal_money,
    resolve_invoice_status_after_payment,
    validate_choice,
)
from app.services.cash_bank_service import create_customer_payment_cash_bank_transaction
from app.services.idempotency_service import (
    IdempotencyConflictError,
    mark_idempotency_completed,
    reserve_idempotency_key,
)
from app.services.manual_backfill_billing_service import sync_manual_backfill_batch_status_from_invoice
from app.services.notification_service import create_or_update_notification
from app.services.portal_payment_proof_service import (
    PAYMENT_PROOF_REFERENCE_TYPE,
    PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
    PORTAL_PAYMENT_MODULE,
)
from app.services.portal_payment_verification_queue_service import PAYMENT_PROOF_VERIFIED_TYPE


PAYMENT_PROOF_PAYMENT_CREATED_TYPE = "PAYMENT_PROOF_PAYMENT_CREATED"
PORTAL_DRAFT_PREPAYMENT_SCOPE = "PORTAL_DRAFT_PREPAYMENT_CREATE"
PORTAL_PAYMENT_CREATE_SCOPE = "PORTAL_VERIFIED_PROOF_PAYMENT_CREATE"


class PortalPaymentCreationError(ValueError):
    pass


def create_payment_from_verified_proof(
    finance_user,
    *,
    attachment_id: int,
    payment_date: date,
    amount,
    payment_method: str,
    bank_account_id: int | None = None,
    reference_number: str | None = None,
    notes: str | None = None,
    idempotency_key: str,
    commit: bool = True,
) -> dict:
    """Create a customer payment from one verified portal proof using existing posting services."""
    if not idempotency_key:
        raise PortalPaymentCreationError("Idempotency key wajib untuk membuat payment dari bukti portal.")

    attachment = _get_proof_attachment_for_branch(attachment_id, getattr(finance_user, "branch_id", None))
    invoice = _get_invoice_for_branch(attachment.reference_id, getattr(finance_user, "branch_id", None))
    payment_date = _normalize_payment_date(payment_date)
    try:
        payment_method = validate_choice(payment_method, CUSTOMER_PAYMENT_METHODS, "Metode pembayaran")
    except BusinessRuleError as error:
        raise PortalPaymentCreationError(str(error)) from error
    amount_input = amount
    bank_account_id = _validate_bank_account(payment_method, bank_account_id, invoice.branch_id)
    reference_number = str(reference_number or "").strip() or None
    notes = str(notes or "").strip() or None

    try:
        idempotency_record, reserved = reserve_idempotency_key(
            scope=PORTAL_PAYMENT_CREATE_SCOPE,
            key=idempotency_key,
            branch_id=invoice.branch_id,
            user_id=getattr(finance_user, "id", None),
            request_payload={
                "attachment_id": attachment.id,
                "invoice_id": invoice.id,
                "payment_date": payment_date.isoformat(),
                "amount": str(amount_input),
                "payment_method": payment_method,
                "bank_account_id": bank_account_id,
                "reference_number": reference_number,
                "notes": notes,
            },
        )
    except IdempotencyConflictError as error:
        raise PortalPaymentCreationError(str(error)) from error

    if not reserved and idempotency_record.status == "COMPLETED":
        return _replay_completed_payment(idempotency_record)
    if not reserved:
        raise PortalPaymentCreationError("Payment dari bukti ini sedang atau pernah diproses dengan idempotency key yang sama.")

    if attachment.attachment_type != PAYMENT_PROOF_VERIFIED_TYPE:
        raise PortalPaymentCreationError("Bukti pembayaran harus verified sebelum payment dibuat.")

    _assert_invoice_payable(invoice)
    try:
        assert_not_future_date(payment_date, date.today(), label="Tanggal pembayaran")
        assert_date_not_before(payment_date, invoice.invoice_date, label="Tanggal pembayaran", reference_label="tanggal invoice")
        assert_payment_amount_not_over_remaining(amount_input, invoice.remaining_amount, label="Nominal pembayaran")
        amount = decimal_money(amount_input, label="Nominal pembayaran")
    except BusinessRuleError as error:
        raise PortalPaymentCreationError(str(error)) from error

    payment = Payment(
        payment_number=_generate_payment_number(payment_date),
        branch_id=invoice.branch_id,
        payment_date=payment_date,
        invoice_id=invoice.id,
        bank_account_id=bank_account_id,
        payment_method=payment_method,
        amount=amount,
        reference_number=reference_number,
        notes=notes,
        received_by=getattr(finance_user, "id", None),
    )

    boundary = (
        atomic_business_action(
            module="FINANCE",
            action="PORTAL_VERIFIED_PROOF_PAYMENT_CREATE",
            description=f"Create customer payment from verified portal proof for invoice {invoice.invoice_number}.",
            reference_type="PAYMENT",
            user_id=getattr(finance_user, "id", None),
            branch_id=invoice.branch_id,
            severity="HIGH",
            metadata={
                "attachment_id": attachment.id,
                "invoice_id": invoice.id,
                "invoice_number": invoice.invoice_number,
                "amount": amount,
                "payment_method": payment_method,
            },
        )
        if commit
        else nullcontext()
    )

    with boundary:
        db.session.add(payment)
        db.session.flush()

        new_paid = float(invoice.paid_amount or 0) + float(amount or 0)
        new_remaining = max(float(invoice.total_amount or 0) - new_paid, 0)
        invoice.status = resolve_invoice_status_after_payment(invoice.total_amount, new_paid)
        invoice.paid_amount = new_paid
        invoice.remaining_amount = new_remaining

        sync_manual_backfill_batch_status_from_invoice(
            invoice,
            updated_by=getattr(finance_user, "id", None),
            commit=False,
        )

        create_payment_journal_for_payment(
            payment=payment,
            created_by=getattr(finance_user, "id", None),
            commit=False,
        )
        create_customer_payment_cash_bank_transaction(
            payment=payment,
            created_by=getattr(finance_user, "id", None),
            commit=False,
        )
        db.session.add(_build_collection_log(invoice, payment, getattr(finance_user, "id", None)))

        attachment.attachment_type = PAYMENT_PROOF_PAYMENT_CREATED_TYPE
        attachment.notes = _append_payment_created_note(attachment.notes, payment.payment_number)

        response_payload = {
            "payment_id": payment.id,
            "payment_number": payment.payment_number,
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "attachment_id": attachment.id,
        }
        mark_idempotency_completed(
            idempotency_record,
            reference_type="PAYMENT",
            reference_id=payment.id,
            response_payload=response_payload,
            commit=False,
        )
        record_audit_log(
            module="FINANCE",
            event_type="PORTAL_VERIFIED_PROOF_PAYMENT_CREATED",
            action="CREATE",
            table_name="payments",
            record_id=payment.id,
            description=f"Payment dibuat dari bukti portal verified: {payment.payment_number}.",
            metadata=response_payload,
            user_id=getattr(finance_user, "id", None),
            branch_id=invoice.branch_id,
            commit=False,
        )
        _notify_portal_payment_created(attachment, invoice, payment, finance_user)

    return _payment_result(payment, invoice, attachment, idempotent_replay=False)


def create_prepayment_from_verified_draft_proof(
    finance_user,
    *,
    attachment_id: int,
    payment_date: date,
    amount,
    payment_method: str,
    bank_account_id: int | None = None,
    reference_number: str | None = None,
    notes: str | None = None,
    idempotency_key: str,
) -> dict:
    """Bukti bayar draft yang sudah diverifikasi menjadi Uang Muka Pelanggan (2008).

    Jalur UMUM (keputusan owner 2026-09-27): nominal dan rekening diisi Finance
    sesuai uang yang benar-benar diterima; jurnalnya dibuat advance_service.
    """
    from app.models.system import PortalOrderDraft
    from app.services.prepaid_order_service import PrepaymentError, record_draft_prepayment

    if not idempotency_key:
        raise PortalPaymentCreationError("Idempotency key wajib untuk mencatat uang muka dari bukti portal.")
    attachment = _get_proof_attachment_for_branch(
        attachment_id, getattr(finance_user, "branch_id", None), reference_type=PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE
    )
    draft = PortalOrderDraft.query.filter_by(id=attachment.reference_id, branch_id=attachment.branch_id).first()
    if not draft:
        raise PortalPaymentCreationError("Draft pesanan untuk bukti ini tidak ditemukan.")
    payment_date = _normalize_payment_date(payment_date)
    try:
        assert_not_future_date(payment_date, date.today(), label="Tanggal pembayaran")
    except BusinessRuleError as error:
        raise PortalPaymentCreationError(str(error)) from error

    try:
        idempotency_record, reserved = reserve_idempotency_key(
            scope=PORTAL_DRAFT_PREPAYMENT_SCOPE,
            key=idempotency_key,
            branch_id=draft.branch_id,
            user_id=getattr(finance_user, "id", None),
            request_payload={
                "attachment_id": attachment.id,
                "draft_id": draft.id,
                "payment_date": payment_date.isoformat(),
                "amount": str(amount),
                "payment_method": payment_method,
                "bank_account_id": bank_account_id,
            },
        )
    except IdempotencyConflictError as error:
        raise PortalPaymentCreationError(str(error)) from error
    if not reserved:
        raise PortalPaymentCreationError("Uang muka dari bukti ini sedang atau pernah diproses.")
    if attachment.attachment_type != PAYMENT_PROOF_VERIFIED_TYPE:
        raise PortalPaymentCreationError("Bukti pembayaran harus verified sebelum uang muka dicatat.")

    with atomic_business_action(
        module="FINANCE",
        action="PORTAL_DRAFT_PREPAYMENT_CREATE",
        description=f"Catat uang muka pesanan portal #{draft.id} dari bukti terverifikasi.",
        reference_type="ADVANCE_TRANSACTION",
        user_id=getattr(finance_user, "id", None),
        branch_id=draft.branch_id,
        severity="HIGH",
        metadata={"attachment_id": attachment.id, "draft_id": draft.id, "amount": str(amount)},
    ):
        try:
            advance = record_draft_prepayment(
                draft=draft,
                amount=amount,
                payment_method=payment_method,
                created_by=getattr(finance_user, "id", None),
                payment_date=payment_date,
                bank_account_id=bank_account_id,
                reference_number=str(reference_number or "").strip() or None,
                notes=str(notes or "").strip() or None,
            )
        except PrepaymentError as error:
            raise PortalPaymentCreationError(str(error)) from error

        attachment.attachment_type = PAYMENT_PROOF_PAYMENT_CREATED_TYPE
        attachment.notes = _append_payment_created_note(attachment.notes, advance.advance_number)
        response_payload = {
            "advance_id": advance.id,
            "advance_number": advance.advance_number,
            "draft_id": draft.id,
            "attachment_id": attachment.id,
        }
        mark_idempotency_completed(
            idempotency_record,
            reference_type="ADVANCE_TRANSACTION",
            reference_id=advance.id,
            response_payload=response_payload,
            commit=False,
        )
        record_audit_log(
            module="FINANCE",
            event_type="PORTAL_DRAFT_PREPAYMENT_CREATED",
            action="CREATE",
            table_name="advance_transactions",
            record_id=advance.id,
            description=f"Uang muka {advance.advance_number} dicatat dari bukti draft #{draft.id}.",
            metadata=response_payload,
            user_id=getattr(finance_user, "id", None),
            branch_id=draft.branch_id,
            commit=False,
        )
    return {**response_payload, "amount": advance.amount}


def _get_invoice_for_branch(invoice_id: int, branch_id: int | None) -> Invoice:
    invoice = Invoice.query.filter(Invoice.id == invoice_id, Invoice.branch_id == branch_id).first()
    if not invoice:
        raise PortalPaymentCreationError("Invoice sumber bukti pembayaran tidak ditemukan.")
    return invoice


def _assert_invoice_payable(invoice: Invoice) -> None:
    if str(invoice.status or "").upper() in INVOICE_CANCELLED_STATUSES:
        raise PortalPaymentCreationError("Invoice yang dibatalkan tidak bisa menerima pembayaran.")
    if float(invoice.remaining_amount or 0) <= 0:
        raise PortalPaymentCreationError("Invoice ini sudah lunas.")


def _get_proof_attachment_for_branch(
    attachment_id: int, branch_id: int | None, reference_type: str = PAYMENT_PROOF_REFERENCE_TYPE
) -> DigitalAttachment:
    attachment = DigitalAttachment.query.filter(
        DigitalAttachment.id == attachment_id,
        DigitalAttachment.branch_id == branch_id,
        DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
        DigitalAttachment.reference_type == reference_type,
        DigitalAttachment.is_deleted.is_(False),
    ).first()
    if not attachment:
        raise PortalPaymentCreationError("Bukti pembayaran tidak ditemukan untuk cabang finance ini.")
    return attachment


def _normalize_payment_date(value) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value or "").strip(), "%Y-%m-%d").date()
    except (TypeError, ValueError) as error:
        raise PortalPaymentCreationError("Tanggal pembayaran tidak valid.") from error


def _validate_bank_account(payment_method: str, bank_account_id: int | None, branch_id: int) -> int | None:
    if payment_method != "TRANSFER":
        return None
    if not bank_account_id:
        raise PortalPaymentCreationError("Pembayaran transfer wajib memilih rekening bank penerima.")
    bank_account = BankAccount.query.filter_by(
        id=int(bank_account_id),
        branch_id=branch_id,
        is_active=True,
    ).first()
    if not bank_account:
        raise PortalPaymentCreationError("Rekening bank penerima tidak ditemukan atau tidak aktif.")
    return bank_account.id


def _generate_payment_number(payment_date: date) -> str:
    prefix = f"PAY-{payment_date.strftime('%Y%m%d')}"
    counter = Payment.query.filter(Payment.payment_number.like(f"{prefix}-%")).count() + 1
    while True:
        payment_number = f"{prefix}-{counter:03d}"
        if not Payment.query.filter_by(payment_number=payment_number).first():
            return payment_number
        counter += 1


def _build_collection_log(invoice: Invoice, payment: Payment, user_id: int | None) -> InvoiceCollectionLog:
    paid = float(payment.amount or 0)
    if invoice.status == "PAID" or float(invoice.remaining_amount or 0) <= 0:
        collection_status = "PAID"
        next_action = "Invoice sudah lunas. Tidak perlu follow up penagihan."
        response_note = f"Pembayaran {payment.payment_number} sebesar {_money(paid)} diterima melalui {payment.payment_method}. Invoice {invoice.invoice_number} sudah lunas."
    else:
        collection_status = "PARTIAL"
        next_action = "Follow up pelunasan sisa piutang."
        response_note = f"Pembayaran {payment.payment_number} sebesar {_money(paid)} diterima melalui {payment.payment_method}. Sisa piutang invoice {invoice.invoice_number}: {_money(invoice.remaining_amount)}."

    if payment.reference_number:
        response_note += f" Referensi: {payment.reference_number}."
    if payment.notes:
        response_note += f" Catatan payment: {payment.notes}."

    return InvoiceCollectionLog(
        branch_id=invoice.branch_id,
        invoice_id=invoice.id,
        follow_up_date=payment.payment_date,
        channel="SYSTEM",
        contact_person="SYSTEM - Portal Payment Verified",
        response_note=response_note,
        promise_date=None,
        next_action=next_action,
        collection_status=collection_status,
        created_by=user_id,
    )


def _append_payment_created_note(existing: str | None, payment_number: str) -> str:
    line = f"PAYMENT_CREATED_FROM_VERIFIED_PROOF: {payment_number}"
    return f"{existing}\n{line}" if existing else line


def _notify_portal_payment_created(
    attachment: DigitalAttachment,
    invoice: Invoice,
    payment: Payment,
    finance_user,
) -> None:
    if not attachment.uploaded_by:
        return
    create_or_update_notification(
        branch_id=invoice.branch_id,
        notification_type="PORTAL_PAYMENT_CREATED",
        title=f"Payment resmi dibuat: {payment.payment_number}",
        message=f"Pembayaran invoice {invoice.invoice_number} sudah dicatat resmi oleh finance.",
        target_user_id=attachment.uploaded_by,
        priority="INFO",
        reference_type="PAYMENT",
        reference_id=payment.id,
        action_url=f"/portal/invoices/{invoice.id}/payment",
        generated_key=f"portal-payment-created-{payment.id}",
        metadata={
            "attachment_id": attachment.id,
            "invoice_id": invoice.id,
            "payment_id": payment.id,
            "created_by": getattr(finance_user, "id", None),
            "mutation_scope": "NOTIFICATION_ONLY",
        },
        commit=False,
    )


def _money(value) -> str:
    return f"Rp {float(value or 0):,.0f}".replace(",", ".")


def _payment_result(payment: Payment, invoice: Invoice, attachment, *, idempotent_replay: bool) -> dict:
    return {
        "payment_id": payment.id,
        "payment_number": payment.payment_number,
        "invoice_id": invoice.id,
        "invoice_number": invoice.invoice_number,
        "invoice_status": invoice.status,
        "invoice_paid_amount": invoice.paid_amount,
        "invoice_remaining_amount": invoice.remaining_amount,
        "amount": payment.amount,
        "proof_attachment_id": attachment.id,
        "proof_attachment_type": attachment.attachment_type,
        "payment_created": True,
        "idempotent_replay": idempotent_replay,
    }


def _replay_completed_payment(idempotency_record) -> dict:
    payload = json.loads(idempotency_record.response_payload_json or "{}")
    payment = Payment.query.get(payload.get("payment_id"))
    if not payment:
        raise PortalPaymentCreationError("Hasil idempotency payment tidak ditemukan.")
    invoice = Invoice.query.get(payment.invoice_id)
    attachment_id = payload.get("attachment_id")
    attachment = _get_proof_attachment_for_branch(attachment_id, payment.branch_id)
    return _payment_result(payment, invoice, attachment, idempotent_replay=True)
