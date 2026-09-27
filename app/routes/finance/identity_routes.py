# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.utils.terms import T

@finance_bp.route("/invoices/<int:invoice_id>/official-identity/refresh", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def refresh_invoice_official_identity(invoice_id):
    invoice = Invoice.query.get_or_404(invoice_id)
    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    if not invoice.client_id:
        flash(f"Invoice ini belum terkait {T.client_lower}.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    client = Client.query.get(invoice.client_id)
    client_pic_id = request.form.get("client_pic_id", type=int)
    client_pic, error = get_required_client_pic(invoice.client_id, client_pic_id)
    if error:
        flash(error, "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    refresh_invoice_identity_snapshot_record(
        invoice,
        client=client,
        client_pic=client_pic,
        branch_id=current_user.branch_id,
    )

    flash(f"Identitas resmi invoice, PIC {T.client_lower}, dan snapshot rekening pembayaran berhasil dikunci ulang.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
