import logging
from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail
from app.models.finance import InvoiceItem, Invoice, Payment, SupplierBill
from datetime import date
from app.services.audit_log_service import record_audit_log

logger = logging.getLogger(__name__)


def generate_journal_number(journal_date):
    prefix = f"JRN-{journal_date.strftime('%Y%m%d')}"
    counter = Journal.query.filter(
        Journal.journal_number.like(f"{prefix}-%")
    ).count() + 1

    while True:
        journal_number = f"{prefix}-{counter:03d}"
        existing = Journal.query.filter_by(journal_number=journal_number).first()

        if not existing:
            return journal_number

        counter += 1


def commit_accounting_transaction():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def rollback_accounting_transaction():
    db.session.rollback()


def get_active_account_by_code(account_code):
    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


CATERING_REVENUE_PROJECT_CODE = "4001"
CATERING_REVENUE_DAILY_CODE = "4002"
SUPPORTED_INVOICE_JOURNAL_SOURCES = {"PERIOD_INVOICE", "DAILY_ORDER", "MANUAL_BILLING_RECAP"}
CATERING_ITEM_TYPES = {"CATERING", "REVISION_INCREASE"}
WARUNG_ITEM_TYPES = {"WARUNG_DEBT", "WARUNG"}
# Ongkir punya akun sendiri supaya bisa dibandingkan dengan 5003 Beban Transport / BBM.
DELIVERY_FEE_ITEM_TYPES = {"ONGKIR"}
DELIVERY_FEE_REVENUE_CODE = "4005"


def _normalize_code(value):
    return str(value or "").strip().upper()


def resolve_invoice_catering_revenue_account(invoice):
    """
    PRODUCTION: resolve akun pendapatan catering tanpa mengubah schema.

    Rule dikunci:
    - PERIOD_INVOICE / invoice berperiode / invoice rekap bulanan -> 4001 Pendapatan Catering Proyek.
    - DAILY_ORDER / invoice order harian non-period -> 4002 Pendapatan Catering Harian.
    - Unknown source tidak dipaksa posting ke 4001 agar laporan pendapatan tidak bias.
    """
    if not invoice:
        return {
            "account_code": None,
            "classification": "UNKNOWN",
            "reason": "Invoice tidak tersedia.",
            "is_supported": False,
        }

    source_type = _normalize_code(getattr(invoice, "source_type", None))
    has_period = bool(getattr(invoice, "period_start", None) and getattr(invoice, "period_end", None))

    if source_type in {"PERIOD_INVOICE", "MANUAL_BILLING_RECAP"} or has_period:
        return {
            "account_code": CATERING_REVENUE_PROJECT_CODE,
            "classification": "PROJECT_PERIOD",
            "reason": "Invoice periode/rekap bulanan diklasifikasikan sebagai pendapatan catering proyek.",
            "is_supported": True,
        }

    if source_type == "DAILY_ORDER":
        return {
            "account_code": CATERING_REVENUE_DAILY_CODE,
            "classification": "DAILY_NON_PERIOD",
            "reason": "Invoice dari order harian non-period diklasifikasikan sebagai pendapatan catering harian.",
            "is_supported": True,
        }

    item_sources = {
        _normalize_code(getattr(item, "source_type", None))
        for item in getattr(invoice, "items", []) or []
        if _normalize_code(getattr(item, "item_type", None)) in CATERING_ITEM_TYPES
    }

    if item_sources and item_sources.issubset({"DAILY_ORDER", "ORDER_DETAIL", "ORDER_REVISION"}) and not has_period:
        return {
            "account_code": CATERING_REVENUE_DAILY_CODE,
            "classification": "DAILY_ITEM_SOURCE",
            "reason": "Item invoice berasal dari order harian dan invoice tidak berperiode.",
            "is_supported": True,
        }

    return {
        "account_code": None,
        "classification": "UNKNOWN",
        "reason": f"Source invoice '{source_type or '-'}' belum cukup aman untuk mapping 4001/4002.",
        "is_supported": False,
    }


def build_invoice_journal_amounts(invoice):
    catering_project_total = 0
    catering_daily_total = 0
    unresolved_catering_total = 0
    warung_total = 0
    warung_transfer_total = 0
    delivery_fee_total = 0
    other_total = 0

    items = InvoiceItem.query.filter_by(
        invoice_id=invoice.id
    ).all()

    revenue_rule = resolve_invoice_catering_revenue_account(invoice)
    catering_revenue_code = revenue_rule.get("account_code")

    is_future_accrual_invoice = (
        "ACCOUNTING9D_CUTOVER_INVOICE_ID" in globals()
        and int(getattr(invoice, "id", 0) or 0) > ACCOUNTING9D_CUTOVER_INVOICE_ID
    )

    for item in items:
        item_type = _normalize_code(getattr(item, "item_type", None))
        subtotal = float(item.subtotal or 0)

        if item_type in CATERING_ITEM_TYPES:
            if catering_revenue_code == CATERING_REVENUE_DAILY_CODE:
                catering_daily_total += subtotal
            elif catering_revenue_code == CATERING_REVENUE_PROJECT_CODE:
                catering_project_total += subtotal
            else:
                # Unknown catering source is left unresolved and blocked before posting.
                unresolved_catering_total += subtotal
        elif item_type in WARUNG_ITEM_TYPES:
            if is_future_accrual_invoice:
                warung_transfer_total += subtotal
            else:
                warung_total += subtotal
        elif item_type in DELIVERY_FEE_ITEM_TYPES:
            delivery_fee_total += subtotal
        else:
            other_total += subtotal

    catering_total = catering_project_total + catering_daily_total

    return {
        "catering_project_total": catering_project_total,
        "catering_daily_total": catering_daily_total,
        "catering_total": catering_total,
        "unresolved_catering_total": unresolved_catering_total,
        "warung_total": warung_total,
        "warung_transfer_total": warung_transfer_total,
        "delivery_fee_total": delivery_fee_total,
        "other_total": other_total,
        "total_credit": (
            catering_total + unresolved_catering_total + warung_total + warung_transfer_total
            + delivery_fee_total + other_total
        ),
        "total_debit": float(invoice.total_amount or 0),
        "revenue_rule": revenue_rule,
    }


def create_invoice_journal_for_invoice(invoice, created_by, commit=False):
    if not invoice:
        return False, "Invoice tidak ditemukan.", None

    source_type = _normalize_code(getattr(invoice, "source_type", None))
    status = _normalize_code(getattr(invoice, "status", None))

    if status in {"CANCELLED", "CANCELED"}:
        return False, "Invoice cancelled tidak boleh dibuat jurnal.", None

    if source_type not in SUPPORTED_INVOICE_JOURNAL_SOURCES:
        return False, "Source invoice belum didukung untuk jurnal otomatis 4001/4002.", None

    existing_journal = Journal.query.filter_by(
        reference_type="INVOICE",
        reference_id=invoice.id
    ).first()

    if existing_journal:
        return False, "Jurnal invoice sudah ada.", existing_journal

    amounts = build_invoice_journal_amounts(invoice)
    revenue_rule = amounts.get("revenue_rule") or {}

    if amounts.get("unresolved_catering_total", 0) > 0 or (
        amounts.get("catering_total", 0) > 0 and not revenue_rule.get("is_supported")
    ):
        return False, revenue_rule.get("reason") or "Invoice catering belum bisa diklasifikasi ke 4001/4002.", None

    total_debit = amounts["total_debit"]
    total_credit = amounts["total_credit"]

    if total_debit <= 0:
        raise Exception(f"Total invoice {invoice.invoice_number} tidak valid untuk jurnal.")

    if round(total_debit, 2) != round(total_credit, 2):
        raise Exception(f"Jurnal invoice {invoice.invoice_number} tidak seimbang.")

    acc_piutang = get_active_account_by_code("1004")
    acc_catering_project = get_active_account_by_code(CATERING_REVENUE_PROJECT_CODE)
    acc_catering_daily = get_active_account_by_code(CATERING_REVENUE_DAILY_CODE)
    acc_warung = get_active_account_by_code("4003")
    acc_piutang_karyawan = get_active_account_by_code("1005")
    acc_lain = get_active_account_by_code("4004")
    acc_delivery = get_active_account_by_code(DELIVERY_FEE_REVENUE_CODE)

    missing_accounts = []

    if not acc_piutang:
        missing_accounts.append("1004 Piutang Usaha")
    if amounts["catering_project_total"] > 0 and not acc_catering_project:
        missing_accounts.append("4001 Pendapatan Catering Proyek")
    if amounts["catering_daily_total"] > 0 and not acc_catering_daily:
        missing_accounts.append("4002 Pendapatan Catering Harian")
    if amounts["warung_total"] > 0 and not acc_warung:
        missing_accounts.append("4003 Pendapatan Warung")
    if amounts["other_total"] > 0 and not acc_lain:
        missing_accounts.append("4004 Pendapatan Lain-Lain")
    if float(amounts.get("warung_transfer_total", 0) or 0) > 0 and not acc_piutang_karyawan:
        missing_accounts.append("1005 Piutang Karyawan")
    if not acc_delivery and amounts.get("delivery_fee_total", 0) > 0:
        missing_accounts.append("4005 Pendapatan Ongkos Kirim")

    if missing_accounts:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing_accounts))

    journal = Journal(
        journal_number=generate_journal_number(invoice.invoice_date),
        journal_date=invoice.invoice_date,
        reference_type="INVOICE",
        reference_id=invoice.id,
        description=(
            f"Jurnal invoice {invoice.invoice_number} "
            f"({revenue_rule.get('classification') or source_type})"
        ),
        created_by=created_by
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_piutang.id,
        debit=total_debit,
        credit=0
    ))

    if amounts["catering_project_total"] > 0:
        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_catering_project.id,
            debit=0,
            credit=amounts["catering_project_total"]
        ))

    if amounts["catering_daily_total"] > 0:
        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_catering_daily.id,
            debit=0,
            credit=amounts["catering_daily_total"]
        ))

    if amounts["warung_total"] > 0:
        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_warung.id,
            debit=0,
            credit=amounts["warung_total"]
        ))

    if float(amounts.get("warung_transfer_total", 0) or 0) > 0:
        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_piutang_karyawan.id,
            debit=0,
            credit=amounts["warung_transfer_total"]
        ))

    if amounts.get("delivery_fee_total", 0) > 0:
        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_delivery.id,
            debit=0,
            credit=amounts["delivery_fee_total"]
        ))

    if amounts["other_total"] > 0:
        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_lain.id,
            debit=0,
            credit=amounts["other_total"]
        ))

    record_audit_log(
        module="ACCOUNTING",
        event_type="JOURNAL_CREATED",
        action="CREATE",
        table_name="journals",
        record_id=journal.id,
        description=f"Jurnal invoice dibuat: {journal.journal_number}.",
        metadata={
            "reference_type": journal.reference_type,
            "reference_id": journal.reference_id,
            "source_type": source_type,
            "revenue_split": {
                "classification": revenue_rule.get("classification"),
                "project_catering_4001": amounts["catering_project_total"],
                "daily_catering_4002": amounts["catering_daily_total"],
                "delivery_fee_4005": amounts.get("delivery_fee_total", 0),
            },
        },
        user_id=created_by,
        branch_id=getattr(invoice, "branch_id", None),
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, "Jurnal invoice berhasil dibuat.", journal

def create_payment_journal_for_payment(payment, created_by, commit=False):
    if not payment:
        return False, "Payment tidak ditemukan.", None

    existing_journal = Journal.query.filter_by(
        reference_type="PAYMENT",
        reference_id=payment.id
    ).first()

    if existing_journal:
        return False, "Jurnal payment sudah ada.", existing_journal

    invoice = Invoice.query.get(payment.invoice_id)

    if not invoice:
        raise Exception("Invoice pembayaran tidak ditemukan.")

    invoice_journal = Journal.query.filter_by(
        reference_type="INVOICE",
        reference_id=invoice.id
    ).first()

    if not invoice_journal:
        raise Exception(
            f"Invoice {invoice.invoice_number} belum punya jurnal invoice. "
            "Buat jurnal invoice dulu sebelum jurnal payment."
        )

    acc_kas = get_active_account_by_code("1001")
    acc_bank = get_active_account_by_code("1002")
    acc_piutang = get_active_account_by_code("1004")

    missing_accounts = []

    if not acc_kas:
        missing_accounts.append("1001 Kas")
    if not acc_bank:
        missing_accounts.append("1002 Bank 1")
    if not acc_piutang:
        missing_accounts.append("1004 Piutang Usaha")

    if missing_accounts:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing_accounts))

    method = str(payment.payment_method or "").upper()
    amount = float(payment.amount or 0)

    if amount <= 0:
        raise Exception(f"Nominal payment {payment.payment_number} tidak valid.")

    if method == "CASH":
        debit_account = acc_kas
    elif method == "TRANSFER":
        debit_account = acc_bank
    else:
        raise Exception(f"Metode pembayaran {method} belum dikenali.")

    journal = Journal(
        journal_number=generate_journal_number(payment.payment_date),
        journal_date=payment.payment_date,
        reference_type="PAYMENT",
        reference_id=payment.id,
        description=f"Jurnal pembayaran invoice {invoice.invoice_number} - {payment.payment_number}",
        created_by=created_by
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=debit_account.id,
        debit=amount,
        credit=0
    ))

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_piutang.id,
        debit=0,
        credit=amount
    ))

    record_audit_log(
        module="ACCOUNTING",
        event_type="JOURNAL_CREATED",
        action="CREATE",
        table_name="journals",
        record_id=journal.id,
        description=f"Jurnal payment dibuat: {journal.journal_number}.",
        metadata={"reference_type": journal.reference_type, "reference_id": journal.reference_id},
        user_id=created_by,
        branch_id=getattr(payment, "branch_id", None),
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, "Jurnal payment berhasil dibuat.", journal


def generate_period_invoice_journals_batch(*, created_by):
    invoices = Invoice.query.filter(
        Invoice.source_type.in_(["PERIOD_INVOICE", "DAILY_ORDER", "MANUAL_BILLING_RECAP"])
    ).order_by(
        Invoice.invoice_date.asc(),
        Invoice.id.asc()
    ).all()

    created_count = 0
    skipped_count = 0
    skipped_cancelled_count = 0

    try:
        for invoice in invoices:
            status = str(getattr(invoice, "status", "") or "").upper()

            if status == "CANCELLED":
                skipped_count += 1
                skipped_cancelled_count += 1
                continue

            success, message, journal = create_invoice_journal_for_invoice(
                invoice=invoice,
                created_by=created_by,
                commit=False
            )

            if success:
                created_count += 1
            else:
                skipped_count += 1

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "created_count": created_count,
        "skipped_count": skipped_count,
        "skipped_cancelled_count": skipped_cancelled_count,
    }


def generate_payment_journals_batch(*, created_by):
    payments = Payment.query.order_by(
        Payment.payment_date.asc(),
        Payment.id.asc()
    ).all()

    created_count = 0
    skipped_count = 0

    try:
        for payment in payments:
            success, message, journal = create_payment_journal_for_payment(
                payment=payment,
                created_by=created_by,
                commit=False
            )

            if success:
                created_count += 1
            else:
                skipped_count += 1

        db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "created_count": created_count,
        "skipped_count": skipped_count,
    }


def _accounting2e_float(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/accounting_service.py:502")
        return 0


def _accounting2e_procurement_amount(procurement):
    amount = _accounting2e_float(getattr(procurement, "total_amount", 0))

    if amount > 0:
        return amount

    total = 0

    for item in getattr(procurement, "items", []) or []:
        total += _accounting2e_float(getattr(item, "subtotal", 0))

    return total


def _accounting2e_purchase_credit_account(procurement):
    purchase_type = str(getattr(procurement, "purchase_type", "") or "").upper()

    if purchase_type == "CASH":
        return get_active_account_by_code("1001"), "Kas"

    if purchase_type == "CREDIT":
        return get_active_account_by_code("2002"), "Hutang Supplier"

    if purchase_type in ["TRANSFER", "BANK"]:
        return get_active_account_by_code("1002"), "Bank 1"

    return None, "UNKNOWN"


def build_procurement_journal_candidates():
    from app.models.logistics import Procurement

    procurements = Procurement.query.order_by(
        Procurement.procurement_date.asc(),
        Procurement.id.asc()
    ).all()

    candidates = []

    for procurement in procurements:
        existing = Journal.query.filter_by(
            reference_type="PROCUREMENT",
            reference_id=procurement.id
        ).first()

        amount = _accounting2e_procurement_amount(procurement)
        credit_account, credit_label = _accounting2e_purchase_credit_account(procurement)

        candidates.append({
            "procurement": procurement,
            "amount": amount,
            "purchase_type": str(procurement.purchase_type or "").upper(),
            "credit_account": credit_account,
            "credit_label": credit_label,
            "existing_journal": existing,
            "can_generate": (
                existing is None
                and amount > 0
                and credit_account is not None
            ),
        })

    return candidates


def generate_procurement_journals_batch(*, created_by_id, commit=True):
    acc_inventory = get_active_account_by_code("1006")

    missing_accounts = []

    if not acc_inventory:
        missing_accounts.append("1006 - Persediaan Bahan Baku")

    candidates = build_procurement_journal_candidates()

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    try:
        for candidate in candidates:
            procurement = candidate["procurement"]
            amount = candidate["amount"]
            credit_account = candidate["credit_account"]
            purchase_type = candidate["purchase_type"]

            if candidate["existing_journal"]:
                skipped.append({
                    "procurement": procurement,
                    "reason": "Sudah ada jurnal",
                })
                continue

            if amount <= 0:
                skipped.append({
                    "procurement": procurement,
                    "reason": "Nominal pembelian tidak valid",
                })
                continue

            if credit_account is None:
                skipped.append({
                    "procurement": procurement,
                    "reason": f"Tipe pembelian belum didukung: {purchase_type}",
                })
                continue

            journal = Journal(
                journal_number=generate_journal_number(procurement.procurement_date),
                journal_date=procurement.procurement_date,
                reference_type="PROCUREMENT",
                reference_id=procurement.id,
                description=f"Jurnal pembelian barang {procurement.procurement_number} - {purchase_type}",
                created_by=created_by_id
            )

            db.session.add(journal)
            db.session.flush()

            db.session.add(JournalDetail(
                journal_id=journal.id,
                account_id=acc_inventory.id,
                debit=amount,
                credit=0
            ))

            db.session.add(JournalDetail(
                journal_id=journal.id,
                account_id=credit_account.id,
                debit=0,
                credit=amount
            ))

            created.append({
                "journal": journal,
                "procurement": procurement,
                "amount": amount,
                "debit_account": acc_inventory,
                "credit_account": credit_account,
            })

        if commit:
            db.session.commit()
    except Exception:
        db.session.rollback()
        raise

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


# ACCOUNTING9D_WARUNG_FUTURE_ACCRUAL_SERVICE
ACCOUNTING9D_CUTOVER_CANTEEN_SALE_ID = 2
ACCOUNTING9D_CUTOVER_WORKER_DEBT_ID = 2
ACCOUNTING9D_CUTOVER_DEBT_PAYMENT_ID = 4
ACCOUNTING9D_CUTOVER_INVOICE_ID = 2


def _accounting9d_float(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/accounting_service.py:676")
        return 0


def _accounting9d_existing_journal(reference_types, reference_id):
    return Journal.query.filter(
        Journal.reference_type.in_(reference_types),
        Journal.reference_id == reference_id
    ).first()


def create_warung_cash_sale_journal(sale, created_by, commit=False):
    """
    Future only:
    CASH warung -> Dr 1001 Kas / Cr 4003 Pendapatan Warung
    Data existing <= ACCOUNTING9D_CUTOVER_CANTEEN_SALE_ID dilindungi.
    """
    if not sale:
        return False, "Transaksi warung tidak ditemukan.", None

    sale_id = int(getattr(sale, "id", 0) or 0)

    if sale_id <= ACCOUNTING9D_CUTOVER_CANTEEN_SALE_ID:
        return False, "Transaksi warung lama dilindungi cutover.", None

    sale_type = str(getattr(sale, "sale_type", "") or "").upper()

    if sale_type != "CASH":
        return False, "Transaksi bukan cash sale warung.", None

    existing = _accounting9d_existing_journal(
        ["WARUNG_CASH_SALE"],
        sale_id
    )

    if existing:
        return False, "Jurnal cash sale warung sudah ada.", existing

    amount = _accounting9d_float(getattr(sale, "total_amount", 0))

    if amount <= 0:
        raise Exception("Nominal cash sale warung tidak valid.")

    acc_cash = get_active_account_by_code("1001")
    acc_warung = get_active_account_by_code("4003")

    missing = []

    if not acc_cash:
        missing.append("1001 Kas")

    if not acc_warung:
        missing.append("4003 Pendapatan Warung")

    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    journal = Journal(
        journal_number=generate_journal_number(sale.sale_date),
        journal_date=sale.sale_date,
        reference_type="WARUNG_CASH_SALE",
        reference_id=sale.id,
        description=f"Jurnal penjualan cash warung - Sale #{sale.id}",
        created_by=created_by
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_cash.id,
        debit=amount,
        credit=0
    ))

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_warung.id,
        debit=0,
        credit=amount
    ))

    if commit:
        db.session.commit()

    return True, "Jurnal cash sale warung berhasil dibuat.", journal


def create_warung_debt_accrual_journal(worker_debt, created_by, commit=False):
    """
    Future only:
    Hutang warung pekerja -> Dr 1005 Piutang Karyawan / Cr 4003 Pendapatan Warung
    Data existing <= ACCOUNTING9D_CUTOVER_WORKER_DEBT_ID dilindungi.
    """
    if not worker_debt:
        return False, "Hutang warung tidak ditemukan.", None

    worker_debt_id = int(getattr(worker_debt, "id", 0) or 0)

    if worker_debt_id <= ACCOUNTING9D_CUTOVER_WORKER_DEBT_ID:
        return False, "Hutang warung lama dilindungi cutover.", None

    existing = _accounting9d_existing_journal(
        ["WARUNG_DEBT_ACCRUAL"],
        worker_debt_id
    )

    if existing:
        return False, "Jurnal accrual hutang warung sudah ada.", existing

    amount = _accounting9d_float(getattr(worker_debt, "debt_amount", 0))

    if amount <= 0:
        raise Exception("Nominal hutang warung tidak valid.")

    acc_piutang_karyawan = get_active_account_by_code("1005")
    acc_warung = get_active_account_by_code("4003")

    missing = []

    if not acc_piutang_karyawan:
        missing.append("1005 Piutang Karyawan")

    if not acc_warung:
        missing.append("4003 Pendapatan Warung")

    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    sale = getattr(worker_debt, "sale", None)
    journal_date = getattr(sale, "sale_date", None)

    if not journal_date:
        from datetime import date
        journal_date = date.today()

    journal = Journal(
        journal_number=generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type="WARUNG_DEBT_ACCRUAL",
        reference_id=worker_debt.id,
        description=f"Jurnal accrual hutang warung pekerja - Worker Debt #{worker_debt.id}",
        created_by=created_by
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_piutang_karyawan.id,
        debit=amount,
        credit=0
    ))

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_warung.id,
        debit=0,
        credit=amount
    ))

    if commit:
        db.session.commit()

    return True, "Jurnal accrual hutang warung berhasil dibuat.", journal


def _warung_cash_bank_account_for_method(payment_method):
    payment_method = str(payment_method or "CASH").upper()
    # CASH -> Kas, QRIS/TRANSFER -> Bank 1. BankAccount operasional tetap dicatat di ledger,
    # sedangkan COA memakai akun bank utama yang sudah ada di chart of accounts.
    return "1001" if payment_method == "CASH" else "1002"


def create_warung_debt_payment_journal(debt_payment, created_by, commit=False):
    """
    Future only:
    Pembayaran hutang warung -> Dr Kas/Bank / Cr 1005 Piutang Karyawan
    Data existing <= ACCOUNTING9D_CUTOVER_DEBT_PAYMENT_ID dilindungi.
    """
    if not debt_payment:
        return False, "Pembayaran hutang warung tidak ditemukan.", None

    debt_payment_id = int(getattr(debt_payment, "id", 0) or 0)

    if debt_payment_id <= ACCOUNTING9D_CUTOVER_DEBT_PAYMENT_ID:
        return False, "Payment warung lama dilindungi cutover.", None

    existing = _accounting9d_existing_journal(
        [
            "WARUNG_DEBT_PAYMENT",
            "WARUNG_PAYMENT_CORRECTION",
            "DEBT_PAYMENT",
            "WORKER_DEBT_PAYMENT",
            "WARUNG_PAYMENT",
        ],
        debt_payment_id
    )

    if existing:
        return False, "Jurnal payment warung sudah ada.", existing

    amount = _accounting9d_float(getattr(debt_payment, "amount", 0))

    if amount <= 0:
        raise Exception("Nominal pembayaran hutang warung tidak valid.")

    payment_method = str(getattr(debt_payment, "payment_method", "CASH") or "CASH").upper()
    debit_code = _warung_cash_bank_account_for_method(payment_method)

    acc_cash_bank = get_active_account_by_code(debit_code)
    acc_piutang_karyawan = get_active_account_by_code("1005")

    missing = []

    if not acc_cash_bank:
        missing.append(f"{debit_code} Kas/Bank")

    if not acc_piutang_karyawan:
        missing.append("1005 Piutang Karyawan")

    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    journal = Journal(
        journal_number=generate_journal_number(debt_payment.payment_date),
        journal_date=debt_payment.payment_date,
        reference_type="WARUNG_DEBT_PAYMENT",
        reference_id=debt_payment.id,
        description=f"Jurnal pembayaran hutang warung pekerja via {payment_method} - Debt Payment #{debt_payment.id}",
        created_by=created_by
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_cash_bank.id,
        debit=amount,
        credit=0
    ))

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_piutang_karyawan.id,
        debit=0,
        credit=amount
    ))

    if commit:
        db.session.commit()

    return True, "Jurnal payment hutang warung berhasil dibuat.", journal


# ==================================================
# SDM2A_PAYROLL_ACCOUNTING_HELPERS
# Helper jurnal payroll internal.
# Mandor tidak termasuk payroll.
# ==================================================

def create_payroll_journal_for_payroll(payroll, created_by, commit=False):
    """
    Posting payroll:
    Dr 5004 Gaji Karyawan
    Cr 2003 Hutang Gaji
    """
    existing = Journal.query.filter_by(
        reference_type="PAYROLL",
        reference_id=payroll.id
    ).first()

    if existing:
        return False, "Jurnal payroll sudah ada.", existing

    if str(payroll.status or "").upper() not in ["FINAL", "POSTED"]:
        return False, "Payroll harus FINAL/POSTED sebelum dijurnal.", None

    total_salary = sum(float(detail.final_salary or 0) for detail in payroll.details)

    if total_salary <= 0:
        return False, "Total payroll masih 0.", None

    acc_salary = get_active_account_by_code("5004")
    acc_payable = get_active_account_by_code("2003")

    missing = []

    if not acc_salary:
        missing.append("5004 Gaji Karyawan")

    if not acc_payable:
        missing.append("2003 Hutang Gaji")

    if missing:
        return False, "Akun belum lengkap: " + ", ".join(missing), None

    from datetime import date

    journal_date = date(payroll.period_year, payroll.period_month, 1)

    journal = Journal(
        journal_number=generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type="PAYROLL",
        reference_id=payroll.id,
        description=f"Jurnal payroll periode {payroll.period_month:02d}-{payroll.period_year}",
        created_by=created_by,
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_salary.id,
        debit=total_salary,
        credit=0,
    ))

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_payable.id,
        debit=0,
        credit=total_salary,
    ))

    if str(payroll.status or "").upper() == "FINAL":
        payroll.status = "POSTED"

    if commit:
        db.session.commit()

    return True, "Jurnal payroll berhasil dibuat.", journal



# SDM5D_PAYROLL_PAYMENT_CASH_BANK_BALANCE_GUARD
def _sdm5d_format_money(value):
    return f"Rp {float(value or 0):,.0f}".replace(",", ".")


def _sdm5d_get_account_balance(account_code):
    account = get_active_account_by_code(account_code)

    details = JournalDetail.query.filter_by(account_id=account.id).all()
    debit = sum(float(detail.debit or 0) for detail in details)
    credit = sum(float(detail.credit or 0) for detail in details)

    # Akun asset dan beban normal debit.
    # Akun hutang, modal, dan pendapatan normal kredit.
    if account_code.startswith("1") or account_code.startswith("5"):
        balance = debit - credit
    else:
        balance = credit - debit

    return account, balance


def create_payroll_payment_journal_for_payroll(payroll, payment_method, created_by, commit=False):
    existing = Journal.query.filter_by(
        reference_type="PAYROLL_PAYMENT",
        reference_id=payroll.id
    ).first()

    if existing:
        return False, "Jurnal pembayaran payroll sudah ada.", existing

    if payroll.status != "POSTED":
        return False, "Payroll harus berstatus POSTED sebelum dibayar.", None

    total = sum(float(detail.final_salary or 0) for detail in payroll.details)

    if total <= 0:
        return False, "Total payroll tidak valid untuk dibayar.", None

    payment_method = (payment_method or "").upper().strip()

    if payment_method == "CASH":
        payment_account_code = "1001"
        payment_label = "CASH"
    elif payment_method == "TRANSFER":
        payment_account_code = "1002"
        payment_label = "TRANSFER"
    else:
        return False, "Metode pembayaran payroll tidak valid.", None

    payable_account = get_active_account_by_code("2003")
    payment_account, available_balance = _sdm5d_get_account_balance(payment_account_code)

    if float(available_balance or 0) < float(total or 0):
        return (
            False,
            (
                f"Saldo {payment_account.account_name} tidak cukup. "
                f"Saldo tersedia {_sdm5d_format_money(available_balance)}, "
                f"nominal pembayaran {_sdm5d_format_money(total)}."
            ),
            None
        )

    journal = Journal(
        journal_number=generate_journal_number(date.today()),
        journal_date=date.today(),
        reference_type="PAYROLL_PAYMENT",
        reference_id=payroll.id,
        description=f"Pembayaran payroll periode {payroll.period_month:02d}-{payroll.period_year} via {payment_label}",
        created_by=created_by,
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=payable_account.id,
        debit=total,
        credit=0,
    ))

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=payment_account.id,
        debit=0,
        credit=total,
    ))

    debit_total = sum(float(detail.debit or 0) for detail in journal.details)
    credit_total = sum(float(detail.credit or 0) for detail in journal.details)

    if round(debit_total, 2) != round(credit_total, 2):
        raise Exception("Jurnal pembayaran payroll tidak seimbang.")

    payroll.status = "PAID"

    if commit:
        db.session.commit()

    return True, "Pembayaran gaji berhasil dicatat otomatis.", journal



# === PRODUCTION_SUPPLIER_PAYMENT_JOURNAL_SERVICE ===
def create_supplier_payment_journal_for_payment(supplier_payment, created_by, commit=False):
    if not supplier_payment:
        return False, "Pembayaran supplier tidak ditemukan.", None

    existing_journal = Journal.query.filter_by(
        reference_type="SUPPLIER_PAYMENT",
        reference_id=supplier_payment.id
    ).first()

    if existing_journal:
        return False, "Jurnal pembayaran supplier sudah ada.", existing_journal

    bill = SupplierBill.query.get(supplier_payment.supplier_bill_id)

    if not bill:
        raise Exception("Supplier bill pembayaran tidak ditemukan.")

    procurement_journal = Journal.query.filter_by(
        reference_type="PROCUREMENT",
        reference_id=bill.procurement_id,
    ).first()

    if not procurement_journal:
        raise Exception(
            f"Pembelian sumber supplier bill {bill.bill_number} belum punya jurnal pembelian. "
            "Sinkronkan jurnal pembelian dulu sebelum pembayaran hutang supplier."
        )

    acc_hutang_supplier = get_active_account_by_code("2002")
    acc_kas = get_active_account_by_code("1001")
    acc_bank = get_active_account_by_code("1002")

    missing_accounts = []

    if not acc_hutang_supplier:
        missing_accounts.append("2002 Hutang Supplier")
    if not acc_kas:
        missing_accounts.append("1001 Kas")
    if not acc_bank:
        missing_accounts.append("1002 Bank 1")

    if missing_accounts:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing_accounts))

    method = str(supplier_payment.payment_method or "").upper()
    amount = float(supplier_payment.amount or 0)

    if amount <= 0:
        raise Exception(f"Nominal pembayaran supplier {supplier_payment.payment_number} tidak valid.")

    if method == "CASH":
        credit_account = acc_kas
    elif method == "TRANSFER":
        credit_account = acc_bank
    else:
        raise Exception(f"Metode pembayaran supplier {method} belum dikenali.")

    journal = Journal(
        journal_number=generate_journal_number(supplier_payment.payment_date),
        journal_date=supplier_payment.payment_date,
        reference_type="SUPPLIER_PAYMENT",
        reference_id=supplier_payment.id,
        description=f"Jurnal pembayaran hutang supplier {bill.bill_number} - {supplier_payment.payment_number}",
        created_by=created_by
    )

    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=acc_hutang_supplier.id,
        debit=amount,
        credit=0
    ))

    db.session.add(JournalDetail(
        journal_id=journal.id,
        account_id=credit_account.id,
        debit=0,
        credit=amount
    ))

    record_audit_log(
        module="ACCOUNTING",
        event_type="JOURNAL_CREATED",
        action="CREATE",
        table_name="journals",
        record_id=journal.id,
        description=f"Jurnal pembayaran supplier dibuat: {journal.journal_number}.",
        metadata={"reference_type": journal.reference_type, "reference_id": journal.reference_id},
        user_id=created_by,
        branch_id=getattr(supplier_payment, "branch_id", None),
        commit=False,
    )

    if commit:
        db.session.commit()

    return True, "Jurnal pembayaran supplier berhasil dibuat.", journal


# ==================================================
# PRODUCTION CANTEEN PAYMENT METHOD + EXTERNAL BUYER FOUNDATION
# ==================================================

def create_warung_direct_sale_journal(sale, created_by, commit=False):
    """
    Cash/QRIS/Transfer warung:
    Dr Kas/Bank
    Cr 4003 Pendapatan Warung
    """
    if not sale:
        return False, "Transaksi warung tidak ditemukan.", None

    sale_id = int(getattr(sale, "id", 0) or 0)
    if sale_id <= ACCOUNTING9D_CUTOVER_CANTEEN_SALE_ID:
        return False, "Transaksi warung lama dilindungi cutover.", None

    payment_method = str(getattr(sale, "payment_method", None) or getattr(sale, "sale_type", None) or "CASH").upper()
    if payment_method not in ["CASH", "QRIS", "TRANSFER"]:
        return False, "Transaksi warung bukan transaksi lunas.", None

    existing = _accounting9d_existing_journal(
        ["WARUNG_DIRECT_SALE", "WARUNG_CASH_SALE"],
        sale_id,
    )
    if existing:
        return False, "Jurnal penjualan warung sudah ada.", existing

    amount = _accounting9d_float(getattr(sale, "total_amount", 0))
    if amount <= 0:
        raise Exception("Nominal penjualan warung tidak valid.")

    debit_code = _warung_cash_bank_account_for_method(payment_method)
    acc_cash_bank = get_active_account_by_code(debit_code)
    acc_warung = get_active_account_by_code("4003")

    missing = []
    if not acc_cash_bank:
        missing.append(f"{debit_code} Kas/Bank")
    if not acc_warung:
        missing.append("4003 Pendapatan Warung")
    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    journal = Journal(
        journal_number=generate_journal_number(sale.sale_date),
        journal_date=sale.sale_date,
        reference_type="WARUNG_DIRECT_SALE",
        reference_id=sale.id,
        description=f"Jurnal penjualan warung {payment_method} - Sale #{sale.id}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_cash_bank.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_warung.id, debit=0, credit=amount))

    if commit:
        db.session.commit()

    return True, "Jurnal penjualan warung berhasil dibuat.", journal


def create_warung_external_debt_accrual_journal(external_receivable, created_by, commit=False):
    """
    Hutang/piutang warung eksternal:
    Dr 1004 Piutang Usaha (dipakai sebagai Piutang Warung Eksternal)
    Cr 4003 Pendapatan Warung
    """
    if not external_receivable:
        return False, "Piutang warung eksternal tidak ditemukan.", None

    existing = _accounting9d_existing_journal(
        ["WARUNG_EXTERNAL_DEBT_ACCRUAL"],
        external_receivable.id,
    )
    if existing:
        return False, "Jurnal accrual piutang warung eksternal sudah ada.", existing

    amount = _accounting9d_float(getattr(external_receivable, "receivable_amount", 0))
    if amount <= 0:
        raise Exception("Nominal piutang warung eksternal tidak valid.")

    acc_receivable = get_active_account_by_code("1004")
    acc_warung = get_active_account_by_code("4003")

    missing = []
    if not acc_receivable:
        missing.append("1004 Piutang Usaha / Piutang Warung Eksternal")
    if not acc_warung:
        missing.append("4003 Pendapatan Warung")
    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    sale = getattr(external_receivable, "sale", None)
    journal_date = getattr(sale, "sale_date", None) or date.today()

    journal = Journal(
        journal_number=generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type="WARUNG_EXTERNAL_DEBT_ACCRUAL",
        reference_id=external_receivable.id,
        description=f"Jurnal accrual piutang warung eksternal - Receivable #{external_receivable.id}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_receivable.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_warung.id, debit=0, credit=amount))

    if commit:
        db.session.commit()

    return True, "Jurnal accrual piutang warung eksternal berhasil dibuat.", journal


def create_warung_external_receivable_payment_journal(external_payment, created_by, commit=False):
    """
    Pembayaran piutang warung eksternal:
    Dr Kas/Bank
    Cr 1004 Piutang Usaha (Piutang Warung Eksternal)
    """
    if not external_payment:
        return False, "Pembayaran piutang warung eksternal tidak ditemukan.", None

    existing = _accounting9d_existing_journal(
        ["WARUNG_EXTERNAL_RECEIVABLE_PAYMENT"],
        external_payment.id,
    )
    if existing:
        return False, "Jurnal pembayaran piutang warung eksternal sudah ada.", existing

    amount = _accounting9d_float(getattr(external_payment, "amount", 0))
    if amount <= 0:
        raise Exception("Nominal pembayaran piutang warung eksternal tidak valid.")

    payment_method = str(getattr(external_payment, "payment_method", "CASH") or "CASH").upper()
    debit_code = _warung_cash_bank_account_for_method(payment_method)
    acc_cash_bank = get_active_account_by_code(debit_code)
    acc_receivable = get_active_account_by_code("1004")

    missing = []
    if not acc_cash_bank:
        missing.append(f"{debit_code} Kas/Bank")
    if not acc_receivable:
        missing.append("1004 Piutang Usaha / Piutang Warung Eksternal")
    if missing:
        raise Exception("Akun wajib belum lengkap: " + ", ".join(missing))

    journal = Journal(
        journal_number=generate_journal_number(external_payment.payment_date),
        journal_date=external_payment.payment_date,
        reference_type="WARUNG_EXTERNAL_RECEIVABLE_PAYMENT",
        reference_id=external_payment.id,
        description=f"Jurnal pembayaran piutang warung eksternal via {payment_method} - Payment #{external_payment.id}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()

    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_cash_bank.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=acc_receivable.id, debit=0, credit=amount))

    if commit:
        db.session.commit()

    return True, "Jurnal pembayaran piutang warung eksternal berhasil dibuat.", journal
