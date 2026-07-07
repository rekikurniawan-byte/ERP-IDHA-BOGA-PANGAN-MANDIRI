from datetime import date

from app.extensions import db
from app.models.accounting import Journal, JournalDetail
from app.models.finance import CashBankTransaction, BankAccount
from app.models.field_transaction import (
    FieldTransactionLink,
    FieldTransactionReviewLog,
    FieldTransactionSettlement,
    ManualPayable,
    ManualPayablePayment,
    ManualReceivable,
    ManualReceivablePayment,
)
from app.services.accounting_service import generate_journal_number, get_active_account_by_code
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.field_transaction_service import create_system_linked_field_transaction
from app.services.business_logic_guard_service import (
    CUSTOMER_PAYMENT_METHODS,
    SUPPLIER_PAYMENT_METHODS,
    BusinessRuleError,
    assert_date_not_before,
    assert_not_future_date,
    assert_payment_amount_not_over_remaining,
    resolve_invoice_status_after_payment,
    resolve_supplier_bill_status_after_payment,
    validate_choice,
)
from app.services.field_transaction_policy_service import resolve_cash_bank_coa_code


class FieldTransactionSettlementError(Exception):
    """Raised when manual receivable/payable settlement is invalid."""


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _normalize_text(value):
    text = str(value or "").strip()
    return text or None


def _resolve_bank_account(branch_id, bank_account_id):
    if not bank_account_id:
        return None
    bank_account = BankAccount.query.filter_by(
        id=bank_account_id,
        branch_id=branch_id,
        is_active=True,
    ).first()
    if not bank_account:
        raise FieldTransactionSettlementError("Rekening bank tidak valid atau tidak aktif.")
    return bank_account


def _ensure_unique_link(field_transaction_id, link_role, reference_type, reference_id, created_by):
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


def _payment_ledger_account_type(payment_method):
    method = str(payment_method or "").strip().upper()
    if method == "CASH":
        return "CASH"
    if method in {"TRANSFER", "QRIS"}:
        return "BANK"
    raise FieldTransactionSettlementError(
        f"Metode pembayaran {method or '-'} belum didukung untuk ledger pembayaran manual."
    )


def _build_manual_payment_description(document_number, payment_number, party_name, amount):
    return (
        f"{payment_number} untuk {document_number} "
        f"({party_name or 'tanpa pihak'}) "
        f"sebesar {_money(amount)}"
    )


def _create_manual_payment_accounting_trace(
    *,
    branch_id,
    payment_date,
    payment_method,
    bank_account,
    amount,
    debit_account_code,
    credit_account_code,
    payment_number,
    party_name,
    document_number,
    reference_type,
    reference_id,
    created_by,
):
    debit_account = get_active_account_by_code(debit_account_code)
    credit_account = get_active_account_by_code(credit_account_code)
    missing = []
    if not debit_account:
        missing.append(debit_account_code)
    if not credit_account:
        missing.append(credit_account_code)
    if missing:
        raise FieldTransactionSettlementError("Akun COA wajib belum tersedia/aktif: " + ", ".join(missing))

    ledger_description = _build_manual_payment_description(
        document_number=document_number,
        payment_number=payment_number,
        party_name=party_name,
        amount=amount,
    )
    ledger_account_type = _payment_ledger_account_type(payment_method)
    ledger_transaction_type = "IN" if reference_type == "MANUAL_RECEIVABLE_PAYMENT" else "OUT"

    ledger = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=payment_date,
        account_type=ledger_account_type,
        bank_account_id=getattr(bank_account, "id", None) if ledger_account_type == "BANK" else None,
        transaction_type=ledger_transaction_type,
        amount=amount,
        description=ledger_description,
        reference_type=reference_type,
        reference_id=reference_id,
        created_by=created_by,
    )
    db.session.add(ledger)
    db.session.flush()

    journal = Journal(
        journal_number=generate_journal_number(payment_date),
        journal_date=payment_date,
        reference_type=reference_type,
        reference_id=reference_id,
        description=f"Jurnal {ledger_description}",
        created_by=created_by,
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

    return ledger, journal


def _create_payment_field_transaction_trace(
    *,
    parent_field_transaction,
    business_event_type,
    transaction_date,
    amount,
    payment_method,
    bank_account_id,
    created_by,
    notes,
    source_reference_type,
    source_reference_id,
    source_document_number,
    payment_number,
    ledger_id,
    journal_id,
):
    if not parent_field_transaction:
        return None

    _, _, trace_transaction = create_system_linked_field_transaction(
        parent_field_transaction=parent_field_transaction,
        transaction_date=transaction_date,
        business_event_type=business_event_type,
        amount=amount,
        created_by=created_by,
        payment_status="PAID",
        payment_method=payment_method,
        bank_account_id=bank_account_id,
        review_status="READY_TO_POST",
        evidence_status=getattr(parent_field_transaction, "evidence_status", None) or "PENDING",
        notes=_normalize_text(notes) or f"Jejak otomatis dari {payment_number} untuk {source_document_number}.",
        source_context={
            "generated_mode": "SYSTEM_LINKED_PAYMENT",
            "source_field_transaction_id": parent_field_transaction.id,
            "source_reference_type": source_reference_type,
            "source_reference_id": source_reference_id,
            "payment_number": payment_number,
            "source_document_number": source_document_number,
        },
        metadata={
            "source_reference_type": source_reference_type,
            "source_reference_id": source_reference_id,
            "payment_number": payment_number,
            "ledger_id": ledger_id,
            "journal_id": journal_id,
        },
        mark_posted=True,
        posting_note="Jejak transaksi lapangan turunan diposting otomatis dari pembayaran manual.",
        additional_links=[
            {
                "link_role": source_reference_type,
                "reference_type": source_reference_type,
                "reference_id": source_reference_id,
                "notes": f"Sumber dokumen {source_document_number}.",
            },
            {
                "link_role": "LEDGER",
                "reference_type": "CASH_BANK_TRANSACTION",
                "reference_id": ledger_id,
            },
            {
                "link_role": "JOURNAL",
                "reference_type": "JOURNAL",
                "reference_id": journal_id,
            },
        ],
        commit=False,
    )
    return trace_transaction


def generate_manual_receivable_number(receivable_date):
    prefix = f"MREC-{receivable_date.strftime('%Y%m%d')}"
    counter = ManualReceivable.query.filter(
        ManualReceivable.receivable_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not ManualReceivable.query.filter_by(receivable_number=number).first():
            return number
        counter += 1


def generate_manual_receivable_payment_number(payment_date):
    prefix = f"MRPAY-{payment_date.strftime('%Y%m%d')}"
    counter = ManualReceivablePayment.query.filter(
        ManualReceivablePayment.payment_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not ManualReceivablePayment.query.filter_by(payment_number=number).first():
            return number
        counter += 1


def generate_manual_payable_number(payable_date):
    prefix = f"MPAY-{payable_date.strftime('%Y%m%d')}"
    counter = ManualPayable.query.filter(
        ManualPayable.payable_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not ManualPayable.query.filter_by(payable_number=number).first():
            return number
        counter += 1


def generate_manual_payable_payment_number(payment_date):
    prefix = f"MPPAY-{payment_date.strftime('%Y%m%d')}"
    counter = ManualPayablePayment.query.filter(
        ManualPayablePayment.payment_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not ManualPayablePayment.query.filter_by(payment_number=number).first():
            return number
        counter += 1


def generate_field_settlement_number(settlement_date, settlement_type):
    type_code = str(settlement_type or "SETTLEMENT").strip().upper()[:6]
    prefix = f"FTS-{type_code}-{settlement_date.strftime('%Y%m%d')}"
    counter = FieldTransactionSettlement.query.filter(
        FieldTransactionSettlement.settlement_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not FieldTransactionSettlement.query.filter_by(settlement_number=number).first():
            return number
        counter += 1


def _ensure_receivable_event(field_transaction):
    event_type = str(getattr(field_transaction, "business_event_type", "") or "").strip().upper()
    if event_type != "MANUAL_RECEIVABLE_CREATED":
        raise FieldTransactionSettlementError(
            "Dokumen piutang manual hanya boleh dibuat dari event MANUAL_RECEIVABLE_CREATED."
        )


def _ensure_payable_event(field_transaction):
    event_type = str(getattr(field_transaction, "business_event_type", "") or "").strip().upper()
    if event_type != "UNFORMAL_VENDOR_PAYABLE":
        raise FieldTransactionSettlementError(
            "Dokumen hutang manual hanya boleh dibuat dari event UNFORMAL_VENDOR_PAYABLE."
        )


def create_manual_receivable_for_field_transaction(
    field_transaction,
    *,
    created_by,
    due_date=None,
    notes=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionSettlementError("Transaksi lapangan tidak ditemukan.")
    _ensure_receivable_event(field_transaction)

    existing = ManualReceivable.query.filter_by(field_transaction_id=field_transaction.id).first()
    if existing:
        return False, "Dokumen piutang manual untuk transaksi ini sudah ada.", existing

    amount = float(field_transaction.amount or 0)
    if amount <= 0:
        raise FieldTransactionSettlementError("Nominal transaksi lapangan tidak valid untuk piutang manual.")

    receivable_date = field_transaction.transaction_date
    due_date = due_date or receivable_date
    if not isinstance(due_date, date):
        raise FieldTransactionSettlementError("Tanggal jatuh tempo piutang manual tidak valid.")
    if due_date < receivable_date:
        raise FieldTransactionSettlementError("Tanggal jatuh tempo piutang manual tidak boleh lebih awal dari tanggal transaksi.")

    party_name = (
        field_transaction.party_snapshot_name
        or getattr(getattr(field_transaction, "counterparty", None), "name", None)
    )
    if not party_name:
        raise FieldTransactionSettlementError("Piutang manual wajib memiliki nama pihak.")

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="MANUAL_RECEIVABLE_CREATE",
        description=f"Buat piutang manual untuk {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=created_by,
        branch_id=field_transaction.branch_id,
        metadata={"amount": amount},
    ):
        receivable = ManualReceivable(
            branch_id=field_transaction.branch_id,
            receivable_number=generate_manual_receivable_number(receivable_date),
            field_transaction_id=field_transaction.id,
            counterparty_id=field_transaction.counterparty_id,
            receivable_date=receivable_date,
            due_date=due_date,
            party_name=party_name,
            party_company=field_transaction.party_snapshot_company,
            party_phone=field_transaction.party_snapshot_phone,
            total_amount=amount,
            paid_amount=0,
            remaining_amount=amount,
            status="OPEN",
            notes=_normalize_text(notes) or field_transaction.notes,
            created_by=created_by,
        )
        db.session.add(receivable)
        db.session.flush()

        _ensure_unique_link(
            field_transaction.id,
            "MANUAL_RECEIVABLE",
            "MANUAL_RECEIVABLE",
            receivable.id,
            created_by,
        )
        field_transaction.payment_status = "UNPAID"
        field_transaction.needs_follow_up = True

        db.session.add(FieldTransactionReviewLog(
            field_transaction_id=field_transaction.id,
            from_review_status=field_transaction.review_status,
            to_review_status=field_transaction.review_status,
            action_type="MANUAL_RECEIVABLE_CREATED",
            note=f"Piutang manual {receivable.receivable_number} dibuat.",
            acted_by=created_by,
        ))

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="MANUAL_RECEIVABLE_CREATED",
            action="CREATE",
            table_name="manual_receivables",
            record_id=receivable.id,
            description=f"Piutang manual {receivable.receivable_number} dibuat dari transaksi lapangan {field_transaction.transaction_number}.",
            metadata={
                "field_transaction_id": field_transaction.id,
                "amount": amount,
                "due_date": due_date.isoformat(),
            },
            user_id=created_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, f"Piutang manual {receivable.receivable_number} sebesar {_money(amount)} berhasil dibuat.", receivable


def create_manual_payable_for_field_transaction(
    field_transaction,
    *,
    created_by,
    due_date=None,
    notes=None,
    commit=False,
):
    if not field_transaction:
        raise FieldTransactionSettlementError("Transaksi lapangan tidak ditemukan.")
    _ensure_payable_event(field_transaction)

    existing = ManualPayable.query.filter_by(field_transaction_id=field_transaction.id).first()
    if existing:
        return False, "Dokumen hutang manual untuk transaksi ini sudah ada.", existing

    amount = float(field_transaction.amount or 0)
    if amount <= 0:
        raise FieldTransactionSettlementError("Nominal transaksi lapangan tidak valid untuk hutang manual.")

    payable_date = field_transaction.transaction_date
    due_date = due_date or payable_date
    if not isinstance(due_date, date):
        raise FieldTransactionSettlementError("Tanggal jatuh tempo hutang manual tidak valid.")
    if due_date < payable_date:
        raise FieldTransactionSettlementError("Tanggal jatuh tempo hutang manual tidak boleh lebih awal dari tanggal transaksi.")

    party_name = (
        field_transaction.party_snapshot_name
        or getattr(getattr(field_transaction, "counterparty", None), "name", None)
    )
    if not party_name:
        raise FieldTransactionSettlementError("Hutang manual wajib memiliki nama pihak.")

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="MANUAL_PAYABLE_CREATE",
        description=f"Buat hutang manual untuk {field_transaction.transaction_number}.",
        reference_type="field_transactions",
        reference_id=field_transaction.id,
        user_id=created_by,
        branch_id=field_transaction.branch_id,
        metadata={"amount": amount},
    ):
        payable = ManualPayable(
            branch_id=field_transaction.branch_id,
            payable_number=generate_manual_payable_number(payable_date),
            field_transaction_id=field_transaction.id,
            counterparty_id=field_transaction.counterparty_id,
            payable_date=payable_date,
            due_date=due_date,
            party_name=party_name,
            party_company=field_transaction.party_snapshot_company,
            party_phone=field_transaction.party_snapshot_phone,
            total_amount=amount,
            paid_amount=0,
            remaining_amount=amount,
            status="OPEN",
            notes=_normalize_text(notes) or field_transaction.notes,
            created_by=created_by,
        )
        db.session.add(payable)
        db.session.flush()

        _ensure_unique_link(
            field_transaction.id,
            "MANUAL_PAYABLE",
            "MANUAL_PAYABLE",
            payable.id,
            created_by,
        )
        field_transaction.payment_status = "UNPAID"
        field_transaction.needs_follow_up = True

        db.session.add(FieldTransactionReviewLog(
            field_transaction_id=field_transaction.id,
            from_review_status=field_transaction.review_status,
            to_review_status=field_transaction.review_status,
            action_type="MANUAL_PAYABLE_CREATED",
            note=f"Hutang manual {payable.payable_number} dibuat.",
            acted_by=created_by,
        ))

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="MANUAL_PAYABLE_CREATED",
            action="CREATE",
            table_name="manual_payables",
            record_id=payable.id,
            description=f"Hutang manual {payable.payable_number} dibuat dari transaksi lapangan {field_transaction.transaction_number}.",
            metadata={
                "field_transaction_id": field_transaction.id,
                "amount": amount,
                "due_date": due_date.isoformat(),
            },
            user_id=created_by,
            branch_id=field_transaction.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, f"Hutang manual {payable.payable_number} sebesar {_money(amount)} berhasil dibuat.", payable


def record_manual_receivable_payment(
    receivable,
    *,
    payment_date,
    payment_method,
    amount,
    paid_by,
    bank_account_id=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not receivable:
        raise FieldTransactionSettlementError("Piutang manual tidak ditemukan.")

    try:
        amount = assert_payment_amount_not_over_remaining(
            amount,
            receivable.remaining_amount,
            label="Nominal pembayaran piutang manual",
        )
        assert_date_not_before(
            payment_date,
            receivable.receivable_date,
            label="Tanggal pembayaran piutang manual",
            reference_label="tanggal piutang manual",
        )
        assert_not_future_date(payment_date, date.today(), label="Tanggal pembayaran piutang manual")
        method = validate_choice(payment_method, CUSTOMER_PAYMENT_METHODS, "Metode pembayaran piutang manual")
    except BusinessRuleError as error:
        raise FieldTransactionSettlementError(str(error))

    bank_account = None
    if method == "TRANSFER":
        bank_account = _resolve_bank_account(receivable.branch_id, bank_account_id)

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="MANUAL_RECEIVABLE_PAYMENT_CREATE",
        description=f"Catat pembayaran piutang manual {receivable.receivable_number}.",
        reference_type="manual_receivables",
        reference_id=receivable.id,
        user_id=paid_by,
        branch_id=receivable.branch_id,
        metadata={"amount": amount, "method": method},
    ):
        payment = ManualReceivablePayment(
            branch_id=receivable.branch_id,
            payment_number=generate_manual_receivable_payment_number(payment_date),
            manual_receivable_id=receivable.id,
            payment_date=payment_date,
            payment_method=method,
            bank_account_id=getattr(bank_account, "id", None),
            amount=amount,
            reference_number=_normalize_text(reference_number),
            notes=_normalize_text(notes),
            paid_by=paid_by,
        )
        db.session.add(payment)
        db.session.flush()

        cash_bank_code = resolve_cash_bank_coa_code(
            payment_method=method,
            bank_account=bank_account,
        )
        ledger, journal = _create_manual_payment_accounting_trace(
            branch_id=receivable.branch_id,
            payment_date=payment_date,
            payment_method=method,
            bank_account=bank_account,
            amount=amount,
            debit_account_code=cash_bank_code,
            credit_account_code="1004",
            payment_number=payment.payment_number,
            party_name=receivable.party_name,
            document_number=receivable.receivable_number,
            reference_type="MANUAL_RECEIVABLE_PAYMENT",
            reference_id=payment.id,
            created_by=paid_by,
        )
        payment.cash_bank_transaction_id = ledger.id
        payment.journal_id = journal.id

        new_paid = float(receivable.paid_amount or 0) + amount
        new_remaining = float(receivable.total_amount or 0) - new_paid
        if new_remaining <= 0:
            new_remaining = 0
        receivable.paid_amount = new_paid
        receivable.remaining_amount = new_remaining
        receivable.status = resolve_invoice_status_after_payment(receivable.total_amount, new_paid)

        settlement = FieldTransactionSettlement(
            field_transaction_id=receivable.field_transaction_id,
            settlement_number=generate_field_settlement_number(payment_date, "RECPAY"),
            settlement_date=payment_date,
            settlement_type="RECEIVABLE_PAYMENT",
            amount=amount,
            reference_type="MANUAL_RECEIVABLE_PAYMENT",
            reference_id=payment.id,
            notes=_normalize_text(notes),
            created_by=paid_by,
        )
        db.session.add(settlement)
        _ensure_unique_link(
            receivable.field_transaction_id,
            "MANUAL_RECEIVABLE_PAYMENT",
            "MANUAL_RECEIVABLE_PAYMENT",
            payment.id,
            paid_by,
        )
        _ensure_unique_link(
            receivable.field_transaction_id,
            "LEDGER",
            "CASH_BANK_TRANSACTION",
            ledger.id,
            paid_by,
        )
        _ensure_unique_link(
            receivable.field_transaction_id,
            "JOURNAL",
            "JOURNAL",
            journal.id,
            paid_by,
        )

        field_transaction = receivable.field_transaction
        if field_transaction:
            field_transaction.payment_status = "PAID" if new_remaining <= 0 else "PARTIAL"
            field_transaction.needs_follow_up = new_remaining > 0
            db.session.add(FieldTransactionReviewLog(
                field_transaction_id=field_transaction.id,
                from_review_status=field_transaction.review_status,
                to_review_status=field_transaction.review_status,
                action_type="MANUAL_RECEIVABLE_PAYMENT",
                note=f"Pembayaran piutang manual {payment.payment_number} dicatat.",
                acted_by=paid_by,
            ))
            _create_payment_field_transaction_trace(
                parent_field_transaction=field_transaction,
                business_event_type="MANUAL_RECEIVABLE_PAYMENT",
                transaction_date=payment_date,
                amount=amount,
                payment_method=method,
                bank_account_id=getattr(bank_account, "id", None),
                created_by=paid_by,
                notes=notes,
                source_reference_type="MANUAL_RECEIVABLE_PAYMENT",
                source_reference_id=payment.id,
                source_document_number=receivable.receivable_number,
                payment_number=payment.payment_number,
                ledger_id=ledger.id,
                journal_id=journal.id,
            )

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="MANUAL_RECEIVABLE_PAYMENT_CREATED",
            action="CREATE",
            table_name="manual_receivable_payments",
            record_id=payment.id,
            description=f"Pembayaran piutang manual {payment.payment_number} dicatat untuk {receivable.receivable_number}.",
            metadata={
                "manual_receivable_id": receivable.id,
                "field_transaction_id": receivable.field_transaction_id,
                "amount": amount,
                "method": method,
                "cash_bank_transaction_id": ledger.id,
                "journal_id": journal.id,
            },
            user_id=paid_by,
            branch_id=receivable.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, f"Pembayaran piutang manual {payment.payment_number} sebesar {_money(amount)} berhasil dicatat.", payment


def record_manual_payable_payment(
    payable,
    *,
    payment_date,
    payment_method,
    amount,
    paid_by,
    bank_account_id=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not payable:
        raise FieldTransactionSettlementError("Hutang manual tidak ditemukan.")

    try:
        amount = assert_payment_amount_not_over_remaining(
            amount,
            payable.remaining_amount,
            label="Nominal pembayaran hutang manual",
        )
        assert_date_not_before(
            payment_date,
            payable.payable_date,
            label="Tanggal pembayaran hutang manual",
            reference_label="tanggal hutang manual",
        )
        assert_not_future_date(payment_date, date.today(), label="Tanggal pembayaran hutang manual")
        method = validate_choice(payment_method, SUPPLIER_PAYMENT_METHODS, "Metode pembayaran hutang manual")
    except BusinessRuleError as error:
        raise FieldTransactionSettlementError(str(error))

    bank_account = None
    if method == "TRANSFER":
        bank_account = _resolve_bank_account(payable.branch_id, bank_account_id)

    with atomic_business_action(
        module="FIELD_TRANSACTION",
        action="MANUAL_PAYABLE_PAYMENT_CREATE",
        description=f"Catat pembayaran hutang manual {payable.payable_number}.",
        reference_type="manual_payables",
        reference_id=payable.id,
        user_id=paid_by,
        branch_id=payable.branch_id,
        metadata={"amount": amount, "method": method},
    ):
        payment = ManualPayablePayment(
            branch_id=payable.branch_id,
            payment_number=generate_manual_payable_payment_number(payment_date),
            manual_payable_id=payable.id,
            payment_date=payment_date,
            payment_method=method,
            bank_account_id=getattr(bank_account, "id", None),
            amount=amount,
            reference_number=_normalize_text(reference_number),
            notes=_normalize_text(notes),
            paid_by=paid_by,
        )
        db.session.add(payment)
        db.session.flush()

        cash_bank_code = resolve_cash_bank_coa_code(
            payment_method=method,
            bank_account=bank_account,
        )
        ledger, journal = _create_manual_payment_accounting_trace(
            branch_id=payable.branch_id,
            payment_date=payment_date,
            payment_method=method,
            bank_account=bank_account,
            amount=amount,
            debit_account_code="2002",
            credit_account_code=cash_bank_code,
            payment_number=payment.payment_number,
            party_name=payable.party_name,
            document_number=payable.payable_number,
            reference_type="MANUAL_PAYABLE_PAYMENT",
            reference_id=payment.id,
            created_by=paid_by,
        )
        payment.cash_bank_transaction_id = ledger.id
        payment.journal_id = journal.id

        new_paid = float(payable.paid_amount or 0) + amount
        new_remaining = float(payable.total_amount or 0) - new_paid
        if new_remaining <= 0:
            new_remaining = 0
        payable.paid_amount = new_paid
        payable.remaining_amount = new_remaining
        payable.status = resolve_supplier_bill_status_after_payment(payable.total_amount, new_paid)

        settlement = FieldTransactionSettlement(
            field_transaction_id=payable.field_transaction_id,
            settlement_number=generate_field_settlement_number(payment_date, "PAYPAY"),
            settlement_date=payment_date,
            settlement_type="PAYABLE_PAYMENT",
            amount=amount,
            reference_type="MANUAL_PAYABLE_PAYMENT",
            reference_id=payment.id,
            notes=_normalize_text(notes),
            created_by=paid_by,
        )
        db.session.add(settlement)
        _ensure_unique_link(
            payable.field_transaction_id,
            "MANUAL_PAYABLE_PAYMENT",
            "MANUAL_PAYABLE_PAYMENT",
            payment.id,
            paid_by,
        )
        _ensure_unique_link(
            payable.field_transaction_id,
            "LEDGER",
            "CASH_BANK_TRANSACTION",
            ledger.id,
            paid_by,
        )
        _ensure_unique_link(
            payable.field_transaction_id,
            "JOURNAL",
            "JOURNAL",
            journal.id,
            paid_by,
        )

        field_transaction = payable.field_transaction
        if field_transaction:
            field_transaction.payment_status = "PAID" if new_remaining <= 0 else "PARTIAL"
            field_transaction.needs_follow_up = new_remaining > 0
            db.session.add(FieldTransactionReviewLog(
                field_transaction_id=field_transaction.id,
                from_review_status=field_transaction.review_status,
                to_review_status=field_transaction.review_status,
                action_type="MANUAL_PAYABLE_PAYMENT",
                note=f"Pembayaran hutang manual {payment.payment_number} dicatat.",
                acted_by=paid_by,
            ))
            _create_payment_field_transaction_trace(
                parent_field_transaction=field_transaction,
                business_event_type="VENDOR_PAYABLE_PAYMENT",
                transaction_date=payment_date,
                amount=amount,
                payment_method=method,
                bank_account_id=getattr(bank_account, "id", None),
                created_by=paid_by,
                notes=notes,
                source_reference_type="MANUAL_PAYABLE_PAYMENT",
                source_reference_id=payment.id,
                source_document_number=payable.payable_number,
                payment_number=payment.payment_number,
                ledger_id=ledger.id,
                journal_id=journal.id,
            )

        record_audit_log(
            module="FIELD_TRANSACTION",
            event_type="MANUAL_PAYABLE_PAYMENT_CREATED",
            action="CREATE",
            table_name="manual_payable_payments",
            record_id=payment.id,
            description=f"Pembayaran hutang manual {payment.payment_number} dicatat untuk {payable.payable_number}.",
            metadata={
                "manual_payable_id": payable.id,
                "field_transaction_id": payable.field_transaction_id,
                "amount": amount,
                "method": method,
                "cash_bank_transaction_id": ledger.id,
                "journal_id": journal.id,
            },
            user_id=paid_by,
            branch_id=payable.branch_id,
            commit=False,
        )

    if commit:
        db.session.commit()

    return True, f"Pembayaran hutang manual {payment.payment_number} sebesar {_money(amount)} berhasil dicatat.", payment
