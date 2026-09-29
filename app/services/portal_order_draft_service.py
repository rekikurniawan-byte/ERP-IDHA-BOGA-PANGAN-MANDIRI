from datetime import date, datetime, time
from decimal import Decimal

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import lazyload

from app.extensions import db
from app.models.accounting import PeriodClosing
from app.models.contract import CustomerContract
from app.models.master import DeliveryLocation
from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import Invoice
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.production import Production
from app.models.system import DigitalAttachment, PortalOrderDraft
from app.services.approval_service import ensure_action_has_approval, has_approved_request
from app.services.credit_control_service import (
    credit_gate_from_decision,
    estimate_order_amount,
    evaluate_credit,
)
from app.services.notification_service import create_or_update_notification
from app.services.portal_financial_visibility_service import build_portal_invoice_read_model
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, build_portal_external_scope
from app.services.user_management_service import ROLE_ADMIN, ROLE_PORTAL_CUSTOMER, ROLE_PORTAL_SUBCLIENT, ROLE_PORTAL_CLIENT
from app.services.operational_service import generate_order_number
from app.utils.terms import T


DRAFT_STATUS_PENDING = "PENDING_ADMIN_CONFIRMATION"
DRAFT_STATUS_CONFIRMED = "CONFIRMED"
DRAFT_STATUS_REJECTED = "REJECTED"
MEAL_TYPES = {"LUNCH", "DINNER"}
PORTAL_CUTOFF_TIMES = {
    "LUNCH": time(10, 0),
    "DINNER": time(15, 0),
}
PAYMENT_PROOF_REFERENCE_TYPE = "INVOICE"
PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE = "PORTAL_ORDER_DRAFT"
PORTAL_PAYMENT_MODULE = "PORTAL_PAYMENT"
PAYMENT_PROOF_PENDING_TYPE = "PAYMENT_PROOF_PENDING"
PAYMENT_PROOF_VERIFIED_TYPES = {"PAYMENT_PROOF_VERIFIED", "PAYMENT_PROOF_PAYMENT_CREATED"}
PORTAL_CREDIT_APPROVAL_ACTION = "PORTAL_ORDER_CREDIT_OVERRIDE"
PORTAL_CUTOFF_APPROVAL_ACTION = "PORTAL_ORDER_CUTOFF_OVERRIDE"
MEAL_TYPE_LABELS = {
    "LUNCH": "Makan Siang",
    "DINNER": "Makan Malam",
}
STATUS_LABELS = {
    DRAFT_STATUS_PENDING: "Menunggu Admin",
    DRAFT_STATUS_CONFIRMED: "Dikonfirmasi",
    DRAFT_STATUS_REJECTED: "Ditolak",
    "WAITING_ADMIN": "Menunggu Admin",
    "ADMIN_CONFIRMED": "Dikonfirmasi Admin",
    "LOCKED": "Dikunci",
    "PRODUCTION": "Produksi",
    "PRODUCTION_DONE": "Produksi Selesai",
    "DELIVERY": "Pengiriman",
    "DELIVERED": "Terkirim",
    "CONFIRMED": "Dikonfirmasi",
    "DRAFT": "Konsep",
    "CANCELLED": "Dibatalkan",
    "READY": "Siap Dikonfirmasi",
    "BLOCKED": "Perlu Review",
    "NEW_DRAFT": "Buat Order Harian Baru",
}


def _clean_text(value):
    return (value or "").strip()


def _label_status(value):
    key = str(value or "").strip().upper()
    return STATUS_LABELS.get(key, key.replace("_", " ").title() if key else "-")


def _meal_label(value):
    key = str(value or "").strip().upper()
    return MEAL_TYPE_LABELS.get(key, key.replace("_", " ").title() if key else "-")


def _parse_date(value):
    try:
        return date.fromisoformat(_clean_text(value))
    except (TypeError, ValueError):
        return None


def _parse_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _money(value):
    if value is None:
        return Decimal("0")
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _commit_or_rollback():
    try:
        db.session.commit()
    except SQLAlchemyError:
        db.session.rollback()
        raise


def orderable_location_ids(user, scope):
    """Lokasi yang boleh dipesan akun portal ini.

    Client/PT melihat semua sub client-nya, tapi hanya boleh memesan untuk
    unit order langsungnya sendiri ("PT X — Langsung"); order untuk mandor
    tetap dibuat mandor itu sendiri (keputusan owner 2026-09-25). Role lain
    memesan untuk seluruh lokasi dalam aksesnya, seperti sebelumnya.
    """
    if not scope.allowed or not scope.delivery_location_ids:
        return set()
    if getattr(user, "role", None) != ROLE_PORTAL_CLIENT:
        return set(scope.delivery_location_ids)

    from app.services.client_direct_order_service import direct_unit_ids

    units = direct_unit_ids(scope.mandor_ids)
    if not units:
        return set()
    return {
        row.id
        for row in DeliveryLocation.query.filter(
            DeliveryLocation.id.in_(sorted(scope.delivery_location_ids)),
            DeliveryLocation.mandor_id.in_(sorted(units)),
        ).with_entities(DeliveryLocation.id).all()
    }


def _allowed_location_options(scope, location_ids=None):
    if not scope.allowed:
        return []
    location_ids = scope.delivery_location_ids if location_ids is None else location_ids
    if not location_ids:
        return []
    return (
        DeliveryLocation.query.filter(DeliveryLocation.id.in_(sorted(location_ids)))
        .order_by(DeliveryLocation.location_name.asc())
        .all()
    )


def _delivery_fee_label(branch_id, client, location):
    """Ongkir yang akan dikenakan ke lokasi ini, untuk ditampilkan sebelum memesan."""
    from app.services.pricing_service import FEE_SOURCE_INCLUDED, free_delivery_min_portions, quote_trip_fee

    fee, source, error = quote_trip_fee(branch_id, client, location, 1)
    if error:
        return "ongkir belum tersedia"
    if source == FEE_SOURCE_INCLUDED or not fee:
        return "ongkir termasuk"
    threshold = free_delivery_min_portions(branch_id)
    free_note = f" (gratis mulai {threshold} porsi)" if threshold else ""
    return f"ongkir Rp {fee:,.0f}/pengiriman{free_note}".replace(",", ".")


def _location_option_cards(locations):
    from app.services.pricing_service import general_min_portions, is_general_client, quote_price

    cards = []
    for location in locations:
        mandor = location.mandor
        client = mandor.client if mandor else None
        quote = quote_price(mandor.branch_id, getattr(client, "id", None)) if mandor else None
        cards.append(
            {
                "price_per_portion": quote.price if quote else None,
                "price_label": quote.source_label if quote else None,
                "delivery_fee_label": _delivery_fee_label(mandor.branch_id, client, location) if mandor else None,
                "min_portions": general_min_portions(mandor.branch_id) if mandor and is_general_client(client) else None,
                "id": location.id,
                "name": location.location_name,
                "description": location.description,
                "mandor_id": mandor.id if mandor else None,
                "mandor_name": mandor.name if mandor else "-",
                "mandor_phone": mandor.phone if mandor else None,
                "client_id": client.id if client else None,
                "client_name": client.name if client else "-",
                "client_phone": client.phone if client else None,
                "branch_id": mandor.branch_id if mandor else None,
                "is_active": bool(location.is_active),
                "label": " - ".join(
                    part
                    for part in [
                        location.location_name,
                        mandor.name if mandor else None,
                        client.name if client else None,
                    ]
                    if part
                ),
            }
        )
    return cards


def _draft_summary(drafts):
    by_status = {}
    by_meal_type = {meal_type: 0 for meal_type in sorted(MEAL_TYPES)}
    portion_total = 0
    next_pending = None
    for draft in drafts:
        by_status[draft.status] = by_status.get(draft.status, 0) + 1
        by_meal_type[draft.meal_type] = by_meal_type.get(draft.meal_type, 0) + int(draft.portion_qty or 0)
        portion_total += int(draft.portion_qty or 0)
        if draft.status == DRAFT_STATUS_PENDING:
            if not next_pending or draft.order_date < next_pending.order_date:
                next_pending = draft
    return {
        "total": len(drafts),
        "pending": by_status.get(DRAFT_STATUS_PENDING, 0),
        "confirmed": by_status.get(DRAFT_STATUS_CONFIRMED, 0),
        "rejected": by_status.get(DRAFT_STATUS_REJECTED, 0),
        "portion_total": portion_total,
        "lunch_portion_total": by_meal_type.get("LUNCH", 0),
        "dinner_portion_total": by_meal_type.get("DINNER", 0),
        "next_pending_date": next_pending.order_date if next_pending else None,
    }


def _portal_payment_precheck(user, scope):
    role = getattr(user, "role", None)
    if role == ROLE_PORTAL_CUSTOMER:
        proof_rows = (
            DigitalAttachment.query.filter(
                DigitalAttachment.uploaded_by == getattr(user, "id", None),
                DigitalAttachment.module == "PORTAL_PAYMENT",
                DigitalAttachment.reference_type.in_([PAYMENT_PROOF_REFERENCE_TYPE, PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE]),
                DigitalAttachment.is_deleted.is_(False),
            )
            .order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc())
            .limit(20)
            .all()
        )
        pending = sum(1 for row in proof_rows if row.attachment_type == "PAYMENT_PROOF_PENDING")
        verified = sum(
            1
            for row in proof_rows
            if row.attachment_type in {"PAYMENT_PROOF_VERIFIED", "PAYMENT_PROOF_PAYMENT_CREATED"}
        )
        rejected = sum(1 for row in proof_rows if row.attachment_type == "PAYMENT_PROOF_REJECTED")
        if verified:
            status = "Bukti Pembayaran Terverifikasi"
            tone = "green"
        elif pending:
            status = "Bukti Menunggu Finance"
            tone = "orange"
        elif rejected:
            status = "Bukti Ditolak"
            tone = "red"
        else:
            status = "Wajib Bayar Dulu"
            tone = "red"
        return {
            "required": True,
            "allowed_to_process": bool(verified),
            "status": status,
            "tone": tone,
            "message": "Pelanggan umum wajib memiliki pembayaran terverifikasi sebelum order diproses.",
            "proof_count": len(proof_rows),
            "pending_count": pending,
            "verified_count": verified,
            "rejected_count": rejected,
            "payable_invoice_count": 0,
            "outstanding_amount": 0,
            "action_endpoint": "portal.customer_payments",
            "action_label": "Cek Pembayaran",
        }

    invoice_model = build_portal_invoice_read_model(user, limit=20)
    totals = invoice_model.get("totals", {})
    outstanding = totals.get("active_outstanding_amount", 0)
    payable = totals.get("payable_invoice_count", totals.get("invoice_count", 0))
    return {
        "required": False,
        "allowed_to_process": bool(scope.allowed),
        "status": "Tempo/Kredit Sesuai Mapping",
        "tone": "green" if scope.allowed else "red",
        "message": f"{T.sub_client}/{T.client_lower} mengikuti aturan tempo atau kredit yang sudah disetujui. Pembayaran tetap dicatat oleh bagian keuangan.",
        "proof_count": totals.get("proof_count", 0),
        "pending_count": totals.get("pending_proof_count", 0),
        "verified_count": totals.get("verified_proof_count", 0),
        "rejected_count": totals.get("rejected_proof_count", 0),
        "payable_invoice_count": payable,
        "outstanding_amount": outstanding,
        "action_endpoint": "portal.mandor_payments" if role != "PORTAL_CLIENT" else "portal.pt_receivables",
        "action_label": "Lihat Pembayaran",
    }


def _draft_payment_proof_counts(draft):
    rows = (
        DigitalAttachment.query.filter(
            DigitalAttachment.module == PORTAL_PAYMENT_MODULE,
            DigitalAttachment.reference_type == PORTAL_DRAFT_PAYMENT_REFERENCE_TYPE,
            DigitalAttachment.reference_id == draft.id,
            DigitalAttachment.is_deleted.is_(False),
        )
        .order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc())
        .all()
    )
    pending = sum(1 for row in rows if row.attachment_type == PAYMENT_PROOF_PENDING_TYPE)
    verified = sum(1 for row in rows if row.attachment_type in PAYMENT_PROOF_VERIFIED_TYPES)
    rejected = sum(1 for row in rows if row.attachment_type == "PAYMENT_PROOF_REJECTED")
    # Diverifikasi tapi uang mukanya belum dicatat Finance.
    unrecorded = sum(1 for row in rows if row.attachment_type == "PAYMENT_PROOF_VERIFIED")
    return {
        "total": len(rows),
        "pending": pending,
        "verified": verified,
        "unrecorded": unrecorded,
        "rejected": rejected,
        "latest": rows[0] if rows else None,
    }


def _active_contract_for_client(branch_id, client_id):
    if not branch_id or not client_id:
        return None
    return (
        CustomerContract.query.filter(
            CustomerContract.branch_id == branch_id,
            CustomerContract.client_id == client_id,
            CustomerContract.status == "ACTIVE",
        )
        .order_by(CustomerContract.end_date.desc(), CustomerContract.id.desc())
        .first()
    )


def _active_outstanding_for_scope(branch_id, client_id, mandor_id=None):
    if not branch_id or not client_id:
        return Decimal("0")
    query = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.client_id == client_id,
        Invoice.status.notin_(["CANCELLED", "PAID", "CLOSED"]),
    )
    if mandor_id:
        query = query.filter(Invoice.mandor_id == mandor_id)
    total = Decimal("0")
    for row in query.with_entities(Invoice.remaining_amount).all():
        total += _money(row.remaining_amount)
    return total


def draft_total_amount(draft):
    """Total yang harus dibayar untuk draft ini: harga terkunci × porsi + ongkir.

    None kalau draft belum punya harga terkunci (draft lama).
    """
    if not getattr(draft, "price_per_portion", None):
        return None
    return (
        Decimal(str(draft.price_per_portion)) * int(draft.portion_qty or 0)
        + Decimal(str(draft.delivery_fee or 0))
    )


def _credit_gate_for_draft(draft):
    role = getattr(draft.user, "role", None) if draft.user else None
    if role not in {ROLE_PORTAL_SUBCLIENT, ROLE_PORTAL_CLIENT}:
        return {
            "key": "CREDIT",
            "title": "Kredit",
            "status": "NOT_REQUIRED",
            "label": "Tidak Berlaku",
            "tone": "neutral",
            "message": "Role ini tidak memakai fasilitas kredit.",
            "needs_approval": False,
            "approved": False,
            "amount": Decimal("0"),
            "limit": Decimal("0"),
        }

    # Pihak yang kreditnya sudah disetel owner dinilai oleh penilai bersama --
    # yang sama dengan jalur order internal. Pihak lain tetap memakai aturan
    # kontrak lama di bawah, tanpa perubahan.
    # Draft yang sudah punya harga terkunci dinilai dengan total sebenarnya;
    # draft lama (sebelum daftar harga) tetap memakai perkiraan.
    estimated_amount = draft_total_amount(draft)
    if estimated_amount is None:
        estimated_amount = estimate_order_amount(
            draft.branch_id, draft.mandor_id, draft.portion_qty, draft.delivery_location_id
        )
    decision = evaluate_credit(
        draft.branch_id,
        client_id=draft.client_id,
        mandor_id=draft.mandor_id,
        pending_amount=estimated_amount,
    )
    if decision.enforced:
        approved = has_approved_request(
            branch_id=draft.branch_id,
            action_key=PORTAL_CREDIT_APPROVAL_ACTION,
            reference_type="PORTAL_ORDER_DRAFT",
            reference_id=draft.id,
        )
        return credit_gate_from_decision(decision, approved=approved)

    contract = _active_contract_for_client(draft.branch_id, draft.client_id)
    outstanding = _active_outstanding_for_scope(
        draft.branch_id,
        draft.client_id,
        draft.mandor_id if role == ROLE_PORTAL_SUBCLIENT else None,
    )
    limit_amount = _money(getattr(contract, "credit_limit", 0))
    over_limit = bool(contract and limit_amount > 0 and outstanding > limit_amount)
    approved = has_approved_request(
        branch_id=draft.branch_id,
        action_key=PORTAL_CREDIT_APPROVAL_ACTION,
        reference_type="PORTAL_ORDER_DRAFT",
        reference_id=draft.id,
    )
    if not contract:
        return {
            "key": "CREDIT",
            "title": "Kredit",
            "status": "WARNING",
            "label": "Kontrak Belum Aktif",
            "tone": "orange",
            "message": "Belum ada kontrak aktif. Admin boleh lanjut jika kebijakan kredit perusahaan mengizinkan.",
            "needs_approval": False,
            "approved": False,
            "amount": outstanding,
            "limit": Decimal("0"),
        }
    if over_limit and not approved:
        return {
            "key": "CREDIT",
            "title": "Kredit",
            "status": "APPROVAL_REQUIRED",
            "label": "Melewati Limit",
            "tone": "red",
            "message": "Outstanding melebihi limit kontrak. Approval checker wajib sebelum konfirmasi order.",
            "needs_approval": True,
            "approved": False,
            "amount": outstanding,
            "limit": limit_amount,
        }
    return {
        "key": "CREDIT",
        "title": "Kredit",
        "status": "APPROVED" if approved else "OK",
        "label": "Approval Ada" if approved else "Aman",
        "tone": "green",
        "message": "Outstanding berada dalam batas kontrak aktif." if not approved else "Approval kredit sudah disetujui.",
        "needs_approval": False,
        "approved": approved,
        "amount": outstanding,
        "limit": limit_amount,
    }


def _cutoff_gate_for_draft(draft):
    cutoff_at = PORTAL_CUTOFF_TIMES.get(str(draft.meal_type or "").upper())
    now = datetime.now()
    today = now.date()
    if draft.order_date < today:
        return {
            "key": "CUTOFF",
            "title": "Batas Waktu",
            "status": "BLOCKED",
            "label": "Tanggal Lampau",
            "tone": "red",
            "message": "Tanggal order sudah lewat. Buat draft tanggal baru atau proses koreksi manual.",
            "needs_approval": False,
            "approved": False,
            "cutoff_label": "-",
        }
    if draft.order_date == today and cutoff_at and now.time() > cutoff_at:
        approved = has_approved_request(
            branch_id=draft.branch_id,
            action_key=PORTAL_CUTOFF_APPROVAL_ACTION,
            reference_type="PORTAL_ORDER_DRAFT",
            reference_id=draft.id,
        )
        return {
            "key": "CUTOFF",
            "title": "Batas Waktu",
            "status": "APPROVED" if approved else "APPROVAL_REQUIRED",
            "label": "Approval Ada" if approved else "Lewat Cut-off",
            "tone": "green" if approved else "orange",
            "message": (
                "Approval cut-off sudah disetujui."
                if approved
                else "Order hari ini melewati batas waktu. Approval checker wajib sebelum diproses."
            ),
            "needs_approval": not approved,
            "approved": approved,
            "cutoff_label": cutoff_at.strftime("%H:%M"),
        }
    return {
        "key": "CUTOFF",
        "title": "Batas Waktu",
        "status": "OK",
        "label": "Aman",
        "tone": "green",
        "message": "Tanggal dan sesi masih sesuai batas waktu portal.",
        "needs_approval": False,
        "approved": False,
        "cutoff_label": cutoff_at.strftime("%H:%M") if cutoff_at else "-",
    }


def _closing_gate_for_draft(draft):
    closing = PeriodClosing.query.filter_by(
        branch_id=draft.branch_id,
        period_year=draft.order_date.year,
        period_month=draft.order_date.month,
    ).first()
    if closing and str(closing.status or "").upper() == "POSTED":
        return {
            "key": "CLOSING",
            "title": "Periode",
            "status": "BLOCKED",
            "label": "Sudah Closing",
            "tone": "red",
            "message": "Periode order sudah closing. Draft tidak boleh masuk order operasional.",
            "closing_number": closing.closing_number,
        }
    return {
        "key": "CLOSING",
        "title": "Periode",
        "status": "OK",
        "label": "Masih Terbuka",
        "tone": "green",
        "message": "Tidak ada closing posted untuk periode order ini.",
        "closing_number": None,
    }


def _payment_gate_for_draft(draft, owner_override=False):
    """Pesanan jalur UMUM baru boleh diproses kalau uang mukanya menutup total.

    Uang muka = pembayaran yang sudah diverifikasi Finance dan dicatat sebagai
    Uang Muka Pelanggan (2008), bukan sekadar bukti yang diunggah. OWNER boleh
    meloloskan (owner_override); keputusannya dicatat saat konfirmasi.
    """
    from app.services.prepaid_order_service import rupiah, draft_prepaid_amount, draft_requires_prepayment

    if not draft_requires_prepayment(draft):
        return {
            "key": "PAYMENT",
            "title": "Pembayaran Awal",
            "status": "NOT_REQUIRED",
            "label": "Tempo/Kredit",
            "tone": "green",
            "message": f"{T.sub_client}/{T.client_lower} mengikuti aturan kredit dan pembayaran perusahaan.",
            "needs_payment": False,
            "proof": {"total": 0, "pending": 0, "verified": 0, "rejected": 0},
        }
    proof = _draft_payment_proof_counts(draft)
    total = draft_total_amount(draft)
    paid = draft_prepaid_amount(draft)
    base = {"key": "PAYMENT", "title": "Pembayaran Awal", "proof": proof, "total_amount": total, "paid_amount": paid}
    if total is not None and paid >= total:
        return {
            **base,
            "status": "OK",
            "label": "Lunas di muka",
            "tone": "green",
            "message": f"Uang muka {rupiah(paid)} sudah tercatat, menutup total {rupiah(total)}.",
            "needs_payment": False,
        }
    due_note = f"Total {rupiah(total)}, sudah dibayar {rupiah(paid)}." if total is not None else "Total belum bisa dihitung."
    if owner_override:
        return {
            **base,
            "status": "OVERRIDE",
            "label": "Diloloskan OWNER",
            "tone": "orange",
            "message": f"OWNER meloloskan pesanan sebelum lunas. {due_note}",
            "needs_payment": False,
        }
    if proof["pending"] or proof.get("unrecorded"):
        return {
            **base,
            "status": "BLOCKED",
            "label": "Menunggu Finance",
            "tone": "orange",
            "message": f"Bukti pembayaran menunggu Finance mencatat uang mukanya. {due_note}",
            "needs_payment": True,
        }
    if paid > 0 and total is not None:
        return {
            **base,
            "status": "BLOCKED",
            "label": "Kurang Bayar",
            "tone": "red",
            "message": f"Pembayaran kurang {rupiah(total - paid)}. {due_note}",
            "needs_payment": True,
        }
    return {
        **base,
        "status": "BLOCKED",
        "label": "Wajib Bayar Dulu",
        "tone": "red",
        "message": f"Pelanggan umum wajib membayar di muka sebelum pesanan diproses. {due_note}",
        "needs_payment": True,
    }


def _contract_gate_for_draft(draft, owner_override=False):
    """Kontrak client yang sudah berakhir dan belum diperpanjang menahan pesanan
    baru sampai OWNER meloloskannya dengan alasan (keputusan owner 2026-09-28)."""
    from app.services.contract_lifecycle_service import lapsed_contract, lapsed_contract_message

    base = {"key": "CONTRACT", "title": "Kontrak"}
    lapsed = lapsed_contract(draft.branch_id, draft.client_id)
    if lapsed is None:
        return {**base, "status": "OK", "label": "Aman", "tone": "green",
                "message": "Tidak ada kontrak yang berakhir tanpa perpanjangan."}
    message = lapsed_contract_message(lapsed)
    if owner_override:
        return {**base, "status": "OVERRIDE", "label": "Diloloskan OWNER", "tone": "orange",
                "message": f"OWNER meloloskan pesanan walau kontrak sudah berakhir. {message}",
                "contract_id": lapsed.id}
    return {**base, "status": "BLOCKED", "label": "Kontrak Berakhir", "tone": "red",
            "message": f"{message} Perpanjang kontraknya, atau OWNER meloloskan pesanan ini dengan alasan.",
            "contract_id": lapsed.id}


def _duplicate_gate_for_draft(draft, daily_order=None):
    daily_order = daily_order or DailyOrder.query.filter_by(
        branch_id=draft.branch_id,
        order_date=draft.order_date,
    ).first()
    existing_detail = None
    if daily_order:
        existing_detail = DailyOrderDetail.query.filter_by(
            daily_order_id=daily_order.id,
            mandor_id=draft.mandor_id,
            delivery_location_id=draft.delivery_location_id,
        ).first()
    if daily_order and daily_order.is_locked:
        return daily_order, existing_detail, {
            "key": "DUPLICATE",
            "title": "Order Internal",
            "status": "BLOCKED",
            "label": "Order Dikunci",
            "tone": "red",
            "message": "Order harian existing sudah dikunci.",
        }
    if existing_detail:
        merge_error = _merge_conflict(draft, existing_detail)
        if merge_error:
            return daily_order, existing_detail, {
                "key": "DUPLICATE",
                "title": "Order Internal",
                "status": "BLOCKED",
                "label": "Sudah Ada",
                "tone": "red",
                "message": merge_error,
            }
        return daily_order, existing_detail, {
            "key": "DUPLICATE",
            "title": "Order Internal",
            "status": "OK",
            "label": "Digabung",
            "tone": "green",
            "message": f"Digabung ke baris {T.sub_client_lower}/lokasi yang sama (sesi makan lain) di order harian ini.",
        }
    return daily_order, existing_detail, {
        "key": "DUPLICATE",
        "title": "Order Internal",
        "status": "OK",
        "label": "Aman",
        "tone": "green",
        "message": f"Belum ada detail {T.sub_client_lower}/lokasi yang bentrok.",
    }


def _merge_conflict(draft, detail):
    """Pesanan portal dikirim per sesi makan, tapi satu lokasi per hari punya satu
    baris order (siang + malam). Sesi yang masih kosong digabung ke baris itu
    (gladi pilot 2026-09-28: mandor tidak bisa memesan siang dan malam). Yang
    ditolak hanya sesi yang sudah terisi (pesanan ganda) atau harga berbeda.
    """
    meal_qty = detail.lunch_qty if draft.meal_type == "LUNCH" else detail.dinner_qty
    if int(meal_qty or 0) > 0:
        return f"Pesanan {_meal_label(draft.meal_type).lower()} untuk {T.location_lower} ini sudah ada di order harian tanggal ini."
    if draft.price_per_portion is not None and detail.price_per_portion is not None and (
        _money(draft.price_per_portion) != _money(detail.price_per_portion)
    ):
        return (
            f"Harga draft Rp {_money(draft.price_per_portion):,.0f} berbeda dengan pesanan lain di "
            f"{T.location_lower} ini (Rp {_money(detail.price_per_portion):,.0f}). Review manual diperlukan."
        )
    return None


# Penghalang yang boleh diloloskan OWNER dengan alasan, dan sebutannya di layar.
OWNER_OVERRIDABLE_GATES = {"PAYMENT": "belum lunas di muka", "CONTRACT": "kontrak sudah berakhir"}


def _owner_override_reasons(gate):
    """Sebutan penghalang kalau SEMUA penghalangnya boleh diloloskan OWNER; kosong kalau tidak."""
    blocked = [item for item in gate["gates"] if item["status"] == "BLOCKED"]
    approvals = [item for item in gate["gates"] if item.get("needs_approval")]
    if not blocked or approvals or any(item["key"] not in OWNER_OVERRIDABLE_GATES for item in blocked):
        return []
    return [OWNER_OVERRIDABLE_GATES[item["key"]] for item in blocked]


def evaluate_portal_order_draft_gate(
    draft, *, daily_order=None, request_approval=False, requested_by=None, owner_override=False
):
    daily_order, existing_detail, duplicate_gate = _duplicate_gate_for_draft(draft, daily_order=daily_order)
    gates = [
        _payment_gate_for_draft(draft, owner_override=owner_override),
        _contract_gate_for_draft(draft, owner_override=owner_override),
        _credit_gate_for_draft(draft),
        _cutoff_gate_for_draft(draft),
        _closing_gate_for_draft(draft),
        duplicate_gate,
    ]
    blockers = [gate["message"] for gate in gates if gate["status"] == "BLOCKED"]
    approvals = [gate for gate in gates if gate.get("needs_approval")]
    approval_messages = []
    if request_approval and approvals:
        for gate in approvals:
            action_key = PORTAL_CREDIT_APPROVAL_ACTION if gate["key"] == "CREDIT" else PORTAL_CUTOFF_APPROVAL_ACTION
            _, request_row, message = ensure_action_has_approval(
                branch_id=draft.branch_id,
                action_key=action_key,
                reference_type="PORTAL_ORDER_DRAFT",
                reference_id=draft.id,
                requested_by=requested_by or draft.user_id,
                requested_reason=gate["message"],
                payload={
                    "draft_id": draft.id,
                    "order_date": draft.order_date,
                    "meal_type": draft.meal_type,
                    "portion_qty": draft.portion_qty,
                    "gate": gate["key"],
                    "source": "portal_order_draft_service",
                },
                # Konfirmasi draft memegang kunci baris draft; commit sekali di
                # akhir alur konfirmasi, bukan di tengah (kunci tidak lepas lebih awal).
                commit=False,
            )
            approval_messages.append(f"{gate['title']}: {message} (approval #{request_row.id})")
    can_confirm = not blockers and not approvals
    return {
        "can_confirm": can_confirm,
        "review_status": "READY" if can_confirm else "BLOCKED",
        "review_status_label": _label_status("READY" if can_confirm else "BLOCKED"),
        "gates": gates,
        "blockers": blockers + [gate["message"] for gate in approvals],
        "warnings": [
            gate["message"]
            for gate in gates
            if gate["status"] in {"WARNING", "WAITING_FINANCE"}
        ]
        + approval_messages,
        "needs_payment": any(gate.get("needs_payment") for gate in gates),
        "needs_approval": bool(approvals),
        "daily_order": daily_order,
        "existing_detail": existing_detail,
    }


def _daily_order_conflict_cards(scope, limit=12):
    if not scope.allowed or not scope.delivery_location_ids:
        return []

    rows = (
        DailyOrderDetail.query.join(DailyOrder, DailyOrderDetail.daily_order_id == DailyOrder.id)
        .join(DeliveryLocation, DailyOrderDetail.delivery_location_id == DeliveryLocation.id)
        .filter(
            DailyOrderDetail.delivery_location_id.in_(sorted(scope.delivery_location_ids)),
            DailyOrder.status != "CANCELLED",
        )
        .order_by(DailyOrder.order_date.desc(), DailyOrder.id.desc(), DailyOrderDetail.id.desc())
        .limit(limit)
        .all()
    )
    cards = []
    for detail in rows:
        order = detail.daily_order
        location = detail.delivery_location
        meal_parts = []
        if int(detail.lunch_qty or 0) > 0:
            meal_parts.append(f"Lunch {int(detail.lunch_qty or 0)}")
        if int(detail.dinner_qty or 0) > 0:
            meal_parts.append(f"Dinner {int(detail.dinner_qty or 0)}")
        cards.append(
            {
                "daily_order_id": order.id,
                "daily_order_detail_id": detail.id,
                "order_number": order.order_number,
                "order_date": order.order_date,
                "status": order.status,
                "is_locked": bool(order.is_locked),
                "location_id": location.id if location else None,
                "location_name": location.location_name if location else "-",
                "mandor_name": detail.mandor.name if detail.mandor else "-",
                "portion_label": ", ".join(meal_parts) or f"Total {int(detail.total_qty or 0)}",
                "total_qty": int(detail.total_qty or 0),
            }
        )
    return cards


def _latest_scope_drafts(user, scope, limit=10):
    if not scope.allowed or not scope.delivery_location_ids:
        return []
    return (
        PortalOrderDraft.query.filter(
            PortalOrderDraft.user_id == getattr(user, "id", None),
            PortalOrderDraft.delivery_location_id.in_(sorted(scope.delivery_location_ids)),
        )
        .order_by(PortalOrderDraft.submitted_at.desc(), PortalOrderDraft.id.desc())
        .limit(limit)
        .all()
    )


def _draft_history_rows(drafts):
    from app.services.prepaid_order_service import draft_prepaid_amount, draft_requires_prepayment

    rows = []
    for draft in drafts:
        gate = evaluate_portal_order_draft_gate(draft) if draft.status == DRAFT_STATUS_PENDING else None
        total = draft_total_amount(draft) if draft_requires_prepayment(draft) else None
        paid = draft_prepaid_amount(draft) if total is not None else None
        rows.append(
            {
                "total_amount": total,
                "paid_amount": paid,
                "amount_due": max(total - paid, 0) if total is not None else None,
                "draft": draft,
                "status_label": _label_status(draft.status),
                "meal_type_label": _meal_label(draft.meal_type),
                "gate": gate,
                "needs_payment": bool(gate and gate["needs_payment"]),
                "needs_approval": bool(gate and gate["needs_approval"]),
                "can_confirm": bool(gate and gate["can_confirm"]),
            }
        )
    return rows


def build_portal_draft_order_context(user):
    scope = build_portal_external_scope(user)
    drafts = list_portal_order_drafts(user)
    precheck = _portal_payment_precheck(user, scope)
    location_ids = orderable_location_ids(user, scope)
    locations = _allowed_location_options(scope, location_ids)
    is_customer = getattr(user, "role", None) == ROLE_PORTAL_CUSTOMER
    return {
        "allowed": scope.allowed and ACCESS_DRAFT_ORDER in scope.access_levels,
        # Untuk PT: True kalau client-nya punya unit order langsung yang
        # bisa dipesan. Tanpa itu PT tetap hanya memantau.
        "direct_ordering_enabled": bool(location_ids) if getattr(user, "role", None) == ROLE_PORTAL_CLIENT else None,
        "scope": scope,
        "reason": scope.reason if scope.allowed else scope.reason,
        "location_options": locations,
        "location_cards": _location_option_cards(locations),
        "drafts": drafts,
        "draft_rows": _draft_history_rows(drafts),
        "draft_summary": _draft_summary(drafts),
        "daily_order_conflicts": _daily_order_conflict_cards(scope),
        "latest_scope_drafts": _latest_scope_drafts(user, scope),
        "meal_types": MEAL_TYPE_LABELS,
        "prepayment_required": is_customer,
        "payment_precheck": precheck,
        "cutoff_times": {key: value.strftime("%H:%M") for key, value in PORTAL_CUTOFF_TIMES.items()},
    }


def list_portal_order_drafts(user, limit=25):
    user_id = getattr(user, "id", None)
    if not user_id:
        return []
    return (
        PortalOrderDraft.query.filter(PortalOrderDraft.user_id == user_id)
        .order_by(PortalOrderDraft.submitted_at.desc(), PortalOrderDraft.id.desc())
        .limit(limit)
        .all()
    )


def build_portal_order_status_context(user, limit=50):
    drafts = list_portal_order_drafts(user, limit=limit)
    rows = []
    for draft in drafts:
        order = draft.converted_daily_order
        detail = _find_converted_order_detail(draft, order)
        production = _find_related_production(draft, order)
        delivery_detail = _find_related_delivery_detail(detail)
        delivery = delivery_detail.delivery if delivery_detail else None
        stage = _resolve_portal_order_stage(draft, order, production, delivery, delivery_detail)
        rows.append(
            {
                "draft_id": draft.id,
                "order_date": draft.order_date,
                "meal_type": draft.meal_type,
                "meal_type_label": _meal_label(draft.meal_type),
                "portion_qty": draft.portion_qty,
                "location_name": draft.delivery_location.location_name if draft.delivery_location else "-",
                "draft_status": draft.status,
                "draft_status_label": _label_status(draft.status),
                "internal_order_number": order.order_number if order else "-",
                "internal_order_status": order.status if order else "-",
                "internal_order_status_label": _label_status(order.status if order else None),
                "internal_order_locked": order.is_locked if order else False,
                "daily_order_id": order.id if order else None,
                "daily_order_detail_id": detail.id if detail else None,
                "production_status": production.status if production else "-",
                "production_status_label": _label_status(production.status if production else None),
                "production_number": f"PROD-{production.id}" if production else "-",
                "delivery_number": delivery.delivery_number if delivery else "-",
                "delivery_status": delivery.status if delivery else "-",
                "delivery_status_label": _label_status(delivery.status if delivery else None),
                "delivered_qty": delivery_detail.delivered_qty if delivery_detail else 0,
                "shortage_qty": delivery_detail.shortage_qty if delivery_detail else 0,
                "stage": stage,
                "stage_label": _label_status(stage),
                "review_note": draft.review_note,
            }
        )
    return {
        "rows": rows,
        "total": len(rows),
        "pending": sum(1 for row in rows if row["draft_status"] == DRAFT_STATUS_PENDING),
        "confirmed": sum(1 for row in rows if row["draft_status"] == DRAFT_STATUS_CONFIRMED),
        "rejected": sum(1 for row in rows if row["draft_status"] == DRAFT_STATUS_REJECTED),
        "in_delivery": sum(1 for row in rows if row["stage"] in {"DELIVERY", "DELIVERED"}),
        "completed": sum(1 for row in rows if row["stage"] == "DELIVERED"),
    }


def _find_converted_order_detail(draft, order):
    if not order:
        return None
    return DailyOrderDetail.query.filter_by(
        daily_order_id=order.id,
        mandor_id=draft.mandor_id,
        delivery_location_id=draft.delivery_location_id,
    ).first()


def _find_related_production(draft, order):
    if not order:
        return None
    return (
        Production.query.filter_by(
            branch_id=order.branch_id,
            production_date=order.order_date,
            production_type=draft.meal_type,
        )
        .order_by(Production.id.desc())
        .first()
    )


def _find_related_delivery_detail(detail):
    if not detail:
        return None
    return (
        DeliveryDetail.query.join(Delivery, DeliveryDetail.delivery_id == Delivery.id)
        .filter(
            DeliveryDetail.daily_order_detail_id == detail.id,
            Delivery.status != "CANCELLED",
        )
        .order_by(Delivery.delivery_date.desc(), Delivery.id.desc(), DeliveryDetail.id.desc())
        .first()
    )


def _resolve_portal_order_stage(draft, order, production, delivery, delivery_detail):
    if draft.status == DRAFT_STATUS_REJECTED:
        return "REJECTED"
    if draft.status == DRAFT_STATUS_PENDING:
        return "WAITING_ADMIN"
    if delivery:
        if str(delivery.status or "").upper() == "DELIVERED" or int(delivery_detail.delivered_qty or 0) > 0:
            return "DELIVERED"
        return "DELIVERY"
    if production:
        if str(production.status or "").upper() == "COMPLETED":
            return "PRODUCTION_DONE"
        return "PRODUCTION"
    if order and order.is_locked:
        return "LOCKED"
    if order:
        return "ADMIN_CONFIRMED"
    return "CONFIRMED"


def _validate_draft_payload(user, form):
    scope = build_portal_external_scope(user)
    if not scope.allowed:
        return None, scope.reason or "User portal belum memiliki akses aktif."

    if ACCESS_DRAFT_ORDER not in scope.access_levels:
        return None, "Akses portal belum dibuka untuk membuat draft order."

    order_date = _parse_date(form.get("order_date"))
    if not order_date:
        return None, "Tanggal order wajib valid."
    if order_date < date.today():
        return None, "Tanggal order portal tidak boleh sebelum hari ini."

    meal_type = _clean_text(form.get("meal_type")).upper()
    if meal_type not in MEAL_TYPES:
        return None, "Sesi makan wajib Makan Siang atau Makan Malam."

    portion_qty = _parse_positive_int(form.get("portion_qty"))
    if not portion_qty:
        return None, "Jumlah porsi wajib lebih dari 0."

    delivery_location_id = _parse_positive_int(form.get("delivery_location_id"))
    if not delivery_location_id or delivery_location_id not in scope.delivery_location_ids:
        return None, "Lokasi tidak termasuk akses portal user."
    if delivery_location_id not in orderable_location_ids(user, scope):
        # Lokasi mandor ada dalam akses PT (untuk dipantau), tapi PT hanya
        # boleh memesan untuk unit order langsungnya.
        return None, f"{T.client} hanya bisa memesan untuk lokasi unit order langsungnya sendiri."

    location = DeliveryLocation.query.get(delivery_location_id)
    if not location or not location.mandor:
        return None, "Lokasi tidak valid."

    if location.mandor_id not in scope.mandor_ids:
        return None, f"{T.sub_client} lokasi tidak termasuk akses portal user."

    from app.services.pricing_service import min_portion_error, quote_price, quote_trip_fee

    branch_id = location.mandor.branch_id
    client = location.mandor.client
    minimum_error = min_portion_error(branch_id, client, [(MEAL_TYPE_LABELS.get(meal_type, meal_type), portion_qty)])
    if minimum_error:
        return None, minimum_error
    # Harga dikunci sekarang: pelanggan membayar angka yang ia lihat saat memesan.
    quote = quote_price(branch_id, getattr(client, "id", None))
    if not quote:
        return None, "Harga pesanan belum tersedia. Hubungi admin untuk mengatur harga."
    delivery_fee, _, fee_error = quote_trip_fee(branch_id, client, location, portion_qty)
    if fee_error:
        return None, fee_error

    idempotency_key = _clean_text(form.get("idempotency_key"))
    if not idempotency_key:
        return None, "Idempotency key wajib tersedia untuk mencegah double submit."

    delivery_time = _clean_text(form.get("delivery_time"))
    contact_name = _clean_text(form.get("contact_name"))
    contact_phone = _clean_text(form.get("contact_phone"))
    note_parts = []
    if delivery_time:
        note_parts.append(f"Jam kirim: {delivery_time}")
    if contact_name:
        note_parts.append(f"Penerima: {contact_name}")
    if contact_phone:
        note_parts.append(f"HP penerima: {contact_phone}")
    if _clean_text(form.get("notes")):
        note_parts.append(_clean_text(form.get("notes")))

    return {
        "user_id": user.id,
        "branch_id": location.mandor.branch_id,
        "client_id": location.mandor.client_id,
        "mandor_id": location.mandor_id,
        "delivery_location_id": location.id,
        "order_date": order_date,
        "meal_type": meal_type,
        "portion_qty": portion_qty,
        "price_per_portion": quote.price,
        "price_source": quote.source,
        "delivery_fee": delivery_fee,
        "notes": "\n".join(note_parts) or None,
        "idempotency_key": idempotency_key,
    }, None


def create_portal_order_draft(user, form):
    payload, error = _validate_draft_payload(user, form)
    if error:
        return None, False, error

    existing = PortalOrderDraft.query.filter(
        PortalOrderDraft.user_id == payload["user_id"],
        PortalOrderDraft.idempotency_key == payload["idempotency_key"],
    ).first()
    if existing:
        return existing, False, None

    draft = PortalOrderDraft(
        **payload,
        status=DRAFT_STATUS_PENDING,
        submitted_at=datetime.utcnow(),
    )
    db.session.add(draft)

    try:
        db.session.flush()
        _notify_portal_order_draft_created(draft)
        _commit_or_rollback()
    except IntegrityError:
        existing = PortalOrderDraft.query.filter(
            PortalOrderDraft.user_id == payload["user_id"],
            PortalOrderDraft.idempotency_key == payload["idempotency_key"],
        ).first()
        if existing:
            return existing, False, None
        return None, False, "Draft order gagal disimpan karena konflik data."

    return draft, True, None


def _draft_title(draft):
    return (
        f"{_meal_label(draft.meal_type)} {int(draft.portion_qty or 0)} porsi "
        f"{draft.order_date.strftime('%d-%m-%Y') if draft.order_date else '-'}"
    )


def _notify_portal_order_draft_created(draft):
    create_or_update_notification(
        branch_id=draft.branch_id,
        notification_type="PORTAL_ORDER_DRAFT",
        title=f"Draft order portal masuk: {_draft_title(draft)}",
        message=(
            f"{draft.user.full_name if draft.user else 'User portal'} mengirim draft order "
            f"untuk {draft.mandor.name if draft.mandor else 'mandor'} di "
            f"{draft.delivery_location.location_name if draft.delivery_location else 'lokasi'}."
        ),
        target_role=ROLE_ADMIN,
        priority="WARNING",
        reference_type="PORTAL_ORDER_DRAFT",
        reference_id=draft.id,
        action_url="/portal/admin/order-drafts",
        generated_key=f"portal-order-draft-created-{draft.id}",
        metadata={
            "draft_id": draft.id,
            "user_id": draft.user_id,
            "client_id": draft.client_id,
            "mandor_id": draft.mandor_id,
            "delivery_location_id": draft.delivery_location_id,
            "mutation_scope": "NOTIFICATION_ONLY",
        },
        commit=False,
    )


def _notify_portal_order_draft_decision(draft, *, status_label, message, priority="INFO"):
    create_or_update_notification(
        branch_id=draft.branch_id,
        notification_type="PORTAL_ORDER_DECISION",
        title=f"Order portal {status_label.lower()}: {_draft_title(draft)}",
        message=message,
        target_user_id=draft.user_id,
        priority=priority,
        reference_type="PORTAL_ORDER_DRAFT",
        reference_id=draft.id,
        action_url="/portal/orders/status",
        generated_key=f"portal-order-draft-{status_label.lower()}-{draft.id}",
        metadata={
            "draft_id": draft.id,
            "daily_order_id": draft.converted_daily_order_id,
            "status": draft.status,
            "mutation_scope": "NOTIFICATION_ONLY",
        },
        commit=False,
    )


def _admin_can_review_draft(admin_user, draft):
    if getattr(admin_user, "role", None) == "OWNER":
        return True
    return draft.branch_id == getattr(admin_user, "branch_id", None)


def list_pending_portal_order_drafts(admin_user, limit=100):
    query = PortalOrderDraft.query.filter(PortalOrderDraft.status == DRAFT_STATUS_PENDING)
    if getattr(admin_user, "role", None) != "OWNER":
        query = query.filter(PortalOrderDraft.branch_id == getattr(admin_user, "branch_id", None))
    return query.order_by(
        PortalOrderDraft.order_date.asc(),
        PortalOrderDraft.submitted_at.asc(),
        PortalOrderDraft.id.asc(),
    ).limit(limit).all()


def build_portal_order_draft_review_queue(admin_user, limit=100):
    drafts = list_pending_portal_order_drafts(admin_user, limit=limit)
    rows = []
    for draft in drafts:
        daily_order = DailyOrder.query.filter_by(
            branch_id=draft.branch_id,
            order_date=draft.order_date,
        ).first()
        gate = evaluate_portal_order_draft_gate(draft, daily_order=daily_order)
        daily_order = gate["daily_order"]
        existing_detail = gate["existing_detail"]
        blockers = list(gate["blockers"])
        warnings = list(gate["warnings"])
        if daily_order and not daily_order.is_locked and not existing_detail:
            warnings.append("Akan ditambahkan ke order harian konsep yang sudah ada.")
        if not daily_order:
            warnings.append("Akan membuat order harian konsep baru untuk tanggal ini.")
        rows.append(
            {
                "draft": draft,
                "daily_order": daily_order,
                "existing_detail": existing_detail,
                "blockers": blockers,
                "warnings": warnings,
                "gates": gate["gates"],
                "needs_payment": gate["needs_payment"],
                "needs_approval": gate["needs_approval"],
                "review_status": gate["review_status"],
                "review_status_label": gate["review_status_label"],
                "can_confirm": gate["can_confirm"],
                # Penghalangnya hanya belum lunas dan/atau kontrak berakhir: OWNER boleh meloloskan.
                "owner_override_reasons": _owner_override_reasons(gate),
                "client_name": draft.client.name if draft.client else "-",
                "mandor_name": draft.mandor.name if draft.mandor else "-",
                "location_name": draft.delivery_location.location_name if draft.delivery_location else "-",
                "daily_order_number": daily_order.order_number if daily_order else "-",
                "daily_order_status": daily_order.status if daily_order else "NEW_DRAFT",
                "daily_order_status_label": _label_status(daily_order.status if daily_order else "NEW_DRAFT"),
                "meal_type_label": _meal_label(draft.meal_type),
            }
        )
    ready_rows = [row for row in rows if row["can_confirm"]]
    payment_rows = [row for row in rows if row["needs_payment"] and not row["can_confirm"]]
    approval_rows = [row for row in rows if row["needs_approval"] and not row["can_confirm"]]
    blocked_rows = [
        row
        for row in rows
        if not row["can_confirm"] and row not in payment_rows and row not in approval_rows
    ]
    return {
        "rows": rows,
        "sections": {
            "ready": ready_rows,
            "payment": payment_rows,
            "approval": approval_rows,
            "blocked": blocked_rows,
        },
        "drafts": drafts,
        "totals": {
            "draft_count": len(rows),
            "ready_count": sum(1 for row in rows if row["can_confirm"]),
            "payment_count": len(payment_rows),
            "approval_count": len(approval_rows),
            "blocked_count": sum(1 for row in rows if not row["can_confirm"]),
            "portion_total": sum(int(row["draft"].portion_qty or 0) for row in rows),
            "lunch_total": sum(
                int(row["draft"].portion_qty or 0)
                for row in rows
                if row["draft"].meal_type == "LUNCH"
            ),
            "dinner_total": sum(
                int(row["draft"].portion_qty or 0)
                for row in rows
                if row["draft"].meal_type == "DINNER"
            ),
        },
    }


def confirm_portal_order_draft(draft_id, admin_user, review_note=None, owner_override=False):
    draft = (
        PortalOrderDraft.query.filter(PortalOrderDraft.id == draft_id)
        .options(lazyload("*"))
        .with_for_update(of=PortalOrderDraft)
        .first()
    )
    if not draft:
        return None, False, "Draft order tidak ditemukan."

    if draft.status == DRAFT_STATUS_CONFIRMED and draft.converted_daily_order_id:
        return draft, False, None

    if draft.status != DRAFT_STATUS_PENDING:
        return draft, False, "Draft order sudah tidak dalam status pending."

    if not _admin_can_review_draft(admin_user, draft):
        return draft, False, "Draft order tidak sesuai cabang admin."

    daily_order = DailyOrder.query.filter_by(
        branch_id=draft.branch_id,
        order_date=draft.order_date,
    ).first()

    # Hanya OWNER yang boleh meloloskan pesanan yang belum lunas di muka atau
    # yang kontraknya sudah berakhir, dan wajib menulis alasannya.
    owner_override = bool(owner_override) and getattr(admin_user, "role", None) == "OWNER"
    if owner_override and not _clean_text(review_note):
        return draft, False, "Tulis alasan kenapa pesanan ini diloloskan."
    gate = evaluate_portal_order_draft_gate(
        draft,
        daily_order=daily_order,
        request_approval=True,
        requested_by=getattr(admin_user, "id", None),
        owner_override=owner_override,
    )
    if not gate["can_confirm"]:
        if gate["needs_approval"]:
            # Permintaan approval yang baru dibuat harus tersimpan walau draft
            # belum bisa dikonfirmasi.
            _commit_or_rollback()
        return draft, False, " ".join(gate["blockers"] or gate["warnings"]) or "Draft order perlu review manual."

    if not daily_order:
        daily_order = DailyOrder(
            order_number=generate_order_number(draft.order_date),
            branch_id=draft.branch_id,
            order_date=draft.order_date,
            status="DRAFT",
            is_locked=False,
            notes=f"Dibuat dari portal draft #{draft.id}",
            created_by=admin_user.id,
        )
        db.session.add(daily_order)
        db.session.flush()

    existing_detail = DailyOrderDetail.query.filter_by(
        daily_order_id=daily_order.id,
        mandor_id=draft.mandor_id,
        delivery_location_id=draft.delivery_location_id,
    ).first()
    if existing_detail is not None:
        merge_error = _merge_conflict(draft, existing_detail)
        if merge_error:
            return draft, False, merge_error

    # Harga terkunci di draft. Draft lama (sebelum daftar harga) diberi harga
    # yang berlaku sekarang; tanpa harga sama sekali, draft tidak bisa masuk order.
    price_per_portion, price_source = draft.price_per_portion, draft.price_source
    if not price_per_portion:
        from app.services.pricing_service import quote_price

        quote = quote_price(draft.branch_id, draft.client_id)
        if not quote:
            return draft, False, (
                "Harga per porsi belum diatur. OWNER perlu mengisi harga standar di "
                "Pengaturan → Harga & Ongkir sebelum draft bisa dikonfirmasi."
            )
        price_per_portion, price_source = quote.price, quote.source

    delivery_fee = draft.delivery_fee
    if delivery_fee is None:
        from app.services.pricing_service import quote_trip_fee

        delivery_fee, _, fee_error = quote_trip_fee(
            draft.branch_id, draft.client, draft.delivery_location, draft.portion_qty
        )
        if fee_error:
            return draft, False, fee_error

    lunch_qty = draft.portion_qty if draft.meal_type == "LUNCH" else 0
    dinner_qty = draft.portion_qty if draft.meal_type == "DINNER" else 0
    note = f"Konfirmasi portal draft #{draft.id}. {draft.notes or ''}".strip()
    if existing_detail is not None:
        # Sesi makan lain untuk lokasi yang sama: isi sesi yang masih kosong.
        detail = existing_detail
        if lunch_qty:
            detail.lunch_qty = lunch_qty
            detail.lunch_delivery_fee = delivery_fee
        else:
            detail.dinner_qty = dinner_qty
            detail.dinner_delivery_fee = delivery_fee
        detail.total_qty = int(detail.lunch_qty or 0) + int(detail.dinner_qty or 0)
        detail.notes = f"{detail.notes or ''} {note}".strip()
    else:
        detail = DailyOrderDetail(
            daily_order_id=daily_order.id,
            mandor_id=draft.mandor_id,
            delivery_location_id=draft.delivery_location_id,
            price_per_portion=price_per_portion,
            price_source=price_source,
            lunch_qty=lunch_qty,
            dinner_qty=dinner_qty,
            total_qty=draft.portion_qty,
            lunch_delivery_fee=delivery_fee if lunch_qty else 0,
            dinner_delivery_fee=delivery_fee if dinner_qty else 0,
            notes=note,
        )
        db.session.add(detail)
    db.session.flush()

    # Uang muka yang dibayar untuk draft ini ikut ke baris order, supaya invoice
    # otomatis setelah pengiriman bisa langsung dilunasi darinya.
    from app.services.prepaid_order_service import link_draft_prepayments_to_detail

    link_draft_prepayments_to_detail(draft, detail)
    payment_gate = next((item for item in gate["gates"] if item["key"] == "PAYMENT"), {})
    if payment_gate.get("status") == "OVERRIDE":
        from app.services.audit_log_service import record_audit_log

        record_audit_log(
            module="PORTAL",
            event_type="PREPAYMENT_OVERRIDE",
            action="UPDATE",
            table_name="portal_order_drafts",
            record_id=draft.id,
            description=f"OWNER meloloskan draft #{draft.id} sebelum lunas di muka. {payment_gate.get('message')} Alasan: {_clean_text(review_note)}",
            metadata={
                "total_amount": str(payment_gate.get("total_amount")),
                "paid_amount": str(payment_gate.get("paid_amount")),
                "reason": _clean_text(review_note),
            },
            user_id=getattr(admin_user, "id", None),
            branch_id=draft.branch_id,
            commit=False,
        )
    contract_gate = next((item for item in gate["gates"] if item["key"] == "CONTRACT"), {})
    if contract_gate.get("status") == "OVERRIDE":
        from app.services.audit_log_service import record_audit_log

        record_audit_log(
            module="PORTAL",
            event_type="CONTRACT_OVERRIDE",
            action="UPDATE",
            table_name="portal_order_drafts",
            record_id=draft.id,
            description=f"OWNER meloloskan draft #{draft.id} walau kontrak sudah berakhir. {contract_gate.get('message')} Alasan: {_clean_text(review_note)}",
            metadata={"contract_id": contract_gate.get("contract_id"), "reason": _clean_text(review_note)},
            user_id=getattr(admin_user, "id", None),
            branch_id=draft.branch_id,
            commit=False,
        )

    draft.status = DRAFT_STATUS_CONFIRMED
    draft.converted_daily_order_id = daily_order.id
    draft.reviewed_by = admin_user.id
    draft.reviewed_at = datetime.utcnow()
    draft.review_note = _clean_text(review_note) or "Dikonfirmasi ke order harian existing."
    _notify_portal_order_draft_decision(
        draft,
        status_label="Dikonfirmasi",
        message=(
            f"Draft order kamu sudah dikonfirmasi admin dan masuk ke order harian "
            f"{daily_order.order_number}."
        ),
    )

    _commit_or_rollback()
    return draft, True, None


def reject_portal_order_draft(draft_id, admin_user, review_note):
    draft = (
        PortalOrderDraft.query.filter(PortalOrderDraft.id == draft_id)
        .options(lazyload("*"))
        .with_for_update(of=PortalOrderDraft)
        .first()
    )
    if not draft:
        return None, False, "Draft order tidak ditemukan."

    if draft.status != DRAFT_STATUS_PENDING:
        return draft, False, "Draft order sudah tidak dalam status pending."

    if not _admin_can_review_draft(admin_user, draft):
        return draft, False, "Draft order tidak sesuai cabang admin."

    draft.status = DRAFT_STATUS_REJECTED
    draft.reviewed_by = admin_user.id
    draft.reviewed_at = datetime.utcnow()
    draft.review_note = _clean_text(review_note) or "Ditolak admin."
    _notify_portal_order_draft_decision(
        draft,
        status_label="Ditolak",
        message=f"Draft order kamu ditolak admin. Catatan: {draft.review_note}",
        priority="WARNING",
    )

    _commit_or_rollback()
    return draft, True, None
