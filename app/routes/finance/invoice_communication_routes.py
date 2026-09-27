# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.utils.terms import T

def _normalize_whatsapp_number(phone):
    import re

    phone = str(phone or "").strip()
    phone = re.sub(r"[^0-9]", "", phone)

    if not phone:
        return ""

    if phone.startswith("0"):
        return "62" + phone[1:]

    if phone.startswith("8"):
        return "62" + phone

    return phone


def _format_money_for_whatsapp(value):
    try:
        return f"Rp {float(value or 0):,.0f}".replace(",", ".")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:2212")
        return "Rp 0"


def _build_invoice_whatsapp_message(invoice, target_name, mandor_name, company_name=None):
    periode = "-"

    if invoice.period_start and invoice.period_end:
        periode = f"{invoice.period_start.strftime('%d-%m-%Y')} s/d {invoice.period_end.strftime('%d-%m-%Y')}"

    company_name = company_name or "PT Idha Boga Pangan Mandiri"

    return f"""Yth. Bapak/Ibu {target_name},

Berikut kami sampaikan informasi tagihan dari {company_name}.

No Invoice      : {invoice.invoice_number}
Periode         : {periode}
Penanggung Jawab: {mandor_name}
Tanggal Invoice : {invoice.invoice_date.strftime('%d-%m-%Y')}
Jatuh Tempo     : {invoice.due_date.strftime('%d-%m-%Y')}

Total Tagihan   : {_format_money_for_whatsapp(invoice.total_amount)}
Sudah Dibayar   : {_format_money_for_whatsapp(invoice.paid_amount)}
Sisa Tagihan    : {_format_money_for_whatsapp(invoice.remaining_amount)}

Mohon dilakukan pengecekan tagihan. Apabila tagihan sudah sesuai, pembayaran dapat dilakukan sebelum tanggal jatuh tempo.

Cetakan invoice dapat kami kirimkan terpisah apabila diperlukan.

Terima kasih.
{company_name}"""


def build_invoice_whatsapp_context(invoice):
    from urllib.parse import quote

    target_name = "-"
    target_phone = ""
    target_source = "-"
    mandor_name = "-"

    client = None
    mandor = None

    if invoice.client_id:
        client = Client.query.get(invoice.client_id)

    if invoice.mandor_id:
        mandor = Mandor.query.get(invoice.mandor_id)
        if mandor:
            mandor_name = mandor.name or "-"

    # PRIORITAS BARU:
    # Invoice ke CLIENT akan dikirim ke PIC aktif yang punya nomor.
    # Kalau belum ada PIC aktif, fallback ke nomor umum client.
    if invoice.bill_to_type == "CLIENT" and client:
        active_pic = None

        try:
            from app.models.master import ClientPic

            active_pic = ClientPic.query.filter_by(
                client_id=client.id,
                is_active=True
            ).filter(
                ClientPic.phone.isnot(None),
                ClientPic.phone != ""
            ).order_by(
                ClientPic.id.asc()
            ).first()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:2283")
            active_pic = None

        if active_pic:
            target_name = active_pic.name or client.name or "-"
            target_phone = active_pic.phone or ""
            target_source = "PIC_CLIENT"
        else:
            target_name = client.name or "-"
            target_phone = client.phone or ""
            target_source = "CLIENT_PHONE_FALLBACK"

    elif invoice.bill_to_type == "MANDOR" and mandor:
        target_name = mandor.name or "-"
        target_phone = mandor.phone or ""
        target_source = "MANDOR"

    wa_number = _normalize_whatsapp_number(target_phone)

    if not wa_number:
        return {
            "url": "",
            "number": "",
            "target_name": target_name,
            "target_phone": target_phone,
            "target_source": target_source,
            "message": ""
        }

    company_settings = get_company_settings(invoice.branch_id)
    message = _build_invoice_whatsapp_message(
        invoice=invoice,
        target_name=target_name,
        mandor_name=mandor_name,
        company_name=company_settings.get("company_name")
    )

    return {
        "url": f"https://wa.me/{wa_number}?text={quote(message)}",
        "number": wa_number,
        "target_name": target_name,
        "target_phone": target_phone,
        "target_source": target_source,
        "message": message
    }



# === PATCH_COLLECTION_HISTORY_STEP12B1B ===
@finance_bp.route("/invoices/<int:invoice_id>/collection/create", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_invoice_collection_log(invoice_id):
    from datetime import datetime, date

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    # HYGIENE5C_BLOCK_COLLECTION_CANCELLED
    if str(invoice.status or "").upper() in ["CANCELLED", "CANCELED"]:
        flash("Invoice yang dibatalkan tidak perlu dicatat follow up penagihan.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    def parse_date(value, default=None):
        value = (value or "").strip()
        if not value:
            return default
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            return default

    allowed_channels = ["WHATSAPP", "PHONE", "EMAIL", "VISIT", "OTHER"]
    allowed_statuses = [
        "SENT",
        "UNPAID",
        "DUE_SOON",
        "OVERDUE",
        "FOLLOW_UP",
        "PROMISE_TO_PAY",
        "STATEMENT_SENT",
        "OFFICIAL_LETTER",
        "INSTALLMENT",
        "PARTIAL",
        "PAID",
        "OTHER"
    ]

    follow_up_date = parse_date(request.form.get("follow_up_date"), date.today())
    promise_date = parse_date(request.form.get("promise_date"), None)

    # RISK_VALIDATION_FOLLOW_UP_DATE_STEP_RISK1B
    if follow_up_date > date.today():
        flash("Tanggal follow up tidak boleh lebih dari hari ini.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    channel = (request.form.get("channel") or "WHATSAPP").strip().upper()
    if channel not in allowed_channels:
        channel = "OTHER"

    collection_status = (request.form.get("collection_status") or "FOLLOW_UP").strip().upper()
    if collection_status not in allowed_statuses:
        collection_status = "FOLLOW_UP"

    contact_person = (request.form.get("contact_person") or "").strip()
    response_note = (request.form.get("response_note") or "").strip()
    next_action = (request.form.get("next_action") or "").strip()

    if not response_note:
        flash(f"Catatan respon {T.client_lower} wajib diisi agar riwayat follow up jelas.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    log = create_invoice_collection_log_record(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id,
        follow_up_date=follow_up_date,
        channel=channel,
        contact_person=contact_person,
        response_note=response_note,
        promise_date=promise_date,
        next_action=next_action,
        collection_status=collection_status,
        created_by=current_user.id
    )

    record_audit_log(
        module="FINANCE",
        event_type="INVOICE_COLLECTION_LOG_CREATED",
        action="CREATE",
        table_name="invoice_collection_logs",
        record_id=log.id,
        description=f"Follow up invoice dicatat: {invoice.invoice_number} via {channel}.",
        metadata={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "channel": channel, "collection_status": collection_status},
    )

    flash("Riwayat follow up invoice berhasil dicatat.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))



# === PATCH_WA_SEND_COLLECTION_STEP12B2A ===
@finance_bp.route("/invoices/<int:invoice_id>/whatsapp/send")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_whatsapp_send(invoice_id):
    from datetime import date
    from flask import redirect, url_for, flash
    from app.models.finance import InvoiceCollectionLog

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    # HYGIENE5C_BLOCK_WA_CANCELLED
    if str(invoice.status or "").upper() in ["CANCELLED", "CANCELED"]:
        flash("Invoice yang dibatalkan tidak bisa dikirim sebagai tagihan WhatsApp.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    wa = build_invoice_whatsapp_context(invoice)

    if not wa.get("url"):
        flash("Nomor WhatsApp tujuan belum tersedia.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    today = date.today()
    target_name = wa.get("target_name") or "-"
    target_source = wa.get("target_source") or "-"
    target_phone = wa.get("target_phone") or "-"

    # Anti dobel:
    # Kalau hari ini sudah ada log SENT untuk invoice + PIC yang sama,
    # sistem tidak membuat log baru lagi.
    existing_log = InvoiceCollectionLog.query.filter_by(
        branch_id=current_user.branch_id,
        invoice_id=invoice.id,
        follow_up_date=today,
        channel="WHATSAPP",
        contact_person=target_name,
        collection_status="SENT"
    ).first()

    if not existing_log:
        note = (
            f"Invoice {invoice.invoice_number} dibuka untuk dikirim melalui WhatsApp "
            f"ke {target_name} ({target_phone})."
        )

        if target_source == "PIC_CLIENT":
            note += f" Target menggunakan PIC aktif {T.client_lower}."
        elif target_source == "CLIENT_PHONE_FALLBACK":
            note += f" Target menggunakan nomor umum {T.client_lower} karena PIC aktif belum tersedia."
        elif target_source == "MANDOR":
            note += f" Target menggunakan nomor {T.sub_client_lower}."

        log = create_invoice_collection_log_record(
            branch_id=current_user.branch_id,
            invoice_id=invoice.id,
            follow_up_date=today,
            channel="WHATSAPP",
            contact_person=target_name,
            response_note=note,
            promise_date=None,
            next_action="Follow up konfirmasi penerimaan invoice.",
            collection_status="SENT",
            created_by=current_user.id
        )

        record_audit_log(
            module="FINANCE",
            event_type="INVOICE_WHATSAPP_OPENED",
            action="CREATE",
            table_name="invoice_collection_logs",
            record_id=log.id,
            description=f"Invoice dibuka untuk dikirim via WhatsApp: {invoice.invoice_number}.",
            metadata={"invoice_id": invoice.id, "invoice_number": invoice.invoice_number, "target_name": target_name, "target_source": target_source},
        )

    return redirect(wa.get("url"))



# === PATCH_AR_WARNING_STEP12B3B ===
