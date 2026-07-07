from datetime import date

from sqlalchemy import inspect

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.finance import (
    AdvanceSettlement,
    AdvanceTransaction,
    BankAccount,
    CashBankTransaction,
    Invoice,
    SupplierBill,
)
from app.models.master import Client, Mandor, Supplier
from app.services.accounting_service import generate_journal_number
from app.services.audit_log_service import record_audit_log
from app.services.field_transaction_service import (
    create_system_linked_field_transaction,
    find_field_transaction_linked_source,
)


ADVANCE_REFERENCE_TYPE = "ADVANCE_TRANSACTION"
ADVANCE_SETTLEMENT_REFERENCE_TYPE = "ADVANCE_SETTLEMENT"

CLIENT_DP_RECEIVED = "CLIENT_DP_RECEIVED"
SUPPLIER_ADVANCE_PAID = "SUPPLIER_ADVANCE_PAID"
MANDOR_OPERATIONAL_ADVANCE = "MANDOR_OPERATIONAL_ADVANCE"

ADVANCE_TYPES = {
    CLIENT_DP_RECEIVED: {
        "label": "DP Client Diterima",
        "party_type": "CLIENT",
        "cash_direction": "IN",
        "journal_direction": "CREDIT_ADVANCE",
        "description": "Uang muka/DP diterima dari client sebelum invoice final.",
    },
    SUPPLIER_ADVANCE_PAID: {
        "label": "Uang Muka Supplier Dibayar",
        "party_type": "SUPPLIER",
        "cash_direction": "OUT",
        "journal_direction": "DEBIT_ADVANCE",
        "description": "Uang muka dibayar ke supplier sebelum tagihan final.",
    },
    MANDOR_OPERATIONAL_ADVANCE: {
        "label": "Panjar Operasional Mandor",
        "party_type": "MANDOR",
        "cash_direction": "OUT",
        "journal_direction": "DEBIT_ADVANCE",
        "description": "Panjar operasional ke mandor/PIC lapangan. Bukan payroll.",
    },
}

SETTLEMENT_TYPES = {
    "CLIENT_INVOICE": {
        "advance_type": CLIENT_DP_RECEIVED,
        "reference_type": "INVOICE",
        "description": "Pemakaian DP client untuk mengurangi piutang invoice.",
    },
    "SUPPLIER_BILL": {
        "advance_type": SUPPLIER_ADVANCE_PAID,
        "reference_type": "SUPPLIER_BILL",
        "description": "Pemakaian uang muka supplier untuk mengurangi hutang supplier.",
    },
    "MANDOR_EXPENSE_PROOF": {
        "advance_type": MANDOR_OPERATIONAL_ADVANCE,
        "reference_type": "MANDOR_EXPENSE_PROOF",
        "description": "Pertanggungjawaban panjar mandor. Jurnal final menunggu PRODUCTION expense mapping.",
    },
}

MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES = {
    "5002": {
        "label": "Operasional Dapur",
        "account_label": "5002 Biaya Operasional Dapur",
        "description": "Pertanggungjawaban panjar untuk kebutuhan operasional dapur.",
    },
    "5003": {
        "label": "Transportasi",
        "account_label": "5003 Biaya Transportasi",
        "description": "Pertanggungjawaban panjar untuk ongkos jalan, kirim, atau logistik.",
    },
    "5005": {
        "label": "Listrik & Air",
        "account_label": "5005 Biaya Listrik & Air",
        "description": "Pertanggungjawaban panjar untuk utilitas lokasi kerja.",
    },
    "5006": {
        "label": "Gas / LPG",
        "account_label": "5006 Biaya Gas",
        "description": "Pertanggungjawaban panjar untuk gas atau LPG.",
    },
    "5007": {
        "label": "Perawatan",
        "account_label": "5007 Biaya Perawatan",
        "description": "Pertanggungjawaban panjar untuk maintenance/perbaikan kecil.",
    },
    "5008": {
        "label": "Administrasi Site",
        "account_label": "5008 Biaya Administrasi",
        "description": "Pertanggungjawaban panjar untuk pembelian operasional umum/site.",
    },
    "5010": {
        "label": "Kemasan",
        "account_label": "5010 Biaya Kemasan",
        "description": "Pertanggungjawaban panjar untuk box, plastik, atau perlengkapan packing.",
    },
    "5011": {
        "label": "BBM",
        "account_label": "5011 Biaya BBM Kendaraan",
        "description": "Pertanggungjawaban panjar untuk bahan bakar kendaraan operasional.",
    },
}


def _money(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        return "Rp 0"


def _normalize(value):
    return str(value or "").strip().upper()


def is_advance_schema_ready():
    """Avoid crashing local runtime when migration has not been applied yet."""
    try:
        inspector = inspect(db.engine)
        return inspector.has_table("advance_transactions") and inspector.has_table("advance_settlements")
    except Exception:
        return False


def get_account_by_code(code):
    return Account.query.filter_by(account_code=code, is_active=True).first()


def resolve_cash_account_code(account_type):
    account_type = _normalize(account_type)
    if account_type == "CASH":
        return "1001"
    if account_type == "BANK":
        return "1002"
    raise Exception("Akun kas/bank harus CASH atau BANK.")


def generate_advance_number(advance_date):
    prefix = f"ADV-{advance_date.strftime('%Y%m%d')}"
    counter = AdvanceTransaction.query.filter(
        AdvanceTransaction.advance_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not AdvanceTransaction.query.filter_by(advance_number=number).first():
            return number
        counter += 1


def generate_settlement_number(settlement_date):
    prefix = f"ADVS-{settlement_date.strftime('%Y%m%d')}"
    counter = AdvanceSettlement.query.filter(
        AdvanceSettlement.settlement_number.like(f"{prefix}-%")
    ).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not AdvanceSettlement.query.filter_by(settlement_number=number).first():
            return number
        counter += 1


def get_advance_type_choices():
    return [
        {"value": key, **value}
        for key, value in ADVANCE_TYPES.items()
    ]


def get_mandor_expense_proof_choices():
    return [
        {"value": key, **value}
        for key, value in sorted(MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES.items())
    ]


def get_advance_status_summary(branch_id):
    if not is_advance_schema_ready():
        return {"total": 0, "open": 0, "settled": 0, "remaining": 0}

    rows = AdvanceTransaction.query.filter_by(branch_id=branch_id).all()
    return {
        "total": len(rows),
        "open": len([row for row in rows if _normalize(row.status) in {"OPEN", "PARTIAL"}]),
        "settled": len([row for row in rows if _normalize(row.status) == "SETTLED"]),
        "remaining": sum(float(row.remaining_amount or 0) for row in rows if _normalize(row.status) in {"OPEN", "PARTIAL"}),
    }


def get_party_label(advance):
    if not advance:
        return "-"
    if advance.party_type == "CLIENT":
        return advance.client.name if advance.client else f"Client ID {advance.client_id or '-'}"
    if advance.party_type == "SUPPLIER":
        return advance.supplier.supplier_name if advance.supplier else f"Supplier ID {advance.supplier_id or '-'}"
    if advance.party_type == "MANDOR":
        return advance.mandor.name if advance.mandor else f"Mandor ID {advance.mandor_id or '-'}"
    return "-"


def validate_party(branch_id, advance_type, client_id=None, supplier_id=None, mandor_id=None):
    rule = ADVANCE_TYPES.get(advance_type)
    if not rule:
        raise Exception("Tipe uang muka tidak dikenali.")

    expected_party_type = rule["party_type"]

    if expected_party_type == "CLIENT":
        if not client_id:
            raise Exception("DP client wajib memilih client.")
        party = Client.query.filter_by(id=client_id, is_active=True).first()
        if not party:
            raise Exception("Client tidak valid atau tidak aktif.")
        return "CLIENT", party.id, None, None

    if expected_party_type == "SUPPLIER":
        if not supplier_id:
            raise Exception("Uang muka supplier wajib memilih supplier.")
        party = Supplier.query.filter_by(id=supplier_id, branch_id=branch_id, is_active=True).first()
        if not party:
            raise Exception("Supplier tidak valid atau tidak aktif.")
        return "SUPPLIER", None, party.id, None

    if expected_party_type == "MANDOR":
        if not mandor_id:
            raise Exception("Panjar mandor wajib memilih mandor/PIC lapangan.")
        party = Mandor.query.filter_by(id=mandor_id, branch_id=branch_id, is_active=True).first()
        if not party:
            raise Exception("Mandor tidak valid atau tidak aktif.")
        return "MANDOR", None, None, party.id

    raise Exception("Party type advance belum dikenali.")


def validate_cash_bank(branch_id, payment_method, bank_account_id=None):
    method = _normalize(payment_method)
    if method == "CASH":
        return "CASH", None
    if method == "TRANSFER":
        if not bank_account_id:
            raise Exception("Transaksi transfer wajib memilih rekening bank.")
        bank = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=branch_id,
            is_active=True,
        ).first()
        if not bank:
            raise Exception("Rekening bank tidak valid atau tidak aktif.")
        return "BANK", bank.id
    raise Exception("Metode advance harus CASH atau TRANSFER.")


def create_advance_transaction(
    branch_id,
    advance_date,
    advance_type,
    payment_method,
    amount,
    created_by,
    client_id=None,
    supplier_id=None,
    mandor_id=None,
    bank_account_id=None,
    reference_number=None,
    notes=None,
    commit=False,
):
    if not is_advance_schema_ready():
        raise Exception("Tabel advance belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")

    advance_type = _normalize(advance_type)
    rule = ADVANCE_TYPES.get(advance_type)
    if not rule:
        raise Exception("Tipe uang muka tidak valid.")

    amount = float(amount or 0)
    if amount <= 0:
        raise Exception("Nominal DP/uang muka harus lebih dari 0.")

    if advance_date > date.today():
        raise Exception("Tanggal DP/uang muka tidak boleh lebih dari hari ini.")

    party_type, client_id, supplier_id, mandor_id = validate_party(
        branch_id=branch_id,
        advance_type=advance_type,
        client_id=client_id,
        supplier_id=supplier_id,
        mandor_id=mandor_id,
    )
    account_type, bank_account_id = validate_cash_bank(branch_id, payment_method, bank_account_id)

    acc_advance = get_account_by_code("1008")
    acc_cash_bank = get_account_by_code(resolve_cash_account_code(account_type))

    missing = []
    if not acc_advance:
        missing.append("1008 Uang Muka / DP")
    if not acc_cash_bank:
        missing.append(resolve_cash_account_code(account_type))
    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    advance = AdvanceTransaction(
        branch_id=branch_id,
        advance_number=generate_advance_number(advance_date),
        advance_date=advance_date,
        advance_type=advance_type,
        party_type=party_type,
        client_id=client_id,
        supplier_id=supplier_id,
        mandor_id=mandor_id,
        account_type=account_type,
        bank_account_id=bank_account_id,
        payment_method=_normalize(payment_method),
        amount=amount,
        settled_amount=0,
        remaining_amount=amount,
        status="OPEN",
        reference_number=(reference_number or None),
        notes=(notes or None),
        created_by=created_by,
    )
    db.session.add(advance)
    db.session.flush()

    cash_direction = rule["cash_direction"]
    source_label = "Kas" if account_type == "CASH" else "Bank"
    transaction = CashBankTransaction(
        branch_id=branch_id,
        transaction_date=advance_date,
        account_type=account_type,
        bank_account_id=bank_account_id,
        transaction_type=cash_direction,
        amount=amount,
        description=f"{rule['label']} {advance.advance_number} via {source_label} sebesar {_money(amount)}",
        reference_type=ADVANCE_REFERENCE_TYPE,
        reference_id=advance.id,
        created_by=created_by,
    )
    db.session.add(transaction)
    db.session.flush()

    journal = Journal(
        journal_number=generate_journal_number(advance_date),
        journal_date=advance_date,
        reference_type=ADVANCE_REFERENCE_TYPE,
        reference_id=advance.id,
        description=f"Jurnal {rule['label']} - {advance.advance_number}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    if rule["journal_direction"] == "CREDIT_ADVANCE":
        # Client DP received: Dr Kas/Bank, Cr 1008.
        debit_account, credit_account = acc_cash_bank, acc_advance
    else:
        # Supplier advance / mandor panjar: Dr 1008, Cr Kas/Bank.
        debit_account, credit_account = acc_advance, acc_cash_bank

    db.session.add(JournalDetail(journal_id=journal.id, account_id=debit_account.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=credit_account.id, debit=0, credit=amount))

    advance.cash_bank_transaction_id = transaction.id
    advance.journal_id = journal.id

    record_audit_log(
        module="FINANCE",
        event_type="ADVANCE_CREATED",
        action="CREATE",
        table_name="advance_transactions",
        record_id=advance.id,
        description=f"Advance dibuat: {advance.advance_number} ({rule['label']}).",
        metadata={
            "advance_type": advance.advance_type,
            "party_type": party_type,
            "amount": amount,
            "cash_bank_transaction_id": transaction.id,
            "journal_id": journal.id,
        },
        user_id=created_by,
        branch_id=branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, f"{rule['label']} berhasil dibuat secara optional dan traceable.", advance


def resolve_settlement_reference(branch_id, settlement_type, reference_id):
    settlement_type = _normalize(settlement_type)
    rule = SETTLEMENT_TYPES.get(settlement_type)
    if not rule:
        raise Exception("Tipe settlement advance tidak valid.")

    if settlement_type == "CLIENT_INVOICE":
        if not reference_id:
            raise Exception("Settlement DP client wajib memilih invoice.")
        invoice = Invoice.query.filter_by(id=reference_id, branch_id=branch_id).first()
        if not invoice:
            raise Exception("Invoice settlement tidak ditemukan.")
        if _normalize(invoice.status) in {"CANCELLED", "CANCELED"}:
            raise Exception("Invoice cancelled tidak boleh dipakai settlement DP.")
        if float(invoice.remaining_amount or 0) <= 0:
            raise Exception("Invoice ini sudah tidak punya sisa piutang.")
        return rule, invoice

    if settlement_type == "SUPPLIER_BILL":
        if not reference_id:
            raise Exception("Settlement uang muka supplier wajib memilih supplier bill.")
        bill = SupplierBill.query.filter_by(id=reference_id, branch_id=branch_id).first()
        if not bill:
            raise Exception("Supplier bill settlement tidak ditemukan.")
        if float(bill.remaining_amount or 0) <= 0:
            raise Exception("Supplier bill ini sudah tidak punya sisa hutang.")
        return rule, bill

    if settlement_type == "MANDOR_EXPENSE_PROOF":
        # PRODUCTION keeps mandor panjar optional and trackable.
        # Expense-account posting is deliberately deferred to PRODUCTION mapping.
        return rule, None

    raise Exception("Tipe settlement belum dikenali.")


def create_advance_settlement(
    advance,
    settlement_date,
    settlement_type,
    amount,
    created_by,
    reference_id=None,
    expense_account_code=None,
    notes=None,
    commit=False,
):
    if not is_advance_schema_ready():
        raise Exception("Tabel advance belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
    if not advance:
        raise Exception("Advance tidak ditemukan.")

    settlement_type = _normalize(settlement_type)
    rule, reference_obj = resolve_settlement_reference(advance.branch_id, settlement_type, reference_id)
    expense_account_code = _normalize(expense_account_code)
    expense_proof_rule = None

    if rule["advance_type"] != _normalize(advance.advance_type):
        raise Exception("Tipe settlement tidak sesuai dengan tipe advance.")

    if _normalize(advance.status) == "SETTLED" or float(advance.remaining_amount or 0) <= 0:
        raise Exception("Advance ini sudah selesai/settled.")

    amount = float(amount or 0)
    if amount <= 0:
        raise Exception("Nominal settlement harus lebih dari 0.")
    if amount > float(advance.remaining_amount or 0):
        raise Exception("Nominal settlement tidak boleh lebih dari sisa advance.")
    if settlement_type == "CLIENT_INVOICE" and amount > float(getattr(reference_obj, "remaining_amount", 0) or 0):
        raise Exception("Nominal settlement tidak boleh lebih dari sisa piutang invoice.")
    if settlement_type == "SUPPLIER_BILL" and amount > float(getattr(reference_obj, "remaining_amount", 0) or 0):
        raise Exception("Nominal settlement tidak boleh lebih dari sisa hutang supplier bill.")
    if settlement_date < advance.advance_date:
        raise Exception("Tanggal settlement tidak boleh lebih awal dari tanggal advance.")
    if settlement_date > date.today():
        raise Exception("Tanggal settlement tidak boleh lebih dari hari ini.")

    acc_advance = get_account_by_code("1008")
    if not acc_advance:
        raise Exception("Akun 1008 Uang Muka / DP belum tersedia.")
    if settlement_type == "MANDOR_EXPENSE_PROOF":
        expense_proof_rule = MANDOR_EXPENSE_PROOF_ACCOUNT_CHOICES.get(expense_account_code)
        if not expense_proof_rule:
            raise Exception("Pilih kategori biaya pertanggungjawaban panjar mandor terlebih dahulu.")

    settlement = AdvanceSettlement(
        branch_id=advance.branch_id,
        settlement_number=generate_settlement_number(settlement_date),
        advance_id=advance.id,
        settlement_date=settlement_date,
        settlement_type=settlement_type,
        reference_type=rule["reference_type"],
        reference_id=reference_id,
        amount=amount,
        notes=(notes or None),
        created_by=created_by,
    )
    db.session.add(settlement)
    db.session.flush()

    journal = None

    if settlement_type == "CLIENT_INVOICE":
        acc_piutang = get_account_by_code("1004")
        if not acc_piutang:
            raise Exception("Akun 1004 Piutang Usaha belum tersedia.")
        journal = Journal(
            journal_number=generate_journal_number(settlement_date),
            journal_date=settlement_date,
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            description=f"Settlement DP client {advance.advance_number} ke invoice {getattr(reference_obj, 'invoice_number', reference_id)}",
            created_by=created_by,
        )
        db.session.add(journal)
        db.session.flush()
        # Invoice journal records full receivable; settlement reduces receivable.
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_advance.id, debit=amount, credit=0))
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_piutang.id, debit=0, credit=amount))

    elif settlement_type == "SUPPLIER_BILL":
        acc_ap = get_account_by_code("2002")
        if not acc_ap:
            raise Exception("Akun 2002 Hutang Supplier belum tersedia.")
        journal = Journal(
            journal_number=generate_journal_number(settlement_date),
            journal_date=settlement_date,
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            description=f"Settlement uang muka supplier {advance.advance_number} ke bill {getattr(reference_obj, 'bill_number', reference_id)}",
            created_by=created_by,
        )
        db.session.add(journal)
        db.session.flush()
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_ap.id, debit=amount, credit=0))
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_advance.id, debit=0, credit=amount))

    elif settlement_type == "MANDOR_EXPENSE_PROOF":
        acc_expense = get_account_by_code(expense_account_code)
        if not acc_expense:
            raise Exception(f"Akun biaya {expense_account_code} belum tersedia atau tidak aktif.")
        journal = Journal(
            journal_number=generate_journal_number(settlement_date),
            journal_date=settlement_date,
            reference_type=ADVANCE_SETTLEMENT_REFERENCE_TYPE,
            reference_id=settlement.id,
            description=(
                f"Settlement panjar mandor {advance.advance_number} "
                f"ke {expense_proof_rule['account_label']}"
            ),
            created_by=created_by,
        )
        db.session.add(journal)
        db.session.flush()
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_expense.id, debit=amount, credit=0))
        db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_advance.id, debit=0, credit=amount))
        note_prefix = f"[{expense_proof_rule['account_label']}]"
        settlement.notes = f"{note_prefix} {notes}".strip() if notes else note_prefix

    if journal:
        settlement.journal_id = journal.id

    # Update operational outstanding without creating a duplicate cash/bank entry.
    # The cash movement happened at advance creation; settlement only applies that advance.
    if settlement_type == "CLIENT_INVOICE" and reference_obj:
        new_paid = float(reference_obj.paid_amount or 0) + amount
        new_remaining_invoice = float(reference_obj.total_amount or 0) - new_paid
        if new_remaining_invoice <= 0:
            new_remaining_invoice = 0
            reference_obj.status = "PAID"
        elif new_paid > 0:
            reference_obj.status = "PARTIAL"
        reference_obj.paid_amount = new_paid
        reference_obj.remaining_amount = new_remaining_invoice

    if settlement_type == "SUPPLIER_BILL" and reference_obj:
        new_paid = float(reference_obj.paid_amount or 0) + amount
        new_remaining_bill = float(reference_obj.total_amount or 0) - new_paid
        if new_remaining_bill <= 0:
            new_remaining_bill = 0
            reference_obj.status = "PAID"
        elif new_paid > 0:
            reference_obj.status = "PARTIAL"
        reference_obj.paid_amount = new_paid
        reference_obj.remaining_amount = new_remaining_bill

    new_settled = float(advance.settled_amount or 0) + amount
    new_remaining = float(advance.amount or 0) - new_settled
    if new_remaining <= 0:
        new_remaining = 0
        advance.status = "SETTLED"
    elif new_settled > 0:
        advance.status = "PARTIAL"
    advance.settled_amount = new_settled
    advance.remaining_amount = new_remaining

    field_transaction_link = find_field_transaction_linked_source(
        ADVANCE_REFERENCE_TYPE,
        advance.id,
        branch_id=advance.branch_id,
    )
    parent_field_transaction = getattr(field_transaction_link, "field_transaction", None) if field_transaction_link else None
    if parent_field_transaction and _normalize(advance.advance_type) == MANDOR_OPERATIONAL_ADVANCE:
        _, _, settlement_trace = create_system_linked_field_transaction(
            parent_field_transaction=parent_field_transaction,
            transaction_date=settlement_date,
            business_event_type="MANDOR_ADVANCE_SETTLEMENT",
            amount=amount,
            created_by=created_by,
            payment_status="PAID" if new_remaining <= 0 else "PARTIAL",
            review_status="RECORDED",
            evidence_status=getattr(parent_field_transaction, "evidence_status", None) or "PENDING",
            notes=(notes or None) or f"Jejak otomatis settlement advance {settlement.settlement_number}.",
            source_context={
                "generated_mode": "SYSTEM_LINKED_ADVANCE_SETTLEMENT",
                "source_field_transaction_id": parent_field_transaction.id,
                "advance_id": advance.id,
                "advance_number": advance.advance_number,
                "advance_settlement_id": settlement.id,
                "advance_settlement_number": settlement.settlement_number,
                "settlement_type": settlement_type,
            },
            metadata={
                "advance_id": advance.id,
                "advance_number": advance.advance_number,
                "advance_settlement_id": settlement.id,
                "advance_settlement_number": settlement.settlement_number,
                "settlement_type": settlement_type,
                "journal_id": journal.id if journal else None,
            },
            mark_posted=bool(journal),
            posting_note="Jejak transaksi lapangan turunan diposting otomatis dari settlement advance." if journal else None,
            additional_links=[
                {
                    "link_role": "ADVANCE_TRANSACTION",
                    "reference_type": ADVANCE_REFERENCE_TYPE,
                    "reference_id": advance.id,
                    "notes": f"Sumber advance {advance.advance_number}.",
                },
                {
                    "link_role": "ADVANCE_SETTLEMENT",
                    "reference_type": ADVANCE_SETTLEMENT_REFERENCE_TYPE,
                    "reference_id": settlement.id,
                    "notes": f"Settlement {settlement.settlement_number}.",
                },
                {
                    "link_role": "JOURNAL",
                    "reference_type": "JOURNAL",
                    "reference_id": journal.id if journal else None,
                },
            ],
            needs_follow_up=not bool(journal),
            commit=False,
        )
    record_audit_log(
        module="FINANCE",
        event_type="ADVANCE_SETTLED",
        action="CREATE",
        table_name="advance_settlements",
        record_id=settlement.id,
        description=f"Settlement advance dibuat: {settlement.settlement_number}.",
        metadata={
            "advance_id": advance.id,
            "advance_number": advance.advance_number,
            "settlement_type": settlement_type,
            "amount": amount,
            "journal_id": journal.id if journal else None,
            "expense_account_code": expense_account_code if settlement_type == "MANDOR_EXPENSE_PROOF" else None,
        },
        user_id=created_by,
        branch_id=advance.branch_id,
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, "Settlement advance berhasil dibuat.", settlement


def get_settlement_reference_options(branch_id, advance):
    if not advance:
        return {"invoices": [], "supplier_bills": []}
    if _normalize(advance.advance_type) == CLIENT_DP_RECEIVED:
        query = Invoice.query.filter(
            Invoice.branch_id == branch_id,
            Invoice.status.notin_(["CANCELLED", "CANCELED"]),
        )
        if advance.client_id:
            query = query.filter(Invoice.client_id == advance.client_id)
        return {"invoices": query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).limit(80).all(), "supplier_bills": []}
    if _normalize(advance.advance_type) == SUPPLIER_ADVANCE_PAID:
        query = SupplierBill.query.filter(SupplierBill.branch_id == branch_id)
        if advance.supplier_id:
            query = query.filter(SupplierBill.supplier_id == advance.supplier_id)
        return {"invoices": [], "supplier_bills": query.order_by(SupplierBill.bill_date.desc(), SupplierBill.id.desc()).limit(80).all()}
    return {"invoices": [], "supplier_bills": []}
