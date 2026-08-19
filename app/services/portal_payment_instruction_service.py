from __future__ import annotations

from decimal import Decimal

from app.services.company_settings_service import get_company_settings
from app.services.invoice_identity_service import get_invoice_official_identity
from app.services.portal_financial_visibility_service import get_portal_owned_invoice
from app.models.system import DigitalAttachment


NON_PAYABLE_INVOICE_STATUSES = {"CANCELLED", "VOID", "VOIDED", "PAID"}
PORTAL_PAYMENT_MODULE = "PORTAL_PAYMENT"
PAYMENT_PROOF_REFERENCE_TYPE = "INVOICE"


def _money(value) -> Decimal:
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _clean(value) -> str:
    return str(value or "").strip()


def _status(value) -> str:
    return _clean(value).upper()


def build_portal_payment_instruction(user, *, invoice_id: int) -> dict:
    """Return static payment instructions for one owned invoice.

    This is Stage 3A only: it does not create payments, allocations, journals,
    cash/bank rows, upload records, or paid status.
    """
    owned = get_portal_owned_invoice(user, invoice_id)
    if not owned["allowed"]:
        return {
            "allowed": False,
            "scope_mode": owned["scope_mode"],
            "reason": owned["reason"],
            "invoice": None,
            "payable": False,
            "amount_due": Decimal("0"),
            "bank_transfer": _empty_bank_instruction(),
            "qris": _empty_qris_instruction(),
            "proofs": [],
            "proof_summary": _empty_proof_summary(),
            "mutation_allowed": False,
        }

    invoice = owned["invoice"]
    invoice_status = _status(invoice.status)
    amount_due = _money(invoice.remaining_amount)
    payable = invoice_status not in NON_PAYABLE_INVOICE_STATUSES and amount_due > 0
    identity = get_invoice_official_identity(invoice)
    settings = get_company_settings(invoice.branch_id)

    return {
        "allowed": True,
        "scope_mode": owned["scope_mode"],
        "reason": "Instruksi pembayaran statis untuk invoice milik user portal.",
        "invoice": {
            "invoice_id": invoice.id,
            "invoice_number": invoice.invoice_number,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "status": invoice_status,
            "remaining_amount": amount_due,
        },
        "payable": payable,
        "amount_due": amount_due if payable else Decimal("0"),
        "bank_transfer": _bank_instruction(identity),
        "qris": _qris_instruction(settings),
        "proofs": _payment_proof_rows(invoice.id),
        "proof_summary": _payment_proof_summary(invoice.id),
        "mutation_allowed": False,
    }


def _payment_proof_rows(invoice_id: int) -> list[dict]:
    attachments = (
        DigitalAttachment.query.filter(
            DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
            DigitalAttachment.reference_type == PAYMENT_PROOF_REFERENCE_TYPE,
            DigitalAttachment.reference_id == invoice_id,
            DigitalAttachment.is_deleted.is_(False),
        )
        .order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc())
        .all()
    )
    return [
        {
            "attachment_id": attachment.id,
            "attachment_type": attachment.attachment_type,
            "filename": attachment.original_filename,
            "file_size": attachment.file_size,
            "uploaded_at": attachment.created_at,
            "notes": attachment.notes,
        }
        for attachment in attachments
    ]


def _empty_proof_summary() -> dict:
    return {
        "count": 0,
        "pending": 0,
        "verified": 0,
        "rejected": 0,
        "payment_created": 0,
        "latest_status": "Belum ada bukti",
    }


def _payment_proof_summary(invoice_id: int) -> dict:
    rows = _payment_proof_rows(invoice_id)
    summary = _empty_proof_summary()
    summary["count"] = len(rows)
    for row in rows:
        attachment_type = row["attachment_type"]
        if attachment_type == "PAYMENT_PROOF_PENDING":
            summary["pending"] += 1
        elif attachment_type == "PAYMENT_PROOF_VERIFIED":
            summary["verified"] += 1
        elif attachment_type == "PAYMENT_PROOF_REJECTED":
            summary["rejected"] += 1
        elif attachment_type == "PAYMENT_PROOF_PAYMENT_CREATED":
            summary["payment_created"] += 1
    if rows:
        latest = rows[0]["attachment_type"]
        summary["latest_status"] = {
            "PAYMENT_PROOF_PENDING": "Menunggu Finance",
            "PAYMENT_PROOF_VERIFIED": "Diverifikasi",
            "PAYMENT_PROOF_REJECTED": "Ditolak",
            "PAYMENT_PROOF_PAYMENT_CREATED": "Payment Dibuat",
        }.get(latest, latest)
    return summary


def _empty_bank_instruction() -> dict:
    return {
        "available": False,
        "bank_name": "",
        "account_number": "",
        "account_name": "",
        "missing": ["rekening pembayaran PT"],
    }


def _bank_instruction(identity: dict) -> dict:
    bank_name = _clean(identity.get("bank_name"))
    account_number = _clean(identity.get("bank_account_number"))
    account_name = _clean(identity.get("bank_account_name"))
    missing = []
    if not bank_name:
        missing.append("nama bank")
    if not account_number:
        missing.append("nomor rekening")
    if not account_name:
        missing.append("nama pemilik rekening")
    return {
        "available": not missing,
        "bank_name": bank_name,
        "account_number": account_number,
        "account_name": account_name,
        "missing": missing,
    }


def _empty_qris_instruction() -> dict:
    return {
        "available": False,
        "label": "",
        "image_url": "",
        "note": "",
    }


def _qris_instruction(settings: dict) -> dict:
    label = _clean(settings.get("payment_qris_label"))
    image_url = _clean(settings.get("payment_qris_image_url"))
    note = _clean(settings.get("payment_qris_note"))
    available = bool(label or image_url or note)
    return {
        "available": available,
        "label": label,
        "image_url": image_url,
        "note": note,
    }
