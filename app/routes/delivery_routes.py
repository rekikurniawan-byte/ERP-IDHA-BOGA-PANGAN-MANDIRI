import logging
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file
from flask_login import current_user
from app.extensions import db
from datetime import datetime

from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
from app.models.operational import DailyOrder
from app.services.delivery_service import (
    create_delivery_from_order,
    update_delivery_receipt,
    get_delivery_type_from_notes,
    create_shortage_replacement_delivery,
    get_shortage_replacement_delivery,
    cancel_delivery,
    get_pending_delivery_next_actions,
)
from app.services.delivery_sla_service import (
    calculate_delivery_detail_sla,
    calculate_delivery_sla_summary,
)

from app.services.digital_attachment_service import (
    AttachmentValidationError,
    format_file_size,
    get_allowed_extensions,
    get_attachment_file_path,
    get_attachment_or_none,
    get_max_upload_bytes,
    list_reference_attachments,
    save_digital_attachment,
    soft_delete_attachment,
)
from app.utils.decorators import role_required
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context
from app.services.atomic_transaction_service import atomic_business_action

logger = logging.getLogger(__name__)


delivery_bp = Blueprint("delivery", __name__, url_prefix="/delivery")


def _parse_delivery_sla_datetime(delivery, field_name):
    value = (request.form.get(field_name) or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(f"{delivery.delivery_date.isoformat()} {value}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _delivery_receipt_or_404(receipt_id):
    receipt = DeliveryReceipt.query.get_or_404(receipt_id)
    delivery = receipt.delivery_detail.delivery
    if delivery.branch_id != current_user.branch_id:
        abort(404)
    return receipt


def _delivery_attachment_or_404(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if not attachment or attachment.module != "DELIVERY" or attachment.reference_type != "DELIVERY_RECEIPT":
        abort(404)

    receipt = DeliveryReceipt.query.get(attachment.reference_id)
    if not receipt or receipt.delivery_detail.delivery.branch_id != current_user.branch_id:
        abort(404)

    return attachment, receipt


def _delivery_receipt_attachment_map(delivery):
    receipt_ids = [detail.receipt.id for detail in delivery.details if detail.receipt]
    if not receipt_ids:
        return {}

    result = {}
    for receipt_id in receipt_ids:
        result[receipt_id] = list_reference_attachments(
            module="DELIVERY",
            reference_type="DELIVERY_RECEIPT",
            reference_id=receipt_id,
            branch_id=delivery.branch_id,
        )
    return result


@delivery_bp.route("/")
@role_required("ADMIN", "PENGANTAR")
def index():
    deliveries = Delivery.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        Delivery.delivery_date.desc(),
        Delivery.id.desc()
    ).all()

    return render_template(
        "delivery/index.html",
        deliveries=deliveries,
        get_delivery_type_from_notes=get_delivery_type_from_notes
    )


@delivery_bp.route("/<int:delivery_id>")
@role_required("ADMIN", "PENGANTAR")
def detail(delivery_id):
    delivery = Delivery.query.get_or_404(delivery_id)

    if delivery.branch_id != current_user.branch_id:
        flash("Data pengiriman tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("delivery.index"))

    shortage_replacement_map = {}

    for detail_item in delivery.details:
        if detail_item.receipt and detail_item.shortage_qty and detail_item.shortage_qty > 0:
            shortage_replacement_map[detail_item.id] = get_shortage_replacement_delivery(detail_item.id)

    can_cancel_delivery = (
        delivery.status not in ["CANCELLED", "DELIVERED"]
        and not any(detail_item.receipt for detail_item in delivery.details)
    )

    delivery_sla_summary = calculate_delivery_sla_summary(delivery)
    delivery_detail_sla_map = {
        detail_item.id: delivery_sla_summary["details"][idx]
        for idx, detail_item in enumerate(delivery.details)
    }

    return render_template(
        "delivery/detail.html",
        delivery=delivery,
        delivery_type=get_delivery_type_from_notes(delivery.notes),
        delivery_sla_summary=delivery_sla_summary,
        delivery_detail_sla_map=delivery_detail_sla_map,
        shortage_replacement_map=shortage_replacement_map,
        can_cancel_delivery=can_cancel_delivery,
        receipt_attachments_map=_delivery_receipt_attachment_map(delivery),
        format_file_size=format_file_size,
    )

@delivery_bp.route("/create-from-order/<int:order_id>/<delivery_type>", methods=["POST"])
@role_required("ADMIN", "PENGANTAR")
def create_from_order(order_id, delivery_type):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    success, message, delivery = create_delivery_from_order(
        daily_order=daily_order,
        delivery_type=delivery_type,
        created_by=current_user.id
    )

    flash(message, "success" if success else "warning")

    if delivery:
        return redirect(url_for("delivery.detail", delivery_id=delivery.id))

    return redirect(url_for("operational.order_detail", order_id=daily_order.id))




@delivery_bp.route("/<int:delivery_id>/dispatch", methods=["POST"])
@role_required("ADMIN", "PENGANTAR")
def mark_dispatch(delivery_id):
    delivery = Delivery.query.get_or_404(delivery_id)

    if delivery.branch_id != current_user.branch_id:
        flash("Data pengiriman tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("delivery.index"))

    if delivery.status == "CANCELLED":
        flash("Pengiriman yang dibatalkan tidak bisa diberangkatkan.", "warning")
        return redirect(url_for("delivery.detail", delivery_id=delivery.id))

    if delivery.status == "DELIVERED":
        flash("Pengiriman sudah diterima.", "info")
        return redirect(url_for("delivery.detail", delivery_id=delivery.id))

    try:
        with atomic_business_action(
            module="DELIVERY",
            action="DELIVERY_DISPATCH",
            description=f"Catat dispatch delivery #{delivery.id} secara atomic.",
            reference_type="deliveries",
            reference_id=delivery.id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"delivery_id": delivery.id, "old_status": delivery.status, "new_status": "ON_THE_WAY"},
        ):
            delivery.actual_departure_time = datetime.utcnow()
            delivery.status = "ON_THE_WAY"
        flash("Jam berangkat pengiriman berhasil dicatat.", "success")
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/delivery_routes.py:198")
        flash(f"Gagal mencatat jam berangkat pengiriman: {error}", "danger")
    return redirect(url_for("delivery.detail", delivery_id=delivery.id))


@delivery_bp.route("/<int:delivery_id>/sla", methods=["POST"])
@role_required("ADMIN")
def update_sla(delivery_id):
    delivery = Delivery.query.get_or_404(delivery_id)

    if delivery.branch_id != current_user.branch_id:
        flash("Data pengiriman tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("delivery.index"))

    target_dispatch = _parse_delivery_sla_datetime(delivery, "target_dispatch_time")
    target_arrival = _parse_delivery_sla_datetime(delivery, "target_arrival_time")
    tolerance_raw = (request.form.get("late_tolerance_minutes") or "15").strip()

    try:
        tolerance = int(tolerance_raw)
    except ValueError:
        tolerance = 15

    if tolerance < 0 or tolerance > 240:
        flash("Toleransi SLA harus 0 sampai 240 menit.", "warning")
        return redirect(url_for("delivery.detail", delivery_id=delivery.id))

    if not target_dispatch or not target_arrival:
        flash("Target dispatch dan target arrival wajib format HH:MM.", "warning")
        return redirect(url_for("delivery.detail", delivery_id=delivery.id))

    if target_arrival < target_dispatch:
        flash("Target arrival tidak boleh lebih awal dari target dispatch.", "warning")
        return redirect(url_for("delivery.detail", delivery_id=delivery.id))

    try:
        with atomic_business_action(
            module="DELIVERY",
            action="DELIVERY_SLA_UPDATE",
            description=f"Update SLA delivery #{delivery.id} secara atomic.",
            reference_type="deliveries",
            reference_id=delivery.id,
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"delivery_id": delivery.id, "late_tolerance_minutes": tolerance},
        ):
            delivery.target_dispatch_time = target_dispatch
            delivery.target_arrival_time = target_arrival
            delivery.late_tolerance_minutes = tolerance

        flash("Target jam tiba pengiriman berhasil diperbarui.", "success")
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/delivery_routes.py:249")
        flash(f"Gagal memperbarui target jam tiba: {error}", "danger")
    return redirect(url_for("delivery.detail", delivery_id=delivery.id))


@delivery_bp.route("/details/<int:detail_id>/receive", methods=["GET", "POST"])
@role_required("ADMIN", "PENGANTAR")
def receive(detail_id):
    delivery_detail = DeliveryDetail.query.get_or_404(detail_id)
    delivery = delivery_detail.delivery

    if delivery.branch_id != current_user.branch_id:
        flash("Data pengiriman tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("delivery.index"))

    if delivery.status == "CANCELLED":
        flash("Pengiriman sudah dibatalkan. Penerimaan tidak bisa dicatat.", "warning")
        return redirect(url_for("delivery.detail", delivery_id=delivery.id))

    w = request.args.get("w", type=int)
    n = request.args.get("n", type=int)
    from_scan = request.args.get("from_scan") == "1" or request.form.get("from_scan") == "1"

    if request.method == "POST":
        delivered_qty = request.form.get("delivered_qty")
        receiver_name = request.form.get("receiver_name")
        notes = request.form.get("notes")
        form_w = request.form.get("w")
        form_n = request.form.get("n")

        if not receiver_name:
            flash("Nama penerima wajib diisi.", "warning")
            redirect_args = {"detail_id": delivery_detail.id}
            if from_scan:
                redirect_args["from_scan"] = 1
            if form_w:
                redirect_args["w"] = form_w
            if form_n:
                redirect_args["n"] = form_n
            return redirect(url_for("delivery.receive", **redirect_args))

        success, message = update_delivery_receipt(
            delivery_detail=delivery_detail,
            delivered_qty=delivered_qty,
            receiver_name=receiver_name,
            notes=notes
        )

        if success:
            proof_file = request.files.get("proof_file")
            if proof_file and proof_file.filename:
                try:
                    save_digital_attachment(
                        file_storage=proof_file,
                        module="DELIVERY",
                        reference_type="DELIVERY_RECEIPT",
                        reference_id=delivery_detail.receipt.id,
                        attachment_type=request.form.get("proof_type") or "FOTO_TERIMA",
                        branch_id=delivery.branch_id,
                        uploaded_by=current_user.id,
                        notes=request.form.get("proof_notes") or None,
                    )
                    flash("Bukti digital penerimaan berhasil diunggah.", "success")
                except AttachmentValidationError as exc:
                    flash(f"Penerimaan tersimpan, tapi bukti digital gagal diunggah: {exc}", "warning")
                except Exception as exc:
                    logger.exception("Suppressed unexpected exception in app/routes/delivery_routes.py:301")
                    flash(f"Penerimaan tersimpan, tapi bukti digital gagal diunggah: {exc}", "danger")

            # Jalur UMUM: begitu semua pengiriman pesanan diterima, invoice dibuat
            # otomatis dan langsung dipotong uang mukanya. Tanda terima tetap
            # tersimpan walau langkah ini gagal.
            from app.services.prepaid_order_service import invoice_after_delivery_receipt

            invoice, invoice_error = invoice_after_delivery_receipt(delivery_detail, current_user.id)
            if invoice_error:
                flash(invoice_error, "warning")
            elif invoice is not None:
                status_note = "lunas dari uang muka" if invoice.status == "PAID" else f"sisa tagihan Rp {float(invoice.remaining_amount or 0):,.0f}"
                flash(f"Invoice {invoice.invoice_number} dibuat otomatis, {status_note}.", "success")
                from app.services.prepaid_order_service import order_leftover_prepayment, rupiah

                leftover = order_leftover_prepayment(delivery_detail.daily_order_detail.daily_order, delivery_detail.mandor_id)
                if leftover > 0:
                    flash(
                        f"Uang muka pelanggan lebih {rupiah(leftover)} dari tagihan (kurang kirim tidak ditagih). "
                        "OWNER perlu mengembalikannya di Finance > Uang Muka.",
                        "warning",
                    )

            if from_scan:
                flash("Tersimpan. Scan label berikutnya.", "success")
                return redirect(url_for("delivery.scan"))

            flash(message, "success")
            return redirect(url_for("delivery.detail", delivery_id=delivery.id))

        flash(message, "warning")
        redirect_args = {"detail_id": delivery_detail.id}
        if from_scan:
            redirect_args["from_scan"] = 1
        if form_w:
            redirect_args["w"] = form_w
        if form_n:
            redirect_args["n"] = form_n
        return redirect(url_for("delivery.receive", **redirect_args))

    delivery_detail_sla = calculate_delivery_detail_sla(delivery_detail)

    from app.services.kitchen_recap_service import split_containers
    container_info_text = None
    if w and n:
        container_info_text = f"Wadah {w}/{n} — pesanan ini punya {n} wadah"
    elif delivery_detail.planned_qty:
        c_list = split_containers(delivery_detail.planned_qty)
        if len(c_list) > 1:
            container_info_text = f"Pesanan ini terdiri dari {len(c_list)} wadah"

    customer_name = "-"
    if delivery_detail.mandor:
        if delivery_detail.mandor.client:
            customer_name = delivery_detail.mandor.client.name
            if not getattr(delivery_detail.mandor, "is_direct_unit", False):
                customer_name += f" ({delivery_detail.mandor.name})"
        else:
            customer_name = delivery_detail.mandor.name

    default_receiver_name = delivery_detail.mandor.name if (delivery_detail.mandor and delivery_detail.mandor.name) else ""

    notes_type = get_delivery_type_from_notes(delivery_detail.delivery.notes)
    session_label = "Siang" if any(k in notes_type.upper() for k in ("LUNCH", "SIANG")) else ("Malam" if any(k in notes_type.upper() for k in ("DINNER", "MALAM")) else notes_type)

    return render_template(
        "delivery/receive.html",
        delivery_detail=delivery_detail,
        delivery_detail_sla=delivery_detail_sla,
        customer_name=customer_name,
        default_receiver_name=default_receiver_name,
        session_label=session_label,
        container_info_text=container_info_text,
        w=w,
        n=n,
        from_scan=from_scan,
        get_delivery_type_from_notes=get_delivery_type_from_notes,
        receipt_attachments=list_reference_attachments(
            module="DELIVERY",
            reference_type="DELIVERY_RECEIPT",
            reference_id=delivery_detail.receipt.id,
            branch_id=delivery.branch_id,
        ) if delivery_detail.receipt else [],
        allowed_extensions=sorted(get_allowed_extensions()),
        max_upload_mb=round(get_max_upload_bytes() / (1024 * 1024), 2),
        format_file_size=format_file_size,
    )


@delivery_bp.route("/details/<int:detail_id>/shortage-replacement", methods=["POST"])
@role_required("ADMIN", "PENGANTAR")
def create_shortage_replacement(detail_id):
    delivery_detail = DeliveryDetail.query.get_or_404(detail_id)
    delivery = delivery_detail.delivery

    if delivery.branch_id != current_user.branch_id:
        flash("Data pengiriman tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("delivery.index"))

    success, message, replacement_delivery = create_shortage_replacement_delivery(
        source_delivery_detail=delivery_detail,
        created_by=current_user.id
    )

    flash(message, "success" if success else "warning")

    if replacement_delivery:
        return redirect(url_for("delivery.detail", delivery_id=replacement_delivery.id))

    return redirect(url_for("delivery.detail", delivery_id=delivery.id))



@delivery_bp.route("/receipts/<int:receipt_id>/attachments/upload", methods=["POST"])
@role_required("ADMIN", "PENGANTAR")
def upload_receipt_attachment(receipt_id):
    receipt = _delivery_receipt_or_404(receipt_id)
    delivery = receipt.delivery_detail.delivery

    proof_file = request.files.get("proof_file")
    try:
        save_digital_attachment(
            file_storage=proof_file,
            module="DELIVERY",
            reference_type="DELIVERY_RECEIPT",
            reference_id=receipt.id,
            attachment_type=request.form.get("proof_type") or "FOTO_TERIMA",
            branch_id=delivery.branch_id,
            uploaded_by=current_user.id,
            notes=request.form.get("proof_notes") or None,
        )
        flash("Bukti digital penerimaan berhasil diunggah.", "success")
    except AttachmentValidationError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/delivery_routes.py:370")
        flash(f"Bukti digital gagal diunggah: {exc}", "danger")

    return redirect(url_for("delivery.receive", detail_id=receipt.delivery_detail_id))


@delivery_bp.route("/attachments/<int:attachment_id>/view")
@role_required("ADMIN", "PENGANTAR")
def view_attachment(attachment_id):
    attachment, receipt = _delivery_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/delivery_routes.py:383")
        flash(f"File bukti digital tidak bisa dibuka: {exc}", "danger")
        return redirect(url_for("delivery.detail", delivery_id=receipt.delivery_detail.delivery_id))

    return send_file(
        str(file_path),
        as_attachment=False,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@delivery_bp.route("/attachments/<int:attachment_id>/download")
@role_required("ADMIN", "PENGANTAR")
def download_attachment(attachment_id):
    attachment, receipt = _delivery_attachment_or_404(attachment_id)

    try:
        file_path = get_attachment_file_path(attachment)
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/delivery_routes.py:402")
        flash(f"File bukti digital tidak bisa diunduh: {exc}", "danger")
        return redirect(url_for("delivery.detail", delivery_id=receipt.delivery_detail.delivery_id))

    return send_file(
        str(file_path),
        as_attachment=True,
        download_name=attachment.original_filename,
        mimetype=attachment.mime_type or "application/octet-stream",
    )


@delivery_bp.route("/attachments/<int:attachment_id>/delete", methods=["POST"])
@role_required("ADMIN")
def delete_attachment(attachment_id):
    attachment, receipt = _delivery_attachment_or_404(attachment_id)
    note = (request.form.get("delete_note") or "Bukti delivery salah upload.").strip()
    soft_delete_attachment(attachment, deleted_by=current_user.id, note=note or None)
    flash("Bukti digital pengiriman berhasil dihapus lunak. File fisik tetap tersimpan untuk audit.", "success")
    return redirect(url_for("delivery.receive", detail_id=receipt.delivery_detail_id))



# === PATCH_PENGANTAR_DELIVERY_PAGES ===
@delivery_bp.route("/today")
@role_required("ADMIN", "PENGANTAR")
def today():
    from datetime import date, datetime

    selected_date_text = request.args.get("date") or date.today().isoformat()

    try:
        selected_date = datetime.strptime(selected_date_text, "%Y-%m-%d").date()
    except ValueError:
        selected_date = date.today()
        selected_date_text = selected_date.isoformat()

    deliveries = Delivery.query.filter_by(
        branch_id=current_user.branch_id,
        delivery_date=selected_date
    ).order_by(
        Delivery.id.desc()
    ).all()

    delivery_next_actions = get_pending_delivery_next_actions(
        branch_id=current_user.branch_id,
        target_date=selected_date,
        limit=6,
    )

    return render_template(
        "delivery/today.html",
        deliveries=deliveries,
        selected_date=selected_date,
        selected_date_text=selected_date_text,
        get_delivery_type_from_notes=get_delivery_type_from_notes,
        calculate_delivery_sla_summary=calculate_delivery_sla_summary,
        delivery_next_actions=delivery_next_actions,
    )


@delivery_bp.route("/receiving")
@role_required("ADMIN", "PENGANTAR")
def receiving():
    from datetime import date, datetime

    selected_date_text = request.args.get("date") or date.today().isoformat()

    try:
        selected_date = datetime.strptime(selected_date_text, "%Y-%m-%d").date()
    except ValueError:
        selected_date = date.today()
        selected_date_text = selected_date.isoformat()

    details = DeliveryDetail.query.join(Delivery).filter(
        Delivery.branch_id == current_user.branch_id,
        Delivery.delivery_date == selected_date,
        Delivery.status != "CANCELLED"
    ).order_by(
        Delivery.id.desc(),
        DeliveryDetail.id.asc()
    ).all()

    pending_details = [
        detail for detail in details
        if not detail.receipt
    ]

    received_details = [
        detail for detail in details
        if detail.receipt
    ]

    return render_template(
        "delivery/receiving.html",
        pending_details=pending_details,
        received_details=received_details,
        selected_date=selected_date,
        selected_date_text=selected_date_text,
        get_delivery_type_from_notes=get_delivery_type_from_notes
    )

@delivery_bp.route("/history")
@role_required("ADMIN", "PENGANTAR")
def history():
    from datetime import date

    status_filter = request.args.get("status") or "ALL"
    date_state = resolve_date_filter(
        request.args,
        start_key="date_from",
        end_key="date_to",
        default_preset="all",
    )
    date_from = date_state.start_date
    date_to = date_state.end_date
    date_from_text = date_state.start_value
    date_to_text = date_state.end_value

    all_deliveries = Delivery.query.filter_by(
        branch_id=current_user.branch_id
    ).order_by(
        Delivery.delivery_date.desc(),
        Delivery.id.desc()
    ).all()

    deliveries = []

    for delivery in all_deliveries:
        if status_filter != "ALL" and delivery.status != status_filter:
            continue

        if date_from and delivery.delivery_date < date_from:
            continue

        if date_to and delivery.delivery_date > date_to:
            continue

        # Kalau tidak ada filter tanggal, riwayat fokus ke delivery selesai/cancelled/masa lalu.
        if not date_from and not date_to:
            if delivery.status not in ["DELIVERED", "CANCELLED"] and delivery.delivery_date >= date.today():
                continue

        deliveries.append(delivery)

    return render_template(
        "delivery/history.html",
        deliveries=deliveries,
        status_filter=status_filter,
        date_from_text=date_from_text,
        date_to_text=date_to_text,
        get_delivery_type_from_notes=get_delivery_type_from_notes,
        calculate_delivery_sla_summary=calculate_delivery_sla_summary,
        filter_bar=build_filter_bar_context(
            state=date_state,
            action_url=url_for("delivery.history"),
            reset_url=url_for("delivery.history"),
            title="Filter Riwayat Delivery",
            description="Custom tanggal dan status delivery untuk audit pengiriman.",
            start_name="date_from",
            end_name="date_to",
            status_name="status",
            status_value=status_filter,
            status_options=[
                {"value": "ALL", "label": "Semua Status"},
                {"value": "DRAFT", "label": "DRAFT"},
                {"value": "DISPATCHED", "label": "DISPATCHED"},
                {"value": "DELIVERED", "label": "DELIVERED"},
                {"value": "CANCELLED", "label": "CANCELLED"},
            ],
        )
    )



# === PATCH_CANCEL_DELIVERY_ROUTE ===
@delivery_bp.route("/<int:delivery_id>/cancel", methods=["POST"])
@role_required("ADMIN", "PENGANTAR")
def cancel(delivery_id):
    delivery = Delivery.query.get_or_404(delivery_id)

    if delivery.branch_id != current_user.branch_id:
        flash("Data pengiriman tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("delivery.index"))

    reason = request.form.get("cancel_reason") or "Delivery dibatalkan sebelum penerimaan."

    success, message = cancel_delivery(
        delivery=delivery,
        cancelled_by=current_user.id,
        reason=reason
    )

    flash(message, "success" if success else "warning")
    return redirect(url_for("delivery.detail", delivery_id=delivery.id))



@delivery_bp.route("/scan", methods=["GET"])
@role_required("OWNER", "ADMIN", "PENGANTAR")
def scan():
    return render_template("delivery/scan.html")


@delivery_bp.route("/scan/<int:daily_order_detail_id>/<string:sesi>")
@role_required("OWNER", "ADMIN", "PENGANTAR")
def scan_qr(daily_order_detail_id, sesi):

    from app.models.operational import DailyOrderDetail
    detail = db.session.get(DailyOrderDetail, daily_order_detail_id)
    if not detail or not detail.daily_order:
        flash("Data pesanan tidak ditemukan.", "danger")
        return redirect(url_for("delivery.scan"))

    if detail.daily_order.branch_id != current_user.branch_id:
        flash("Data pesanan tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("delivery.scan"))

    norm_sesi = "LUNCH" if (sesi or "").strip().upper() in ("LUNCH", "SIANG") else "DINNER"

    delivery_detail = (
        DeliveryDetail.query.join(Delivery)
        .filter(
            DeliveryDetail.daily_order_detail_id == daily_order_detail_id,
            Delivery.status != "CANCELLED",
            db.or_(
                Delivery.notes.like(f"%delivery_type={norm_sesi}%"),
                Delivery.delivery_number.like(f"%{norm_sesi}%"),
            ),
        )
        .first()
    )

    if not delivery_detail:
        delivery_detail = (
            DeliveryDetail.query.join(Delivery)
            .filter(
                DeliveryDetail.daily_order_detail_id == daily_order_detail_id,
                Delivery.status != "CANCELLED",
            )
            .first()
        )

    if not delivery_detail:
        flash("Pengiriman untuk pesanan ini belum dibuat oleh admin. Hubungi admin atau koordinator pengiriman.", "warning")
        return redirect(url_for("delivery.scan"))

    w = request.args.get("w")
    n = request.args.get("n")
    kwargs = {"detail_id": delivery_detail.id, "from_scan": 1}
    if w:
        kwargs["w"] = w
    if n:
        kwargs["n"] = n

    return redirect(url_for("delivery.receive", **kwargs))
