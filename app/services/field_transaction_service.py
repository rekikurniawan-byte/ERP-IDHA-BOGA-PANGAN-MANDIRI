import json
import re
from datetime import date, datetime

from app.utils.clock import today_wib

from app.extensions import db
from app.models.field_transaction import (
    FIELD_TRANSACTION_CHANNELS,
    FIELD_TRANSACTION_COUNTERPARTY_TYPES,
    FIELD_TRANSACTION_DIRECTIONS,
    FIELD_TRANSACTION_EVIDENCE_STATUSES,
    FIELD_TRANSACTION_PAYMENT_STATUSES,
    FIELD_TRANSACTION_REVIEW_STATUSES,
    FieldCounterparty,
    FieldTransaction,
    FieldTransactionAttachment,
    FieldTransactionLink,
    FieldTransactionReviewLog,
)
from app.models.finance import BankAccount
from app.models.master import Mandor
from app.models.system import DigitalAttachment
from app.utils.terms import T
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.business_logic_guard_service import BusinessRuleError, assert_positive_amount
from app.services.field_transaction_policy_service import (
    FieldTransactionPolicyError,
    ensure_field_transaction_event_ui_ready,
    get_field_transaction_event_policy,
    resolve_policy_defaults,
    validate_field_transaction_event_payload,
)


class FieldTransactionValidationError(Exception):
    """Raised when field transaction input is invalid."""


REVIEW_STATUS_TRANSITIONS = {
    "DRAFT": {
        "RECORDED",
        "WAITING_EVIDENCE",
        "WAITING_CLASSIFICATION",
        "IN_REVIEW",
        "WAITING_APPROVAL",
        "READY_TO_POST",
        "REJECTED",
        "VOID",
    },
    "RECORDED": {
        "WAITING_EVIDENCE",
        "WAITING_CLASSIFICATION",
        "IN_REVIEW",
        "WAITING_APPROVAL",
        "READY_TO_POST",
        "REJECTED",
        "VOID",
    },
    "WAITING_EVIDENCE": {
        "WAITING_CLASSIFICATION",
        "IN_REVIEW",
        "WAITING_APPROVAL",
        "READY_TO_POST",
        "REJECTED",
        "VOID",
    },
    "WAITING_CLASSIFICATION": {
        "WAITING_EVIDENCE",
        "IN_REVIEW",
        "WAITING_APPROVAL",
        "READY_TO_POST",
        "REJECTED",
        "VOID",
    },
    "IN_REVIEW": {
        "WAITING_EVIDENCE",
        "WAITING_CLASSIFICATION",
        "WAITING_APPROVAL",
        "READY_TO_POST",
        "REJECTED",
        "VOID",
    },
    "WAITING_APPROVAL": {
        "WAITING_EVIDENCE",
        "WAITING_CLASSIFICATION",
        "IN_REVIEW",
        "READY_TO_POST",
        "REJECTED",
        "VOID",
    },
    "READY_TO_POST": {
        "WAITING_EVIDENCE",
        "WAITING_CLASSIFICATION",
        "IN_REVIEW",
        "WAITING_APPROVAL",
        "REJECTED",
        "VOID",
    },
    "POSTED": {"RECONCILED"},
    "REJECTED": {
        "WAITING_EVIDENCE",
        "WAITING_CLASSIFICATION",
        "IN_REVIEW",
        "WAITING_APPROVAL",
        "READY_TO_POST",
        "VOID",
    },
    "VOID": set(),
    "RECONCILED": set(),
}


def _normalize_text(value):
    text = str(value or "").strip()
    return text or None


def _normalize_choice(value, allowed, label):
    normalized = str(value or "").strip().upper()
    if normalized not in allowed:
        raise FieldTransactionValidationError(f"{label} tidak valid.")
    return normalized


def _safe_json(value):
    if value in (None, ""):
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _normalize_identity_token(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return re.sub(r"[^a-z0-9]+", "", raw)


def _resolve_counterparty(branch_id, counterparty_id):
    if not counterparty_id:
        return None
    counterparty = FieldCounterparty.query.filter_by(
        id=counterparty_id,
        branch_id=branch_id,
        is_active=True,
    ).first()
    if not counterparty:
        raise FieldTransactionValidationError("Pihak transaksi lapangan tidak valid atau tidak aktif.")
    return counterparty


def _resolve_bank_account(branch_id, bank_account_id):
    if not bank_account_id:
        return None
    bank_account = BankAccount.query.filter_by(
        id=bank_account_id,
        branch_id=branch_id,
        is_active=True,
    ).first()
    if not bank_account:
        raise FieldTransactionValidationError("Rekening bank transaksi lapangan tidak valid atau tidak aktif.")
    return bank_account


def _snapshot_counterparty(counterparty):
    if not counterparty:
        return {
            "counterparty_type_snapshot": None,
            "party_snapshot_name": None,
            "party_snapshot_company": None,
            "party_snapshot_phone": None,
            "site_location": None,
        }
    return {
        "counterparty_type_snapshot": getattr(counterparty, "counterparty_type", None),
        "party_snapshot_name": getattr(counterparty, "name", None),
        "party_snapshot_company": getattr(counterparty, "company_name", None),
        "party_snapshot_phone": getattr(counterparty, "phone", None),
        "site_location": getattr(counterparty, "site_location", None),
    }


def generate_field_transaction_number(transaction_date):
    prefix = f"FTX-{transaction_date.strftime('%Y%m%d')}"
    counter = FieldTransaction.query.filter(
        FieldTransaction.transaction_number.like(f"{prefix}-%")
    ).count() + 1

    while True:
        number = f"{prefix}-{counter:04d}"
        if not FieldTransaction.query.filter_by(transaction_number=number).first():
            return number
        counter += 1


def _validate_review_status_transition(field_transaction, from_review_status, to_review_status, note=None):
    if to_review_status == "POSTED":
        raise FieldTransactionValidationError(
            "Status POSTED hanya boleh dibentuk melalui proses posting resmi, bukan perubahan status manual."
        )

    from_review_status = str(from_review_status or "").strip().upper() or "DRAFT"
    posting_status = str(getattr(field_transaction, "posting_status", "") or "").strip().upper()
    if posting_status == "POSTED" and from_review_status != "POSTED":
        raise FieldTransactionValidationError(
            "Status posting transaksi lapangan tidak sinkron. Investigasi manual diperlukan sebelum review dilanjutkan."
        )
    if posting_status == "VOIDED":
        raise FieldTransactionValidationError(
            "Transaksi lapangan yang sudah di-void tidak dapat diubah status review-nya lagi."
        )

    allowed_targets = REVIEW_STATUS_TRANSITIONS.get(from_review_status)
    if allowed_targets is None:
        raise FieldTransactionValidationError("Status review transaksi lapangan saat ini tidak dikenali.")
    if to_review_status not in allowed_targets:
        allowed_text = ", ".join(sorted(allowed_targets)) if allowed_targets else "tidak ada"
        raise FieldTransactionValidationError(
            f"Perubahan status dari {from_review_status} ke {to_review_status} tidak diizinkan. "
            f"Status tujuan yang boleh: {allowed_text}."
        )

    if from_review_status == "POSTED" and to_review_status == "RECONCILED" and posting_status != "POSTED":
        raise FieldTransactionValidationError(
            "Status RECONCILED hanya boleh dipakai setelah transaksi benar-benar memiliki jejak posting finansial."
        )

    if to_review_status in {"REJECTED", "VOID", "RECONCILED"} and not _normalize_text(note):
        raise FieldTransactionValidationError(
            f"Catatan wajib diisi saat mengubah transaksi lapangan ke status {to_review_status}."
        )


def create_field_counterparty(
    *,
    branch_id,
    counterparty_type,
    name,
    created_by=None,
    company_name=None,
    phone=None,
    site_location=None,
    notes=None,
    linked_client_id=None,
    linked_supplier_id=None,
    linked_mandor_id=None,
    commit=False,
):
    counterparty_type = _normalize_choice(
        counterparty_type,
        FIELD_TRANSACTION_COUNTERPARTY_TYPES,
        "Tipe pihak transaksi lapangan",
    )
    clean_name = _normalize_text(name)
    if not clean_name:
        raise FieldTransactionValidationError("Nama pihak transaksi lapangan wajib diisi.")
    clean_company_name = _normalize_text(company_name)
    clean_phone = _normalize_text(phone)
    clean_site_location = _normalize_text(site_location)
    clean_notes = _normalize_text(notes)

    normalized_name = _normalize_identity_token(clean_name)
    normalized_phone = _normalize_identity_token(clean_phone)
    normalized_company = _normalize_identity_token(clean_company_name)
    normalized_site = _normalize_identity_token(clean_site_location)

    active_counterparties = FieldCounterparty.query.filter_by(
        branch_id=branch_id,
        is_active=True,
    ).all()
    for existing in active_counterparties:
        if _normalize_identity_token(existing.name) != normalized_name:
            continue
        if str(existing.counterparty_type or "").strip().upper() != counterparty_type:
            continue

        existing_phone = _normalize_identity_token(getattr(existing, "phone", None))
        existing_company = _normalize_identity_token(getattr(existing, "company_name", None))
        existing_site = _normalize_identity_token(getattr(existing, "site_location", None))

        phone_matches = not normalized_phone or not existing_phone or existing_phone == normalized_phone
        company_matches = not normalized_company or not existing_company or existing_company == normalized_company
        site_matches = not normalized_site or not existing_site or existing_site == normalized_site

        if phone_matches and company_matches and site_matches:
            raise FieldTransactionValidationError(
                f"Pihak transaksi lapangan yang sama sudah ada: {existing.name} "
                f"(ID {existing.id}). Pilih pihak existing agar data tidak ganda."
            )

    resolved_linked_mandor_id = linked_mandor_id
    if counterparty_type == "MANDOR_NON_PT" and not resolved_linked_mandor_id:
        mandors = Mandor.query.filter_by(branch_id=branch_id, is_active=True).all()
        matched_mandor = None
        for mandor in mandors:
            if _normalize_identity_token(mandor.name) != normalized_name:
                continue
            mandor_phone = _normalize_identity_token(getattr(mandor, "phone", None))
            if normalized_phone and mandor_phone and mandor_phone != normalized_phone:
                continue
            matched_mandor = mandor
            break

        if matched_mandor:
            resolved_linked_mandor_id = matched_mandor.id
            for existing in active_counterparties:
                if int(getattr(existing, "linked_mandor_id", 0) or 0) == int(matched_mandor.id):
                    raise FieldTransactionValidationError(
                        f"{T.sub_client} {matched_mandor.name} sudah punya pihak transaksi lapangan aktif "
                        f"(ID {existing.id}). Pilih pihak existing itu agar histori tetap menyatu."
                    )

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_COUNTERPARTY_CREATE",
        description=f"Buat pihak transaksi lapangan {clean_name}.",
        reference_type="field_counterparties",
        user_id=created_by,
        branch_id=branch_id,
        metadata={"counterparty_type": counterparty_type},
    ):
        counterparty = FieldCounterparty(
            branch_id=branch_id,
            counterparty_type=counterparty_type,
            name=clean_name,
            company_name=clean_company_name,
            phone=clean_phone,
            site_location=clean_site_location,
            notes=clean_notes,
            linked_client_id=linked_client_id,
            linked_supplier_id=linked_supplier_id,
            linked_mandor_id=resolved_linked_mandor_id,
            created_by=created_by,
        )
        db.session.add(counterparty)
        db.session.flush()

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_COUNTERPARTY_CREATED",
            action="CREATE",
            table_name="field_counterparties",
            record_id=counterparty.id,
            description=f"Pihak transaksi lapangan dibuat: {counterparty.name}.",
            metadata={
                "counterparty_type": counterparty.counterparty_type,
                "linked_client_id": linked_client_id,
                "linked_supplier_id": linked_supplier_id,
                "linked_mandor_id": resolved_linked_mandor_id,
            },
            user_id=created_by,
            branch_id=branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Pihak transaksi lapangan berhasil dibuat.", counterparty


def create_field_transaction(
    *,
    branch_id,
    transaction_date,
    transaction_direction,
    business_event_type,
    amount,
    created_by=None,
    entry_date=None,
    field_channel="MANUAL",
    counterparty_id=None,
    party_snapshot_name=None,
    party_snapshot_company=None,
    party_snapshot_phone=None,
    site_location=None,
    payment_status=None,
    payment_method=None,
    bank_account_id=None,
    review_status=None,
    evidence_status=None,
    is_manual=True,
    needs_follow_up=False,
    notes=None,
    source_context=None,
    metadata=None,
    allow_non_ui_event=False,
    commit=False,
):
    if not isinstance(transaction_date, date):
        raise FieldTransactionValidationError("Tanggal transaksi lapangan tidak valid.")

    entry_date = entry_date or today_wib()
    if not isinstance(entry_date, date):
        raise FieldTransactionValidationError("Tanggal input transaksi lapangan tidak valid.")

    transaction_direction = _normalize_choice(
        transaction_direction,
        FIELD_TRANSACTION_DIRECTIONS,
        "Arah transaksi lapangan",
    )
    field_channel = _normalize_choice(
        field_channel,
        FIELD_TRANSACTION_CHANNELS,
        "Kanal transaksi lapangan",
    )
    business_event_type = str(business_event_type or "").strip().upper()
    if not business_event_type:
        raise FieldTransactionValidationError("Event bisnis transaksi lapangan wajib diisi.")
    if not allow_non_ui_event:
        try:
            ensure_field_transaction_event_ui_ready(business_event_type)
        except FieldTransactionPolicyError as exc:
            raise FieldTransactionValidationError(str(exc)) from exc

    try:
        policy_defaults = resolve_policy_defaults(business_event_type)
    except FieldTransactionPolicyError as exc:
        raise FieldTransactionValidationError(str(exc)) from exc

    if payment_status in (None, ""):
        payment_status = policy_defaults["payment_status"]
    if review_status in (None, ""):
        review_status = policy_defaults["review_status"]
    if evidence_status in (None, ""):
        evidence_status = policy_defaults["evidence_status"]

    payment_status = _normalize_choice(
        payment_status,
        FIELD_TRANSACTION_PAYMENT_STATUSES,
        "Status pembayaran transaksi lapangan",
    )
    review_status = _normalize_choice(
        review_status,
        FIELD_TRANSACTION_REVIEW_STATUSES,
        "Status review transaksi lapangan",
    )
    evidence_status = _normalize_choice(
        evidence_status,
        FIELD_TRANSACTION_EVIDENCE_STATUSES,
        "Status bukti transaksi lapangan",
    )

    try:
        amount = assert_positive_amount(amount, label="Nominal transaksi lapangan")
    except BusinessRuleError as exc:
        raise FieldTransactionValidationError(str(exc)) from exc

    counterparty = _resolve_counterparty(branch_id, counterparty_id)
    bank_account = _resolve_bank_account(branch_id, bank_account_id)
    counterparty_snapshot = _snapshot_counterparty(counterparty)

    if not party_snapshot_name:
        party_snapshot_name = counterparty_snapshot["party_snapshot_name"]
    if not party_snapshot_company:
        party_snapshot_company = counterparty_snapshot["party_snapshot_company"]
    if not party_snapshot_phone:
        party_snapshot_phone = counterparty_snapshot["party_snapshot_phone"]
    if not site_location:
        site_location = counterparty_snapshot["site_location"]

    try:
        validate_field_transaction_event_payload(
            event_type=business_event_type,
            transaction_direction=transaction_direction,
            amount=amount,
            payment_status=payment_status,
            payment_method=payment_method,
            bank_account_id=getattr(bank_account, "id", None),
            counterparty_id=getattr(counterparty, "id", None),
            party_snapshot_name=party_snapshot_name,
        )
    except FieldTransactionPolicyError as exc:
        raise FieldTransactionValidationError(str(exc)) from exc

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_CREATE",
        description=f"Buat transaksi lapangan {business_event_type}.",
        reference_type="field_transactions",
        user_id=created_by,
        branch_id=branch_id,
        metadata={
            "business_event_type": business_event_type,
            "transaction_direction": transaction_direction,
            "field_channel": field_channel,
            "payment_status": payment_status,
        },
    ):
        transaction = FieldTransaction(
            branch_id=branch_id,
            transaction_number=generate_field_transaction_number(transaction_date),
            transaction_date=transaction_date,
            entry_date=entry_date,
            transaction_direction=transaction_direction,
            business_event_type=business_event_type,
            field_channel=field_channel,
            counterparty_id=getattr(counterparty, "id", None),
            counterparty_type_snapshot=counterparty_snapshot["counterparty_type_snapshot"],
            party_snapshot_name=_normalize_text(party_snapshot_name),
            party_snapshot_company=_normalize_text(party_snapshot_company),
            party_snapshot_phone=_normalize_text(party_snapshot_phone),
            site_location=_normalize_text(site_location),
            amount=amount,
            payment_status=payment_status,
            payment_method=_normalize_text(payment_method),
            bank_account_id=getattr(bank_account, "id", None),
            review_status=review_status,
            posting_status="NOT_POSTED",
            evidence_status=evidence_status,
            is_manual=bool(is_manual),
            needs_follow_up=bool(needs_follow_up),
            notes=_normalize_text(notes),
            source_context_json=_safe_json(source_context),
            metadata_json=_safe_json(metadata),
            created_by=created_by,
        )
        db.session.add(transaction)
        db.session.flush()

        review_log = FieldTransactionReviewLog(
            field_transaction_id=transaction.id,
            from_review_status=None,
            to_review_status=review_status,
            action_type="CREATE",
            note="Draft transaksi lapangan dibuat.",
            metadata_json=_safe_json({"business_event_type": business_event_type}),
            acted_by=created_by,
        )
        db.session.add(review_log)

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_CREATED",
            action="CREATE",
            table_name="field_transactions",
            record_id=transaction.id,
            description=f"Transaksi lapangan dibuat: {transaction.transaction_number}.",
            metadata={
                "transaction_number": transaction.transaction_number,
                "business_event_type": business_event_type,
                "transaction_direction": transaction_direction,
                "amount": amount,
                "payment_status": payment_status,
            },
            user_id=created_by,
            branch_id=branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Transaksi lapangan berhasil dibuat.", transaction


def create_system_linked_field_transaction(
    *,
    parent_field_transaction,
    transaction_date,
    business_event_type,
    amount,
    created_by,
    entry_date=None,
    payment_status=None,
    payment_method=None,
    bank_account_id=None,
    review_status=None,
    evidence_status=None,
    notes=None,
    source_context=None,
    metadata=None,
    mark_posted=False,
    posting_note=None,
    additional_links=None,
    needs_follow_up=False,
    commit=False,
):
    if not parent_field_transaction:
        raise FieldTransactionValidationError("Transaksi lapangan induk tidak ditemukan.")

    policy = get_field_transaction_event_policy(business_event_type)
    _, _, transaction = create_field_transaction(
        branch_id=parent_field_transaction.branch_id,
        transaction_date=transaction_date,
        entry_date=entry_date or transaction_date,
        transaction_direction=policy.get("direction"),
        business_event_type=business_event_type,
        amount=amount,
        created_by=created_by,
        field_channel="SYSTEM",
        counterparty_id=getattr(parent_field_transaction, "counterparty_id", None),
        party_snapshot_name=getattr(parent_field_transaction, "party_snapshot_name", None),
        party_snapshot_company=getattr(parent_field_transaction, "party_snapshot_company", None),
        party_snapshot_phone=getattr(parent_field_transaction, "party_snapshot_phone", None),
        site_location=getattr(parent_field_transaction, "site_location", None),
        payment_status=payment_status,
        payment_method=payment_method,
        bank_account_id=bank_account_id,
        review_status=review_status,
        evidence_status=evidence_status,
        is_manual=False,
        needs_follow_up=needs_follow_up,
        notes=notes,
        source_context=source_context,
        metadata=metadata,
        allow_non_ui_event=True,
        commit=False,
    )

    link_field_transaction(
        transaction,
        link_role="SOURCE_TRANSACTION",
        reference_type="FIELD_TRANSACTION",
        reference_id=parent_field_transaction.id,
        created_by=created_by,
        notes="Jejak sistem dari transaksi lapangan induk.",
        commit=False,
    )

    for item in additional_links or []:
        reference_id = item.get("reference_id")
        if reference_id in (None, ""):
            continue
        link_field_transaction(
            transaction,
            link_role=item.get("link_role"),
            reference_type=item.get("reference_type"),
            reference_id=reference_id,
            created_by=created_by,
            notes=item.get("notes"),
            commit=False,
        )

    if mark_posted:
        previous_review_status = transaction.review_status
        transaction.review_status = "POSTED"
        transaction.posting_status = "POSTED"
        transaction.posted_at = datetime.utcnow()
        transaction.posted_by = created_by
        transaction.reviewed_at = datetime.utcnow()
        transaction.reviewed_by = created_by

        db.session.add(FieldTransactionReviewLog(
            field_transaction_id=transaction.id,
            from_review_status=previous_review_status,
            to_review_status="POSTED",
            action_type="SYSTEM_AUTO_POSTED",
            note=_normalize_text(posting_note) or "Jejak transaksi lapangan turunan diposting otomatis dari transaksi sumber.",
            metadata_json=_safe_json(source_context),
            acted_by=created_by,
        ))

    if commit:
        db.session.commit()

    return True, "Jejak transaksi lapangan turunan berhasil dibuat.", transaction


def update_field_transaction_draft(
    field_transaction,
    *,
    transaction_date,
    transaction_direction,
    business_event_type,
    amount,
    updated_by=None,
    entry_date=None,
    field_channel="MANUAL",
    counterparty_id=None,
    party_snapshot_name=None,
    party_snapshot_company=None,
    party_snapshot_phone=None,
    site_location=None,
    payment_status=None,
    payment_method=None,
    bank_account_id=None,
    notes=None,
    metadata=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionValidationError("Transaksi lapangan tidak ditemukan.")

    current_review_status = str(field_transaction.review_status or "").strip().upper()
    current_posting_status = str(field_transaction.posting_status or "").strip().upper()
    if current_posting_status in {"POSTED", "VOIDED"} or current_review_status in {"POSTED", "VOID", "RECONCILED"}:
        raise FieldTransactionValidationError(
            "Transaksi lapangan yang sudah diposting, di-void, atau direkonsiliasi tidak boleh diedit lagi."
        )

    if not isinstance(transaction_date, date):
        raise FieldTransactionValidationError("Tanggal transaksi lapangan tidak valid.")

    entry_date = entry_date or field_transaction.entry_date or today_wib()
    if not isinstance(entry_date, date):
        raise FieldTransactionValidationError("Tanggal input transaksi lapangan tidak valid.")

    transaction_direction = _normalize_choice(
        transaction_direction,
        FIELD_TRANSACTION_DIRECTIONS,
        "Arah transaksi lapangan",
    )
    field_channel = _normalize_choice(
        field_channel,
        FIELD_TRANSACTION_CHANNELS,
        "Kanal transaksi lapangan",
    )
    business_event_type = str(business_event_type or "").strip().upper()
    if not business_event_type:
        raise FieldTransactionValidationError("Event bisnis transaksi lapangan wajib diisi.")
    try:
        ensure_field_transaction_event_ui_ready(business_event_type)
    except FieldTransactionPolicyError as exc:
        raise FieldTransactionValidationError(str(exc)) from exc

    try:
        amount = assert_positive_amount(amount, label="Nominal transaksi lapangan")
    except BusinessRuleError as exc:
        raise FieldTransactionValidationError(str(exc)) from exc

    counterparty = _resolve_counterparty(field_transaction.branch_id, counterparty_id)
    bank_account = _resolve_bank_account(field_transaction.branch_id, bank_account_id)
    counterparty_snapshot = _snapshot_counterparty(counterparty)

    if not party_snapshot_name:
        party_snapshot_name = counterparty_snapshot["party_snapshot_name"]
    if not party_snapshot_company:
        party_snapshot_company = counterparty_snapshot["party_snapshot_company"]
    if not party_snapshot_phone:
        party_snapshot_phone = counterparty_snapshot["party_snapshot_phone"]
    if not site_location:
        site_location = counterparty_snapshot["site_location"]

    try:
        validate_field_transaction_event_payload(
            event_type=business_event_type,
            transaction_direction=transaction_direction,
            amount=amount,
            payment_status=payment_status or field_transaction.payment_status,
            payment_method=payment_method,
            bank_account_id=getattr(bank_account, "id", None),
            counterparty_id=getattr(counterparty, "id", None),
            party_snapshot_name=party_snapshot_name,
        )
    except FieldTransactionPolicyError as exc:
        raise FieldTransactionValidationError(str(exc)) from exc

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_DRAFT_UPDATE",
        description=f"Perbarui transaksi lapangan {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=updated_by,
        branch_id=field_transaction.branch_id,
        metadata={
            "business_event_type": business_event_type,
            "transaction_direction": transaction_direction,
            "field_channel": field_channel,
        },
    ):
        field_transaction.transaction_date = transaction_date
        field_transaction.entry_date = entry_date
        field_transaction.transaction_direction = transaction_direction
        field_transaction.business_event_type = business_event_type
        field_transaction.field_channel = field_channel
        field_transaction.counterparty_id = getattr(counterparty, "id", None)
        field_transaction.counterparty_type_snapshot = counterparty_snapshot["counterparty_type_snapshot"]
        field_transaction.party_snapshot_name = _normalize_text(party_snapshot_name)
        field_transaction.party_snapshot_company = _normalize_text(party_snapshot_company)
        field_transaction.party_snapshot_phone = _normalize_text(party_snapshot_phone)
        field_transaction.site_location = _normalize_text(site_location)
        field_transaction.amount = amount
        field_transaction.payment_method = _normalize_text(payment_method)
        field_transaction.bank_account_id = getattr(bank_account, "id", None)
        field_transaction.notes = _normalize_text(notes)
        if metadata is not None:
            field_transaction.metadata_json = _safe_json(metadata)

        log = FieldTransactionReviewLog(
            field_transaction_id=field_transaction.id,
            from_review_status=current_review_status,
            to_review_status=current_review_status,
            action_type="DRAFT_UPDATED",
            note="Draft transaksi lapangan diperbarui.",
            metadata_json=_safe_json({"business_event_type": business_event_type, "amount": amount}),
            acted_by=updated_by,
        )
        db.session.add(log)

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_UPDATED",
            action="UPDATE",
            table_name="field_transactions",
            record_id=field_transaction.id,
            description=f"Transaksi lapangan diperbarui: {field_transaction.transaction_number}.",
            metadata={
                "transaction_number": field_transaction.transaction_number,
                "business_event_type": business_event_type,
                "transaction_direction": transaction_direction,
                "amount": amount,
            },
            user_id=updated_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Draft transaksi lapangan berhasil diperbarui.", field_transaction


def update_field_transaction_review_status(
    field_transaction,
    *,
    to_review_status,
    acted_by=None,
    note=None,
    metadata=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionValidationError("Transaksi lapangan tidak ditemukan.")

    to_review_status = _normalize_choice(
        to_review_status,
        FIELD_TRANSACTION_REVIEW_STATUSES,
        "Status review transaksi lapangan",
    )
    from_review_status = str(field_transaction.review_status or "").strip().upper() or None

    if from_review_status == to_review_status:
        return False, "Status review transaksi lapangan tidak berubah.", field_transaction
    _validate_review_status_transition(
        field_transaction,
        from_review_status,
        to_review_status,
        note=note,
    )

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_REVIEW_STATUS_UPDATE",
        description=f"Ubah status review transaksi lapangan {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=acted_by,
        branch_id=field_transaction.branch_id,
        metadata={"from_review_status": from_review_status, "to_review_status": to_review_status},
    ):
        field_transaction.review_status = to_review_status
        field_transaction.reviewed_at = datetime.utcnow()
        field_transaction.reviewed_by = acted_by
        if to_review_status == "POSTED":
            field_transaction.posting_status = "POSTED"
            field_transaction.posted_at = datetime.utcnow()
            field_transaction.posted_by = acted_by
        elif to_review_status == "VOID":
            field_transaction.posting_status = "VOIDED"

        log = FieldTransactionReviewLog(
            field_transaction_id=field_transaction.id,
            from_review_status=from_review_status,
            to_review_status=to_review_status,
            action_type="STATUS_CHANGE",
            note=_normalize_text(note),
            metadata_json=_safe_json(metadata),
            acted_by=acted_by,
        )
        db.session.add(log)

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_STATUS_UPDATED",
            action="UPDATE",
            table_name="field_transactions",
            record_id=field_transaction.id,
            description=(
                f"Status review transaksi lapangan {field_transaction.transaction_number} "
                f"diubah dari {from_review_status or '-'} ke {to_review_status}."
            ),
            metadata={
                "transaction_number": field_transaction.transaction_number,
                "from_review_status": from_review_status,
                "to_review_status": to_review_status,
            },
            user_id=acted_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Status review transaksi lapangan berhasil diperbarui.", field_transaction


def attach_existing_digital_attachment_to_field_transaction(
    field_transaction,
    *,
    digital_attachment_id,
    created_by=None,
    attachment_role="EVIDENCE",
    notes=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionValidationError("Transaksi lapangan tidak ditemukan.")

    attachment_role = str(attachment_role or "EVIDENCE").strip().upper()
    digital_attachment = DigitalAttachment.query.filter_by(
        id=digital_attachment_id,
        is_deleted=False,
    ).first()
    if not digital_attachment:
        raise FieldTransactionValidationError("Lampiran digital tidak ditemukan.")
    if digital_attachment.branch_id not in (None, field_transaction.branch_id):
        raise FieldTransactionValidationError("Lampiran digital tidak sesuai cabang transaksi lapangan.")

    existing = FieldTransactionAttachment.query.filter_by(
        field_transaction_id=field_transaction.id,
        digital_attachment_id=digital_attachment.id,
    ).first()
    if existing:
        return False, "Lampiran digital sudah terhubung ke transaksi lapangan ini.", existing

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_ATTACHMENT_LINK",
        description=f"Tautkan lampiran ke transaksi lapangan {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=created_by,
        branch_id=field_transaction.branch_id,
        metadata={"digital_attachment_id": digital_attachment.id, "attachment_role": attachment_role},
    ):
        from_review_status = str(field_transaction.review_status or "").strip().upper() or None
        attachment_link = FieldTransactionAttachment(
            field_transaction_id=field_transaction.id,
            digital_attachment_id=digital_attachment.id,
            attachment_role=attachment_role,
            status="ATTACHED",
            notes=_normalize_text(notes),
            created_by=created_by,
        )
        db.session.add(attachment_link)

        field_transaction.evidence_status = "ATTACHED"
        to_review_status = (
            "WAITING_CLASSIFICATION"
            if from_review_status == "WAITING_EVIDENCE"
            else from_review_status
        )
        field_transaction.review_status = to_review_status

        log = FieldTransactionReviewLog(
            field_transaction_id=field_transaction.id,
            from_review_status=from_review_status,
            to_review_status=to_review_status,
            action_type="ATTACHMENT_LINKED",
            note="Lampiran bukti ditautkan ke transaksi lapangan.",
            metadata_json=_safe_json({"digital_attachment_id": digital_attachment.id}),
            acted_by=created_by,
        )
        db.session.add(log)

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_ATTACHMENT_LINKED",
            action="UPDATE",
            table_name="field_transactions",
            record_id=field_transaction.id,
            description=f"Lampiran digital ditautkan ke transaksi lapangan {field_transaction.transaction_number}.",
            metadata={
                "transaction_number": field_transaction.transaction_number,
                "digital_attachment_id": digital_attachment.id,
                "attachment_role": attachment_role,
            },
            user_id=created_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Lampiran digital berhasil ditautkan ke transaksi lapangan.", attachment_link


def verify_field_transaction_attachment(
    field_transaction_attachment,
    *,
    verified_by=None,
    note=None,
    commit=False,
):
    if not field_transaction_attachment:
        raise FieldTransactionValidationError("Lampiran transaksi lapangan tidak ditemukan.")

    field_transaction = getattr(field_transaction_attachment, "field_transaction", None)
    if not field_transaction:
        raise FieldTransactionValidationError("Transaksi lapangan untuk lampiran ini tidak ditemukan.")

    current_status = str(field_transaction_attachment.status or "").strip().upper()
    if current_status == "VERIFIED":
        return False, "Lampiran transaksi lapangan sudah terverifikasi.", field_transaction_attachment

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_ATTACHMENT_VERIFY",
        description=f"Verifikasi lampiran transaksi lapangan {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=verified_by,
        branch_id=field_transaction.branch_id,
        metadata={"attachment_id": field_transaction_attachment.id},
    ):
        field_transaction_attachment.status = "VERIFIED"
        field_transaction_attachment.verified_at = datetime.utcnow()
        field_transaction_attachment.verified_by = verified_by
        if note is not None:
            field_transaction_attachment.notes = _normalize_text(note)

        all_attachments = list(getattr(field_transaction, "attachments", []) or [])
        if field_transaction_attachment not in all_attachments:
            all_attachments.append(field_transaction_attachment)
        has_unverified = any(
            str(getattr(item, "status", "") or "").strip().upper() != "VERIFIED"
            for item in all_attachments
        )
        field_transaction.evidence_status = "ATTACHED" if has_unverified else "VERIFIED"

        log = FieldTransactionReviewLog(
            field_transaction_id=field_transaction.id,
            from_review_status=field_transaction.review_status,
            to_review_status=field_transaction.review_status,
            action_type="ATTACHMENT_VERIFIED",
            note="Lampiran transaksi lapangan diverifikasi."
            if not _normalize_text(note)
            else _normalize_text(note),
            metadata_json=_safe_json({"attachment_id": field_transaction_attachment.id}),
            acted_by=verified_by,
        )
        db.session.add(log)

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_ATTACHMENT_VERIFIED",
            action="UPDATE",
            table_name="field_transaction_attachments",
            record_id=field_transaction_attachment.id,
            description=(
                f"Lampiran transaksi lapangan diverifikasi untuk {field_transaction.transaction_number}."
            ),
            metadata={
                "transaction_number": field_transaction.transaction_number,
                "attachment_id": field_transaction_attachment.id,
                "digital_attachment_id": field_transaction_attachment.digital_attachment_id,
            },
            user_id=verified_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Lampiran transaksi lapangan berhasil diverifikasi.", field_transaction_attachment


def find_field_transaction_linked_source(reference_type, reference_id, *, branch_id=None):
    reference_type = str(reference_type or "").strip().upper()
    if not reference_type or reference_id in (None, ""):
        return None

    query = (
        FieldTransactionLink.query.join(
            FieldTransaction,
            FieldTransaction.id == FieldTransactionLink.field_transaction_id,
        )
        .filter(
            FieldTransactionLink.reference_type == reference_type,
            FieldTransactionLink.reference_id == reference_id,
        )
        .order_by(FieldTransactionLink.id.desc())
    )
    if branch_id is not None:
        query = query.filter(FieldTransaction.branch_id == branch_id)
    return query.first()


def link_field_transaction(
    field_transaction,
    *,
    link_role,
    reference_type,
    reference_id,
    created_by=None,
    notes=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionValidationError("Transaksi lapangan tidak ditemukan.")

    link_role = str(link_role or "").strip().upper()
    reference_type = str(reference_type or "").strip().upper()
    if not link_role:
        raise FieldTransactionValidationError("Peran relasi transaksi lapangan wajib diisi.")
    if not reference_type or reference_id in (None, ""):
        raise FieldTransactionValidationError("Referensi relasi transaksi lapangan tidak lengkap.")

    existing = FieldTransactionLink.query.filter_by(
        field_transaction_id=field_transaction.id,
        link_role=link_role,
        reference_type=reference_type,
        reference_id=reference_id,
    ).first()
    if existing:
        return False, "Relasi transaksi lapangan sudah ada.", existing

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_LINK_CREATE",
        description=f"Buat relasi transaksi lapangan {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=created_by,
        branch_id=field_transaction.branch_id,
        metadata={"link_role": link_role, "reference_type": reference_type, "reference_id": reference_id},
    ):
        link = FieldTransactionLink(
            field_transaction_id=field_transaction.id,
            link_role=link_role,
            reference_type=reference_type,
            reference_id=reference_id,
            notes=_normalize_text(notes),
            created_by=created_by,
        )
        db.session.add(link)

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_LINK_CREATED",
            action="CREATE",
            table_name="field_transaction_links",
            record_id=field_transaction.id,
            description=f"Relasi transaksi lapangan dibuat untuk {field_transaction.transaction_number}.",
            metadata={
                "transaction_number": field_transaction.transaction_number,
                "link_role": link_role,
                "reference_type": reference_type,
                "reference_id": reference_id,
            },
            user_id=created_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Relasi transaksi lapangan berhasil dibuat.", link
