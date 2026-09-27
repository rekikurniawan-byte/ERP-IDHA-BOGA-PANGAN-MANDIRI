# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.routes.finance.invoice_communication_routes import build_invoice_whatsapp_context
from app.utils.terms import T

@finance_bp.route("/invoices/<int:invoice_id>")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_detail(invoice_id):
    from datetime import date
    from app.models.finance import InvoiceCollectionLog
    from app.models.master import ClientPic

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    payments = Payment.query.filter_by(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id
    ).order_by(
        Payment.payment_date.desc(),
        Payment.id.desc()
    ).all()

    collection_logs = InvoiceCollectionLog.query.filter_by(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id
    ).order_by(
        InvoiceCollectionLog.follow_up_date.desc(),
        InvoiceCollectionLog.id.desc()
    ).all()

    client_name = "-"
    mandor_name = "-"
    client_pics = []

    if invoice.client_id:
        client = Client.query.get(invoice.client_id)
        client_name = client.name if client else f"{T.client} ID {invoice.client_id}"

        client_pics = ClientPic.query.filter_by(
            client_id=invoice.client_id,
            is_active=True
        ).order_by(
            ClientPic.id.asc()
        ).all()

    if invoice.mandor_id:
        mandor = Mandor.query.get(invoice.mandor_id)
        mandor_name = mandor.name if mandor else f"{T.sub_client} ID {invoice.mandor_id}"

    official_identity = get_invoice_official_identity(invoice)
    whatsapp = build_invoice_whatsapp_context(invoice)
    manual_billing_batch = None
    manual_billing_source_refs = {}
    if getattr(invoice, "source_type", None) == "MANUAL_BILLING_RECAP":
        from app.services.manual_billing_service import get_manual_billing_batch_for_invoice
        manual_billing_batch = get_manual_billing_batch_for_invoice(invoice)
        for item in invoice.items:
            ref = _resolve_manual_billing_source_reference(
                getattr(item, "source_type", None),
                getattr(item, "source_id", None),
                current_user.branch_id,
            )
            if ref:
                manual_billing_source_refs[item.id] = ref
    from app.services.accounting_posting_status_service import build_single_source_posting_status
    posting_status = build_single_source_posting_status("INVOICE", invoice)

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc()
    ).all()

    payment_attachments = {
        payment.id: list_reference_attachments(
            module=CUSTOMER_PAYMENT_ATTACHMENT_MODULE,
            reference_type=CUSTOMER_PAYMENT_ATTACHMENT_REFERENCE,
            reference_id=payment.id,
            branch_id=current_user.branch_id,
        )
        for payment in payments
    }

    from app.services.billing_trace_service import build_invoice_billing_trace_context
    billing_trace = build_invoice_billing_trace_context(invoice)

    return render_template(
        "finance/invoice_detail.html",
        invoice=invoice,
        payments=payments,
        collection_logs=collection_logs,
        client_pics=client_pics,
        active_bank_accounts=active_bank_accounts,
        today_date=date.today().isoformat(),
        bill_to=get_invoice_bill_to(invoice),
        official_identity=official_identity,
        client_name=client_name,
        mandor_name=mandor_name,
        whatsapp=whatsapp,
        manual_billing_batch=manual_billing_batch,
        manual_billing_source_refs=manual_billing_source_refs,
        posting_status=posting_status,
        payment_attachments=payment_attachments,
        billing_trace=billing_trace,
        input_source_context=build_input_source_context(getattr(invoice, "input_source", None)),
        payment_form_idempotency_key=uuid4().hex,
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
        format_file_size=format_file_size,
    )


# === PATCH_GENERATE_CATERING_INVOICE ===
