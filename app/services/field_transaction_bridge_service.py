import json
from datetime import datetime

from app.extensions import db
from app.models.delivery import Delivery
from app.models.field_transaction import FieldTransactionLink, FieldTransactionReviewLog
from app.models.master import Driver, Mandor, Supplier
from app.services.advance_service import create_advance_transaction
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.operational_expense_service import create_operational_expense
from app.services.transport_expense_service import create_transport_vehicle_expense
from app.utils.terms import T


class FieldTransactionBridgeError(Exception):
    """Raised when a field transaction cannot be bridged safely to a legacy module."""


def _normalize(value):
    return str(value or "").strip().upper()


def _ensure_not_already_posted_or_bridged(field_transaction, link_role):
    posting_status = _normalize(getattr(field_transaction, "posting_status", None))
    review_status = _normalize(getattr(field_transaction, "review_status", None))

    if posting_status == "POSTED":
        raise FieldTransactionBridgeError(
            "Transaksi lapangan ini sudah diposting. Bridge ke modul lama diblok untuk mencegah double posting."
        )
    if posting_status == "VOIDED" or review_status in {"POSTED", "RECONCILED", "VOID", "REJECTED"}:
        raise FieldTransactionBridgeError(
            "Transaksi lapangan ini sudah berada pada status final/tertutup sehingga tidak boleh di-bridge."
        )
    existing_link = FieldTransactionLink.query.filter_by(
        field_transaction_id=field_transaction.id,
        link_role=link_role,
    ).first()
    if existing_link:
        raise FieldTransactionBridgeError("Bridge transaksi lapangan ini sudah pernah dibuat.")
    existing_financial_links = FieldTransactionLink.query.filter(
        FieldTransactionLink.field_transaction_id == field_transaction.id,
        FieldTransactionLink.link_role.in_(("LEDGER", "JOURNAL")),
    ).count()
    if existing_financial_links:
        raise FieldTransactionBridgeError(
            "Transaksi lapangan ini sudah punya jejak ledger/journal. Bridge ke modul lama diblok untuk mencegah double posting."
        )


def _create_link(field_transaction_id, link_role, reference_type, reference_id, created_by):
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


def _mark_field_transaction_bridged(field_transaction, *, created_by, action_type, note, metadata=None):
    previous_status = field_transaction.review_status
    field_transaction.review_status = "POSTED"
    field_transaction.posting_status = "POSTED"
    field_transaction.posted_at = datetime.utcnow()
    field_transaction.posted_by = created_by
    field_transaction.reviewed_at = datetime.utcnow()
    field_transaction.reviewed_by = created_by

    db.session.add(FieldTransactionReviewLog(
        field_transaction_id=field_transaction.id,
        from_review_status=previous_status,
        to_review_status="POSTED",
        action_type=action_type,
        note=note,
        metadata_json=None if metadata is None else json.dumps(metadata),
        acted_by=created_by,
    ))


def _resolve_supplier(branch_id, supplier_id):
    if not supplier_id:
        return None
    supplier = Supplier.query.filter_by(id=supplier_id, branch_id=branch_id, is_active=True).first()
    if not supplier:
        raise FieldTransactionBridgeError("Supplier bridge tidak valid atau tidak aktif.")
    return supplier


def _resolve_driver(branch_id, driver_id):
    if not driver_id:
        return None
    driver = Driver.query.filter_by(id=driver_id, branch_id=branch_id, is_active=True).first()
    if not driver:
        raise FieldTransactionBridgeError("Driver bridge tidak valid atau tidak aktif.")
    return driver


def _resolve_delivery(branch_id, delivery_id):
    if not delivery_id:
        return None
    delivery = Delivery.query.filter_by(id=delivery_id, branch_id=branch_id).first()
    if not delivery:
        raise FieldTransactionBridgeError("Delivery bridge tidak valid.")
    return delivery


def _resolve_mandor(branch_id, mandor_id):
    if not mandor_id:
        return None
    mandor = Mandor.query.filter_by(id=mandor_id, branch_id=branch_id, is_active=True).first()
    if not mandor:
        raise FieldTransactionBridgeError(f"{T.sub_client} bridge tidak valid atau tidak aktif.")
    return mandor


def bridge_to_operational_expense(
    field_transaction,
    *,
    created_by,
    expense_category,
    supplier_id=None,
    vendor_name=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionBridgeError("Transaksi lapangan tidak ditemukan.")
    if _normalize(field_transaction.business_event_type) not in {"SITE_OPERATION_EXPENSE", "KITCHEN_OPERATION_EXPENSE"}:
        raise FieldTransactionBridgeError("Bridge operational expense hanya berlaku untuk event biaya operasional.")
    _ensure_not_already_posted_or_bridged(field_transaction, "OPERATIONAL_EXPENSE")

    supplier = _resolve_supplier(field_transaction.branch_id, supplier_id)

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_BRIDGE_OPERATIONAL_EXPENSE",
        description=f"Bridge transaksi lapangan {field_transaction.transaction_number} ke operational expense.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=created_by,
        branch_id=field_transaction.branch_id,
        metadata={"expense_category": expense_category},
    ):
        _, _, expense = create_operational_expense(
            branch_id=field_transaction.branch_id,
            expense_date=field_transaction.transaction_date,
            expense_category=expense_category,
            payment_method=field_transaction.payment_method,
            amount=field_transaction.amount,
            created_by=created_by,
            bank_account_id=field_transaction.bank_account_id,
            supplier_id=getattr(supplier, "id", None),
            vendor_name=vendor_name or field_transaction.party_snapshot_name,
            reference_number=reference_number,
            notes=notes or field_transaction.notes,
            commit=False,
        )
        db.session.flush()

        _create_link(field_transaction.id, "OPERATIONAL_EXPENSE", "OPERATIONAL_EXPENSE", expense.id, created_by)
        if expense.cash_bank_transaction_id:
            _create_link(field_transaction.id, "LEDGER", "CASH_BANK_TRANSACTION", expense.cash_bank_transaction_id, created_by)
        if expense.journal_id:
            _create_link(field_transaction.id, "JOURNAL", "JOURNAL", expense.journal_id, created_by)

        _mark_field_transaction_bridged(
            field_transaction,
            created_by=created_by,
            action_type="BRIDGE_OPERATIONAL_EXPENSE",
            note=f"Transaksi lapangan dijembatani ke operational expense {expense.expense_number}.",
            metadata={"operational_expense_id": expense.id},
        )

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_BRIDGED_OPERATIONAL_EXPENSE",
            action="UPDATE",
            table_name="field_transactions",
            record_id=field_transaction.id,
            description=f"Transaksi lapangan {field_transaction.transaction_number} dijembatani ke operational expense {expense.expense_number}.",
            metadata={"operational_expense_id": expense.id},
            user_id=created_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()
    return True, "Transaksi lapangan berhasil dijembatani ke biaya operasional.", expense


def bridge_to_transport_expense(
    field_transaction,
    *,
    created_by,
    vehicle_label=None,
    driver_id=None,
    delivery_id=None,
    vendor_name=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionBridgeError("Transaksi lapangan tidak ditemukan.")
    event_type = _normalize(field_transaction.business_event_type)
    if event_type not in {"TRANSPORT_TRIP_EXPENSE", "FUEL_EXPENSE"}:
        raise FieldTransactionBridgeError("Bridge transport hanya berlaku untuk event transport atau BBM.")
    _ensure_not_already_posted_or_bridged(field_transaction, "TRANSPORT_EXPENSE")

    expense_type = "VEHICLE_FUEL" if event_type == "FUEL_EXPENSE" else "TRANSPORT"
    driver = _resolve_driver(field_transaction.branch_id, driver_id)
    delivery = _resolve_delivery(field_transaction.branch_id, delivery_id)

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_BRIDGE_TRANSPORT_EXPENSE",
        description=f"Bridge transaksi lapangan {field_transaction.transaction_number} ke transport expense.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=created_by,
        branch_id=field_transaction.branch_id,
        metadata={"expense_type": expense_type},
    ):
        _, _, expense = create_transport_vehicle_expense(
            branch_id=field_transaction.branch_id,
            expense_date=field_transaction.transaction_date,
            expense_type=expense_type,
            payment_method=field_transaction.payment_method,
            amount=field_transaction.amount,
            created_by=created_by,
            vehicle_label=vehicle_label,
            driver_id=getattr(driver, "id", None),
            delivery_id=getattr(delivery, "id", None),
            bank_account_id=field_transaction.bank_account_id,
            vendor_name=vendor_name or field_transaction.party_snapshot_name,
            reference_number=reference_number,
            notes=notes or field_transaction.notes,
            commit=False,
        )
        db.session.flush()

        _create_link(field_transaction.id, "TRANSPORT_EXPENSE", "TRANSPORT_VEHICLE_EXPENSE", expense.id, created_by)
        if expense.cash_bank_transaction_id:
            _create_link(field_transaction.id, "LEDGER", "CASH_BANK_TRANSACTION", expense.cash_bank_transaction_id, created_by)
        if expense.journal_id:
            _create_link(field_transaction.id, "JOURNAL", "JOURNAL", expense.journal_id, created_by)

        _mark_field_transaction_bridged(
            field_transaction,
            created_by=created_by,
            action_type="BRIDGE_TRANSPORT_EXPENSE",
            note=f"Transaksi lapangan dijembatani ke transport expense {expense.expense_number}.",
            metadata={"transport_expense_id": expense.id},
        )

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_BRIDGED_TRANSPORT_EXPENSE",
            action="UPDATE",
            table_name="field_transactions",
            record_id=field_transaction.id,
            description=f"Transaksi lapangan {field_transaction.transaction_number} dijembatani ke transport expense {expense.expense_number}.",
            metadata={"transport_expense_id": expense.id},
            user_id=created_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()
    return True, "Transaksi lapangan berhasil dijembatani ke biaya transport/BBM.", expense


def bridge_to_advance_transaction(
    field_transaction,
    *,
    created_by,
    mandor_id=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionBridgeError("Transaksi lapangan tidak ditemukan.")
    if _normalize(field_transaction.business_event_type) != "MANDOR_OPERATIONAL_ADVANCE":
        raise FieldTransactionBridgeError(f"Bridge advance hanya berlaku untuk event panjar operasional {T.sub_client_lower}.")
    _ensure_not_already_posted_or_bridged(field_transaction, "ADVANCE_TRANSACTION")

    linked_mandor_id = mandor_id or getattr(getattr(field_transaction, "counterparty", None), "linked_mandor_id", None)
    mandor = _resolve_mandor(field_transaction.branch_id, linked_mandor_id)
    if not mandor:
        raise FieldTransactionBridgeError(
            f"Bridge panjar {T.sub_client_lower} membutuhkan {T.sub_client_lower} master yang valid. Hubungkan pihak transaksi lapangan ke {T.sub_client_lower} atau pilih {T.sub_client_lower} saat bridge."
        )

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="FIELD_TRANSACTION_BRIDGE_ADVANCE",
        description=f"Bridge transaksi lapangan {field_transaction.transaction_number} ke advance.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=created_by,
        branch_id=field_transaction.branch_id,
        metadata={"mandor_id": mandor.id},
    ):
        _, _, advance = create_advance_transaction(
            branch_id=field_transaction.branch_id,
            advance_date=field_transaction.transaction_date,
            advance_type="MANDOR_OPERATIONAL_ADVANCE",
            payment_method=field_transaction.payment_method,
            amount=field_transaction.amount,
            created_by=created_by,
            mandor_id=mandor.id,
            bank_account_id=field_transaction.bank_account_id,
            reference_number=reference_number,
            notes=notes or field_transaction.notes,
            commit=False,
        )
        db.session.flush()

        _create_link(field_transaction.id, "ADVANCE_TRANSACTION", "ADVANCE_TRANSACTION", advance.id, created_by)
        if advance.cash_bank_transaction_id:
            _create_link(field_transaction.id, "LEDGER", "CASH_BANK_TRANSACTION", advance.cash_bank_transaction_id, created_by)
        if advance.journal_id:
            _create_link(field_transaction.id, "JOURNAL", "JOURNAL", advance.journal_id, created_by)

        _mark_field_transaction_bridged(
            field_transaction,
            created_by=created_by,
            action_type="BRIDGE_ADVANCE_TRANSACTION",
            note=f"Transaksi lapangan dijembatani ke advance {advance.advance_number}.",
            metadata={"advance_id": advance.id},
        )

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="FIELD_TRANSACTION_BRIDGED_ADVANCE",
            action="UPDATE",
            table_name="field_transactions",
            record_id=field_transaction.id,
            description=f"Transaksi lapangan {field_transaction.transaction_number} dijembatani ke advance {advance.advance_number}.",
            metadata={"advance_id": advance.id, "mandor_id": mandor.id},
            user_id=created_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()
    return True, f"Transaksi lapangan berhasil dijembatani ke advance {T.sub_client_lower}.", advance
