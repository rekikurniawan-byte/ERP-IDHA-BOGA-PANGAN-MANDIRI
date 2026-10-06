from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func

from app.extensions import db
from app.models.finance import AdvanceTransaction, BankAccount, Payment
from app.models.system import DigitalAttachment, PortalOrderDraft, PortalPaymentProofClaim
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.business_logic_guard_service import decimal_money
from app.services.cash_bank_service import create_cash_bank_adjustment
from app.services.idempotency_service import (
    IdempotencyConflictError,
    mark_idempotency_completed,
    reserve_idempotency_key,
)
from app.services.notification_service import create_or_update_notification
from app.services.portal_order_draft_service import (
    confirm_portal_order_draft,
    draft_total_amount,
    evaluate_portal_order_draft_gate,
)
from app.services.portal_payment_verification_queue_service import decide_payment_proof
from app.services.prepaid_order_service import (
    PrepaymentError,
    draft_prepaid_amount,
    draft_transfer_amount,
    draft_unique_code_amount,
    record_draft_prepayment,
)
from app.utils.clock import today_wib


REJECTION_REASONS = {
    "NOT_RECEIVED": "Dana tidak masuk ke rekening",
    "UNREADABLE": "Bukti tidak jelas/terbaca",
    "WRONG_ORDER": "Bukti untuk pesanan lain",
    "WRONG_AMOUNT": "Nominal tidak sesuai",
    "OTHER": "Lainnya",
}


class PaymentApprovalError(ValueError):
    pass


def _append_payment_created_note(existing: str | None, advance_number: str, user_id: int) -> str:
    line = f"PAYMENT_CREATED {advance_number} by user_id={user_id}"
    return f"{existing}\n{line}" if existing else line


def batch_build_draft_prepaids(draft_ids: list[int]) -> dict[int, Decimal]:
    from app.models.finance import AdvanceTransaction
    from app.services.advance_service import CLIENT_DP_RECEIVED
    from app.services.prepaid_order_service import _money

    if not draft_ids:
        return {}
    advances = (
        AdvanceTransaction.query.filter(
            AdvanceTransaction.portal_order_draft_id.in_(draft_ids),
            AdvanceTransaction.advance_type == CLIENT_DP_RECEIVED,
        )
        .order_by(AdvanceTransaction.id.asc())
        .all()
    )
    result = {did: Decimal("0.00") for did in draft_ids}
    for adv in advances:
        if adv.portal_order_draft_id in result:
            result[adv.portal_order_draft_id] += _money(adv.remaining_amount)
    return result


def batch_build_draft_blockers(
    drafts: list[PortalOrderDraft], branch_id: int, today: date | None = None
) -> dict[int, list[str]]:
    from app.models.accounting import PeriodClosing
    from app.models.operational import DailyOrder, DailyOrderDetail
    from app.services.contract_lifecycle_service import lapsed_contract, lapsed_contract_message
    from app.services.portal_order_draft_service import _merge_conflict
    from app.utils.clock import today_wib

    if today is None:
        today = today_wib()

    posted_closings = {
        (c.period_year, c.period_month)
        for c in PeriodClosing.query.filter_by(branch_id=branch_id, status="POSTED").all()
    }

    client_ids = {d.client_id for d in drafts if d and d.client_id}
    lapsed_messages = {}
    for cid in client_ids:
        lapsed = lapsed_contract(branch_id, cid)
        if lapsed:
            lapsed_messages[cid] = (
                f"{lapsed_contract_message(lapsed)} Perpanjang kontraknya, atau OWNER meloloskan pesanan ini dengan alasan."
            )

    order_dates = {d.order_date for d in drafts if d and d.order_date}
    daily_orders_by_date = {}
    details_by_key = {}
    if order_dates:
        daily_orders = DailyOrder.query.filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.order_date.in_(order_dates),
        ).all()
        daily_orders_by_date = {do.order_date: do for do in daily_orders}
        do_ids = [do.id for do in daily_orders]
        if do_ids:
            details = DailyOrderDetail.query.filter(DailyOrderDetail.daily_order_id.in_(do_ids)).all()
            details_by_key = {
                (det.daily_order_id, det.mandor_id, det.delivery_location_id): det
                for det in details
            }

    result = {}
    for d in drafts:
        if not d:
            continue
        d_blockers = []
        if d.order_date and (d.order_date.year, d.order_date.month) in posted_closings:
            d_blockers.append("Periode order sudah closing. Draft tidak boleh masuk order operasional.")
        if d.order_date and d.order_date < today:
            d_blockers.append("Tanggal order sudah lewat. Buat draft tanggal baru atau proses koreksi manual.")
        if d.client_id and d.client_id in lapsed_messages:
            d_blockers.append(lapsed_messages[d.client_id])
        do = daily_orders_by_date.get(d.order_date)
        if do:
            if do.is_locked:
                d_blockers.append("Order harian existing sudah dikunci.")
            else:
                det = details_by_key.get((do.id, d.mandor_id, d.delivery_location_id))
                if det:
                    merge_err = _merge_conflict(d, det)
                    if merge_err:
                        d_blockers.append(merge_err)
        result[d.id] = d_blockers
    return result


def build_draft_payment_review(
    attachment: DigitalAttachment,
    *,
    draft: PortalOrderDraft | None = None,
    claim: PortalPaymentProofClaim | None = None,
    dup_file_map: dict | None = None,
    dup_ref_map: dict | None = None,
    gate_eval: dict | None = None,
    prepaid: Decimal | None = None,
    blockers: list[str] | None = None,
) -> dict:
    """Read-only review builder for draft payment proof."""
    if draft is None:
        draft = PortalOrderDraft.query.filter_by(
            id=attachment.reference_id,
            branch_id=attachment.branch_id,
        ).first()

    if claim is None:
        claim = PortalPaymentProofClaim.query.filter_by(attachment_id=attachment.id).first()

    # Determine view URL
    try:
        from flask import has_request_context, url_for

        if has_request_context():
            view_url = url_for("finance.view_portal_payment_proof_attachment", attachment_id=attachment.id)
        else:
            view_url = f"/finance/portal-payment-proofs/attachment/{attachment.id}"
    except Exception:
        view_url = f"/finance/portal-payment-proofs/attachment/{attachment.id}"

    # Customer info
    customer_name = "-"
    if attachment.uploader and getattr(attachment.uploader, "full_name", None):
        customer_name = attachment.uploader.full_name
    elif draft and draft.user and getattr(draft.user, "full_name", None):
        customer_name = draft.user.full_name

    client_name = draft.client.name if draft and draft.client else "-"
    mandor_name = draft.mandor.name if draft and draft.mandor else "-"

    phone = "-"
    if draft:
        if draft.mandor and getattr(draft.mandor, "phone", None):
            phone = draft.mandor.phone
        elif draft.client and getattr(draft.client, "phone", None):
            phone = draft.client.phone

    location_name = draft.delivery_location.location_name if draft and draft.delivery_location else "-"

    # Order info
    order_date = draft.order_date if draft else None
    today = today_wib()
    is_today = bool(order_date and order_date == today)

    if draft:
        if draft.meal_type == "LUNCH":
            meal_label = "Makan Siang"
        elif draft.meal_type == "DINNER":
            meal_label = "Makan Malam"
        else:
            meal_label = draft.meal_type or "-"
        portion_qty = draft.portion_qty or 0
        draft_status = draft.status or "-"
    else:
        meal_label = "-"
        portion_qty = 0
        draft_status = "-"

    # Financial info
    total = draft_total_amount(draft) if draft else None
    if prepaid is None:
        prepaid = draft_prepaid_amount(draft) if draft else Decimal("0.00")
        unique_code = draft_unique_code_amount(draft) if draft else Decimal("0.00")
        expected_transfer = draft_transfer_amount(draft) if draft else None
    else:
        code = int(getattr(draft, "payment_unique_code", None) or 0) if draft else 0
        if code <= 0 or (prepaid and prepaid > Decimal("0.00")):
            unique_code = Decimal("0.00")
        else:
            unique_code = Decimal(code).quantize(Decimal("0.01"))
        expected_transfer = (
            None
            if total is None
            else (
                Decimal("0.00")
                if (total - prepaid) <= Decimal("0.00")
                else (max(total - prepaid, Decimal("0.00")) + unique_code)
            )
        )
    outstanding = max(total - prepaid, Decimal("0.00")) if total is not None else None

    claimed_amount = claim.claimed_amount if claim else None
    sender_name = claim.sender_name if claim else None
    transfer_reference = claim.transfer_reference if claim else None

    # Match calculation
    if claimed_amount is None or total is None or outstanding is None:
        match = "UNKNOWN"
        match_label = "Nominal tidak diisi pelanggan"
    elif claimed_amount == expected_transfer or claimed_amount == outstanding:
        match = "EXACT"
        match_label = "Cocok"
    elif claimed_amount < outstanding:
        match = "SHORT"
        shortage = outstanding - claimed_amount
        match_label = f"Kurang Rp {shortage:,.0f}".replace(",", ".")
    elif expected_transfer is not None and claimed_amount > expected_transfer:
        match = "OVER"
        excess = claimed_amount - expected_transfer
        match_label = f"Lebih Rp {excess:,.0f}".replace(",", ".")
    else:
        match = "EXACT"
        match_label = "Cocok"

    # Warnings
    warnings: list[str] = []
    if attachment.sha256_hash:
        if dup_file_map is not None:
            candidates = dup_file_map.get(attachment.sha256_hash, [])
            if isinstance(candidates, list):
                dup_file = next((c for c in candidates if c.id != attachment.id), None)
            else:
                dup_file = candidates if candidates.id != attachment.id else None
        else:
            dup_file = (
                DigitalAttachment.query.filter(
                    DigitalAttachment.id != attachment.id,
                    DigitalAttachment.module == "PORTAL_PAYMENT",
                    DigitalAttachment.branch_id == attachment.branch_id,
                    DigitalAttachment.is_deleted.is_(False),
                    DigitalAttachment.sha256_hash == attachment.sha256_hash,
                    DigitalAttachment.attachment_type != "PAYMENT_PROOF_REJECTED",
                ).first()
            )
        if dup_file:
            warnings.append(f"File sama persis dengan bukti draft #{dup_file.reference_id}.")

    if claim and claim.transfer_reference:
        clean_ref = str(claim.transfer_reference).strip().upper()
        if dup_ref_map is not None:
            candidates = dup_ref_map.get(clean_ref, [])
            if isinstance(candidates, list):
                dup_ref_claim = next((c for c in candidates if c.attachment_id != attachment.id), None)
            else:
                dup_ref_claim = candidates if candidates.attachment_id != attachment.id else None
        else:
            dup_ref_claim = (
                PortalPaymentProofClaim.query
                .join(DigitalAttachment, PortalPaymentProofClaim.attachment_id == DigitalAttachment.id)
                .filter(
                    PortalPaymentProofClaim.branch_id == attachment.branch_id,
                    PortalPaymentProofClaim.transfer_reference == clean_ref,
                    DigitalAttachment.is_deleted.is_(False),
                    DigitalAttachment.attachment_type != "PAYMENT_PROOF_REJECTED",
                    PortalPaymentProofClaim.attachment_id != attachment.id,
                ).first()
            )
        if dup_ref_claim:
            ref_draft_id = dup_ref_claim.attachment.reference_id if dup_ref_claim.attachment else "?"
            warnings.append(f"No. referensi sama dengan bukti draft #{ref_draft_id}.")

    if draft and draft.status != "PENDING_ADMIN_CONFIRMATION":
        warnings.append(f"Pesanan sudah tidak menunggu (status: {draft.status}).")

    if draft and draft.order_date and draft.order_date < today:
        warnings.append("Tanggal pesanan sudah lewat.")

    # Blockers (all gates BLOCKED except PAYMENT)
    if blockers is None:
        blockers = []
        if draft:
            if gate_eval is None:
                gate_eval = evaluate_portal_order_draft_gate(draft, request_approval=False)
            for g in gate_eval.get("gates", []):
                if g.get("status") == "BLOCKED" and g.get("key") != "PAYMENT":
                    blockers.append(g.get("message", "Gate terblokir."))

    has_duplicate_warning = any("File sama persis" in w or "No. referensi sama" in w for w in warnings)
    can_approve = bool(
        draft
        and draft.status == "PENDING_ADMIN_CONFIRMATION"
        and not has_duplicate_warning
        and len(blockers) == 0
    )

    return {
        "attachment_id": attachment.id,
        "draft_id": draft.id if draft else attachment.reference_id,
        "status_key": attachment.attachment_type,
        "uploaded_at": attachment.created_at,
        "is_image": bool(attachment.mime_type and attachment.mime_type.startswith("image/")),
        "view_url": view_url,
        "customer_name": customer_name,
        "client_name": client_name,
        "mandor_name": mandor_name,
        "phone": phone,
        "location_name": location_name,
        "order_date": order_date,
        "meal_label": meal_label,
        "portion_qty": portion_qty,
        "draft_status": draft_status,
        "is_today": is_today,
        "total": total,
        "prepaid": prepaid,
        "outstanding": outstanding,
        "unique_code": unique_code,
        "expected_transfer": expected_transfer,
        "claimed_amount": claimed_amount,
        "sender_name": sender_name,
        "transfer_reference": transfer_reference,
        "match": match,
        "match_label": match_label,
        "warnings": warnings,
        "blockers": blockers,
        "can_approve": can_approve,
    }


def approve_draft_payment(
    user: Any,
    *,
    attachment_id: int,
    draft_id: int,
    received_amount: Any,
    payment_method: str,
    bank_account_id: int | None = None,
    payment_date: Any = None,
    reference_number: str | None = None,
    checked_mutation: bool = False,
    note: str | None = None,
    idempotency_key: str,
) -> dict:
    """Unified service action: verify proof + record advance + confirm order draft in single transaction."""
    # 1. Validasi input dasar
    if not checked_mutation:
        raise PaymentApprovalError("Centang dulu bahwa Anda sudah mengecek mutasi rekening.")

    if not idempotency_key or not str(idempotency_key).strip():
        raise PaymentApprovalError("Idempotency key wajib diisi.")

    try:
        received = decimal_money(received_amount, label="Nominal pembayaran")
    except Exception as exc:
        raise PaymentApprovalError(str(exc))

    if received <= Decimal("0"):
        raise PaymentApprovalError("Nominal pembayaran harus lebih besar dari 0.")

    today = today_wib()
    if payment_date is None:
        payment_date = today
    elif isinstance(payment_date, str):
        try:
            payment_date = datetime.strptime(payment_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            raise PaymentApprovalError("Format tanggal pembayaran tidak valid (gunakan YYYY-MM-DD).")

    if payment_date > today:
        raise PaymentApprovalError("Tanggal pembayaran tidak boleh di masa depan.")

    method = str(payment_method or "").strip().upper()
    if method in {"TRANSFER", "QRIS"}:
        if not bank_account_id:
            raise PaymentApprovalError("Pilih rekening bank penerima.")
        bank_account = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=user.branch_id,
            is_active=True,
        ).first()
        if not bank_account:
            raise PaymentApprovalError("Rekening bank tidak valid atau tidak aktif di cabang Anda.")
    elif method == "CASH":
        bank_account_id = None
    else:
        raise PaymentApprovalError("Metode pembayaran tidak valid.")

    with atomic_business_action(
        module="FINANCE",
        action="PORTAL_DRAFT_PAYMENT_APPROVED",
        description=f"Persetujuan pembayaran pesanan portal draft #{draft_id}",
        reference_type="PORTAL_ORDER_DRAFT",
        reference_id=draft_id,
        user_id=user.id,
        branch_id=user.branch_id,
        severity="HIGH",
        metadata={
            "draft_id": draft_id,
            "attachment_id": attachment_id,
            "received_amount": str(received),
            "payment_method": method,
        },
    ):
        # 2. Kunci draft
        draft = (
            PortalOrderDraft.query.filter_by(id=draft_id, branch_id=user.branch_id)
            .with_for_update(of=PortalOrderDraft)
            .first()
        )
        if not draft:
            raise PaymentApprovalError("Pesanan draft tidak ditemukan.")

        # 3. Ambil attachment & validasi kepemilikan
        attachment = (
            DigitalAttachment.query.filter_by(
                id=attachment_id,
                branch_id=user.branch_id,
                module="PORTAL_PAYMENT",
                reference_type="PORTAL_ORDER_DRAFT",
                is_deleted=False,
            )
            .with_for_update(of=DigitalAttachment)
            .first()
        )
        if not attachment:
            raise PaymentApprovalError("Bukti pembayaran tidak ditemukan.")

        if attachment.reference_id != draft.id:
            raise PaymentApprovalError("Bukti ini bukan milik pesanan tersebut. Muat ulang halaman.")

        # 4. Status attachment
        if attachment.attachment_type == "PAYMENT_PROOF_PAYMENT_CREATED":
            raise PaymentApprovalError("Bukti ini sudah diproses.")
        if attachment.attachment_type == "PAYMENT_PROOF_REJECTED":
            raise PaymentApprovalError("Bukti ini sudah ditolak.")
        if attachment.attachment_type not in {"PAYMENT_PROOF_PENDING", "PAYMENT_PROOF_VERIFIED"}:
            raise PaymentApprovalError(f"Status bukti pembayaran tidak valid ({attachment.attachment_type}).")

        # 5. Draft harus PENDING_ADMIN_CONFIRMATION
        if draft.status != "PENDING_ADMIN_CONFIRMATION":
            raise PaymentApprovalError(f"Pesanan sudah tidak menunggu konfirmasi (status: {draft.status}).")

        # 6. Cek duplikat ulang (hash & referensi)
        if attachment.sha256_hash:
            dup_file = DigitalAttachment.query.filter(
                DigitalAttachment.id != attachment.id,
                DigitalAttachment.module == "PORTAL_PAYMENT",
                DigitalAttachment.branch_id == user.branch_id,
                DigitalAttachment.is_deleted.is_(False),
                DigitalAttachment.sha256_hash == attachment.sha256_hash,
                DigitalAttachment.attachment_type != "PAYMENT_PROOF_REJECTED",
            ).first()
            if dup_file:
                raise PaymentApprovalError(f"File bukti ini sama persis dengan bukti draft #{dup_file.reference_id}.")

        claim = PortalPaymentProofClaim.query.filter_by(attachment_id=attachment.id).first()
        if claim and claim.transfer_reference:
            clean_claim_ref = str(claim.transfer_reference).strip().upper()
            dup_ref = (
                PortalPaymentProofClaim.query
                .join(DigitalAttachment, PortalPaymentProofClaim.attachment_id == DigitalAttachment.id)
                .filter(
                    PortalPaymentProofClaim.branch_id == user.branch_id,
                    PortalPaymentProofClaim.transfer_reference == clean_claim_ref,
                    DigitalAttachment.is_deleted.is_(False),
                    DigitalAttachment.attachment_type != "PAYMENT_PROOF_REJECTED",
                    PortalPaymentProofClaim.attachment_id != attachment.id,
                ).first()
            )
            if dup_ref:
                raise PaymentApprovalError(f"No. referensi sama dengan bukti draft #{dup_ref.attachment.reference_id}.")

        # 7. Kalau reference_number diisi: tolak bila sudah dipakai
        clean_ref_no = str(reference_number or "").strip().upper() or None
        if clean_ref_no:
            dup_adv = AdvanceTransaction.query.filter(
                AdvanceTransaction.branch_id == user.branch_id,
                func.upper(func.trim(AdvanceTransaction.reference_number)) == clean_ref_no,
            ).first()
            if dup_adv:
                raise PaymentApprovalError(f"No. referensi bank sudah pernah digunakan untuk transaksi uang muka ({dup_adv.advance_number}).")

            dup_pay = Payment.query.filter(
                Payment.branch_id == user.branch_id,
                func.upper(func.trim(Payment.reference_number)) == clean_ref_no,
            ).first()
            if dup_pay:
                raise PaymentApprovalError(f"No. referensi bank sudah pernah digunakan untuk pembayaran invoice ({dup_pay.payment_number}).")

        # 8. reserve_idempotency_key
        try:
            record, reserved = reserve_idempotency_key(
                scope="PORTAL_DRAFT_PAYMENT_APPROVE",
                key=idempotency_key,
                branch_id=user.branch_id,
                user_id=user.id,
                request_payload={
                    "draft_id": draft.id,
                    "attachment_id": attachment.id,
                    "received_amount": str(received),
                },
            )
        except IdempotencyConflictError as err:
            raise PaymentApprovalError(str(err))

        if not reserved:
            raise PaymentApprovalError("Pembayaran ini sedang atau sudah diproses.")

        # 9. Hitung (semua Decimal)
        total = draft_total_amount(draft)
        if total is None:
            raise PaymentApprovalError("Pesanan belum punya harga terkunci.")
        prepaid_before = draft_prepaid_amount(draft)
        outstanding = total - prepaid_before
        if outstanding <= Decimal("0"):
            raise PaymentApprovalError("Pesanan ini sudah lunas.")

        code_amount = draft_unique_code_amount(draft)
        if received <= outstanding:
            prepay, extra = received, Decimal("0.00")
        elif received - outstanding <= code_amount:
            prepay, extra = outstanding, received - outstanding
        else:
            raise PaymentApprovalError("Nominal lebih besar dari tagihan + kode unik. Tolak bukti atau hubungi pelanggan.")

        expected_transfer = draft_transfer_amount(draft)
        clean_note = str(note or "").strip()
        if received != expected_transfer and received != outstanding:
            if len(clean_note) < 5:
                raise PaymentApprovalError("Nominal berbeda dari tagihan. Tulis catatan alasannya.")

        # 10. Jika attachment masih PENDING -> verifikasi
        if attachment.attachment_type == "PAYMENT_PROOF_PENDING":
            decide_payment_proof(
                user,
                attachment_id=attachment.id,
                decision="VERIFIED",
                notes="Diterima lewat Antrean Pembayaran.",
                commit=False,
            )

        # 11. Catat uang muka
        try:
            advance = record_draft_prepayment(
                draft=draft,
                amount=prepay,
                payment_method=method,
                created_by=user.id,
                payment_date=payment_date,
                bank_account_id=bank_account_id,
                reference_number=clean_ref_no,
                notes=clean_note or None,
            )
        except PrepaymentError as exc:
            raise PaymentApprovalError(str(exc))

        # 12. Jika extra > 0: catat penyesuaian kas/bank kategori KODE_UNIK
        if extra > Decimal("0"):
            try:
                create_cash_bank_adjustment(
                    adjustment_date=payment_date,
                    account_type="BANK" if bank_account_id else "CASH",
                    bank_account_id=bank_account_id,
                    adjustment_type="INCREASE",
                    amount=extra,
                    reason=f"Kode unik transfer pesanan portal #{draft.id} ({advance.advance_number})",
                    created_by=user.id,
                    branch_id=draft.branch_id,
                    category="KODE_UNIK",
                    allow_system_category=True,
                    commit=False,
                )
            except Exception as exc:
                raise PaymentApprovalError(str(exc))

        # 13. Ubah attachment
        attachment.attachment_type = "PAYMENT_PROOF_PAYMENT_CREATED"
        attachment.notes = _append_payment_created_note(attachment.notes, advance.advance_number, user.id)

        # 14. Jika sekarang lunas -> konfirmasi draft, jika belum -> tahan (HELD_SHORT)
        new_prepaid = draft_prepaid_amount(draft)
        if new_prepaid >= total:
            _, converted, error = confirm_portal_order_draft(
                draft.id,
                user,
                review_note=clean_note or "Pembayaran diterima & dikonfirmasi.",
                commit=False,
            )
            if error:
                raise PaymentApprovalError(error)
            outcome = "CONFIRMED"
        else:
            outcome = "HELD_SHORT"
            remaining_due = max(total - new_prepaid, Decimal("0.00"))
            rupiah_prepay = f"{prepay:,.0f}".replace(",", ".")
            rupiah_rem = f"{remaining_due:,.0f}".replace(",", ".")
            create_or_update_notification(
                branch_id=draft.branch_id,
                notification_type="PORTAL_DRAFT_SHORT_PAYMENT",
                target_user_id=attachment.uploaded_by,
                priority="WARNING",
                title="Pembayaran kurang",
                message=(
                    f"Pembayaran Rp {rupiah_prepay} sudah diterima. "
                    f"Sisa yang harus dibayar Rp {rupiah_rem}. "
                    f"Unggah bukti transfer sisa di halaman Pesan."
                ),
                action_url="/portal/orders/status",
                generated_key=f"portal-draft-short-{attachment.id}",
                commit=False,
            )

        # 15. Tandai idempotency & catat audit log
        remaining_amount = max(total - new_prepaid, Decimal("0.00"))
        response_payload = {
            "outcome": outcome,
            "draft_id": draft.id,
            "advance_number": advance.advance_number,
            "prepay": str(prepay),
            "extra": str(extra),
            "remaining": str(remaining_amount),
        }
        mark_idempotency_completed(
            record,
            reference_type="ADVANCE_TRANSACTION",
            reference_id=advance.id,
            response_payload=response_payload,
            commit=False,
        )
        record_audit_log(
            module="FINANCE",
            event_type="PORTAL_DRAFT_PAYMENT_APPROVED",
            action="UPDATE",
            table_name="portal_order_drafts",
            record_id=draft.id,
            description=f"Pembayaran draft #{draft.id} disetujui ({outcome}). Prepay: Rp {prepay:,.0f}, Extra: Rp {extra:,.0f}.",
            metadata={
                "draft_id": draft.id,
                "attachment_id": attachment.id,
                "received": str(received),
                "prepay": str(prepay),
                "extra": str(extra),
                "outcome": outcome,
                "sender_name": claim.sender_name if claim else None,
                "reference_number": clean_ref_no,
            },
            user_id=user.id,
            branch_id=draft.branch_id,
            commit=False,
        )

        # 16. Return
        return {
            "outcome": outcome,
            "draft_id": draft.id,
            "advance_number": advance.advance_number,
            "prepay": prepay,
            "extra": extra,
            "remaining": remaining_amount,
        }


def reject_draft_payment(
    user: Any,
    *,
    attachment_id: int,
    draft_id: int,
    reason_code: str,
    note: str | None = None,
) -> dict:
    """Reject portal draft payment proof with specific reason without rejecting the draft."""
    if reason_code not in REJECTION_REASONS:
        raise PaymentApprovalError("Alasan penolakan tidak valid.")

    clean_note = str(note or "").strip()
    if reason_code == "OTHER" and not clean_note:
        raise PaymentApprovalError("Catatan alasan wajib diisi untuk pilihan Lainnya.")

    draft = PortalOrderDraft.query.filter_by(id=draft_id, branch_id=user.branch_id).first()
    if not draft:
        raise PaymentApprovalError("Pesanan draft tidak ditemukan.")

    attachment = DigitalAttachment.query.filter_by(
        id=attachment_id,
        branch_id=user.branch_id,
        module="PORTAL_PAYMENT",
        reference_type="PORTAL_ORDER_DRAFT",
        is_deleted=False,
    ).first()
    if not attachment:
        raise PaymentApprovalError("Bukti pembayaran tidak ditemukan.")

    if attachment.reference_id != draft.id:
        raise PaymentApprovalError("Bukti ini bukan milik pesanan tersebut. Muat ulang halaman.")

    label = REJECTION_REASONS[reason_code]
    full_note = f"{label}. {clean_note}".strip() if clean_note else label

    with atomic_business_action(
        module="FINANCE",
        action="PORTAL_DRAFT_PAYMENT_REJECTED",
        description=f"Penolakan bukti pembayaran draft #{draft.id}",
        reference_type="PORTAL_ORDER_DRAFT",
        reference_id=draft.id,
        user_id=user.id,
        branch_id=user.branch_id,
        severity="MEDIUM",
        metadata={
            "draft_id": draft.id,
            "attachment_id": attachment.id,
            "reason_code": reason_code,
            "note": clean_note,
        },
    ):
        decide_payment_proof(
            user,
            attachment_id=attachment.id,
            decision="REJECTED",
            notes=full_note,
            commit=False,
        )

    return {
        "rejected": True,
        "attachment_id": attachment.id,
        "draft_id": draft.id,
    }
