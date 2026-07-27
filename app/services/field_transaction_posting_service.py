import logging
import json
from datetime import datetime

from app.extensions import db
from app.models.accounting import Journal, JournalDetail
from app.models.finance import CashBankTransaction
from app.models.field_transaction import FieldTransactionLink, FieldTransactionReviewLog
from app.services.accounting_service import generate_journal_number, get_active_account_by_code
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.field_transaction_policy_service import (
    FieldTransactionPolicyError,
    get_field_transaction_event_policy,
    resolve_event_account_map,
)

logger = logging.getLogger(__name__)


FIELD_TRANSACTION_REFERENCE_TYPE = "FIELD_TRANSACTION"


class FieldTransactionPostingError(Exception):
    """Raised when a field transaction cannot be posted safely."""


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/field_transaction_posting_service.py:28")
        return "Rp 0"


def _normalize(value):
    return str(value or "").strip().upper()


def _ledger_account_type(payment_method):
    method = _normalize(payment_method)
    if method == "CASH":
        return "CASH"
    if method in {"TRANSFER", "QRIS"}:
        return "BANK"
    raise FieldTransactionPostingError(f"Metode pembayaran {method or '-'} belum didukung untuk posting ledger.")


def _build_posting_description(field_transaction):
    counterparty_name = (
        getattr(field_transaction, "party_snapshot_name", None)
        or getattr(getattr(field_transaction, "counterparty", None), "name", None)
        or "tanpa pihak"
    )
    return (
        f"{field_transaction.business_event_type} "
        f"{field_transaction.transaction_number} "
        f"({counterparty_name}) "
        f"sebesar {_money(field_transaction.amount)}"
    )


def _ensure_field_transaction_can_post(field_transaction):
    if not field_transaction:
        raise FieldTransactionPostingError("Transaksi lapangan tidak ditemukan.")

    try:
        policy = get_field_transaction_event_policy(field_transaction.business_event_type)
    except FieldTransactionPolicyError as exc:
        raise FieldTransactionPostingError(str(exc)) from exc

    if not policy.get("supports_auto_post"):
        raise FieldTransactionPostingError(
            f"Event {policy['label']} belum didukung untuk posting otomatis pada fase ini."
        )

    if _normalize(field_transaction.review_status) not in {"READY_TO_POST", "POSTED"}:
        raise FieldTransactionPostingError(
            "Transaksi lapangan harus berstatus READY_TO_POST sebelum diposting."
        )

    if _normalize(field_transaction.posting_status) == "POSTED":
        existing_journal = Journal.query.filter_by(
            reference_type=FIELD_TRANSACTION_REFERENCE_TYPE,
            reference_id=field_transaction.id,
        ).first()
        existing_ledger = CashBankTransaction.query.filter_by(
            reference_type=FIELD_TRANSACTION_REFERENCE_TYPE,
            reference_id=field_transaction.id,
        ).first()
        if not existing_journal or not existing_ledger:
            raise FieldTransactionPostingError(
                "Status transaksi lapangan sudah POSTED tetapi jejak journal/ledger tidak lengkap. Perlu investigasi manual."
            )
        return policy, existing_journal, existing_ledger

    if float(field_transaction.amount or 0) <= 0:
        raise FieldTransactionPostingError("Nominal transaksi lapangan tidak valid untuk diposting.")

    if not field_transaction.payment_method:
        raise FieldTransactionPostingError("Metode pembayaran transaksi lapangan wajib ada sebelum posting.")

    existing_journal = Journal.query.filter_by(
        reference_type=FIELD_TRANSACTION_REFERENCE_TYPE,
        reference_id=field_transaction.id,
    ).first()
    existing_ledger = CashBankTransaction.query.filter_by(
        reference_type=FIELD_TRANSACTION_REFERENCE_TYPE,
        reference_id=field_transaction.id,
    ).first()
    if existing_journal or existing_ledger:
        raise FieldTransactionPostingError(
            "Jejak posting transaksi lapangan sudah ada tetapi status posting belum sinkron. Perlu investigasi manual."
        )

    return policy, None, None


def _ensure_link(field_transaction_id, link_role, reference_type, reference_id, created_by):
    existing = FieldTransactionLink.query.filter_by(
        field_transaction_id=field_transaction_id,
        link_role=link_role,
        reference_type=reference_type,
        reference_id=reference_id,
    ).first()
    if existing:
        return existing
    link = FieldTransactionLink(
        field_transaction_id=field_transaction_id,
        link_role=link_role,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )
    db.session.add(link)
    return link


def post_field_transaction(field_transaction, *, posted_by, commit=False):
    policy, existing_journal, existing_ledger = _ensure_field_transaction_can_post(field_transaction)
    if existing_journal and existing_ledger:
        return False, "Transaksi lapangan sudah pernah diposting.", {
            "journal": existing_journal,
            "ledger": existing_ledger,
        }

    account_map = resolve_event_account_map(
        event_type=field_transaction.business_event_type,
        payment_method=field_transaction.payment_method,
        bank_account=field_transaction.bank_account,
    )
    debit_code = account_map.get("debit_account_code")
    credit_code = account_map.get("credit_account_code")
    if not debit_code or not credit_code:
        raise FieldTransactionPostingError(
            f"Mapping akun untuk event {policy['label']} belum lengkap pada fase ini."
        )

    debit_account = get_active_account_by_code(debit_code)
    credit_account = get_active_account_by_code(credit_code)
    missing_accounts = []
    if not debit_account:
        missing_accounts.append(debit_code)
    if not credit_account:
        missing_accounts.append(credit_code)
    if missing_accounts:
        raise FieldTransactionPostingError(
            "Akun COA wajib belum tersedia/aktif: " + ", ".join(missing_accounts)
        )

    amount = float(field_transaction.amount or 0)
    ledger_description = _build_posting_description(field_transaction)
    ledger_account_type = _ledger_account_type(field_transaction.payment_method)
    ledger_transaction_type = "IN" if _normalize(field_transaction.transaction_direction) == "IN" else "OUT"

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_POST",
        description=f"Posting transaksi lapangan {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=posted_by,
        branch_id=field_transaction.branch_id,
        metadata={
            "transaction_number": field_transaction.transaction_number,
            "business_event_type": field_transaction.business_event_type,
            "debit_account_code": debit_code,
            "credit_account_code": credit_code,
        },
    ):
        ledger = CashBankTransaction(
            branch_id=field_transaction.branch_id,
            transaction_date=field_transaction.transaction_date,
            account_type=ledger_account_type,
            bank_account_id=field_transaction.bank_account_id if ledger_account_type == "BANK" else None,
            transaction_type=ledger_transaction_type,
            amount=amount,
            description=ledger_description,
            reference_type=FIELD_TRANSACTION_REFERENCE_TYPE,
            reference_id=field_transaction.id,
            created_by=posted_by,
        )
        db.session.add(ledger)
        db.session.flush()

        journal = Journal(
            journal_number=generate_journal_number(field_transaction.transaction_date),
            journal_date=field_transaction.transaction_date,
            reference_type=FIELD_TRANSACTION_REFERENCE_TYPE,
            reference_id=field_transaction.id,
            description=f"Jurnal {ledger_description}",
            created_by=posted_by,
        )
        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=debit_account.id,
            debit=amount,
            credit=0,
        ))
        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=credit_account.id,
            debit=0,
            credit=amount,
        ))

        _ensure_link(field_transaction.id, "LEDGER", "CASH_BANK_TRANSACTION", ledger.id, posted_by)
        _ensure_link(field_transaction.id, "JOURNAL", "JOURNAL", journal.id, posted_by)

        previous_review_status = field_transaction.review_status
        field_transaction.review_status = "POSTED"
        field_transaction.posting_status = "POSTED"
        field_transaction.posted_at = datetime.utcnow()
        field_transaction.posted_by = posted_by
        field_transaction.reviewed_at = datetime.utcnow()
        field_transaction.reviewed_by = posted_by

        db.session.add(FieldTransactionReviewLog(
            field_transaction_id=field_transaction.id,
            from_review_status=previous_review_status,
            to_review_status="POSTED",
            action_type="POST",
            note="Transaksi lapangan diposting ke ledger kas/bank dan jurnal.",
            metadata_json=json.dumps({
                "journal_id": journal.id,
                "ledger_id": ledger.id,
                "debit_account_code": debit_code,
                "credit_account_code": credit_code,
            }),
            acted_by=posted_by,
        ))

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_POSTED",
            action="POST",
            table_name="field_transactions",
            record_id=field_transaction.id,
            description=f"Transaksi lapangan {field_transaction.transaction_number} diposting.",
            metadata={
                "transaction_number": field_transaction.transaction_number,
                "journal_id": journal.id,
                "ledger_id": ledger.id,
                "debit_account_code": debit_code,
                "credit_account_code": credit_code,
            },
            user_id=posted_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, "Transaksi lapangan berhasil diposting.", {
        "journal": journal,
        "ledger": ledger,
    }
