import logging
from datetime import datetime, date
import json

from app.utils.clock import today_wib

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from app.utils.decorators import module_required, role_required
from app.services.branch_module_service import WARUNG, WORKER_DEBT, module_enabled
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context, apply_date_range_to_query
from app.models.canteen import CanteenSale, WorkerDebt, CanteenExternalReceivable
from app.models.finance import BankAccount
from app.models.master import Item, Worker, Mandor
from app.services.canteen_service import (
    create_canteen_sale,
    get_or_create_custom_item,
    pay_worker_debt,
    pay_external_receivable,
    get_debt_paid_amount,
    get_debt_remaining_amount,
    get_external_receivable_paid_amount,
    get_external_receivable_remaining_amount,
    PAYMENT_METHODS,
    PAID_PAYMENT_METHODS,
    BUYER_TYPES,
)
from app.services.manual_billing_service import (
    MANUAL_BILLING_SOURCE_WORKER_DEBT,
    find_manual_billing_invoice_for_source,
)
from app.utils.terms import T

logger = logging.getLogger(__name__)

canteen_bp = Blueprint("canteen", __name__, url_prefix="/canteen")


QUICK_ITEM_PRICES = {
    "Kopi Sachet": 5000,
    "Mie Instan": 8000,
    "Snack": 3000,
    "Air Mineral": 4000,
    "Rokok": 25000,
}


def _active_bank_accounts():
    return BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc(),
    ).all()


def _parse_date(value, fallback=None):
    fallback = fallback or today_wib()
    try:
        return datetime.strptime(str(value or ""), "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/canteen_routes.py:56")
        return fallback


def get_quick_canteen_items():
    items = get_canteen_items()
    quick_items = []

    for item in items:
        quick_items.append({
            "id": item.id,
            "item_name": item.item_name,
            "unit": item.unit,
            "default_price": item.selling_price or QUICK_ITEM_PRICES.get(item.item_name, 0)
        })

    return quick_items


def _sale_payment_method(sale):
    return str(getattr(sale, "payment_method", None) or getattr(sale, "sale_type", None) or "CASH").upper()


def _sale_buyer_type(sale):
    return str(getattr(sale, "buyer_type", None) or ("REGISTERED_WORKER" if getattr(sale, "sale_type", None) == "DEBT" else "GENERAL_BUYER")).upper()


def _sale_buyer_label(sale):
    buyer_type = _sale_buyer_type(sale)
    if buyer_type == "REGISTERED_WORKER" and getattr(sale, "worker_debt", None) and sale.worker_debt.worker:
        return sale.worker_debt.worker.full_name
    if getattr(sale, "buyer_name", None):
        company = f" / {sale.buyer_company}" if getattr(sale, "buyer_company", None) else ""
        return f"{sale.buyer_name}{company}"
    if buyer_type == "GENERAL_BUYER":
        return "Pembeli umum"
    if buyer_type == "GUEST":
        return "Tamu/guest"
    if buyer_type == "EXTERNAL_COMPANY_WORKER":
        return f"{T.worker} perusahaan luar"
    return "-"


@canteen_bp.route("/")
@role_required("ADMIN")
@module_required(WARUNG)
def index():
    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    payment_filter = (request.args.get("payment_method") or "ALL").upper().strip()
    allowed_payment_methods = ["ALL", "CASH", "QRIS", "TRANSFER", "DEBT"]
    if payment_filter not in allowed_payment_methods:
        payment_filter = "ALL"

    sales_query = CanteenSale.query.filter_by(branch_id=current_user.branch_id)
    sales_query = apply_date_range_to_query(sales_query, CanteenSale.sale_date, date_filter)
    if payment_filter != "ALL":
        sales_query = sales_query.filter(CanteenSale.payment_method == payment_filter)

    sales = sales_query.order_by(
        CanteenSale.sale_date.desc(),
        CanteenSale.id.desc()
    ).all()

    debts = WorkerDebt.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        WorkerDebt.id.desc()
    ).all()

    external_receivables = CanteenExternalReceivable.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        CanteenExternalReceivable.status.asc(),
        CanteenExternalReceivable.id.desc(),
    ).all()

    total_cash_sales = sum(sale.total_amount for sale in sales if _sale_payment_method(sale) == "CASH")
    total_qris_sales = sum(sale.total_amount for sale in sales if _sale_payment_method(sale) == "QRIS")
    total_transfer_sales = sum(sale.total_amount for sale in sales if _sale_payment_method(sale) == "TRANSFER")
    total_debt_sales = sum(sale.total_amount for sale in sales if _sale_payment_method(sale) == "DEBT")
    total_unpaid_debt = sum(get_debt_remaining_amount(debt) for debt in debts)
    total_external_remaining = sum(get_external_receivable_remaining_amount(row) for row in external_receivables)

    return render_template(
        "canteen/index.html",
        sales=sales,
        debts=debts,
        external_receivables=external_receivables,
        total_cash_sales=total_cash_sales,
        total_qris_sales=total_qris_sales,
        total_transfer_sales=total_transfer_sales,
        total_debt_sales=total_debt_sales,
        total_unpaid_debt=total_unpaid_debt,
        total_external_remaining=total_external_remaining,
        get_debt_paid_amount=get_debt_paid_amount,
        get_debt_remaining_amount=get_debt_remaining_amount,
        get_external_receivable_paid_amount=get_external_receivable_paid_amount,
        get_external_receivable_remaining_amount=get_external_receivable_remaining_amount,
        sale_payment_method=_sale_payment_method,
        sale_buyer_type=_sale_buyer_type,
        sale_buyer_label=_sale_buyer_label,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("canteen.index"),
            reset_url=url_for("canteen.index"),
            title="Filter Transaksi Warung",
            description="Custom tanggal dan metode pembayaran warung.",
            status_name="payment_method",
            status_value=payment_filter,
            status_options=[
                {"value": "ALL", "label": "Semua Metode"},
                {"value": "CASH", "label": "Cash"},
                {"value": "QRIS", "label": "QRIS"},
                {"value": "TRANSFER", "label": "Transfer"},
                {"value": "DEBT", "label": "Hutang"},
            ],
        ),
    )


@canteen_bp.route("/quick", methods=["GET", "POST"])
@role_required("ADMIN")
@module_required(WARUNG)
def quick_sale():
    items = get_quick_canteen_items()
    workers = get_branch_workers() if module_enabled(WORKER_DEBT) else []
    bank_accounts = _active_bank_accounts()

    if request.method == "POST":
        payment_method = request.form.get("payment_method") or request.form.get("sale_type") or "CASH"
        buyer_type = request.form.get("buyer_type") or "GENERAL_BUYER"
        worker_id = request.form.get("worker_id") or None
        buyer_name = request.form.get("buyer_name")
        buyer_company = request.form.get("buyer_company")
        buyer_phone = request.form.get("buyer_phone")
        payment_reference = request.form.get("payment_reference")
        cash_bank_account_id = request.form.get("cash_bank_account_id") or None
        cart_json = request.form.get("cart_json") or "[]"

        if payment_method not in PAYMENT_METHODS:
            flash("Metode pembayaran warung tidak valid.", "warning")
            return redirect(url_for("canteen.quick_sale"))

        try:
            cart_items = json.loads(cart_json)
        except json.JSONDecodeError:
            flash("Data keranjang tidak valid.", "warning")
            return redirect(url_for("canteen.quick_sale"))

        if not cart_items:
            flash("Keranjang masih kosong.", "warning")
            return redirect(url_for("canteen.quick_sale"))

        item_rows = []

        for cart in cart_items:
            is_custom = cart.get("is_custom")
            item_id = cart.get("item_id")
            item_name = cart.get("item_name")
            qty = cart.get("qty")
            price = cart.get("price")

            if is_custom:
                custom_item = get_or_create_custom_item(item_name, price)

                if not custom_item:
                    continue

                item_id = custom_item.id

            item_rows.append({
                "item_id": item_id,
                "qty": qty,
                "price": price,
            })

        notes = request.form.get("notes") or "Transaksi cepat warung"

        success, message, sale = create_canteen_sale(
            branch_id=current_user.branch_id,
            sale_date=today_wib(),
            payment_method=payment_method,
            buyer_type=buyer_type,
            worker_id=worker_id,
            buyer_name=buyer_name,
            buyer_company=buyer_company,
            buyer_phone=buyer_phone,
            payment_reference=payment_reference,
            cash_bank_account_id=cash_bank_account_id,
            item_rows=item_rows,
            notes=notes,
            created_by=current_user.id
        )

        flash(message, "success" if success else "warning")

        if success:
            return redirect(url_for("canteen.index"))

        return redirect(url_for("canteen.quick_sale"))

    return render_template(
        "canteen/quick_sale.html",
        items=items,
        workers=workers,
        bank_accounts=bank_accounts,
        today=today_wib(),
        buyer_types=BUYER_TYPES,
        payment_methods=PAYMENT_METHODS,
    )


@canteen_bp.route("/sales/create", methods=["GET", "POST"])
@role_required("ADMIN")
@module_required(WARUNG)
def create_sale():
    items = get_canteen_items()
    workers = get_branch_workers() if module_enabled(WORKER_DEBT) else []
    bank_accounts = _active_bank_accounts()

    if request.method == "POST":
        sale_date = _parse_date(request.form.get("sale_date"), today_wib())
        payment_method = request.form.get("payment_method") or request.form.get("sale_type") or "CASH"
        buyer_type = request.form.get("buyer_type") or "GENERAL_BUYER"
        worker_id = request.form.get("worker_id") or None
        buyer_name = request.form.get("buyer_name")
        buyer_company = request.form.get("buyer_company")
        buyer_phone = request.form.get("buyer_phone")
        payment_reference = request.form.get("payment_reference")
        cash_bank_account_id = request.form.get("cash_bank_account_id") or None
        notes = request.form.get("notes")

        item_ids = request.form.getlist("item_id[]")
        qtys = request.form.getlist("qty[]")
        prices = request.form.getlist("price[]")

        item_rows = []

        for index, item_id in enumerate(item_ids):
            item_rows.append({
                "item_id": item_id,
                "qty": qtys[index] if index < len(qtys) else 0,
                "price": prices[index] if index < len(prices) else 0
            })

        success, message, sale = create_canteen_sale(
            branch_id=current_user.branch_id,
            sale_date=sale_date,
            payment_method=payment_method,
            buyer_type=buyer_type,
            worker_id=worker_id,
            buyer_name=buyer_name,
            buyer_company=buyer_company,
            buyer_phone=buyer_phone,
            payment_reference=payment_reference,
            cash_bank_account_id=cash_bank_account_id,
            item_rows=item_rows,
            notes=notes,
            created_by=current_user.id
        )

        flash(message, "success" if success else "warning")

        if success:
            return redirect(url_for("canteen.index"))

        return redirect(url_for("canteen.create_sale"))

    return render_template(
        "canteen/sale_form.html",
        items=items,
        workers=workers,
        bank_accounts=bank_accounts,
        today=today_wib(),
        buyer_types=BUYER_TYPES,
        payment_methods=PAYMENT_METHODS,
    )


@canteen_bp.route("/debts")
@role_required("ADMIN")
@module_required(WARUNG)
def debts():
    debts = WorkerDebt.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        WorkerDebt.status.asc(),
        WorkerDebt.id.desc()
    ).all() if module_enabled(WORKER_DEBT) else []

    external_receivables = CanteenExternalReceivable.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        CanteenExternalReceivable.status.asc(),
        CanteenExternalReceivable.id.desc(),
    ).all()

    billed_invoice_by_debt_id = {}
    for debt in debts:
        invoice = find_manual_billing_invoice_for_source(MANUAL_BILLING_SOURCE_WORKER_DEBT, debt.id)
        if invoice and invoice.branch_id == current_user.branch_id:
            billed_invoice_by_debt_id[debt.id] = invoice

    return render_template(
        "canteen/debts.html",
        debts=debts,
        external_receivables=external_receivables,
        billed_invoice_by_debt_id=billed_invoice_by_debt_id,
        get_debt_paid_amount=get_debt_paid_amount,
        get_debt_remaining_amount=get_debt_remaining_amount,
        get_external_receivable_paid_amount=get_external_receivable_paid_amount,
        get_external_receivable_remaining_amount=get_external_receivable_remaining_amount,
    )


@canteen_bp.route("/debts/<int:debt_id>/payment", methods=["GET", "POST"])
@role_required("ADMIN")
@module_required(WORKER_DEBT)
def debt_payment(debt_id):
    worker_debt = WorkerDebt.query.get_or_404(debt_id)

    if worker_debt.branch_id != current_user.branch_id:
        flash("Data hutang tidak sesuai cabang user.", "danger")
        return redirect(url_for("canteen.debts"))

    billed_invoice = find_manual_billing_invoice_for_source(MANUAL_BILLING_SOURCE_WORKER_DEBT, worker_debt.id)
    if billed_invoice and billed_invoice.branch_id == current_user.branch_id:
        flash(
            f"Hutang warung ini sudah masuk invoice formal {billed_invoice.invoice_number}. "
            "Lanjutkan penagihan dan penerimaan pembayaran dari invoice tersebut.",
            "warning",
        )
        return redirect(url_for("finance.invoice_detail", invoice_id=billed_invoice.id))

    bank_accounts = _active_bank_accounts()

    if request.method == "POST":
        payment_date = _parse_date(request.form.get("payment_date"), today_wib())
        amount = request.form.get("amount")
        payment_method = request.form.get("payment_method") or "CASH"
        cash_bank_account_id = request.form.get("cash_bank_account_id") or None
        payment_reference = request.form.get("payment_reference")
        notes = request.form.get("notes")

        success, message = pay_worker_debt(
            worker_debt=worker_debt,
            payment_date=payment_date,
            amount=amount,
            payment_method=payment_method,
            cash_bank_account_id=cash_bank_account_id,
            payment_reference=payment_reference,
            notes=notes,
            created_by=current_user.id
        )

        flash(message, "success" if success else "warning")
        return redirect(url_for("canteen.debts"))

    return render_template(
        "canteen/debt_payment.html",
        debt=worker_debt,
        today=today_wib(),
        bank_accounts=bank_accounts,
        paid_amount=get_debt_paid_amount(worker_debt),
        remaining_amount=get_debt_remaining_amount(worker_debt),
        payment_methods=PAID_PAYMENT_METHODS,
        is_external=False,
    )


@canteen_bp.route("/external-receivables/<int:receivable_id>/payment", methods=["GET", "POST"])
@role_required("ADMIN")
@module_required(WARUNG)
def external_receivable_payment(receivable_id):
    receivable = CanteenExternalReceivable.query.get_or_404(receivable_id)

    if receivable.branch_id != current_user.branch_id:
        flash("Data piutang eksternal tidak sesuai cabang user.", "danger")
        return redirect(url_for("canteen.debts"))

    bank_accounts = _active_bank_accounts()

    if request.method == "POST":
        payment_date = _parse_date(request.form.get("payment_date"), today_wib())
        amount = request.form.get("amount")
        payment_method = request.form.get("payment_method") or "CASH"
        cash_bank_account_id = request.form.get("cash_bank_account_id") or None
        payment_reference = request.form.get("payment_reference")
        notes = request.form.get("notes")

        success, message = pay_external_receivable(
            receivable=receivable,
            payment_date=payment_date,
            amount=amount,
            payment_method=payment_method,
            cash_bank_account_id=cash_bank_account_id,
            payment_reference=payment_reference,
            notes=notes,
            created_by=current_user.id,
        )

        flash(message, "success" if success else "warning")
        return redirect(url_for("canteen.debts"))

    return render_template(
        "canteen/debt_payment.html",
        debt=receivable,
        today=today_wib(),
        bank_accounts=bank_accounts,
        paid_amount=get_external_receivable_paid_amount(receivable),
        remaining_amount=get_external_receivable_remaining_amount(receivable),
        payment_methods=PAID_PAYMENT_METHODS,
        is_external=True,
    )


# === PATCH_FILTER_ACTIVE_WARUNG_HELPERS ===
def _canteen_is_active_record(record):
    """
    Cek aktif/nonaktif secara aman.
    Support:
    - is_active = True/False
    - status = ACTIVE / AKTIF
    """
    if hasattr(record, "is_active"):
        return bool(record.is_active)

    if hasattr(record, "status"):
        return str(record.status).upper() in ["ACTIVE", "AKTIF"]

    return True


def _canteen_belongs_to_user_branch(record):
    """
    Filter cabang aman.
    Worker biasanya lewat mandor.branch_id.
    Item bisa punya branch_id atau bisa global.
    """
    user_branch_id = current_user.branch_id

    if hasattr(record, "branch_id"):
        return record.branch_id == user_branch_id

    if hasattr(record, "mandor") and record.mandor:
        if hasattr(record.mandor, "branch_id"):
            return record.mandor.branch_id == user_branch_id

    if hasattr(record, "mandor_id") and record.mandor_id:
        mandor = Mandor.query.get(record.mandor_id)
        if mandor and hasattr(mandor, "branch_id"):
            return mandor.branch_id == user_branch_id

    return True


def _canteen_is_merchandise_item(item):
    """
    Pastikan hanya barang warung yang tampil.
    Support beberapa kemungkinan nama field kategori.
    """
    for field_name in ["category", "item_category", "item_type", "type"]:
        if hasattr(item, field_name):
            return str(getattr(item, field_name) or "").upper() == "MERCHANDISE"

    return True


def _canteen_sort_name(record):
    for field_name in ["item_name", "name", "worker_name", "full_name"]:
        if hasattr(record, field_name):
            return str(getattr(record, field_name) or "").lower()

    return ""


def get_canteen_items(*args, **kwargs):
    items = Item.query.all()

    items = [
        item for item in items
        if _canteen_is_active_record(item)
        and _canteen_belongs_to_user_branch(item)
        and _canteen_is_merchandise_item(item)
    ]

    return sorted(items, key=_canteen_sort_name)


def get_branch_workers(*args, **kwargs):
    workers = Worker.query.all()

    workers = [
        worker for worker in workers
        if _canteen_is_active_record(worker)
        and _canteen_belongs_to_user_branch(worker)
    ]

    return sorted(workers, key=_canteen_sort_name)
