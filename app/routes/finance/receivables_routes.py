"""Receivables and customer payment routes.

Route functions moved out of app.routes.finance_routes without changing URL rules or endpoint names.
"""
from app.routes.finance_routes import *  # noqa: F401,F403
from app.routes.finance.ar_dashboard_routes import _build_receivables_dashboard_context, build_invoice_ar_warning
from app.routes.finance_routes import (
    _payment_attachment_or_404,
    _payment_or_404,
)
from app.utils.terms import T


@finance_bp.route("/receivables")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables():
    context = _build_receivables_dashboard_context(request.args)
    return render_template("finance/receivables_dashboard.html", **context)


@finance_bp.route("/receivables/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables_print():
    context = _build_receivables_dashboard_context(request.args)
    return render_template("finance/receivables_print.html", **context)

# === PATCH_SOA_STEP13A1 ===
@finance_bp.route("/receivables/statement")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables_statement():
    from datetime import date
    from urllib.parse import quote
    # SOA5B_IMPORT_PAYMENT
    from app.models.finance import Invoice, InvoiceCollectionLog, Payment
    from app.models.master import Client, Mandor, ClientPic

    # SOA2C2_HELPERS_IN_RECEIVABLES_STATEMENT
    def _soa_money(value):
        try:
            return f"Rp {float(value or 0):,.0f}".replace(",", ".")
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3113")
            return "Rp 0"

    def _soa_date(value):
        if not value:
            return "-"

        try:
            return value.strftime("%d-%m-%Y")
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3122")
            return str(value)

    def _soa_normalize_whatsapp(phone):
        raw = str(phone or "").strip()

        if not raw:
            return ""

        cleaned = ""

        for char in raw:
            if char.isdigit():
                cleaned += char

        if not cleaned:
            return ""

        if cleaned.startswith("0"):
            cleaned = "62" + cleaned[1:]

        if cleaned.startswith("8"):
            cleaned = "62" + cleaned

        return cleaned

    def _soa_build_message(group):
        target_name = group.get("wa_target_name") or "PIC Finance"
        client_name = group.get("client_name") or "-"
        rows = group.get("rows") or []

        lines = []

        lines.append("Yth. " + target_name + ",")
        lines.append("")
        lines.append("Berikut kami sampaikan Statement of Account / rekap piutang aktif PT Idha Boga Pangan Mandiri.")
        lines.append("")
        lines.append(f"{T.client}: " + client_name)
        lines.append("Tanggal Rekap: " + _soa_date(date.today()))
        lines.append("")
        lines.append("Ringkasan Piutang:")
        lines.append("- Total Tagihan: " + _soa_money(group.get("total_amount")))
        lines.append("- Sudah Dibayar: " + _soa_money(group.get("paid_amount")))
        lines.append("- Sisa Piutang: " + _soa_money(group.get("remaining_total")))
        lines.append("")
        lines.append("Detail Invoice:")

        for idx, row in enumerate(rows, start=1):
            invoice = row.get("invoice")
            ar = row.get("ar") or {}
            latest_log = row.get("latest_log")

            lines.append(
                f"{idx}. {invoice.invoice_number} | Jatuh Tempo: {_soa_date(invoice.due_date)} | "
                f"Total: {_soa_money(invoice.total_amount)} | Dibayar: {_soa_money(invoice.paid_amount)} | "
                f"Sisa: {_soa_money(invoice.remaining_amount)} | Status: {invoice.status} | "
                f"Catatan: {ar.get('stage_label') or '-'}"
            )

            if latest_log:
                lines.append(
                    f"   Follow up terakhir: {latest_log.collection_status} pada {_soa_date(latest_log.follow_up_date)} "
                    f"oleh {latest_log.contact_person or '-'}"
                )

        lines.append("")
        lines.append(f"Mohon konfirmasi jadwal pelunasan atau informasi proses pembayaran dari pihak {T.client_lower}.")
        lines.append("")
        lines.append("Terima kasih.")

        return "\n".join(lines)

    selected_client_id = (request.args.get("client_id") or "").strip()
    date_filter = resolve_date_filter(request.args, default_preset="all")

    active_query = Invoice.query.filter(
        Invoice.branch_id == current_user.branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"])
    )

    all_active_invoices = active_query.order_by(
        Invoice.client_id.asc(),
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    client_stats = {}

    for invoice in all_active_invoices:
        if invoice.client_id:
            client = Client.query.get(invoice.client_id)
            client_key = str(invoice.client_id)
            client_name = client.name if client else f"{T.client} ID {invoice.client_id}"
        else:
            client_key = "NO_CLIENT"
            client_name = f"Tanpa {T.client} / {T.sub_client}"

        if client_key not in client_stats:
            client_stats[client_key] = {
                "value": client_key,
                "label": client_name,
                "invoice_count": 0,
                "total_amount": 0,
                "paid_amount": 0,
                "remaining_total": 0
            }

        client_stats[client_key]["invoice_count"] += 1
        client_stats[client_key]["total_amount"] += float(invoice.total_amount or 0)
        client_stats[client_key]["paid_amount"] += float(invoice.paid_amount or 0)
        client_stats[client_key]["remaining_total"] += float(invoice.remaining_amount or 0)

    client_options = sorted(
        client_stats.values(),
        key=lambda row: row["label"].lower()
    )

    selected_client_name = ""

    statement_query = Invoice.query.filter(
        Invoice.branch_id == current_user.branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"])
    )
    statement_query = apply_date_range_to_query(statement_query, Invoice.due_date, date_filter)

    if selected_client_id:
        if selected_client_id == "NO_CLIENT":
            statement_query = statement_query.filter(Invoice.client_id.is_(None))
            selected_client_name = f"Tanpa {T.client} / {T.sub_client}"
        else:
            try:
                selected_client_int = int(selected_client_id)
            except Exception:
                logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3256")
                selected_client_int = None

            if not selected_client_int:
                flash(f"Filter {T.client_lower} tidak valid.", "warning")
                return redirect(url_for("finance.receivables_statement"))

            statement_query = statement_query.filter(Invoice.client_id == selected_client_int)

            selected_client = Client.query.get(selected_client_int)
            selected_client_name = selected_client.name if selected_client else f"{T.client} ID {selected_client_int}"

    invoices = statement_query.order_by(
        Invoice.client_id.asc(),
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    grouped = {}

    for invoice in invoices:
        client = Client.query.get(invoice.client_id) if invoice.client_id else None
        mandor = Mandor.query.get(invoice.mandor_id) if invoice.mandor_id else None

        if client:
            client_key = str(client.id)
            client_name = client.name or f"{T.client} ID {client.id}"
            client_address = client.address or "-"
            client_phone = client.phone or "-"
            pics = ClientPic.query.filter_by(
                client_id=client.id,
                is_active=True
            ).order_by(
                ClientPic.id.asc()
            ).all()
        else:
            client_key = "NO_CLIENT"
            client_name = f"Tanpa {T.client} / {T.sub_client}"
            client_address = "-"
            client_phone = "-"
            pics = []

        # SOA2B_TARGET_WHATSAPP_GROUP
        selected_pic = None

        for pic in pics:
            if not selected_pic and pic.phone:
                selected_pic = pic

        if selected_pic:
            wa_target_source = "PIC_CLIENT"
            wa_target_name = selected_pic.name or client_name
            wa_target_phone = selected_pic.phone or ""
        elif client_phone and client_phone != "-":
            wa_target_source = "CLIENT_PHONE_FALLBACK"
            wa_target_name = client_name
            wa_target_phone = client_phone
        else:
            wa_target_source = "NO_PHONE"
            wa_target_name = client_name
            wa_target_phone = ""

        wa_number = _soa_normalize_whatsapp(wa_target_phone)

        if client_key not in grouped:
            grouped[client_key] = {
                "client_key": client_key,
                "client_name": client_name,
                "client_address": client_address,
                "client_phone": client_phone,
                "pics": pics,
                "wa_target_source": wa_target_source,
                "wa_target_name": wa_target_name,
                "wa_target_phone": wa_target_phone,
                "wa_number": wa_number,
                "soa_message": "",
                "soa_whatsapp_url": "",
                "rows": [],
                "invoice_count": 0,
                "total_amount": 0,
                "paid_amount": 0,
                "remaining_total": 0
            }

        # SOA5B_LATEST_PAYMENT_AND_FOLLOWUP
        latest_payment = Payment.query.filter_by(
            branch_id=current_user.branch_id,
            invoice_id=invoice.id
        ).order_by(
            Payment.payment_date.desc(),
            Payment.id.desc()
        ).first()

        latest_log = InvoiceCollectionLog.query.filter(
            InvoiceCollectionLog.branch_id == current_user.branch_id,
            InvoiceCollectionLog.invoice_id == invoice.id,
            InvoiceCollectionLog.channel != "SYSTEM"
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

        ar = build_invoice_ar_warning(invoice)

        row = {
            "invoice": invoice,
            "bill_to": get_invoice_bill_to(invoice),
            "mandor_name": mandor.name if mandor else "-",
            "latest_payment": latest_payment,
            "latest_log": latest_log,
            "ar": ar
        }

        grouped[client_key]["rows"].append(row)
        grouped[client_key]["invoice_count"] += 1
        grouped[client_key]["total_amount"] += float(invoice.total_amount or 0)
        grouped[client_key]["paid_amount"] += float(invoice.paid_amount or 0)
        grouped[client_key]["remaining_total"] += float(invoice.remaining_amount or 0)

    client_groups = sorted(
        grouped.values(),
        key=lambda row: row["remaining_total"],
        reverse=True
    )

    # SOA2B_BUILD_MESSAGE_URL
    for group in client_groups:
        message = _soa_build_message(group)
        group["soa_message"] = message

        if group.get("wa_number"):
            group["soa_whatsapp_url"] = f"https://wa.me/{group['wa_number']}?text={quote(message)}"
        else:
            group["soa_whatsapp_url"] = ""

    summary = {
        "generated_date": date.today(),
        "client_count": len(client_groups),
        "invoice_count": len(invoices),
        "total_amount": sum(float(invoice.total_amount or 0) for invoice in invoices),
        "paid_amount": sum(float(invoice.paid_amount or 0) for invoice in invoices),
        "remaining_total": sum(float(invoice.remaining_amount or 0) for invoice in invoices)
    }

    return render_template(
        "finance/receivables_statement.html",
        client_groups=client_groups,
        client_options=client_options,
        selected_client_id=selected_client_id,
        selected_client_name=selected_client_name,
        summary=summary,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("finance.receivables_statement"),
            reset_url=url_for("finance.receivables_statement"),
            title="Filter Statement Piutang",
            description=f"Custom tanggal jatuh tempo invoice dan {T.client_lower} yang ingin ditagih.",
            hidden_fields={"client_id": selected_client_id},
        )
    )

# SOA4B_STATEMENT_SENT_ROUTE
@finance_bp.route("/receivables/statement/send")
@role_required("OWNER", "ADMIN", "FINANCE")
def receivables_statement_send():
    from datetime import date
    from urllib.parse import quote
    from app.models.finance import Invoice
    from app.models.master import Client, Mandor, ClientPic

    def _soa_money(value):
        try:
            return f"Rp {float(value or 0):,.0f}".replace(",", ".")
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3429")
            return "Rp 0"

    def _soa_date(value):
        if not value:
            return "-"

        try:
            return value.strftime("%d-%m-%Y")
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3438")
            return str(value)

    def _soa_normalize_whatsapp(phone):
        cleaned = ""

        for char in str(phone or ""):
            if char.isdigit():
                cleaned += char

        if cleaned.startswith("0"):
            cleaned = "62" + cleaned[1:]

        if cleaned.startswith("8"):
            cleaned = "62" + cleaned

        return cleaned

    selected_client_id = (request.args.get("client_id") or "").strip()

    if not selected_client_id:
        flash(f"Pilih {T.client_lower} terlebih dahulu sebelum mengirim Statement of Account.", "warning")
        return redirect(url_for("finance.receivables_statement"))

    query = Invoice.query.filter(
        Invoice.branch_id == current_user.branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(["CANCELLED", "CANCELED"])
    )

    client = None
    client_name = f"Tanpa {T.client} / {T.sub_client}"
    client_phone = ""

    if selected_client_id == "NO_CLIENT":
        query = query.filter(Invoice.client_id.is_(None))
    else:
        try:
            client_id_int = int(selected_client_id)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3477")
            flash(f"Filter {T.client_lower} tidak valid.", "warning")
            return redirect(url_for("finance.receivables_statement"))

        client = Client.query.get(client_id_int)

        if not client:
            flash(f"Data {T.client_lower} tidak ditemukan.", "warning")
            return redirect(url_for("finance.receivables_statement"))

        client_name = client.name or f"{T.client} ID {client.id}"
        client_phone = client.phone or ""

        query = query.filter(Invoice.client_id == client.id)

    invoices = query.order_by(
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    if not invoices:
        flash(f"Tidak ada invoice piutang aktif untuk {T.client_lower} tersebut.", "info")
        return redirect(url_for("finance.receivables_statement", client_id=selected_client_id))

    pics = []
    if client:
        pics = ClientPic.query.filter_by(
            client_id=client.id,
            is_active=True
        ).order_by(
            ClientPic.id.asc()
        ).all()

    selected_pic = None

    for pic in pics:
        if not selected_pic and pic.phone:
            selected_pic = pic

    if selected_pic:
        target_source = "PIC_CLIENT"
        target_name = selected_pic.name or client_name
        target_phone = selected_pic.phone or ""
    elif client_phone:
        target_source = "CLIENT_PHONE_FALLBACK"
        target_name = client_name
        target_phone = client_phone
    else:
        target_source = "NO_PHONE"
        target_name = client_name
        target_phone = ""

    wa_number = _soa_normalize_whatsapp(target_phone)

    if not wa_number:
        flash(f"Nomor WhatsApp tujuan belum tersedia untuk {T.client_lower} ini.", "warning")
        return redirect(url_for("finance.receivables_statement", client_id=selected_client_id))

    rows = []
    total_amount = 0
    paid_amount = 0
    remaining_total = 0

    for invoice in invoices:
        mandor = Mandor.query.get(invoice.mandor_id) if invoice.mandor_id else None
        latest_log = InvoiceCollectionLog.query.filter_by(
            branch_id=current_user.branch_id,
            invoice_id=invoice.id
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

        ar = build_invoice_ar_warning(invoice)

        rows.append({
            "invoice": invoice,
            "mandor": mandor,
            "latest_log": latest_log,
            "ar": ar
        })

        total_amount += float(invoice.total_amount or 0)
        paid_amount += float(invoice.paid_amount or 0)
        remaining_total += float(invoice.remaining_amount or 0)

    lines = []

    lines.append("Yth. " + target_name + ",")
    lines.append("")
    lines.append("Berikut kami sampaikan Statement of Account / rekap piutang aktif PT Idha Boga Pangan Mandiri.")
    lines.append("")
    lines.append(f"{T.client}: " + client_name)
    lines.append("Tanggal Rekap: " + _soa_date(date.today()))
    lines.append("")
    lines.append("Ringkasan Piutang:")
    lines.append("- Total Tagihan: " + _soa_money(total_amount))
    lines.append("- Sudah Dibayar: " + _soa_money(paid_amount))
    lines.append("- Sisa Piutang: " + _soa_money(remaining_total))
    lines.append("")
    lines.append("Detail Invoice:")

    for index, row in enumerate(rows, start=1):
        invoice = row["invoice"]
        ar = row["ar"]
        latest_log = row["latest_log"]

        lines.append(
            f"{index}. {invoice.invoice_number} | Jatuh Tempo: {_soa_date(invoice.due_date)} | "
            f"Total: {_soa_money(invoice.total_amount)} | Dibayar: {_soa_money(invoice.paid_amount)} | "
            f"Sisa: {_soa_money(invoice.remaining_amount)} | Status: {invoice.status} | "
            f"Catatan: {ar.get('stage_label') or '-'}"
        )

        if latest_log:
            lines.append(
                f"   Follow up terakhir: {latest_log.collection_status} pada {_soa_date(latest_log.follow_up_date)} "
                f"oleh {latest_log.contact_person or '-'}"
            )

    lines.append("")
    lines.append(f"Mohon konfirmasi jadwal pelunasan atau informasi proses pembayaran dari pihak {T.client_lower}.")
    lines.append("")
    lines.append("Terima kasih.")

    message = "\n".join(lines)
    wa_url = f"https://wa.me/{wa_number}?text={quote(message)}"

    created_count = 0
    skipped_count = 0
    today = date.today()

    try:
        created_count, skipped_count = create_receivables_statement_logs(
            invoices=invoices,
            branch_id=current_user.branch_id,
            follow_up_date=today,
            contact_person=target_name,
            response_note_factory=lambda invoice: (
                f"Statement of Account / rekap piutang aktif {T.client_lower} {client_name} "
                f"dikirim melalui WhatsApp ke {target_name} ({target_phone}). "
                f"Target menggunakan {target_source}. "
                f"Total tagihan { _soa_money(total_amount) }, sudah dibayar { _soa_money(paid_amount) }, "
                f"sisa piutang { _soa_money(remaining_total) }."
            ),
            created_by=current_user.id,
        )

        if created_count > 0:
            record_audit_log(
                module="FINANCE",
                event_type="RECEIVABLES_STATEMENT_LOG_CREATED",
                action="CREATE",
                table_name="invoice_collection_logs",
                record_id=None,
                description=f"Statement of Account dicatat untuk {created_count} invoice {T.client_lower} {client_name}.",
                metadata={"client_id": selected_client_id, "client_name": client_name, "created_count": created_count, "skipped_count": skipped_count},
            )
            flash(f"Log Statement of Account berhasil dicatat untuk {created_count} invoice.", "success")
        else:
            flash("Statement of Account sudah pernah dicatat hari ini. Tidak dibuat log ganda.", "info")

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3639")
        flash(f"Gagal mencatat log Statement of Account: {error}", "danger")
        return redirect(url_for("finance.receivables_statement", client_id=selected_client_id))

    return redirect(wa_url)

# RECEIPT1B_PAYMENT_RECEIPT_ROUTE
@finance_bp.route("/payments/<int:payment_id>/receipt")
@role_required("OWNER", "ADMIN", "FINANCE")
def payment_receipt(payment_id):
    from app.models.finance import Invoice, Payment
    from app.models.master import Client, Mandor, ClientPic
    from app.models.accounting import Journal, JournalDetail

    payment = Payment.query.get_or_404(payment_id)
    invoice = Invoice.query.get_or_404(payment.invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data pembayaran tidak sesuai cabang aktif.", "danger")
        return redirect(url_for("finance.invoices"))

    client = Client.query.get(invoice.client_id) if invoice.client_id else None
    mandor = Mandor.query.get(invoice.mandor_id) if invoice.mandor_id else None

    client_pics = []
    if client:
        client_pics = ClientPic.query.filter_by(
            client_id=client.id,
            is_active=True
        ).order_by(
            ClientPic.id.asc()
        ).all()

    journal = Journal.query.filter_by(
        reference_type="PAYMENT",
        reference_id=payment.id
    ).order_by(
        Journal.id.desc()
    ).first()

    journal_details = []

    if journal:
        journal_details = JournalDetail.query.filter_by(
            journal_id=journal.id
        ).order_by(
            JournalDetail.id.asc()
        ).all()

    company_settings = get_company_settings(current_user.branch_id)

    payment_attachments = list_reference_attachments(
        module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
        reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
        reference_id=payment.id,
        branch_id=current_user.branch_id,
    )

    receipt = {
        "receipt_number": payment.payment_number,
        "payment": payment,
        "invoice": invoice,
        "client": client,
        "mandor": mandor,
        "client_pics": client_pics,
        "journal": journal,
        "journal_details": journal_details,
        "company_name": company_settings.get("company_name"),
        "company_subtitle": company_settings.get("company_subtitle"),
        "company_address": company_settings.get("company_address"),
        "company_phone": company_settings.get("company_phone"),
        "company_email": company_settings.get("company_email"),
        "company_npwp": company_settings.get("company_npwp"),
        "invoice_authorized_name": company_settings.get("invoice_authorized_name"),
        "invoice_authorized_position": company_settings.get("invoice_authorized_position"),
        "received_from": client.name if client else (mandor.name if mandor else "-"),
        "for_invoice": invoice.invoice_number,
        "remaining_after_payment": invoice.remaining_amount,
    }

    return render_template(
        "finance/payment_receipt.html",
        receipt=receipt,
        payment=payment,
        invoice=invoice,
        client=client,
        mandor=mandor,
        client_pics=client_pics,
        journal=journal,
        journal_details=journal_details,
        company_settings=company_settings,
        payment_attachments=payment_attachments,
        format_file_size=format_file_size,
    )


@finance_bp.route("/payments/<int:payment_id>/attachments/upload", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def upload_customer_payment_attachment(payment_id):
    payment = _payment_or_404(payment_id)

    proof_file = request.files.get("proof_file")
    try:
        save_digital_attachment(
            file_storage=proof_file,
            module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=payment.id,
            attachment_type=request.form.get("proof_type") or "BUKTI_TRANSFER_CUSTOMER",
            branch_id=current_user.branch_id,
            uploaded_by=current_user.id,
            notes=request.form.get("proof_notes") or None,
        )
        flash("Bukti transfer/pembayaran pelanggan berhasil diunggah.", "success")
    except AttachmentValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3755")
        flash(f"Bukti transfer/pembayaran pelanggan gagal diunggah: {exc}", "danger")

    return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))


@finance_bp.route("/payments/attachments/<int:attachment_id>/view")
@role_required("OWNER", "ADMIN", "FINANCE")
def view_customer_payment_attachment(attachment_id):
    attachment, payment = _payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3768")
        flash(f"File bukti payment tidak bisa dibuka: {exc}", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))

    return send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/payments/attachments/<int:attachment_id>/download")
@role_required("OWNER", "ADMIN", "FINANCE")
def download_customer_payment_attachment(attachment_id):
    attachment, payment = _payment_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3787")
        flash(f"File bukti payment tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@finance_bp.route("/payments/attachments/<int:attachment_id>/delete", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def delete_customer_payment_attachment(attachment_id):
    attachment, payment = _payment_attachment_or_404(attachment_id)
    note = (request.form.get("delete_note") or "Bukti payment customer salah upload.").strip()
    soft_delete_attachment(attachment, deleted_by=current_user.id, note=note or None)
    flash("Bukti payment customer berhasil dihapus lunak. File fisik tetap tersimpan untuk audit.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=payment.invoice_id))


# FINANCE3B_PAYMENT_HISTORY_ROUTE
@finance_bp.route("/payment-history")
@role_required("OWNER", "ADMIN", "FINANCE")
def payment_history():
    # FINANCE3B_FINAL_LOCAL_JOURNAL_IMPORT
    from app.models.accounting import Journal
    from app.models.finance import CashBankTransaction
    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    method_filter = (request.args.get("payment_method") or "ALL").upper().strip()
    if method_filter not in ["ALL", "CASH", "TRANSFER", "QRIS"]:
        method_filter = "ALL"

    payment_query = Payment.query.filter(Payment.branch_id == current_user.branch_id)
    payment_query = apply_date_range_to_query(payment_query, Payment.payment_date, date_filter)
    if method_filter != "ALL":
        payment_query = payment_query.filter(Payment.payment_method == method_filter)

    payments = (
        payment_query
        .order_by(Payment.payment_date.desc(), Payment.id.desc())
        .all()
    )

    rows = []
    total_paid = 0

    for payment in payments:
        invoice = payment.invoice

        if not invoice:
            invoice = Invoice.query.filter_by(id=payment.invoice_id).first()

        client = None
        mandor = None

        if invoice and invoice.client_id:
            client = Client.query.filter_by(id=invoice.client_id).first()

        if invoice and invoice.mandor_id:
            mandor = Mandor.query.filter_by(id=invoice.mandor_id).first()

        journal = Journal.query.filter_by(
            reference_type="PAYMENT",
            reference_id=payment.id
        ).first()

        ledger_transaction = CashBankTransaction.query.filter_by(
            reference_type="PAYMENT",
            reference_id=payment.id
        ).first()

        amount = float(payment.amount or 0)
        total_paid += amount

        rows.append({
            "payment": payment,
            "invoice": invoice,
            "client": client,
            "mandor": mandor,
            "journal": journal,
            "ledger_transaction": ledger_transaction,
            "attachment_count": count_reference_attachments(
                module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
                reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
                reference_id=payment.id,
                branch_id=current_user.branch_id,
            ),
            "amount": amount,
        })

    return render_template(
        "finance/payment_history.html",
        rows=rows,
        total_paid=total_paid,
        filter_bar=build_filter_bar_context(
            state=date_filter,
            action_url=url_for("finance.payment_history"),
            reset_url=url_for("finance.payment_history"),
            title="Filter Pembayaran Invoice",
            description="Custom tanggal pembayaran dan metode masuk kas/bank.",
            status_name="payment_method",
            status_value=method_filter,
            status_options=[
                {"value": "ALL", "label": "Semua Metode"},
                {"value": "CASH", "label": "Cash"},
                {"value": "TRANSFER", "label": "Transfer"},
                {"value": "QRIS", "label": "QRIS"},
            ],
        ),
    )


