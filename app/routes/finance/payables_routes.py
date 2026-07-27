"""Accounts payable and supplier payment routes.

Route functions moved out of app.routes.finance_routes without changing URL rules or endpoint names.
"""
from app.routes.finance_routes import *  # noqa: F401,F403
from app.routes.finance_routes import (
    _supplier_payment_attachment_or_404,
    _supplier_payment_or_404,
)


@finance_bp.route("/accounts-payable-aging")
@role_required("OWNER", "ADMIN", "FINANCE")
def accounts_payable_aging():
    from datetime import date, datetime
    from app.models.master import Supplier
    from app.services.accounts_payable_report_service import build_ap_aging_report

    as_of_raw = (request.args.get("as_of_date") or "").strip()
    supplier_id_raw = (request.args.get("supplier_id") or "").strip()

    try:
        as_of_date = datetime.strptime(as_of_raw, "%Y-%m-%d").date() if as_of_raw else date.today()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4591")
        flash("Tanggal aging tidak valid. Sistem memakai tanggal hari ini.", "warning")
        as_of_date = date.today()

    supplier_id = None
    if supplier_id_raw:
        try:
            supplier_id = int(supplier_id_raw)
        except (TypeError, ValueError):
            supplier_id = None

    suppliers = Supplier.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(
        Supplier.supplier_name.asc(),
    ).all()

    report = build_ap_aging_report(
        branch_id=current_user.branch_id,
        as_of_date=as_of_date,
        supplier_id=supplier_id,
    )

    return render_template(
        "finance/accounts_payable_aging.html",
        report=report,
        suppliers=suppliers,
        selected_supplier_id=supplier_id,
        as_of_date=as_of_date,
    )


@finance_bp.route("/supplier-payable-card")
@role_required("OWNER", "ADMIN", "FINANCE")
def supplier_payable_card():
    from datetime import datetime
    from app.services.accounts_payable_report_service import build_supplier_payable_card

    supplier_key = (request.args.get("supplier_key") or "").strip() or None
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()

    start_date = None
    end_date = None

    try:
        if start_raw:
            start_date = datetime.strptime(start_raw, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4639")
        flash("Tanggal awal kartu hutang tidak valid dan diabaikan.", "warning")
        start_date = None

    try:
        if end_raw:
            end_date = datetime.strptime(end_raw, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4646")
        flash("Tanggal akhir kartu hutang tidak valid dan diabaikan.", "warning")
        end_date = None

    if start_date and end_date and start_date > end_date:
        flash("Tanggal awal tidak boleh lebih besar dari tanggal akhir. Filter tanggal diabaikan.", "warning")
        start_date = None
        end_date = None

    report = build_supplier_payable_card(
        branch_id=current_user.branch_id,
        supplier_key=supplier_key,
        start_date=start_date,
        end_date=end_date,
    )

    return render_template(
        "finance/supplier_payable_card.html",
        report=report,
        selected_supplier_key=supplier_key,
        start_date=start_date,
        end_date=end_date,
    )

# === PRODUCTION_SUPPLIER_BILL_AP_ROUTES ===
@finance_bp.route("/supplier-bills")
@role_required("OWNER", "ADMIN", "FINANCE")
def supplier_bills():
    from datetime import date
    from app.models.finance import SupplierBill
    from app.services.accounts_payable_service import supplier_bill_aging_stage

    selected_filter = (request.args.get("filter") or "OPEN").strip().upper()
    allowed_filters = ["OPEN", "OVERDUE", "DUE_SOON", "ALL", "PAID"]
    date_filter = resolve_date_filter(request.args, default_preset="all")

    if selected_filter not in allowed_filters:
        selected_filter = "OPEN"

    bills_query = SupplierBill.query.filter_by(branch_id=current_user.branch_id)
    bills_query = apply_date_range_to_query(bills_query, SupplierBill.due_date, date_filter)

    bills = bills_query.order_by(
        SupplierBill.due_date.asc(),
        SupplierBill.id.desc()
    ).all()

    today = date.today()
    rows = []
    summary = {
        "total_open": 0,
        "open_count": 0,
        "overdue_total": 0,
        "overdue_count": 0,
        "due_soon_total": 0,
        "due_soon_count": 0,
        "paid_count": 0,
    }

    for bill in bills:
        aging = supplier_bill_aging_stage(bill, today)
        remaining = float(bill.remaining_amount or 0)

        if aging["stage"] != "PAID":
            summary["total_open"] += remaining
            summary["open_count"] += 1

        if aging["stage"] == "OVERDUE":
            summary["overdue_total"] += remaining
            summary["overdue_count"] += 1
        elif aging["stage"] == "DUE_SOON":
            summary["due_soon_total"] += remaining
            summary["due_soon_count"] += 1
        elif aging["stage"] == "PAID":
            summary["paid_count"] += 1

        show_row = False

        if selected_filter == "ALL":
            show_row = True
        elif selected_filter == "OPEN" and aging["stage"] != "PAID":
            show_row = True
        elif selected_filter == aging["stage"]:
            show_row = True

        if show_row:
            rows.append({
                "bill": bill,
                "aging": aging,
                "procurement": bill.procurement,
                "supplier": bill.supplier,
            })

    filter_options = [
        {"value": "OPEN", "label": "Belum Lunas"},
        {"value": "OVERDUE", "label": "Overdue"},
        {"value": "DUE_SOON", "label": "Segera Jatuh Tempo"},
        {"value": "PAID", "label": "Lunas"},
        {"value": "ALL", "label": "Semua"},
    ]

    return render_template(
        "finance/supplier_bills.html",
        rows=rows,
        summary=summary,
        selected_filter=selected_filter,
        filter_options=filter_options,
        today=today,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("finance.supplier_bills"),
            reset_url=url_for("finance.supplier_bills"),
            title="Filter Hutang Supplier",
            description="Custom tanggal jatuh tempo dan status hutang supplier.",
            status_name="filter",
            status_value=selected_filter,
            status_options=filter_options,
        ),
    )


@finance_bp.route("/supplier-bills/<int:bill_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def supplier_bill_detail(bill_id):
    from datetime import date
    from app.models.finance import BankAccount, CashBankTransaction, SupplierBill, SupplierPayment
    from app.models.accounting import Journal
    from app.models.logistics import StockMovement
    from app.services.accounts_payable_service import supplier_bill_aging_stage

    bill = SupplierBill.query.get_or_404(bill_id)

    if bill.branch_id != current_user.branch_id:
        flash("Data hutang supplier tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.supplier_bills"))

    procurement = bill.procurement
    journal = None
    stock_movements = []

    procurement_posting_status = None

    if procurement:
        journal = Journal.query.filter_by(
            reference_type="PROCUREMENT",
            reference_id=procurement.id,
        ).first()
        from app.services.accounting_posting_status_service import build_single_source_posting_status
        procurement_posting_status = build_single_source_posting_status("PROCUREMENT", procurement)

        stock_movements = StockMovement.query.filter_by(
            branch_id=current_user.branch_id,
            reference_type="PEMBELIAN_BARANG",
            reference_id=procurement.id,
        ).all()

    payments = SupplierPayment.query.filter_by(
        branch_id=current_user.branch_id,
        supplier_bill_id=bill.id,
    ).order_by(
        SupplierPayment.payment_date.desc(),
        SupplierPayment.id.desc(),
    ).all()

    payment_ids = [payment.id for payment in payments]
    journal_by_payment = {}
    ledger_by_payment = {}
    supplier_payment_attachments = {
        payment.id: list_reference_attachments(
            module=SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=payment.id,
            branch_id=current_user.branch_id,
        )
        for payment in payments
    }

    if payment_ids:
        journals = Journal.query.filter(
            Journal.reference_type == "SUPPLIER_PAYMENT",
            Journal.reference_id.in_(payment_ids),
        ).all()
        journal_by_payment = {row.reference_id: row for row in journals}

        ledgers = CashBankTransaction.query.filter(
            CashBankTransaction.branch_id == current_user.branch_id,
            CashBankTransaction.reference_type == "SUPPLIER_PAYMENT",
            CashBankTransaction.reference_id.in_(payment_ids),
        ).all()
        ledger_by_payment = {row.reference_id: row for row in ledgers}

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc(),
    ).all()

    return render_template(
        "finance/supplier_bill_detail.html",
        bill=bill,
        procurement=procurement,
        supplier=bill.supplier,
        journal=journal,
        procurement_posting_status=procurement_posting_status,
        stock_movements=stock_movements,
        payments=payments,
        journal_by_payment=journal_by_payment,
        ledger_by_payment=ledger_by_payment,
        active_bank_accounts=active_bank_accounts,
        today_date=date.today().isoformat(),
        supplier_payment_form_idempotency_key=uuid4().hex,
        aging=supplier_bill_aging_stage(bill, date.today()),
        supplier_payment_attachments=supplier_payment_attachments,
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
        format_file_size=format_file_size,
    )


@finance_bp.route("/supplier-bills/<int:bill_id>/payments/create", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_supplier_bill_payment(bill_id):
    from datetime import datetime
    from app.extensions import db
    from app.models.finance import BankAccount, SupplierBill
    from app.models.accounting import Journal
    from app.services.accounts_payable_service import create_supplier_payment_for_bill
    from app.services.accounting_service import create_supplier_payment_journal_for_payment
    from app.services.cash_bank_service import create_supplier_payment_cash_bank_transaction

    bill = SupplierBill.query.get_or_404(bill_id)

    if bill.branch_id != current_user.branch_id:
        flash("Data hutang supplier tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.supplier_bills"))

    if float(bill.remaining_amount or 0) <= 0 or str(bill.status or "").upper() == "PAID":
        flash("Supplier bill ini sudah lunas.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    procurement_journal = Journal.query.filter_by(
        reference_type="PROCUREMENT",
        reference_id=bill.procurement_id,
    ).first()

    if not procurement_journal:
        flash("Jurnal pembelian sumber belum ada. Sinkronkan jurnal pembelian dulu sebelum membayar hutang supplier.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    payment_date_raw = (request.form.get("payment_date") or "").strip()
    payment_method = (request.form.get("payment_method") or "").strip().upper()
    bank_account_id_raw = (request.form.get("bank_account_id") or "").strip()
    amount_raw = (request.form.get("amount") or "").strip()
    reference_number = (request.form.get("reference_number") or "").strip()
    notes = (request.form.get("notes") or "").strip()

    try:
        payment_date = datetime.strptime(payment_date_raw, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4906")
        flash("Tanggal pembayaran hutang supplier tidak valid.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    if payment_date > datetime.now().date():
        flash("Tanggal pembayaran hutang supplier tidak boleh lebih dari hari ini.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    if payment_method not in ["CASH", "TRANSFER"]:
        flash("Metode pembayaran hutang supplier tidak valid.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    bank_account_id = None

    if payment_method == "TRANSFER":
        if not bank_account_id_raw:
            flash("Pembayaran supplier via transfer wajib memilih rekening bank keluar.", "warning")
            return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

        try:
            bank_account_id = int(bank_account_id_raw)
        except (TypeError, ValueError):
            flash("Rekening bank keluar tidak valid.", "warning")
            return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

        bank_account = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=current_user.branch_id,
            is_active=True,
        ).first()

        if not bank_account:
            flash("Rekening bank keluar tidak ditemukan atau tidak aktif.", "warning")
            return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    try:
        amount = _parse_payment_amount(amount_raw)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4943")
        flash("Nominal pembayaran hutang supplier tidak valid.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    idempotency_key = (request.form.get("idempotency_key") or "").strip() or uuid4().hex
    try:
        idempotency_record, reserved = reserve_idempotency_key(
            scope="FINANCE_SUPPLIER_PAYMENT_CREATE",
            key=idempotency_key,
            branch_id=current_user.branch_id,
            user_id=current_user.id,
            request_payload={
                "bill_id": bill.id,
                "payment_date": payment_date.isoformat(),
                "payment_method": payment_method,
                "bank_account_id": bank_account_id,
                "amount": str(amount),
                "reference_number": reference_number,
                "notes": notes,
            },
        )
    except IdempotencyConflictError:
        flash("Submit pembayaran supplier berbeda memakai idempotency key yang sama. Muat ulang bill lalu coba lagi.", "warning")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    if not reserved:
        flash("Submit pembayaran supplier ini sudah pernah diproses.", "info")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    try:
        proof_file = request.files.get("proof_file")
        proof_uploaded = False

        with atomic_business_action(
            module="FINANCE",
            action="SUPPLIER_PAYMENT_CREATE",
            description=f"Create payment supplier bill {bill.bill_number} + jurnal + ledger + bukti secara atomic.",
            reference_type="supplier_payments",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"supplier_bill_id": bill.id, "amount": amount, "method": payment_method},
        ) as atomic:
            _, _, supplier_payment = create_supplier_payment_for_bill(
                bill=bill,
                payment_date=payment_date,
                payment_method=payment_method,
                amount=amount,
                paid_by=current_user.id,
                bank_account_id=bank_account_id,
                reference_number=reference_number,
                notes=notes,
                commit=False,
            )

            db.session.flush()

            create_supplier_payment_journal_for_payment(
                supplier_payment=supplier_payment,
                created_by=current_user.id,
                commit=False,
            )

            create_supplier_payment_cash_bank_transaction(
                supplier_payment=supplier_payment,
                created_by=current_user.id,
                commit=False,
            )

            db.session.flush()
            mark_idempotency_completed(
                idempotency_record,
                reference_type="SUPPLIER_PAYMENT",
                reference_id=supplier_payment.id,
                response_payload={"supplier_payment_id": supplier_payment.id, "bill_id": bill.id},
            )

            if proof_file and proof_file.filename:
                attachment = save_digital_attachment(
                    file_storage=proof_file,
                    module=SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
                    reference_type=SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
                    reference_id=supplier_payment.id,
                    attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_SUPPLIER",
                    branch_id=current_user.branch_id,
                    uploaded_by=current_user.id,
                    notes=request.form.get("proof_notes") or None,
                    commit=False,
                )
                atomic.track_attachment(attachment)
                proof_uploaded = True
                record_audit_log(
                    module="ATTACHMENT",
                    event_type="DIGITAL_ATTACHMENT_UPLOADED",
                    action="CREATE",
                    table_name="digital_attachments",
                    record_id=attachment.id,
                    description=f"Lampiran payment supplier diunggah secara atomic untuk {supplier_payment.payment_number}.",
                    metadata={
                        "module": SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
                        "reference_type": SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
                        "reference_id": supplier_payment.id,
                        "attachment_type": attachment.attachment_type,
                        "original_filename": attachment.original_filename,
                        "file_size": attachment.file_size,
                        "sha256": attachment.sha256_hash,
                        "atomic_guard": "PRODUCTION",
                    },
                    commit=False,
                )

        record_audit_log(
            module="FINANCE",
            event_type="SUPPLIER_PAYMENT_CREATED",
            action="CREATE",
            table_name="supplier_payments",
            record_id=supplier_payment.id,
            description=f"Pembayaran hutang supplier dicatat atomic: {supplier_payment.payment_number}.",
            metadata={"supplier_bill_id": bill.id, "amount": supplier_payment.amount, "method": supplier_payment.payment_method, "atomic_guard": "PRODUCTION"},
        )

        if proof_uploaded:
            flash("Bukti transfer/payment supplier berhasil diunggah dalam transaksi atomic.", "success")

        flash("Pembayaran hutang supplier berhasil disimpan, jurnal otomatis dicatat, dan ledger kas/bank OUT dibuat.", "success")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5038")
        flash(f"Gagal menyimpan pembayaran hutang supplier: {error}", "danger")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=bill.id))


@finance_bp.route("/supplier-payments/<int:payment_id>/attachments/upload", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def upload_supplier_payment_attachment(payment_id):
    supplier_payment = _supplier_payment_or_404(payment_id)

    proof_file = request.files.get("proof_file")
    try:
        save_digital_attachment(
            file_storage=proof_file,
            module=SUPPLIER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=SUPPLIER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=supplier_payment.id,
            attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_SUPPLIER",
            branch_id=current_user.branch_id,
            uploaded_by=current_user.id,
            notes=request.form.get("proof_notes") or None,
        )
        flash("Bukti transfer/payment supplier berhasil diunggah.", "success")
    except AttachmentValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5063")
        flash(f"Bukti transfer/payment supplier gagal diunggah: {exc}", "danger")

    return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))


@finance_bp.route("/supplier-payments/attachments/<int:attachment_id>/view")
@role_required("OWNER", "ADMIN", "FINANCE")
def view_supplier_payment_attachment(attachment_id):
    attachment, supplier_payment = _supplier_payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5076")
        flash(f"File bukti payment supplier tidak bisa dibuka: {exc}", "danger")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))

    return send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/supplier-payments/attachments/<int:attachment_id>/download")
@role_required("OWNER", "ADMIN", "FINANCE")
def download_supplier_payment_attachment(attachment_id):
    attachment, supplier_payment = _supplier_payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5095")
        flash(f"File bukti payment supplier tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/supplier-payments/attachments/<int:attachment_id>/delete", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def delete_supplier_payment_attachment(attachment_id):
    attachment, supplier_payment = _supplier_payment_attachment_or_404(attachment_id)
    note = (request.form.get("delete_note") or "Bukti payment supplier salah upload.").strip()
    soft_delete_attachment(attachment, deleted_by=current_user.id, note=note or None)
    flash("Bukti payment supplier berhasil dihapus lunak. File fisik tetap tersimpan untuk audit.", "success")
    return redirect(url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill_id))
