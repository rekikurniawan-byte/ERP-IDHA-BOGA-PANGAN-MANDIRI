# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.services.mandor_invoice_helper_service import (
    calculate_realtime_locked_base_quantities,
    get_client_for_mandor_invoice,
)

def _period_parse_date(value):
    from datetime import datetime

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:913")
        return None


def _period_safe_label(obj):
    if not obj:
        return "-"

    for attr in ["name", "full_name", "mandor_name", "worker_name", "location_name", "item_name"]:
        value = getattr(obj, attr, None)
        if value:
            return str(value)

    return f"ID {getattr(obj, 'id', '-')}"


def _period_is_after_lock_increase(revision):
    revision_type = str(getattr(revision, "revision_type", "") or "").upper()
    direction = str(getattr(revision, "revision_direction", "") or "").upper()

    return direction == "INCREASE" and revision_type.startswith("AFTER_LOCK")


def _period_invoice_item_exists(source_type, source_id):
    from app.models.finance import InvoiceItem

    if not source_type or not source_id:
        return False

    return InvoiceItem.query.filter_by(
        source_type=source_type,
        source_id=source_id
    ).first() is not None


# PRODUCTION_INVOICE_PROFIT_REPORT_READONLY
@finance_bp.route("/invoice-profit-report")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_profit_report():
    from app.models.finance import Invoice
    from app.services.invoice_profit_service import build_invoice_profit_report_index

    start_value = request.args.get("start_date", "").strip()
    end_value = request.args.get("end_date", "").strip()

    start_date = _period_parse_date(start_value) if start_value else None
    end_date = _period_parse_date(end_value) if end_value else None

    if start_value and not start_date:
        flash("Tanggal awal filter profit invoice tidak valid.", "warning")
        start_value = ""

    if end_value and not end_date:
        flash("Tanggal akhir filter profit invoice tidak valid.", "warning")
        end_value = ""

    if start_date and end_date and start_date > end_date:
        flash("Tanggal awal tidak boleh lebih besar dari tanggal akhir.", "warning")
        start_date = None
        end_date = None
        start_value = ""
        end_value = ""

    report_index = build_invoice_profit_report_index(
        branch_id=current_user.branch_id,
        start_date=start_date,
        end_date=end_date,
    )

    rows = []

    for row in report_index["rows"]:
        invoice = row["invoice"]
        rows.append({
            "invoice": invoice,
            "summary": row["summary"],
            "bill_to": get_invoice_bill_to(invoice),
        })

    return render_template(
        "finance/invoice_profit_report.html",
        rows=rows,
        totals=report_index["totals"],
        start_value=start_value,
        end_value=end_value,
    )


@finance_bp.route("/invoices/<int:invoice_id>/profit-report")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_profit_detail(invoice_id):
    from app.services.invoice_profit_service import build_invoice_profit_report

    invoice = Invoice.query.get_or_404(invoice_id)

    if invoice.branch_id != current_user.branch_id:
        flash("Data invoice tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.invoices"))

    report = build_invoice_profit_report(invoice)

    return render_template(
        "finance/invoice_profit_detail.html",
        invoice=invoice,
        report=report,
        bill_to=get_invoice_bill_to(invoice),
    )


@finance_bp.route("/invoices/generate-period", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_period_invoice_preview():
    from datetime import date
    from flask import request
    from app.models.master import Client, Mandor
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice
    from app.models.canteen import WorkerDebt
    from app.services.canteen_service import get_debt_paid_amount, get_debt_remaining_amount

    mandor_query = Mandor.query

    if hasattr(Mandor, "branch_id"):
        mandor_query = mandor_query.filter_by(branch_id=current_user.branch_id)

    if hasattr(Mandor, "is_active"):
        mandor_query = mandor_query.filter_by(is_active=True)

    mandors = mandor_query.order_by(Mandor.id.asc()).all()

    today_value = date.today().strftime("%Y-%m-%d")

    selected_mandor_id = ""
    period_start_value = today_value
    period_end_value = today_value

    lines = []
    total_catering = 0
    total_revision = 0
    total_warung = 0
    grand_total = 0
    selected_mandor = None
    selected_client = None
    selected_client_error = None
    selected_client_pics = []
    preview_ready = False

    if request.method == "POST":
        selected_mandor_id = request.form.get("mandor_id", "").strip()
        period_start_value = request.form.get("period_start", "").strip()
        period_end_value = request.form.get("period_end", "").strip()

        period_start = _period_parse_date(period_start_value)
        period_end = _period_parse_date(period_end_value)

        if not selected_mandor_id:
            flash("Pilih mandor terlebih dahulu.", "warning")
        elif not period_start or not period_end:
            flash("Tanggal mulai dan tanggal selesai wajib diisi dengan benar.", "warning")
        elif period_start > period_end:
            flash("Tanggal mulai tidak boleh lebih besar dari tanggal selesai.", "warning")
        else:
            selected_mandor_id_int = int(selected_mandor_id)
            selected_mandor = Mandor.query.get(selected_mandor_id_int)
            selected_client, selected_client_error = get_client_for_mandor_invoice(selected_mandor)

            if selected_client_error:
                flash(selected_client_error, "danger")
            else:
                selected_client_pics = get_active_client_pics(selected_client.id) if selected_client else []
                if not selected_client_pics:
                    flash("Client belum punya PIC resmi aktif. Lihat data tetap tampil, tapi invoice belum bisa disimpan.", "warning")
                preview_ready = True

            orders = DailyOrder.query.filter(
                DailyOrder.branch_id == current_user.branch_id,
                DailyOrder.status == "LOCKED",
                DailyOrder.order_date >= period_start,
                DailyOrder.order_date <= period_end
            ).order_by(
                DailyOrder.order_date.asc(),
                DailyOrder.id.asc()
            ).all()

            for order in orders:
                old_order_invoice = Invoice.query.filter_by(
                    branch_id=current_user.branch_id,
                    source_type="DAILY_ORDER",
                    source_order_id=order.id,
                    mandor_id=selected_mandor_id_int
                ).first()

                for detail in order.details:
                    if int(detail.mandor_id) != selected_mandor_id_int:
                        continue

                    mandor_name = _period_safe_label(getattr(detail, "mandor", None))
                    location_name = _period_safe_label(getattr(detail, "delivery_location", None))

                    lunch_qty, dinner_qty = calculate_realtime_locked_base_quantities(
                        detail,
                        _period_is_after_lock_increase,
                    )
                    total_qty = lunch_qty + dinner_qty
                    price = float(getattr(detail, "price_per_portion", 0) or 0)
                    subtotal = total_qty * price

                    blocked_reason = None

                    if old_order_invoice:
                        blocked_reason = f"Sudah ada invoice order {old_order_invoice.invoice_number}"
                    elif _period_invoice_item_exists("ORDER_DETAIL", detail.id):
                        blocked_reason = "Sudah pernah masuk invoice periode"

                    included = blocked_reason is None

                    if total_qty > 0 and subtotal >= 0:
                        lines.append({
                            "date": order.order_date,
                            "item_type": "CATERING",
                            "description": (
                                f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                                f"Locked: Lunch {lunch_qty}, Dinner {dinner_qty}"
                            ),
                            "qty": total_qty,
                            "unit_price": price,
                            "subtotal": subtotal,
                            "included": included,
                            "blocked_reason": blocked_reason,
                            "source_type": "ORDER_DETAIL",
                            "source_id": detail.id,
                        })

                        if included:
                            total_catering += subtotal
                            grand_total += subtotal

                    for revision in getattr(detail, "revisions", []) or []:
                        if not _period_is_after_lock_increase(revision):
                            continue

                        lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
                        dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
                        qty_change = lunch_change + dinner_change

                        if qty_change <= 0:
                            continue

                        revision_price = getattr(revision, "price_per_portion", None)

                        if revision_price is None:
                            revision_price = price

                        revision_price = float(revision_price or 0)
                        revision_subtotal = qty_change * revision_price

                        blocked_reason = None

                        if old_order_invoice:
                            blocked_reason = f"Sudah ada invoice order {old_order_invoice.invoice_number}"
                        elif _period_invoice_item_exists("ORDER_REVISION", revision.id):
                            blocked_reason = "Sudah pernah masuk invoice periode"

                        included = blocked_reason is None

                        lines.append({
                            "date": order.order_date,
                            "item_type": "REVISION_INCREASE",
                            "description": (
                                f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                                f"Revisi tambah: Lunch +{lunch_change}, Dinner +{dinner_change}"
                            ),
                            "qty": qty_change,
                            "unit_price": revision_price,
                            "subtotal": revision_subtotal,
                            "included": included,
                            "blocked_reason": blocked_reason,
                            "source_type": "ORDER_REVISION",
                            "source_id": revision.id,
                        })

                        if included:
                            total_revision += revision_subtotal
                            grand_total += revision_subtotal

            debts = WorkerDebt.query.filter_by(
                branch_id=current_user.branch_id
            ).order_by(
                WorkerDebt.id.asc()
            ).all()

            for debt in debts:
                worker = getattr(debt, "worker", None)
                sale = getattr(debt, "sale", None)

                if not worker or not sale:
                    continue

                if int(getattr(worker, "mandor_id", 0) or 0) != selected_mandor_id_int:
                    continue

                sale_date = getattr(sale, "sale_date", None)

                if hasattr(sale_date, "date"):
                    sale_date = sale_date.date()

                if not sale_date:
                    continue

                if sale_date < period_start or sale_date > period_end:
                    continue

                remaining = float(get_debt_remaining_amount(debt) or 0)

                if remaining <= 0:
                    continue

                paid = float(get_debt_paid_amount(debt) or 0)

                blocked_reason = None

                if _period_invoice_item_exists("WORKER_DEBT", debt.id):
                    blocked_reason = "Sudah pernah masuk invoice periode"

                included = blocked_reason is None

                lines.append({
                    "date": sale_date,
                    "item_type": "WARUNG_DEBT",
                    "description": (
                        f"Hutang warung pekerja {_period_safe_label(worker)} | "
                        f"Hutang {float(debt.debt_amount or 0):,.0f} | Dibayar {paid:,.0f} | Sisa {remaining:,.0f}"
                    ),
                    "qty": 1,
                    "unit_price": remaining,
                    "subtotal": remaining,
                    "included": included,
                    "blocked_reason": blocked_reason,
                    "source_type": "WORKER_DEBT",
                    "source_id": debt.id,
                })

                if included:
                    total_warung += remaining
                    grand_total += remaining

            lines = sorted(lines, key=lambda row: (row["date"], row["item_type"], row["source_id"]))

    return render_template(
        "finance/invoice_generate_period_preview.html",
        mandors=mandors,
        selected_mandor_id=selected_mandor_id,
        selected_mandor=selected_mandor,
        selected_client=selected_client,
        selected_client_error=selected_client_error,
        selected_client_pics=selected_client_pics,
        period_start_value=period_start_value,
        period_end_value=period_end_value,
        lines=lines,
        total_catering=total_catering,
        total_revision=total_revision,
        total_warung=total_warung,
        grand_total=grand_total,
        preview_ready=preview_ready
    )



# === PATCH_PERIOD_INVOICE_SAVE ===
def _period_generate_invoice_number(invoice_date):
    from app.models.finance import Invoice

    prefix = f"INV-{invoice_date.strftime('%Y%m%d')}"
    counter = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}-%")).count() + 1

    while True:
        invoice_number = f"{prefix}-{counter:03d}"
        existing = Invoice.query.filter_by(invoice_number=invoice_number).first()

        if not existing:
            return invoice_number

        counter += 1


def _build_period_invoice_lines_for_save(mandor_id, period_start, period_end, branch_id):
    from app.models.operational import DailyOrder
    from app.models.finance import Invoice
    from app.models.canteen import WorkerDebt
    from app.services.canteen_service import get_debt_paid_amount, get_debt_remaining_amount

    mandor_id = int(mandor_id)
    lines = []

    orders = DailyOrder.query.filter(
        DailyOrder.branch_id == branch_id,
        DailyOrder.status == "LOCKED",
        DailyOrder.order_date >= period_start,
        DailyOrder.order_date <= period_end
    ).order_by(
        DailyOrder.order_date.asc(),
        DailyOrder.id.asc()
    ).all()

    for order in orders:
        old_order_invoice = Invoice.query.filter_by(
            branch_id=branch_id,
            source_type="DAILY_ORDER",
            source_order_id=order.id,
            mandor_id=mandor_id
        ).first()

        for detail in order.details:
            if int(detail.mandor_id) != mandor_id:
                continue

            mandor_name = _period_safe_label(getattr(detail, "mandor", None))
            location_name = _period_safe_label(getattr(detail, "delivery_location", None))

            lunch_qty, dinner_qty = calculate_realtime_locked_base_quantities(
                detail,
                _period_is_after_lock_increase,
            )
            total_qty = lunch_qty + dinner_qty
            price = float(getattr(detail, "price_per_portion", 0) or 0)
            subtotal = total_qty * price

            if total_qty > 0 and subtotal >= 0:
                if not old_order_invoice and not _period_invoice_item_exists("ORDER_DETAIL", detail.id):
                    lines.append({
                        "item_type": "CATERING",
                        "description": (
                            f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                            f"Locked: Lunch {lunch_qty}, Dinner {dinner_qty}"
                        ),
                        "qty": total_qty,
                        "unit_price": price,
                        "subtotal": subtotal,
                        "source_type": "ORDER_DETAIL",
                        "source_id": detail.id,
                    })

            for revision in getattr(detail, "revisions", []) or []:
                if not _period_is_after_lock_increase(revision):
                    continue

                lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
                dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
                qty_change = lunch_change + dinner_change

                if qty_change <= 0:
                    continue

                revision_price = getattr(revision, "price_per_portion", None)

                if revision_price is None:
                    revision_price = price

                revision_price = float(revision_price or 0)
                revision_subtotal = qty_change * revision_price

                if not old_order_invoice and not _period_invoice_item_exists("ORDER_REVISION", revision.id):
                    lines.append({
                        "item_type": "REVISION_INCREASE",
                        "description": (
                            f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                            f"Revisi tambah: Lunch +{lunch_change}, Dinner +{dinner_change}"
                        ),
                        "qty": qty_change,
                        "unit_price": revision_price,
                        "subtotal": revision_subtotal,
                        "source_type": "ORDER_REVISION",
                        "source_id": revision.id,
                    })

    debts = WorkerDebt.query.filter_by(
        branch_id=branch_id
    ).order_by(
        WorkerDebt.id.asc()
    ).all()

    for debt in debts:
        worker = getattr(debt, "worker", None)
        sale = getattr(debt, "sale", None)

        if not worker or not sale:
            continue

        if int(getattr(worker, "mandor_id", 0) or 0) != mandor_id:
            continue

        sale_date = getattr(sale, "sale_date", None)

        if hasattr(sale_date, "date"):
            sale_date = sale_date.date()

        if not sale_date:
            continue

        if sale_date < period_start or sale_date > period_end:
            continue

        remaining = float(get_debt_remaining_amount(debt) or 0)

        if remaining <= 0:
            continue

        if _period_invoice_item_exists("WORKER_DEBT", debt.id):
            continue

        paid = float(get_debt_paid_amount(debt) or 0)

        lines.append({
            "item_type": "WARUNG_DEBT",
            "description": (
                f"Hutang warung pekerja {_period_safe_label(worker)} | "
                f"Hutang {float(debt.debt_amount or 0):,.0f} | Dibayar {paid:,.0f} | Sisa {remaining:,.0f}"
            ),
            "qty": 1,
            "unit_price": remaining,
            "subtotal": remaining,
            "source_type": "WORKER_DEBT",
            "source_id": debt.id,
        })

    return lines


@finance_bp.route("/invoices/generate-period/save", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def generate_period_invoice_save():
    from datetime import date, timedelta
    from app.extensions import db
    from app.models.master import Mandor
    from app.models.finance import Invoice, InvoiceItem

    mandor_id = request.form.get("mandor_id", "").strip()
    period_start_value = request.form.get("period_start", "").strip()
    period_end_value = request.form.get("period_end", "").strip()

    period_start = _period_parse_date(period_start_value)
    period_end = _period_parse_date(period_end_value)

    if not mandor_id:
        flash("Mandor wajib dipilih.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    if not period_start or not period_end:
        flash("Periode invoice tidak valid.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    if period_start > period_end:
        flash("Tanggal mulai tidak boleh lebih besar dari tanggal selesai.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    mandor_id = int(mandor_id)
    mandor = Mandor.query.get(mandor_id)

    if not mandor:
        flash("Data mandor tidak ditemukan.", "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    if int(getattr(mandor, "branch_id", 0) or 0) != int(current_user.branch_id):
        flash("Mandor/PIC lapangan tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    client, client_error = get_client_for_mandor_invoice(mandor)

    if client_error:
        flash(client_error, "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    client_pic_id = request.form.get("client_pic_id", type=int)
    client_pic, client_pic_error = get_required_client_pic(client.id, client_pic_id)
    if client_pic_error:
        flash(client_pic_error, "warning")
        return redirect(url_for("finance.generate_period_invoice_preview", mandor_id=mandor_id, period_start=period_start, period_end=period_end))

    existing_period_invoice = Invoice.query.filter_by(
        branch_id=current_user.branch_id,
        source_type="PERIOD_INVOICE",
        mandor_id=mandor_id,
        period_start=period_start,
        period_end=period_end
    ).first()

    if existing_period_invoice:
        flash("Invoice periode untuk mandor dan rentang tanggal ini sudah pernah dibuat.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=existing_period_invoice.id))

    lines = _build_period_invoice_lines_for_save(
        mandor_id=mandor_id,
        period_start=period_start,
        period_end=period_end,
        branch_id=current_user.branch_id
    )

    total_amount = sum(float(line["subtotal"] or 0) for line in lines)

    if not lines or total_amount <= 0:
        flash("Tidak ada item valid untuk disimpan menjadi invoice periode.", "warning")
        return redirect(url_for("finance.generate_period_invoice_preview"))

    invoice_date = date.today()
    due_date = invoice_date + timedelta(days=7)

    invoice = Invoice(
        branch_id=current_user.branch_id,
        invoice_number=_period_generate_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=due_date,
        period_start=period_start,
        period_end=period_end,
        bill_to_type="CLIENT",
        client_id=client.id,
        mandor_id=mandor_id,
        client_pic_id=client_pic.id,
        **build_company_bank_snapshot(current_user.branch_id),
        client_name_snapshot=client.name,
        client_code_snapshot=getattr(client, "client_code", None),
        client_pic_name_snapshot=client_pic.name,
        client_pic_position_snapshot=getattr(client_pic, "position", None),
        client_pic_phone_snapshot=getattr(client_pic, "phone", None),
        client_pic_email_snapshot=getattr(client_pic, "email", None),
        expected_payment_percent=100,
        total_amount=total_amount,
        paid_amount=0,
        remaining_amount=total_amount,
        status="DRAFT",
        notes=(
            f"Invoice periode resmi ke client {client.name} "
            f"({period_start.strftime('%d-%m-%Y')} s/d {period_end.strftime('%d-%m-%Y')}). "
            f"PIC lapangan: {mandor.name}. "
            f"Isi: catering locked, revisi tambah setelah lock, dan hutang warung belum lunas. "
            f"Sumber bukan dari pengiriman."
        ),
        source_type="PERIOD_INVOICE",
        source_order_id=None,
        input_source=INPUT_SOURCE_REALTIME,
        created_by=current_user.id
    )

    try:
        with atomic_business_action(
            module="FINANCE",
            action="PERIOD_INVOICE_CREATE",
            description=f"Create invoice periode {period_start} s/d {period_end} secara atomic.",
            reference_type="invoices",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"source_type": "PERIOD_INVOICE", "input_source": INPUT_SOURCE_REALTIME, "mandor_id": mandor.id, "item_count": len(lines)},
        ):
            db.session.add(invoice)
            db.session.flush()

            for line in lines:
                item = InvoiceItem(
                    invoice_id=invoice.id,
                    item_type=line["item_type"],
                    description=line["description"],
                    qty=line["qty"],
                    unit_price=line["unit_price"],
                    subtotal=line["subtotal"],
                    source_type=line["source_type"],
                    source_id=line["source_id"],
                    input_source=INPUT_SOURCE_REALTIME,
                )

                db.session.add(item)

            # AUTO_JOURNAL_PERIOD_INVOICE_STEP10F4B
            db.session.flush()

            from app.services.accounting_service import create_invoice_journal_for_invoice
            create_invoice_journal_for_invoice(
                invoice=invoice,
                created_by=current_user.id,
                commit=False
            )

        record_audit_log(
            module="FINANCE",
            event_type="INVOICE_CREATED",
            action="CREATE",
            table_name="invoices",
            record_id=invoice.id,
            description=f"Invoice periode dibuat: {invoice.invoice_number}.",
            metadata={"invoice_number": invoice.invoice_number, "source_type": invoice.source_type, "input_source": invoice.input_source, "total_amount": invoice.total_amount},
        )
        flash("Invoice periode resmi ke client berhasil dibuat dan jurnal otomatis dicatat.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1605")
        flash(f"Gagal menyimpan invoice periode: {error}", "danger")
        return redirect(url_for("finance.generate_period_invoice_preview"))



# === PATCH_INVOICE_PAYMENT_STEP10E1 ===
