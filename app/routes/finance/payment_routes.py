# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403

def _generate_payment_number(payment_date):
    from app.models.finance import Payment

    prefix = f"PAY-{payment_date.strftime('%Y%m%d')}"
    counter = Payment.query.filter(Payment.payment_number.like(f"{prefix}-%")).count() + 1

    while True:
        payment_number = f"{prefix}-{counter:03d}"
        existing = Payment.query.filter_by(payment_number=payment_number).first()

        if not existing:
            return payment_number

        counter += 1


def _parse_payment_amount(value):
    value = str(value or "").strip()

    if not value:
        return 0

    # Form number biasanya masuk tanpa pemisah ribuan.
    # Ini hanya jaga-jaga kalau user mengetik koma desimal.
    value = value.replace(",", ".")

    return float(value)


@finance_bp.route("/invoices/<int:invoice_id>/payments/create", methods=["POST"])
@limiter.limit("10 per minute", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_invoice_payment(invoice_id):
    from datetime import datetime
    from flask import request
    from app.extensions import db
    from app.models.finance import Invoice, Payment, BankAccount, SupplierBill, SupplierPayment

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    # HYGIENE5C_BLOCK_PAYMENT_CANCELLED
    if str(invoice.status or "").upper() in INVOICE_CANCELLED_STATUSES:
        flash("Invoice yang dibatalkan tidak bisa menerima pembayaran.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    if float(invoice.remaining_amount or 0) <= 0:
        flash("Invoice ini sudah lunas.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    payment_date_raw = request.form.get("payment_date", "").strip()
    payment_method = request.form.get("payment_method", "").strip()
    bank_account_id_raw = request.form.get("bank_account_id", "").strip()
    amount_raw = request.form.get("amount", "").strip()
    reference_number = request.form.get("reference_number", "").strip()
    notes = request.form.get("notes", "").strip()

    try:
        payment_date = datetime.strptime(payment_date_raw, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1674")
        flash("Tanggal pembayaran tidak valid.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    # RISK_VALIDATION_PAYMENT_DATE_STEP_RISK1B
    try:
        assert_not_future_date(payment_date, datetime.now().date(), label="Tanggal pembayaran")
        assert_date_not_before(payment_date, invoice.invoice_date, label="Tanggal pembayaran", reference_label="tanggal invoice")
        payment_method = validate_choice(payment_method, CUSTOMER_PAYMENT_METHODS, "Metode pembayaran")
    except BusinessRuleError as error:
        flash(str(error), "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    bank_account_id = None

    if payment_method == "TRANSFER":
        if not bank_account_id_raw:
            flash("Pembayaran transfer wajib memilih rekening bank penerima.", "warning")
            return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

        try:
            bank_account_id = int(bank_account_id_raw)
        except (TypeError, ValueError):
            flash("Rekening bank penerima tidak valid.", "warning")
            return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

        bank_account = BankAccount.query.filter_by(
            id=bank_account_id,
            branch_id=current_user.branch_id,
            is_active=True
        ).first()

        if not bank_account:
            flash("Rekening bank penerima tidak ditemukan atau tidak aktif.", "warning")
            return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    try:
        amount = _parse_payment_amount(amount_raw)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1712")
        flash("Nominal pembayaran tidak valid.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    if amount <= 0:
        flash("Nominal pembayaran harus lebih dari 0.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    current_remaining = float(invoice.remaining_amount or 0)

    try:
        amount = assert_payment_amount_not_over_remaining(amount, current_remaining, label="Nominal pembayaran")
    except BusinessRuleError as error:
        flash(str(error), "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    idempotency_key = (request.form.get("idempotency_key") or "").strip() or uuid4().hex
    try:
        idempotency_record, reserved = reserve_idempotency_key(
            scope="FINANCE_CUSTOMER_PAYMENT_CREATE",
            key=idempotency_key,
            branch_id=current_user.branch_id,
            user_id=current_user.id,
            request_payload={
                "invoice_id": invoice.id,
                "payment_date": payment_date.isoformat(),
                "payment_method": payment_method,
                "bank_account_id": bank_account_id,
                "amount": str(amount),
                "reference_number": reference_number,
                "notes": notes,
            },
        )
    except IdempotencyConflictError:
        flash("Submit pembayaran berbeda memakai idempotency key yang sama. Muat ulang invoice lalu coba lagi.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    if not reserved:
        flash("Submit pembayaran ini sudah pernah diproses.", "info")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    payment = Payment(
        payment_number=_generate_payment_number(payment_date),
        branch_id=current_user.branch_id,
        payment_date=payment_date,
        invoice_id=invoice.id,
        bank_account_id=bank_account_id,
        payment_method=payment_method,
        amount=amount,
        reference_number=reference_number or None,
        notes=notes or None,
        received_by=current_user.id
    )

    try:
        proof_file = request.files.get("proof_file")
        proof_uploaded = False

        with atomic_business_action(
            module="FINANCE",
            action="CUSTOMER_PAYMENT_CREATE",
            description=f"Create payment invoice {invoice.invoice_number} + jurnal + ledger + bukti secara atomic.",
            reference_type="payments",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "amount": amount, "method": payment_method},
        ) as atomic:
            db.session.add(payment)

            new_paid = float(invoice.paid_amount or 0) + amount
            new_remaining = float(invoice.total_amount or 0) - new_paid

            if new_remaining <= 0:
                new_remaining = 0

            invoice.status = resolve_invoice_status_after_payment(invoice.total_amount, new_paid)
            invoice.paid_amount = new_paid
            invoice.remaining_amount = new_remaining

            from app.services.manual_backfill_billing_service import sync_manual_backfill_batch_status_from_invoice
            sync_manual_backfill_batch_status_from_invoice(
                invoice,
                updated_by=current_user.id,
                commit=False,
            )

            # AUTO_JOURNAL_PAYMENT_STEP10F4B
            db.session.flush()

            from app.services.accounting_service import create_payment_journal_for_payment
            create_payment_journal_for_payment(
                payment=payment,
                created_by=current_user.id,
                commit=False
            )

            # PRODUCTION_CASH_BANK_LEDGER_CUSTOMER_PAYMENT
            from app.services.cash_bank_service import create_customer_payment_cash_bank_transaction
            create_customer_payment_cash_bank_transaction(
                payment=payment,
                created_by=current_user.id,
                commit=False
            )

            # AUTO_COLLECTION_LOG_PAYMENT_STEP12B2B
            from app.models.finance import InvoiceCollectionLog

            def _collection_money(value):
                try:
                    return f"Rp {float(value or 0):,.0f}".replace(",", ".")
                except Exception:
                    logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1797")
                    return "Rp 0"

            if invoice.status == "PAID" or float(invoice.remaining_amount or 0) <= 0:
                collection_status = "PAID"
                next_action = "Invoice sudah lunas. Tidak perlu follow up penagihan."
                response_note = (
                    f"Pembayaran {payment.payment_number} sebesar {_collection_money(payment.amount)} "
                    f"diterima melalui {payment.payment_method}. "
                    f"Invoice {invoice.invoice_number} sudah lunas."
                )
            else:
                collection_status = "PARTIAL"
                next_action = "Follow up pelunasan sisa piutang."
                response_note = (
                    f"Pembayaran {payment.payment_number} sebesar {_collection_money(payment.amount)} "
                    f"diterima melalui {payment.payment_method}. "
                    f"Sisa piutang invoice {invoice.invoice_number}: {_collection_money(invoice.remaining_amount)}."
                )

            if payment.reference_number:
                response_note += f" Referensi: {payment.reference_number}."

            if payment.notes:
                response_note += f" Catatan payment: {payment.notes}."

            collection_log = InvoiceCollectionLog(
                branch_id=current_user.branch_id,
                invoice_id=invoice.id,
                follow_up_date=payment.payment_date,
                channel="SYSTEM",
                contact_person="SYSTEM - Pembayaran Masuk",
                response_note=response_note,
                promise_date=None,
                next_action=next_action,
                collection_status=collection_status,
                created_by=current_user.id
            )

            db.session.add(collection_log)
            db.session.flush()
            mark_idempotency_completed(
                idempotency_record,
                reference_type="PAYMENT",
                reference_id=payment.id,
                response_payload={"payment_id": payment.id, "invoice_id": invoice.id},
            )

            if proof_file and proof_file.filename:
                attachment = save_digital_attachment(
                    file_storage=proof_file,
                    module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
                    reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
                    reference_id=payment.id,
                    attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_CUSTOMER",
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
                    description=f"Lampiran payment customer diunggah secara atomic untuk {payment.payment_number}.",
                    metadata={
                        "module": CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
                        "reference_type": CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
                        "reference_id": payment.id,
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
            event_type="CUSTOMER_PAYMENT_CREATED",
            action="CREATE",
            table_name="payments",
            record_id=payment.id,
            description=f"Pembayaran customer dicatat atomic: {payment.payment_number} untuk invoice {invoice.invoice_number}.",
            metadata={"payment_number": payment.payment_number, "invoice_id": invoice.id, "amount": payment.amount, "method": payment.payment_method, "atomic_guard": "PRODUCTION"},
        )

        if proof_uploaded:
            flash("Bukti transfer/payment customer berhasil diunggah dalam transaksi atomic.", "success")

        flash("Pembayaran invoice berhasil disimpan, jurnal otomatis dicatat, dan ledger kas/bank masuk dibuat.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1889")
        flash(f"Gagal menyimpan pembayaran invoice: {error}", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))


# === PATCH_PRINT_INVOICE_STEP11A1 ===
# === PATCH_PRINT_OPERASIONAL_STEP12D1 ===
