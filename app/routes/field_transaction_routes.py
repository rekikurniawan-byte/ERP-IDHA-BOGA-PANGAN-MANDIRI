import logging
from datetime import date, datetime
from types import SimpleNamespace

from app.utils.clock import today_wib

from flask import Blueprint, abort, flash, redirect, render_template, request, send_file, url_for
from flask_login import current_user
from sqlalchemy import or_

from app.models.delivery import Delivery
from app.models.field_transaction import (
    FIELD_TRANSACTION_CHANNELS,
    FieldCounterparty,
    FieldTransactionAttachment,
    FieldTransaction,
    ManualPayable,
    ManualReceivable,
)
from app.models.finance import BankAccount
from app.models.master import Driver, Mandor, Supplier
from app.models.system import DigitalAttachment
from app.services.digital_attachment_service import (
    get_attachment_file_path,
    is_inline_view_safe,
)
from app.services.field_transaction_policy_service import (
    get_field_transaction_event_policy,
    list_field_transaction_event_choices,
    resolve_policy_defaults,
)
from app.services.field_transaction_bridge_service import (
    FieldTransactionBridgeError,
    bridge_to_advance_transaction,
    bridge_to_operational_expense,
    bridge_to_transport_expense,
)
from app.services.field_transaction_monitoring_service import build_field_transaction_monitoring
from app.services.field_transaction_posting_service import (
    FieldTransactionPostingError,
    post_field_transaction,
)
from app.services.field_transaction_service import (
    REVIEW_STATUS_TRANSITIONS,
    FieldTransactionValidationError,
    attach_existing_digital_attachment_to_field_transaction,
    create_field_counterparty,
    create_field_transaction,
    update_field_transaction_draft,
    update_field_transaction_review_status,
    verify_field_transaction_attachment,
)
from app.services.field_transaction_settlement_service import (
    FieldTransactionSettlementError,
    create_manual_payable_for_field_transaction,
    create_manual_receivable_for_field_transaction,
    record_manual_payable_payment,
    record_manual_receivable_payment,
)
from app.services.manual_billing_service import (
    MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
    find_manual_billing_invoice_for_source,
)
from app.utils.decorators import role_required
from app.utils.terms import T

logger = logging.getLogger(__name__)


field_transaction_bp = Blueprint(
    "field_transactions",
    __name__,
    url_prefix="/field-transactions",
)

REVIEW_ACTION_LABELS = {
    "RECORDED": "Tandai Tercatat",
    "WAITING_EVIDENCE": "Minta Bukti",
    "WAITING_CLASSIFICATION": "Minta Klasifikasi",
    "IN_REVIEW": "Kirim untuk Diperiksa",
    "WAITING_APPROVAL": "Minta Persetujuan",
    "READY_TO_POST": "Tandai Siap Dijurnal",
    "REJECTED": "Tolak",
    "VOID": "Batalkan",
    "RECONCILED": "Tandai Sudah Rekonsiliasi",
}

FIELD_TRANSACTION_SYSTEM_TRACE_EVENTS = {
    "MANUAL_RECEIVABLE_PAYMENT",
    "VENDOR_PAYABLE_PAYMENT",
    "MANDOR_ADVANCE_SETTLEMENT",
}

FIELD_TRANSACTION_TERMINAL_REVIEW_STATUSES = {
    "POSTED",
    "RECONCILED",
    "VOID",
    "REJECTED",
}


def _field_transaction_event_labels():
    return {row["value"]: row["label"] for row in list_field_transaction_event_choices()}


def _parse_date(value, label):
    raw_value = str(value or "").strip()
    if not raw_value:
        raise FieldTransactionValidationError(f"{label} wajib diisi.")
    try:
        return datetime.strptime(raw_value, "%Y-%m-%d").date()
    except Exception:
        raise FieldTransactionValidationError(f"{label} tidak valid. Gunakan format YYYY-MM-DD.")


def _to_int(value):
    try:
        return int(value) if value not in (None, "") else None
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:113")
        return None


def _build_detail_state(transaction, manual_receivable=None, manual_payable=None):
    event_type = str(transaction.business_event_type or "").strip().upper()
    review_status = str(transaction.review_status or "").strip().upper()
    posting_status = str(transaction.posting_status or "").strip().upper()
    link_roles = {str(link.link_role or "").strip().upper() for link in transaction.links}
    event_policy = get_field_transaction_event_policy(event_type)
    show_partial_warning = not bool(event_policy.get("ui_ready")) and event_type not in FIELD_TRANSACTION_SYSTEM_TRACE_EVENTS
    available_review_targets = []
    for status in sorted(REVIEW_STATUS_TRANSITIONS.get(review_status, set())):
        available_review_targets.append({
            "value": status,
            "label": REVIEW_ACTION_LABELS.get(status, status.replace("_", " ").title()),
            "needs_note": status in {"REJECTED", "VOID", "RECONCILED"},
        })
    can_reconcile = any(item["value"] == "RECONCILED" for item in available_review_targets)

    bridge_action = None
    if event_type in {"SITE_OPERATION_EXPENSE", "KITCHEN_OPERATION_EXPENSE"}:
        bridge_action = "OPERATIONAL_EXPENSE"
    elif event_type in {"TRANSPORT_TRIP_EXPENSE", "FUEL_EXPENSE"}:
        bridge_action = "TRANSPORT_EXPENSE"
    elif event_type == "MANDOR_OPERATIONAL_ADVANCE":
        bridge_action = "ADVANCE_TRANSACTION"
    can_bridge = (
        bool(bridge_action)
        and posting_status not in {"POSTED", "VOIDED"}
        and review_status not in FIELD_TRANSACTION_TERMINAL_REVIEW_STATUSES
        and bridge_action not in link_roles
        and not bool(link_roles & {"LEDGER", "JOURNAL"})
    )

    next_actions = []
    supports_auto_post = bool(event_policy.get("supports_auto_post"))
    if review_status not in {"READY_TO_POST", "POSTED", "RECONCILED", "VOID", "REJECTED"} and supports_auto_post:
        next_actions.append("Lengkapi bukti dan klasifikasi, lalu tandai transaksi siap dijurnal.")
    if review_status == "READY_TO_POST" and posting_status != "POSTED" and supports_auto_post:
        next_actions.append("Jurnal transaksi ini untuk membentuk buku kas/bank dan jurnal langsung dari transaksi lapangan ini.")
    if event_type == "MANUAL_RECEIVABLE_CREATED" and not manual_receivable:
        next_actions.append("Buat dokumen piutang manual agar transaksi yang belum lunas bisa ditagih bertahap.")
    if event_type == "UNFORMAL_VENDOR_PAYABLE" and not manual_payable:
        next_actions.append("Buat dokumen hutang manual agar kewajiban ke vendor lapangan bisa dilacak dan dibayar parsial.")
    if event_type in {"SITE_OPERATION_EXPENSE", "KITCHEN_OPERATION_EXPENSE"} and "OPERATIONAL_EXPENSE" not in link_roles and posting_status != "POSTED":
        next_actions.append("Bila perlu, hubungkan transaksi ini ke modul Biaya Operasional.")
    if event_type in {"TRANSPORT_TRIP_EXPENSE", "FUEL_EXPENSE"} and "TRANSPORT_EXPENSE" not in link_roles and posting_status != "POSTED":
        next_actions.append("Bila perlu, hubungkan biaya ini ke modul Biaya Transport.")
    if event_type == "MANDOR_OPERATIONAL_ADVANCE" and "ADVANCE_TRANSACTION" not in link_roles and posting_status != "POSTED":
        next_actions.append(f"Hubungkan ke uang muka {T.sub_client_lower} bila panjar ini perlu diselesaikan lewat modul uang muka.")
    if event_type == "MANDOR_ADVANCE_SETTLEMENT" and posting_status != "POSTED":
        next_actions.append(f"Cek detail uang muka untuk memastikan penyelesaian panjar {T.sub_client_lower} sudah punya jurnal beban dan jejak transaksi lapangan.")
    if event_type in {"OWNER_CASH_INJECTION", "OWNER_DRAWING"} and review_status == "WAITING_APPROVAL":
        next_actions.append("Minta persetujuan owner sebelum transaksi modal ini dijurnal ke buku kas/bank dan jurnal.")
    if event_type not in {
        "CATERING_DAILY_CASH_SALE",
        "CATERING_PERIOD_RECAP_REVENUE",
        "OTHER_OPERATING_INCOME",
        "MANUAL_RECEIVABLE_CREATED",
        "MANUAL_RECEIVABLE_PAYMENT",
        "SITE_OPERATION_EXPENSE",
        "KITCHEN_OPERATION_EXPENSE",
        "TRANSPORT_TRIP_EXPENSE",
        "FUEL_EXPENSE",
        "UNFORMAL_VENDOR_PAYABLE",
        "VENDOR_PAYABLE_PAYMENT",
        "MANDOR_OPERATIONAL_ADVANCE",
        "MANDOR_ADVANCE_SETTLEMENT",
        "OWNER_CASH_INJECTION",
        "OWNER_DRAWING",
    }:
        next_actions.append("Event ini belum dibuka lagi untuk entry UI baru karena alur end-to-end-nya masih parsial. Gunakan dokumen turunan atau modul legacy yang relevan.")
    if not next_actions and posting_status == "POSTED":
        next_actions.append("Transaksi sudah selesai diposting. Gunakan halaman ini untuk audit jurnal, ledger, lampiran, dan relasi dokumen.")
    elif not next_actions:
        next_actions.append("Tidak ada tindak lanjut wajib yang mendesak; transaksi sudah cukup lengkap untuk fase saat ini.")

    return {
        "event_label": event_policy.get("label", event_type),
        "event_ui_ready": bool(event_policy.get("ui_ready")) or event_type in FIELD_TRANSACTION_SYSTEM_TRACE_EVENTS,
        "show_partial_warning": show_partial_warning,
        "link_roles": sorted(link_roles),
        "available_review_targets": available_review_targets,
        "show_review_panel": bool(available_review_targets) and review_status != "POSTED",
        "can_reconcile": can_reconcile,
        "can_mark_ready": any(item["value"] == "READY_TO_POST" for item in available_review_targets),
        "can_post": review_status == "READY_TO_POST" and posting_status != "POSTED",
        "can_edit": bool(event_policy.get("ui_ready")) and posting_status not in {"POSTED", "VOIDED"} and review_status not in {"POSTED", "VOID", "RECONCILED"},
        "is_completed": posting_status == "POSTED" or review_status == "RECONCILED",
        "manual_document_event": event_type in {"MANUAL_RECEIVABLE_CREATED", "UNFORMAL_VENDOR_PAYABLE"},
        "bridge_action": bridge_action,
        "can_bridge": can_bridge,
        "has_financial_trace": bool(link_roles & {"LEDGER", "JOURNAL", "OPERATIONAL_EXPENSE", "TRANSPORT_EXPENSE", "ADVANCE_TRANSACTION"}),
        "next_actions": next_actions,
    }


def _resolve_document_link_target(link, transaction):
    link_role = str(getattr(link, "link_role", "") or "").strip().upper()
    reference_type = str(getattr(link, "reference_type", "") or "").strip().upper()
    reference_id = getattr(link, "reference_id", None)

    label = f"{link_role} - {reference_type} #{reference_id}"
    href = None
    helper_text = None

    if reference_type == "JOURNAL":
        href = url_for("accounting.journal_detail", journal_id=reference_id)
        helper_text = "Buka detail jurnal"
    elif reference_type == "CASH_BANK_TRANSACTION":
        href = url_for("finance.cash_bank_transaction_detail", transaction_id=reference_id)
        helper_text = "Buka detail ledger kas/bank"
    elif reference_type == "OPERATIONAL_EXPENSE":
        href = url_for("finance.operational_expense_detail", expense_id=reference_id)
        helper_text = "Buka detail biaya operasional"
    elif reference_type == "TRANSPORT_VEHICLE_EXPENSE":
        href = url_for("finance.transport_expense_detail", expense_id=reference_id)
        helper_text = "Buka detail biaya transport/BBM"
    elif reference_type == "ADVANCE_TRANSACTION":
        href = url_for("finance.advance_detail", advance_id=reference_id)
        helper_text = "Buka detail advance"
    elif reference_type == "ADVANCE_SETTLEMENT":
        href = url_for("finance.advances")
        helper_text = "Buka modul advance untuk melihat settlement terkait"
    elif reference_type == "MANUAL_RECEIVABLE":
        href = url_for("field_transactions.detail", transaction_id=transaction.id) + "#manual-receivable"
        helper_text = "Buka bagian piutang manual"
    elif reference_type == "MANUAL_RECEIVABLE_PAYMENT":
        href = url_for("field_transactions.detail", transaction_id=transaction.id) + "#manual-receivable-payments"
        helper_text = "Buka riwayat pembayaran piutang"
    elif reference_type == "MANUAL_PAYABLE":
        href = url_for("field_transactions.detail", transaction_id=transaction.id) + "#manual-payable"
        helper_text = "Buka bagian hutang manual"
    elif reference_type == "MANUAL_PAYABLE_PAYMENT":
        href = url_for("field_transactions.detail", transaction_id=transaction.id) + "#manual-payable-payments"
        helper_text = "Buka riwayat pembayaran hutang"

    return {
        "label": label,
        "href": href,
        "helper_text": helper_text,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "link_role": link_role,
    }


def _get_owned_transaction_or_redirect(transaction_id):
    transaction = FieldTransaction.query.get_or_404(transaction_id)
    if transaction.branch_id != current_user.branch_id:
        flash("Transaksi lapangan tidak sesuai cabang user.", "danger")
        return None, redirect(url_for("field_transactions.index"))
    return transaction, None


def _get_owned_field_attachment_or_404(attachment_id):
    attachment_link = FieldTransactionAttachment.query.get_or_404(attachment_id)
    field_transaction = getattr(attachment_link, "field_transaction", None)
    if not field_transaction or field_transaction.branch_id != current_user.branch_id:
        abort(404)
    return attachment_link


def _load_field_transaction_form_options(branch_id):
    bank_accounts = BankAccount.query.filter_by(
        branch_id=branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    counterparties = FieldCounterparty.query.filter_by(
        branch_id=branch_id,
        is_active=True,
    ).order_by(FieldCounterparty.name.asc()).all()
    event_choices = list_field_transaction_event_choices(ui_ready_only=True)
    return bank_accounts, counterparties, event_choices


def _build_field_transaction_form_data(source):
    return {
        "transaction_date": getattr(source, "transaction_date", None).isoformat() if getattr(source, "transaction_date", None) else today_wib().isoformat(),
        "entry_date": getattr(source, "entry_date", None).isoformat() if getattr(source, "entry_date", None) else today_wib().isoformat(),
        "amount": getattr(source, "amount", "") or "",
        "business_event_type": getattr(source, "business_event_type", "") or "",
        "field_channel": getattr(source, "field_channel", "MANUAL") or "MANUAL",
        "counterparty_id": getattr(source, "counterparty_id", "") or "",
        "new_counterparty_type": "LAINNYA",
        "party_snapshot_name": getattr(source, "party_snapshot_name", "") or "",
        "party_snapshot_company": getattr(source, "party_snapshot_company", "") or "",
        "party_snapshot_phone": getattr(source, "party_snapshot_phone", "") or "",
        "site_location": getattr(source, "site_location", "") or "",
        "register_counterparty": False,
        "payment_method": getattr(source, "payment_method", "") or "",
        "bank_account_id": getattr(source, "bank_account_id", "") or "",
        "notes": getattr(source, "notes", "") or "",
    }


def _build_attachment_ui_state(attachment_link):
    digital_attachment = getattr(attachment_link, "digital_attachment", None)
    if not digital_attachment or getattr(digital_attachment, "is_deleted", False):
        return {
            "availability": "MISSING",
            "can_view": False,
            "can_download": False,
            "helper": "Metadata ada, tetapi file lampiran sudah tidak tersedia.",
        }

    can_view = is_inline_view_safe(digital_attachment)
    try:
        get_attachment_file_path(digital_attachment)
        availability = "READY"
        helper = "Lihat membuka tab baru. Unduh menyimpan file asli ke browser."
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:325")
        availability = "MISSING"
        can_view = False
        helper = f"File fisik tidak ditemukan: {exc}"

    return {
        "availability": availability,
        "can_view": can_view,
        "can_download": availability == "READY",
        "helper": helper,
    }


@field_transaction_bp.route("/")
@role_required("ADMIN", "FINANCE", "ACCOUNTING")
def index():
    selected_status = (request.args.get("status") or "ALL").strip().upper()
    selected_event = (request.args.get("event") or "ALL").strip().upper()
    selected_direction = (request.args.get("direction") or "ALL").strip().upper()

    query = FieldTransaction.query.filter_by(branch_id=current_user.branch_id)
    if selected_status != "ALL":
        query = query.filter(FieldTransaction.review_status == selected_status)
    if selected_event != "ALL":
        query = query.filter(FieldTransaction.business_event_type == selected_event)
    if selected_direction != "ALL":
        query = query.filter(FieldTransaction.transaction_direction == selected_direction)

    transactions = query.order_by(
        FieldTransaction.transaction_date.desc(),
        FieldTransaction.id.desc(),
    ).all()

    summary = {
        "total": len(transactions),
        "total_in": sum(float(row.amount or 0) for row in transactions if row.transaction_direction == "IN"),
        "total_out": sum(float(row.amount or 0) for row in transactions if row.transaction_direction == "OUT"),
        "pending_review": len(
            [row for row in transactions if str(row.review_status or "").upper() in {"DRAFT", "WAITING_EVIDENCE", "WAITING_CLASSIFICATION", "IN_REVIEW", "WAITING_APPROVAL"}]
        ),
    }

    return render_template(
        "field_transactions/index.html",
        transactions=transactions,
        summary=summary,
        event_choices=list_field_transaction_event_choices(),
        event_labels=_field_transaction_event_labels(),
        selected_status=selected_status,
        selected_event=selected_event,
        selected_direction=selected_direction,
    )


@field_transaction_bp.route("/monitoring")
@role_required("ADMIN", "FINANCE", "ACCOUNTING")
def monitoring():
    monitoring_data = build_field_transaction_monitoring(current_user.branch_id)
    return render_template(
        "field_transactions/monitoring.html",
        monitoring=monitoring_data,
        event_labels=_field_transaction_event_labels(),
    )


@field_transaction_bp.route("/create", methods=["GET", "POST"])
@role_required("ADMIN", "FINANCE")
def create():
    bank_accounts, counterparties, event_choices = _load_field_transaction_form_options(current_user.branch_id)
    form_data = _build_field_transaction_form_data(SimpleNamespace())

    if request.method == "POST":
        event_type = (request.form.get("business_event_type") or "").strip().upper()
        defaults = {}
        try:
            defaults = resolve_policy_defaults(event_type)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:401")
            pass
        form_data = dict(request.form)

        try:
            transaction_date = _parse_date(request.form.get("transaction_date"), "Tanggal kejadian")
            entry_date = _parse_date(request.form.get("entry_date"), "Tanggal input")
            amount = request.form.get("amount")
            field_channel = (request.form.get("field_channel") or "MANUAL").strip().upper()
            payment_method = (request.form.get("payment_method") or "").strip().upper() or None
            bank_account_id = _to_int(request.form.get("bank_account_id"))
            counterparty_id = _to_int(request.form.get("counterparty_id"))
            notes = request.form.get("notes")
            site_location = request.form.get("site_location")
            register_counterparty = (request.form.get("register_counterparty") or "").strip() == "1"
            new_counterparty_type = (request.form.get("new_counterparty_type") or "").strip().upper()
            party_snapshot_name = request.form.get("party_snapshot_name")
            party_snapshot_company = request.form.get("party_snapshot_company")
            party_snapshot_phone = request.form.get("party_snapshot_phone")

            if register_counterparty and party_snapshot_name:
                _, _, counterparty = create_field_counterparty(
                    branch_id=current_user.branch_id,
                    counterparty_type=new_counterparty_type or "LAINNYA",
                    name=party_snapshot_name,
                    created_by=current_user.id,
                    company_name=party_snapshot_company,
                    phone=party_snapshot_phone,
                    site_location=site_location,
                    commit=False,
                )
                counterparty_id = counterparty.id

            _, message, transaction = create_field_transaction(
                branch_id=current_user.branch_id,
                transaction_date=transaction_date,
                entry_date=entry_date,
                transaction_direction=defaults.get("transaction_direction") or request.form.get("transaction_direction"),
                business_event_type=event_type,
                amount=amount,
                created_by=current_user.id,
                field_channel=field_channel,
                counterparty_id=counterparty_id,
                party_snapshot_name=party_snapshot_name,
                party_snapshot_company=party_snapshot_company,
                party_snapshot_phone=party_snapshot_phone,
                site_location=site_location,
                payment_status=defaults.get("payment_status"),
                payment_method=payment_method,
                bank_account_id=bank_account_id,
                review_status=defaults.get("review_status"),
                evidence_status=defaults.get("evidence_status"),
                notes=notes,
                commit=True,
            )
            flash(message, "success")
            return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))
        except FieldTransactionValidationError as exc:
            flash(str(exc), "warning")
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:460")
            flash(f"Gagal membuat transaksi lapangan: {exc}", "danger")

    return render_template(
        "field_transactions/form.html",
        mode="create",
        page_title="Buat Draft Transaksi Kas Lapangan",
        page_subtitle="Form ini dipakai untuk menangkap transaksi manual lapangan lebih dulu. Review, klasifikasi, dan posting formal dilakukan bertahap.",
        submit_label="Simpan Draft",
        action_url=url_for("field_transactions.create"),
        event_choices=event_choices,
        field_channels=FIELD_TRANSACTION_CHANNELS,
        bank_accounts=bank_accounts,
        counterparties=counterparties,
        form_data=form_data,
    )


@field_transaction_bp.route("/<int:transaction_id>/edit", methods=["GET", "POST"])
@role_required("ADMIN", "FINANCE")
def edit(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    detail_state = _build_detail_state(transaction)
    if not detail_state["can_edit"]:
        flash("Transaksi lapangan ini tidak bisa diedit pada status saat ini.", "warning")
        return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))

    bank_accounts, counterparties, event_choices = _load_field_transaction_form_options(current_user.branch_id)
    form_data = _build_field_transaction_form_data(transaction)

    if request.method == "POST":
        event_type = (request.form.get("business_event_type") or "").strip().upper()
        defaults = {}
        try:
            defaults = resolve_policy_defaults(event_type)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:498")
            pass
        form_data = dict(request.form)

        try:
            transaction_date = _parse_date(request.form.get("transaction_date"), "Tanggal kejadian")
            entry_date = _parse_date(request.form.get("entry_date"), "Tanggal input")
            amount = request.form.get("amount")
            field_channel = (request.form.get("field_channel") or "MANUAL").strip().upper()
            payment_method = (request.form.get("payment_method") or "").strip().upper() or None
            bank_account_id = _to_int(request.form.get("bank_account_id"))
            counterparty_id = _to_int(request.form.get("counterparty_id"))
            notes = request.form.get("notes")
            site_location = request.form.get("site_location")
            register_counterparty = (request.form.get("register_counterparty") or "").strip() == "1"
            new_counterparty_type = (request.form.get("new_counterparty_type") or "").strip().upper()
            party_snapshot_name = request.form.get("party_snapshot_name")
            party_snapshot_company = request.form.get("party_snapshot_company")
            party_snapshot_phone = request.form.get("party_snapshot_phone")

            if register_counterparty and party_snapshot_name:
                _, _, counterparty = create_field_counterparty(
                    branch_id=current_user.branch_id,
                    counterparty_type=new_counterparty_type or "LAINNYA",
                    name=party_snapshot_name,
                    created_by=current_user.id,
                    company_name=party_snapshot_company,
                    phone=party_snapshot_phone,
                    site_location=site_location,
                    commit=False,
                )
                counterparty_id = counterparty.id

            _, message, _ = update_field_transaction_draft(
                transaction,
                transaction_date=transaction_date,
                entry_date=entry_date,
                transaction_direction=defaults.get("transaction_direction") or request.form.get("transaction_direction"),
                business_event_type=event_type,
                amount=amount,
                updated_by=current_user.id,
                field_channel=field_channel,
                counterparty_id=counterparty_id,
                party_snapshot_name=party_snapshot_name,
                party_snapshot_company=party_snapshot_company,
                party_snapshot_phone=party_snapshot_phone,
                site_location=site_location,
                payment_status=transaction.payment_status,
                payment_method=payment_method,
                bank_account_id=bank_account_id,
                notes=notes,
                commit=True,
            )
            flash(message, "success")
            return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))
        except FieldTransactionValidationError as exc:
            flash(str(exc), "warning")
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:555")
            flash(f"Gagal memperbarui draft transaksi lapangan: {exc}", "danger")

    return render_template(
        "field_transactions/form.html",
        mode="edit",
        page_title=f"Edit Draft {transaction.transaction_number}",
        page_subtitle="Perbarui data inti transaksi lapangan sebelum diposting atau dijembatani ke modul lain.",
        submit_label="Simpan Perubahan",
        action_url=url_for("field_transactions.edit", transaction_id=transaction.id),
        event_choices=event_choices,
        field_channels=FIELD_TRANSACTION_CHANNELS,
        bank_accounts=bank_accounts,
        counterparties=counterparties,
        form_data=form_data,
    )


@field_transaction_bp.route("/<int:transaction_id>")
@role_required("ADMIN", "FINANCE", "ACCOUNTING")
def detail(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    manual_receivable = ManualReceivable.query.filter_by(field_transaction_id=transaction.id).first()
    manual_payable = ManualPayable.query.filter_by(field_transaction_id=transaction.id).first()
    manual_receivable_billing_invoice = None
    if manual_receivable:
        manual_receivable_billing_invoice = find_manual_billing_invoice_for_source(
            MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
            manual_receivable.id,
        )
    bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    suppliers = Supplier.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Supplier.supplier_name.asc()).all()
    drivers = Driver.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Driver.name.asc()).all()
    deliveries = Delivery.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(Delivery.delivery_date.desc(), Delivery.id.desc()).limit(100).all()
    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Mandor.name.asc()).all()
    linked_attachment_ids = {
        item.digital_attachment_id for item in transaction.attachments if getattr(item, "digital_attachment_id", None)
    }
    available_attachments = (
        DigitalAttachment.query.filter(
            DigitalAttachment.is_deleted == False,
            or_(
                DigitalAttachment.branch_id == current_user.branch_id,
                DigitalAttachment.branch_id.is_(None),
            ),
        )
        .order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc())
        .limit(100)
        .all()
    )
    available_attachments = [
        item for item in available_attachments if item.id not in linked_attachment_ids
    ]
    attachment_ui_state = {
        item.id: _build_attachment_ui_state(item)
        for item in transaction.attachments
    }

    return render_template(
        "field_transactions/detail.html",
        transaction=transaction,
        manual_receivable=manual_receivable,
        manual_payable=manual_payable,
        manual_receivable_billing_invoice=manual_receivable_billing_invoice,
        bank_accounts=bank_accounts,
        suppliers=suppliers,
        drivers=drivers,
        deliveries=deliveries,
        mandors=mandors,
        available_attachments=available_attachments,
        attachment_ui_state=attachment_ui_state,
        is_inline_view_safe=is_inline_view_safe,
        document_links=[
            _resolve_document_link_target(link, transaction)
            for link in sorted(transaction.links, key=lambda item: ((item.link_role or ""), item.id))
        ],
        detail_state=_build_detail_state(transaction, manual_receivable, manual_payable),
    )


@field_transaction_bp.route("/<int:transaction_id>/attachments/link", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def link_attachment(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    digital_attachment_id = _to_int(request.form.get("digital_attachment_id"))
    attachment_role = (request.form.get("attachment_role") or "EVIDENCE").strip().upper()
    notes = request.form.get("notes")
    try:
        ok, message, _ = attach_existing_digital_attachment_to_field_transaction(
            transaction,
            digital_attachment_id=digital_attachment_id,
            created_by=current_user.id,
            attachment_role=attachment_role,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:674")
        flash(f"Gagal menautkan lampiran transaksi lapangan: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))


@field_transaction_bp.route("/attachments/<int:attachment_id>/verify", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def verify_attachment(attachment_id):
    attachment_link = _get_owned_field_attachment_or_404(attachment_id)
    try:
        ok, message, _ = verify_field_transaction_attachment(
            attachment_link,
            verified_by=current_user.id,
            note=request.form.get("notes"),
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:693")
        flash(f"Gagal memverifikasi lampiran transaksi lapangan: {exc}", "danger")
    return redirect(
        url_for(
            "field_transactions.detail",
            transaction_id=attachment_link.field_transaction_id,
        )
    )


@field_transaction_bp.route("/attachments/<int:attachment_id>/download")
@role_required("ADMIN", "FINANCE", "ACCOUNTING")
def download_attachment(attachment_id):
    attachment_link = _get_owned_field_attachment_or_404(attachment_id)
    digital_attachment = attachment_link.digital_attachment
    if not digital_attachment or digital_attachment.is_deleted:
        abort(404)

    try:
        file_path = get_attachment_file_path(digital_attachment)
    except FileNotFoundError as exc:
        logger.warning("File lampiran transaksi lapangan hilang: attachment_id=%s", attachment_id)
        flash(f"File lampiran transaksi lapangan tidak ditemukan: {exc}", "warning")
        return redirect(
            url_for(
                "field_transactions.detail",
                transaction_id=attachment_link.field_transaction_id,
            )
        )
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:713")
        flash(f"File lampiran transaksi lapangan tidak bisa diunduh: {exc}", "danger")
        return redirect(
            url_for(
                "field_transactions.detail",
                transaction_id=attachment_link.field_transaction_id,
            )
        )

    response = send_file(
        str(file_path),
        as_attachment=True,
        download_name=digital_attachment.original_filename,
        mimetype=digital_attachment.mime_type or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@field_transaction_bp.route("/attachments/<int:attachment_id>/view")
@role_required("ADMIN", "FINANCE", "ACCOUNTING")
def view_attachment(attachment_id):
    attachment_link = _get_owned_field_attachment_or_404(attachment_id)
    digital_attachment = attachment_link.digital_attachment
    if not digital_attachment or digital_attachment.is_deleted:
        abort(404)
    if not is_inline_view_safe(digital_attachment):
        abort(403)

    try:
        file_path = get_attachment_file_path(digital_attachment)
    except FileNotFoundError as exc:
        logger.warning("File lampiran transaksi lapangan hilang: attachment_id=%s", attachment_id)
        flash(f"File lampiran transaksi lapangan tidak ditemukan: {exc}", "warning")
        return redirect(
            url_for(
                "field_transactions.detail",
                transaction_id=attachment_link.field_transaction_id,
            )
        )
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:745")
        flash(f"File lampiran transaksi lapangan tidak bisa dibuka: {exc}", "danger")
        return redirect(
            url_for(
                "field_transactions.detail",
                transaction_id=attachment_link.field_transaction_id,
            )
        )

    response = send_file(
        str(file_path),
        as_attachment=False,
        download_name=digital_attachment.original_filename,
        mimetype=digital_attachment.mime_type or "application/octet-stream",
        max_age=0,
    )
    response.headers["Cache-Control"] = "no-store"
    return response


@field_transaction_bp.route("/<int:transaction_id>/review-status", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def update_review_status(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    to_review_status = (request.form.get("to_review_status") or "").strip().upper()
    note = request.form.get("note")
    try:
        _, message, _ = update_field_transaction_review_status(
            transaction,
            to_review_status=to_review_status,
            acted_by=current_user.id,
            note=note,
            commit=True,
        )
        flash(message, "success")
    except FieldTransactionValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:785")
        flash(f"Gagal memperbarui status review: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))


@field_transaction_bp.route("/<int:transaction_id>/post", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def post(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    try:
        ok, message, _ = post_field_transaction(
            transaction,
            posted_by=current_user.id,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionPostingError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:806")
        flash(f"Gagal melakukan posting transaksi lapangan: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))


@field_transaction_bp.route("/<int:transaction_id>/manual-receivable/create", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def create_manual_receivable_doc(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    try:
        due_date = _parse_date(request.form.get("due_date"), "Tanggal jatuh tempo")
        notes = request.form.get("notes")
        ok, message, _ = create_manual_receivable_for_field_transaction(
            transaction,
            created_by=current_user.id,
            due_date=due_date,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionValidationError as exc:
        flash(str(exc), "warning")
    except FieldTransactionSettlementError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:833")
        flash(f"Gagal membuat piutang manual: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))


@field_transaction_bp.route("/<int:transaction_id>/manual-payable/create", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def create_manual_payable_doc(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    try:
        due_date = _parse_date(request.form.get("due_date"), "Tanggal jatuh tempo")
        notes = request.form.get("notes")
        ok, message, _ = create_manual_payable_for_field_transaction(
            transaction,
            created_by=current_user.id,
            due_date=due_date,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionValidationError as exc:
        flash(str(exc), "warning")
    except FieldTransactionSettlementError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:860")
        flash(f"Gagal membuat hutang manual: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))


@field_transaction_bp.route("/manual-receivables/<int:receivable_id>/payments/create", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def create_manual_receivable_payment(receivable_id):
    receivable = ManualReceivable.query.get_or_404(receivable_id)
    if receivable.branch_id != current_user.branch_id:
        flash("Piutang manual tidak sesuai cabang user.", "danger")
        return redirect(url_for("field_transactions.index"))

    billed_invoice = find_manual_billing_invoice_for_source(
        MANUAL_BILLING_SOURCE_MANUAL_RECEIVABLE,
        receivable.id,
    )
    if billed_invoice and billed_invoice.branch_id == current_user.branch_id:
        flash(
            f"Piutang manual ini sudah masuk invoice formal {billed_invoice.invoice_number}. "
            "Terima pembayaran dari menu invoice agar trace penagihan tetap satu jalur.",
            "warning",
        )
        return redirect(url_for("finance.invoice_detail", invoice_id=billed_invoice.id))

    try:
        payment_date = _parse_date(request.form.get("payment_date"), "Tanggal bayar")
        payment_method = (request.form.get("payment_method") or "").strip().upper()
        bank_account_id = _to_int(request.form.get("bank_account_id"))
        amount = request.form.get("amount")
        reference_number = request.form.get("reference_number")
        notes = request.form.get("notes")
        ok, message, _ = record_manual_receivable_payment(
            receivable,
            payment_date=payment_date,
            payment_method=payment_method,
            amount=amount,
            paid_by=current_user.id,
            bank_account_id=bank_account_id,
            reference_number=reference_number,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionValidationError as exc:
        flash(str(exc), "warning")
    except FieldTransactionSettlementError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:908")
        flash(f"Gagal mencatat pembayaran piutang manual: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=receivable.field_transaction_id))


@field_transaction_bp.route("/manual-payables/<int:payable_id>/payments/create", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def create_manual_payable_payment(payable_id):
    payable = ManualPayable.query.get_or_404(payable_id)
    if payable.branch_id != current_user.branch_id:
        flash("Hutang manual tidak sesuai cabang user.", "danger")
        return redirect(url_for("field_transactions.index"))

    try:
        payment_date = _parse_date(request.form.get("payment_date"), "Tanggal bayar")
        payment_method = (request.form.get("payment_method") or "").strip().upper()
        bank_account_id = _to_int(request.form.get("bank_account_id"))
        amount = request.form.get("amount")
        reference_number = request.form.get("reference_number")
        notes = request.form.get("notes")
        ok, message, _ = record_manual_payable_payment(
            payable,
            payment_date=payment_date,
            payment_method=payment_method,
            amount=amount,
            paid_by=current_user.id,
            bank_account_id=bank_account_id,
            reference_number=reference_number,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionValidationError as exc:
        flash(str(exc), "warning")
    except FieldTransactionSettlementError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:944")
        flash(f"Gagal mencatat pembayaran hutang manual: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=payable.field_transaction_id))


@field_transaction_bp.route("/<int:transaction_id>/bridge/operational-expense", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def bridge_operational_expense(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    expense_category = (request.form.get("expense_category") or "").strip().upper()
    supplier_id = _to_int(request.form.get("supplier_id"))
    vendor_name = request.form.get("vendor_name")
    reference_number = request.form.get("reference_number")
    notes = request.form.get("notes")

    try:
        ok, message, _ = bridge_to_operational_expense(
            transaction,
            created_by=current_user.id,
            expense_category=expense_category,
            supplier_id=supplier_id,
            vendor_name=vendor_name,
            reference_number=reference_number,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionBridgeError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:976")
        flash(f"Gagal bridge ke biaya operasional: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))


@field_transaction_bp.route("/<int:transaction_id>/bridge/transport-expense", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def bridge_transport_expense(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    vehicle_label = request.form.get("vehicle_label")
    driver_id = _to_int(request.form.get("driver_id"))
    delivery_id = _to_int(request.form.get("delivery_id"))
    vendor_name = request.form.get("vendor_name")
    reference_number = request.form.get("reference_number")
    notes = request.form.get("notes")

    try:
        ok, message, _ = bridge_to_transport_expense(
            transaction,
            created_by=current_user.id,
            vehicle_label=vehicle_label,
            driver_id=driver_id,
            delivery_id=delivery_id,
            vendor_name=vendor_name,
            reference_number=reference_number,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionBridgeError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:1010")
        flash(f"Gagal bridge ke biaya transport/BBM: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))


@field_transaction_bp.route("/<int:transaction_id>/bridge/advance", methods=["POST"])
@role_required("FINANCE", "ACCOUNTING")
def bridge_advance(transaction_id):
    transaction, redirect_response = _get_owned_transaction_or_redirect(transaction_id)
    if redirect_response:
        return redirect_response

    mandor_id = _to_int(request.form.get("mandor_id"))
    reference_number = request.form.get("reference_number")
    notes = request.form.get("notes")

    try:
        ok, message, _ = bridge_to_advance_transaction(
            transaction,
            created_by=current_user.id,
            mandor_id=mandor_id,
            reference_number=reference_number,
            notes=notes,
            commit=True,
        )
        flash(message, "success" if ok else "warning")
    except FieldTransactionBridgeError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/field_transaction_routes.py:1038")
        flash(f"Gagal bridge ke advance {T.sub_client_lower}: {exc}", "danger")
    return redirect(url_for("field_transactions.detail", transaction_id=transaction.id))
