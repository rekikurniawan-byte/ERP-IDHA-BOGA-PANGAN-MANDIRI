"""Manual billing routes.

Route functions moved out of app.routes.finance_routes without changing URL rules or endpoint names.
"""
from app.routes.finance_routes import *  # noqa: F401,F403
from app.routes.finance.payment_routes import _parse_payment_amount
from app.routes.finance.period_invoice_routes import _period_parse_date
from app.utils.clock import today_wib
from app.utils.terms import T


@finance_bp.route("/transactions", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def finance_transactions():
    """Unified finance transaction entry.

    This page intentionally consolidates the daily finance posting flows that used
    to be separated in the sidebar: DP/advance, transport/BBM, and operational
    expense. It does not replace invoice/AP/asset/closing workflows because those
    have their own business documents and controls.
    """
    from datetime import date, datetime
    from app.models.delivery import Delivery
    from app.models.finance import BankAccount
    from app.models.master import Client, Driver, Mandor, Supplier
    from app.services.advance_service import (
        get_advance_type_choices,
        is_advance_schema_ready,
        create_advance_transaction_record,
    )
    from app.services.operational_expense_service import (
        get_operational_expense_category_choices,
        is_operational_expense_schema_ready,
        create_operational_expense_record,
    )
    from app.services.transport_expense_service import (
        get_transport_expense_type_choices,
        is_transport_expense_schema_ready,
        create_transport_vehicle_expense_record,
    )

    schema_ready = {
        "advance": is_advance_schema_ready(),
        "transport": is_transport_expense_schema_ready(),
        "operational": is_operational_expense_schema_ready(),
    }

    def _to_int(value):
        try:
            return int(value) if value not in (None, "") else None
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5158")
            return None

    if request.method == "POST":
        transaction_kind = (request.form.get("transaction_kind") or "").strip().upper()
        transaction_date_raw = (request.form.get("transaction_date") or "").strip()
        amount_raw = (request.form.get("amount") or "").strip()
        payment_method = (request.form.get("payment_method") or "").strip().upper()
        bank_account_id = _to_int((request.form.get("bank_account_id") or "").strip())
        reference_number = (request.form.get("reference_number") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            transaction_date = datetime.strptime(transaction_date_raw, "%Y-%m-%d").date()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5172")
            flash("Tanggal transaksi tidak valid.", "warning")
            return redirect(url_for("finance.finance_transactions", tx=transaction_kind.lower()))

        try:
            amount = _parse_payment_amount(amount_raw)
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5178")
            flash("Nominal transaksi tidak valid.", "warning")
            return redirect(url_for("finance.finance_transactions", tx=transaction_kind.lower()))

        try:
            if transaction_kind == "ADVANCE":
                if not schema_ready["advance"]:
                    raise Exception("Tabel uang muka/DP belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
                ok, message, advance = create_advance_transaction_record(
                    branch_id=current_user.branch_id,
                    advance_date=transaction_date,
                    advance_type=(request.form.get("advance_type") or "").strip().upper(),
                    payment_method=payment_method,
                    amount=amount,
                    created_by=current_user.id,
                    client_id=_to_int(request.form.get("advance_client_id")),
                    supplier_id=_to_int(request.form.get("advance_supplier_id")),
                    mandor_id=_to_int(request.form.get("advance_mandor_id")),
                    bank_account_id=bank_account_id,
                    reference_number=reference_number,
                    notes=notes,
                )
                flash("Transaksi DP/uang muka berhasil diposting dari input terpadu.", "success")
                return redirect(url_for("finance.advance_detail", advance_id=advance.id))

            if transaction_kind == "TRANSPORT":
                if not schema_ready["transport"]:
                    raise Exception("Tabel transport/BBM belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
                ok, message, expense = create_transport_vehicle_expense_record(
                    branch_id=current_user.branch_id,
                    expense_date=transaction_date,
                    expense_type=(request.form.get("transport_expense_type") or "").strip().upper(),
                    payment_method=payment_method,
                    amount=amount,
                    created_by=current_user.id,
                    vehicle_label=(request.form.get("vehicle_label") or "").strip(),
                    driver_id=_to_int(request.form.get("driver_id")),
                    delivery_id=_to_int(request.form.get("delivery_id")),
                    bank_account_id=bank_account_id,
                    vendor_name=(request.form.get("transport_vendor_name") or "").strip(),
                    reference_number=reference_number,
                    notes=notes,
                )
                flash("Transaksi transport/BBM berhasil diposting dari input terpadu.", "success")
                return redirect(url_for("finance.transport_expense_detail", expense_id=expense.id))

            if transaction_kind == "OPERATIONAL_EXPENSE":
                if not schema_ready["operational"]:
                    raise Exception("Tabel biaya operasional belum tersedia. Jalankan migration PRODUCTION terlebih dahulu.")
                ok, message, expense = create_operational_expense_record(
                    branch_id=current_user.branch_id,
                    expense_date=transaction_date,
                    expense_category=(request.form.get("operational_expense_category") or "").strip().upper(),
                    payment_method=payment_method,
                    amount=amount,
                    created_by=current_user.id,
                    bank_account_id=bank_account_id,
                    supplier_id=_to_int(request.form.get("operational_supplier_id")),
                    vendor_name=(request.form.get("operational_vendor_name") or "").strip(),
                    reference_number=reference_number,
                    notes=notes,
                )
                flash("Transaksi biaya operasional berhasil diposting dari input terpadu.", "success")
                return redirect(url_for("finance.operational_expense_detail", expense_id=expense.id))

            flash("Jenis transaksi belum dipilih atau belum didukung input terpadu.", "warning")
            return redirect(url_for("finance.finance_transactions"))
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5245")
            flash(str(exc), "danger")
            return redirect(url_for("finance.finance_transactions", tx=transaction_kind.lower()))

    selected_tx = (request.args.get("tx") or "advance").strip().lower()
    if selected_tx not in {"advance", "transport", "operational_expense"}:
        selected_tx = "advance"

    bank_accounts = BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()
    clients = Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all()
    suppliers = Supplier.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Supplier.supplier_name.asc()).all()
    mandors = Mandor.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Mandor.name.asc()).all()
    drivers = Driver.query.filter_by(branch_id=current_user.branch_id, is_active=True).order_by(Driver.name.asc()).all()
    deliveries = Delivery.query.filter_by(branch_id=current_user.branch_id).order_by(Delivery.delivery_date.desc(), Delivery.id.desc()).limit(80).all()

    return render_template(
        "finance/transactions.html",
        today_date=today_wib().isoformat(),
        selected_tx=selected_tx,
        schema_ready=schema_ready,
        bank_accounts=bank_accounts,
        clients=clients,
        suppliers=suppliers,
        mandors=mandors,
        drivers=drivers,
        deliveries=deliveries,
        advance_type_choices=get_advance_type_choices(),
        transport_expense_type_choices=get_transport_expense_type_choices(),
        operational_expense_category_choices=get_operational_expense_category_choices(),
    )


@finance_bp.route("/manual-billing", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def manual_billing():
    from datetime import date
    from app.models.finance import ManualBillingBatch
    from app.models.master import Mandor
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import get_manual_backfill_status_context, get_manual_backfill_bill_to_context
    from app.services.manual_billing_service import (
        collect_manual_billing_candidates,
        get_active_client_pics_for_mandor,
    )

    today_value = today_wib().isoformat()
    selected_mandor_id = (request.form.get("mandor_id") if request.method == "POST" else request.args.get("mandor_id")) or ""
    period_start_value = (request.form.get("period_start") if request.method == "POST" else request.args.get("period_start")) or today_value
    period_end_value = (request.form.get("period_end") if request.method == "POST" else request.args.get("period_end")) or today_value

    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Mandor.name.asc()).all()

    selected_mandor = None
    client_pics = []
    preview = {
        "rows": [],
        "blocked_rows": [],
        "total_amount": 0,
        "manual_receivable_total": 0,
        "warung_total": 0,
    }
    preview_ready = False

    if selected_mandor_id:
        period_start = _period_parse_date(period_start_value)
        period_end = _period_parse_date(period_end_value)
        try:
            selected_mandor_id_int = int(selected_mandor_id)
        except (TypeError, ValueError):
            selected_mandor_id_int = None
        if not period_start or not period_end:
            flash(f"Periode rekap tagihan {T.sub_client_lower} tidak valid.", "warning")
        elif period_start > period_end:
            flash("Tanggal mulai tidak boleh lebih besar dari tanggal selesai.", "warning")
        elif not selected_mandor_id_int:
            flash(f"{T.sub_client}/PIC lapangan tidak valid.", "warning")
        else:
            selected_mandor = Mandor.query.filter_by(
                id=selected_mandor_id_int,
                branch_id=current_user.branch_id,
            ).first()
            if not selected_mandor:
                flash(f"{T.sub_client}/PIC lapangan tidak ditemukan.", "warning")
            elif not getattr(selected_mandor, "client", None):
                flash(f"{T.sub_client}/PIC lapangan belum terhubung ke {T.client_lower}.", "warning")
            else:
                preview = collect_manual_billing_candidates(
                    branch_id=current_user.branch_id,
                    mandor_id=selected_mandor.id,
                    period_start=period_start,
                    period_end=period_end,
                )
                client_pics = get_active_client_pics_for_mandor(selected_mandor)
                preview_ready = True
                if not client_pics:
                    flash(f"{T.client} belum punya PIC resmi aktif. Tambahkan PIC di Master {T.client} sebelum membuat invoice.", "warning")

    manual_backfill_batches = ManualBillingBatch.query.filter_by(
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).order_by(ManualBillingBatch.id.desc()).limit(10).all()

    return render_template(
        "finance/manual_billing.html",
        mandors=mandors,
        selected_mandor_id=str(selected_mandor_id or ""),
        selected_mandor=selected_mandor,
        client_pics=client_pics,
        period_start_value=period_start_value,
        period_end_value=period_end_value,
        preview=preview,
        preview_ready=preview_ready,
        manual_backfill_batches=manual_backfill_batches,
        get_manual_backfill_status_context=get_manual_backfill_status_context,
        get_manual_backfill_bill_to_context=get_manual_backfill_bill_to_context,
    )


def _pad_manual_backfill_rows(rows, minimum):
    rows = list(rows or [])
    while len(rows) < minimum:
        rows.append({})
    return rows


def _manual_backfill_period_dates(period_start_value, period_end_value):
    from datetime import timedelta

    period_start = _period_parse_date(period_start_value) if period_start_value else None
    period_end = _period_parse_date(period_end_value) if period_end_value else None
    if not period_start or not period_end or period_start > period_end:
        return []

    # Keep the generated table bounded so an accidental multi-year range does not
    # make the browser unusable. Backend validation still owns final truth.
    dates = []
    current = period_start
    for _ in range(370):
        if current > period_end:
            break
        dates.append(current.isoformat())
        current += timedelta(days=1)
    return dates


def _manual_backfill_catering_rows_for_period(period_start_value, period_end_value, existing_rows=None, minimum=1):
    existing_rows = list(existing_rows or [])
    by_date = {str(row.get("date") or ""): row for row in existing_rows if row.get("date")}
    used_dates = set()
    rows = []

    for iso_date in _manual_backfill_period_dates(period_start_value, period_end_value):
        row = dict(by_date.get(iso_date) or {})
        row["date"] = iso_date
        rows.append(row)
        used_dates.add(iso_date)

    # Preserve manual adjustment rows outside the period or without date, especially
    # after a failed POST/edit. JavaScript can still add/remove rows in the browser.
    for row in existing_rows:
        row_date = str(row.get("date") or "")
        if not row_date or row_date not in used_dates:
            rows.append(row)

    return _pad_manual_backfill_rows(rows, minimum)


def _manual_backfill_request_catering_rows(minimum=1):
    dates = request.form.getlist("catering_date[]")
    breakfast_qtys = request.form.getlist("catering_breakfast_qty[]")
    lunch_qtys = request.form.getlist("catering_lunch_qty[]")
    dinner_qtys = request.form.getlist("catering_dinner_qty[]")
    unit_prices = request.form.getlist("catering_unit_price[]")
    notes = request.form.getlist("catering_note[]")
    max_len = max(len(dates), len(breakfast_qtys), len(lunch_qtys), len(dinner_qtys), len(unit_prices), len(notes), minimum)
    return [
        {
            "date": dates[index] if index < len(dates) else "",
            "breakfast_qty": breakfast_qtys[index] if index < len(breakfast_qtys) else "",
            "lunch_qty": lunch_qtys[index] if index < len(lunch_qtys) else "",
            "dinner_qty": dinner_qtys[index] if index < len(dinner_qtys) else "",
            "unit_price": unit_prices[index] if index < len(unit_prices) else "",
            "note": notes[index] if index < len(notes) else "",
        }
        for index in range(max_len)
    ]


def _manual_backfill_request_warung_rows(minimum=8):
    worker_names = request.form.getlist("warung_worker_name[]")
    amounts = request.form.getlist("warung_amount[]")
    notes = request.form.getlist("warung_note[]")
    max_len = max(len(worker_names), len(amounts), len(notes), minimum)
    return [
        {
            "worker_name": worker_names[index] if index < len(worker_names) else "",
            "amount": amounts[index] if index < len(amounts) else "",
            "note": notes[index] if index < len(notes) else "",
        }
        for index in range(max_len)
    ]


def _number_for_form(value):
    try:
        value = float(value or 0)
    except (TypeError, ValueError):
        value = 0
    if value == int(value):
        return str(int(value))
    return (f"{value:.2f}").rstrip("0").rstrip(".")


def _manual_backfill_existing_catering_rows(batch, minimum=14):
    import re

    rows = []
    for item in getattr(batch, "items", []) or []:
        if getattr(item, "item_type", None) != "CATERING":
            continue
        description = str(getattr(item, "description", "") or "")
        breakfast_qty = 0
        lunch_qty = getattr(item, "qty", 0) or 0
        dinner_qty = 0
        meal_match = re.search(
            r"(?:Sarapan\s+([0-9.,]+)\s*\|\s*)?Siang\s+([0-9.,]+)\s*\|\s*Sore\s+([0-9.,]+)",
            description,
            flags=re.I,
        )
        if meal_match:
            breakfast_qty = meal_match.group(1) or 0
            lunch_qty = meal_match.group(2)
            dinner_qty = meal_match.group(3)
        parts = [part.strip() for part in description.split("|")]
        note_start = 5 if any(part.lower().startswith("total ") for part in parts[:5]) else 4
        note = " | ".join(parts[note_start:]).strip() if len(parts) > note_start else ""
        source_date = getattr(item, "source_date", None)
        rows.append({
            "date": source_date.isoformat() if source_date else "",
            "breakfast_qty": breakfast_qty,
            "lunch_qty": lunch_qty,
            "dinner_qty": dinner_qty,
            "unit_price": _number_for_form(getattr(item, "unit_price", 0)),
            "note": note,
        })
    return _pad_manual_backfill_rows(rows, minimum)


def _manual_backfill_existing_warung_rows(batch, minimum=8):
    rows = []
    prefix = "Kasbon/hutang warung pekerja "
    for item in getattr(batch, "items", []) or []:
        if getattr(item, "item_type", None) != "WARUNG_DEBT":
            continue
        description = str(getattr(item, "description", "") or "")
        parts = [part.strip() for part in description.split("|")]
        worker_name = str(getattr(item, "source_label", "") or "").strip()
        if not worker_name and parts:
            worker_name = parts[0]
            if worker_name.startswith(prefix):
                worker_name = worker_name[len(prefix):].strip()
        note = " | ".join(parts[1:]).strip() if len(parts) > 1 else ""
        rows.append({
            "worker_name": worker_name,
            "amount": _number_for_form(getattr(item, "unit_price", None) or getattr(item, "subtotal", 0)),
            "note": note,
        })
    return _pad_manual_backfill_rows(rows, minimum)


@finance_bp.route("/manual-billing/batches")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def manual_billing_batches_list():
    """Register semua rekap manual dari buku dengan filter operasional.

    Halaman ini hanya membaca lane MANUAL_BACKFILL. Tidak mengubah alur REALTIME.
    """
    from sqlalchemy import or_
    from app.models.finance import ManualBillingBatch
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import (
        build_manual_backfill_register_summary,
        get_manual_backfill_bill_to_context,
        get_manual_backfill_bill_to_filter_choices,
        get_manual_backfill_status_context,
        get_manual_backfill_status_filter_choices,
        normalize_manual_backfill_bill_to_filter,
        normalize_manual_backfill_status_filter,
    )

    status_filter = normalize_manual_backfill_status_filter(request.args.get("status"))
    bill_to_type_filter = normalize_manual_backfill_bill_to_filter(request.args.get("bill_to_type"))
    q = (request.args.get("q") or "").strip()
    period_start_value = (request.args.get("period_start") or "").strip()
    period_end_value = (request.args.get("period_end") or "").strip()
    period_start = _period_parse_date(period_start_value) if period_start_value else None
    period_end = _period_parse_date(period_end_value) if period_end_value else None

    if period_start_value and not period_start:
        flash("Tanggal mulai filter rekap manual tidak valid.", "warning")
        period_start_value = ""
    if period_end_value and not period_end:
        flash("Tanggal selesai filter rekap manual tidak valid.", "warning")
        period_end_value = ""
    if period_start and period_end and period_start > period_end:
        flash("Tanggal mulai filter tidak boleh lebih besar dari tanggal selesai.", "warning")
        period_start, period_end = period_end, period_start
        period_start_value, period_end_value = period_start.isoformat(), period_end.isoformat()

    query = ManualBillingBatch.query.filter_by(
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    )

    if status_filter:
        query = query.filter(ManualBillingBatch.status == status_filter)
    if bill_to_type_filter:
        legacy_bill_to_types = {
            "MANDOR_EXISTING": ["MANDOR_EXISTING", "MANDOR"],
            "CLIENT_EXISTING": ["CLIENT_EXISTING", "CLIENT"],
        }
        query = query.filter(ManualBillingBatch.bill_to_type.in_(
            legacy_bill_to_types.get(bill_to_type_filter, [bill_to_type_filter])
        ))
    if period_start:
        query = query.filter(ManualBillingBatch.period_end >= period_start)
    if period_end:
        query = query.filter(ManualBillingBatch.period_start <= period_end)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(
            ManualBillingBatch.batch_number.ilike(like),
            ManualBillingBatch.bill_to_name_snapshot.ilike(like),
            ManualBillingBatch.bill_to_phone_snapshot.ilike(like),
            ManualBillingBatch.notes.ilike(like),
        ))

    batches = query.order_by(ManualBillingBatch.id.desc()).limit(300).all()

    return render_template(
        "finance/manual_billing_batches.html",
        batches=batches,
        summary=build_manual_backfill_register_summary(batches),
        status_choices=get_manual_backfill_status_filter_choices(),
        bill_to_type_choices=get_manual_backfill_bill_to_filter_choices(),
        selected_status=status_filter,
        selected_bill_to_type=bill_to_type_filter,
        q=q,
        period_start_value=period_start_value,
        period_end_value=period_end_value,
        get_manual_backfill_status_context=get_manual_backfill_status_context,
        get_manual_backfill_bill_to_context=get_manual_backfill_bill_to_context,
    )


@finance_bp.route("/manual-billing/input-buku", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def manual_billing_backfill_form():
    """Input old/manual book recap as a MANUAL_BACKFILL draft batch.

    This is the second input path. It must not change the realtime order flow and
    it must not create invoice/piutang yet; later roadmap stages will lock and
    promote these batches.
    """
    from datetime import date
    from app.models.master import Mandor
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        build_catering_backfill_rows,
        build_warung_backfill_rows,
        create_manual_backfill_batch_record,
    )

    today_value = today_wib().isoformat()
    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Mandor.name.asc()).all()
    clients = Client.query.filter_by(
        is_active=True,
    ).order_by(Client.name.asc()).all()

    default_warung_rows = 8
    form_values = {
        "bill_to_type": request.form.get("bill_to_type", "MANDOR_EXISTING"),
        "mandor_id": request.form.get("mandor_id", ""),
        "client_id": request.form.get("client_id", ""),
        "bill_to_name_snapshot": request.form.get("bill_to_name_snapshot", ""),
        "bill_to_phone_snapshot": request.form.get("bill_to_phone_snapshot", ""),
        "bill_to_address_snapshot": request.form.get("bill_to_address_snapshot", ""),
        "bill_to_notes": request.form.get("bill_to_notes", ""),
        "period_start": request.form.get("period_start", today_value),
        "period_end": request.form.get("period_end", today_value),
        "notes": request.form.get("notes", ""),
    }
    default_rows = max(len(_manual_backfill_period_dates(form_values["period_start"], form_values["period_end"])), 1)
    catering_form_rows = (
        _manual_backfill_request_catering_rows(default_rows)
        if request.method == "POST"
        else _manual_backfill_catering_rows_for_period(form_values["period_start"], form_values["period_end"], minimum=default_rows)
    )
    warung_form_rows = _manual_backfill_request_warung_rows(default_warung_rows) if request.method == "POST" else _pad_manual_backfill_rows([], default_warung_rows)

    if request.method == "POST":
        try:
            catering_rows = build_catering_backfill_rows(
                request.form.getlist("catering_date[]"),
                request.form.getlist("catering_lunch_qty[]"),
                request.form.getlist("catering_dinner_qty[]"),
                request.form.getlist("catering_unit_price[]"),
                request.form.getlist("catering_note[]"),
                request.form.getlist("catering_breakfast_qty[]"),
            )
            warung_rows = build_warung_backfill_rows(
                request.form.getlist("warung_worker_name[]"),
                request.form.getlist("warung_amount[]"),
                request.form.getlist("warung_note[]"),
            )
            batch = create_manual_backfill_batch_record(
                branch_id=current_user.branch_id,
                bill_to_type=form_values["bill_to_type"],
                mandor_id=form_values["mandor_id"],
                client_id=form_values["client_id"],
                bill_to_name_snapshot=form_values["bill_to_name_snapshot"],
                bill_to_phone_snapshot=form_values["bill_to_phone_snapshot"],
                bill_to_address_snapshot=form_values["bill_to_address_snapshot"],
                bill_to_notes=form_values["bill_to_notes"],
                period_start=form_values["period_start"],
                period_end=form_values["period_end"],
                catering_rows=catering_rows,
                warung_rows=warung_rows,
                notes=form_values["notes"],
                created_by=current_user.id,
            )
            flash(f"Input rekap manual dari buku {batch.batch_number} berhasil disimpan sebagai draft.", "success")
            return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch.id))
        except ManualBackfillBillingError as exc:
            flash(str(exc), "warning")
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5686")
            flash(f"Gagal menyimpan input rekap manual dari buku: {exc}", "danger")

    return render_template(
        "finance/manual_billing_backfill_form.html",
        mandors=mandors,
        clients=clients,
        form_values=form_values,
        catering_form_rows=catering_form_rows,
        warung_form_rows=warung_form_rows,
        default_rows=default_rows,
        default_warung_rows=default_warung_rows,
        action_url=url_for("finance.manual_billing_backfill_form"),
        page_title="Input Rekap Manual dari Buku",
        page_subtitle="Jalur tambahan untuk memasukkan rekap lama/buku manual. Ini tidak mengubah alur realtime order harian.",
        mode_badge="Input Belakangan",
        form_confirm="Simpan rekap manual dari buku sebagai draft?",
        submit_heading="Simpan Draft Rekap Manual",
        submit_help="Draft ini belum menjadi invoice/piutang. Setelah tersimpan, cek detail lalu kunci rekap jika total sudah benar.",
        submit_label="Simpan Draft",
        submit_icon="bi-save",
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>/edit", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def edit_manual_billing_backfill_batch(batch_id):
    from app.models.finance import ManualBillingBatch
    from app.models.master import Mandor
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import (
        MANUAL_BACKFILL_STATUS_DRAFT,
        ManualBackfillBillingError,
        build_catering_backfill_rows,
        build_warung_backfill_rows,
        update_manual_backfill_batch_record,
    )

    batch = ManualBillingBatch.query.filter_by(
        id=batch_id,
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).first_or_404()

    if batch.status != MANUAL_BACKFILL_STATUS_DRAFT or batch.invoice_id:
        flash("Hanya draft rekap manual yang belum memiliki invoice yang bisa diedit.", "warning")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch.id))

    default_warung_rows = 8
    mandors = Mandor.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(Mandor.name.asc()).all()
    clients = Client.query.filter_by(
        is_active=True,
    ).order_by(Client.name.asc()).all()

    if request.method == "POST":
        form_values = {
            "bill_to_type": request.form.get("bill_to_type", "MANDOR_EXISTING"),
            "mandor_id": request.form.get("mandor_id", ""),
            "client_id": request.form.get("client_id", ""),
            "bill_to_name_snapshot": request.form.get("bill_to_name_snapshot", ""),
            "bill_to_phone_snapshot": request.form.get("bill_to_phone_snapshot", ""),
            "bill_to_address_snapshot": request.form.get("bill_to_address_snapshot", ""),
            "bill_to_notes": request.form.get("bill_to_notes", ""),
            "period_start": request.form.get("period_start", ""),
            "period_end": request.form.get("period_end", ""),
            "notes": request.form.get("notes", ""),
        }
        default_rows = max(len(_manual_backfill_period_dates(form_values["period_start"], form_values["period_end"])), 1)
        catering_form_rows = _manual_backfill_request_catering_rows(default_rows)
        warung_form_rows = _manual_backfill_request_warung_rows(default_warung_rows)
        try:
            catering_rows = build_catering_backfill_rows(
                request.form.getlist("catering_date[]"),
                request.form.getlist("catering_lunch_qty[]"),
                request.form.getlist("catering_dinner_qty[]"),
                request.form.getlist("catering_unit_price[]"),
                request.form.getlist("catering_note[]"),
                request.form.getlist("catering_breakfast_qty[]"),
            )
            warung_rows = build_warung_backfill_rows(
                request.form.getlist("warung_worker_name[]"),
                request.form.getlist("warung_amount[]"),
                request.form.getlist("warung_note[]"),
            )
            updated_batch = update_manual_backfill_batch_record(
                batch_id=batch.id,
                branch_id=current_user.branch_id,
                bill_to_type=form_values["bill_to_type"],
                mandor_id=form_values["mandor_id"],
                client_id=form_values["client_id"],
                bill_to_name_snapshot=form_values["bill_to_name_snapshot"],
                bill_to_phone_snapshot=form_values["bill_to_phone_snapshot"],
                bill_to_address_snapshot=form_values["bill_to_address_snapshot"],
                bill_to_notes=form_values["bill_to_notes"],
                period_start=form_values["period_start"],
                period_end=form_values["period_end"],
                catering_rows=catering_rows,
                warung_rows=warung_rows,
                notes=form_values["notes"],
                updated_by=current_user.id,
            )
            flash(f"Draft rekap manual {updated_batch.batch_number} berhasil diperbarui.", "success")
            return redirect(url_for("finance.manual_billing_batch_detail", batch_id=updated_batch.id))
        except ManualBackfillBillingError as exc:
            flash(str(exc), "warning")
        except Exception as exc:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5794")
            flash(f"Gagal memperbarui draft rekap manual dari buku: {exc}", "danger")
    else:
        selected_bill_to_type = batch.bill_to_type or "MANDOR_EXISTING"
        if selected_bill_to_type == "MANDOR":
            selected_bill_to_type = "MANDOR_EXISTING"
        elif selected_bill_to_type == "CLIENT":
            selected_bill_to_type = "CLIENT_EXISTING"
        form_values = {
            "bill_to_type": selected_bill_to_type,
            "mandor_id": str(batch.mandor_id or ""),
            "client_id": str(batch.client_id or ""),
            "bill_to_name_snapshot": batch.bill_to_name_snapshot or "",
            "bill_to_phone_snapshot": batch.bill_to_phone_snapshot or "",
            "bill_to_address_snapshot": batch.bill_to_address_snapshot or "",
            "bill_to_notes": batch.bill_to_notes or "",
            "period_start": batch.period_start.isoformat() if batch.period_start else "",
            "period_end": batch.period_end.isoformat() if batch.period_end else "",
            "notes": batch.notes or "",
        }
        existing_catering_rows = _manual_backfill_existing_catering_rows(batch, minimum=0)
        default_rows = max(len(_manual_backfill_period_dates(form_values["period_start"], form_values["period_end"])), len(existing_catering_rows), 1)
        catering_form_rows = _manual_backfill_catering_rows_for_period(
            form_values["period_start"],
            form_values["period_end"],
            existing_catering_rows,
            minimum=default_rows,
        )
        warung_form_rows = _manual_backfill_existing_warung_rows(batch, default_warung_rows)

    return render_template(
        "finance/manual_billing_backfill_form.html",
        mandors=mandors,
        clients=clients,
        form_values=form_values,
        catering_form_rows=catering_form_rows,
        warung_form_rows=warung_form_rows,
        default_rows=default_rows,
        default_warung_rows=default_warung_rows,
        action_url=url_for("finance.edit_manual_billing_backfill_batch", batch_id=batch.id),
        page_title=f"Edit Draft Rekap Manual {batch.batch_number}",
        page_subtitle="Edit hanya diizinkan saat rekap masih Draft dan belum dibuat invoice/piutang.",
        mode_badge="Edit Draft",
        form_confirm="Simpan perubahan draft rekap manual ini?",
        submit_heading="Simpan Perubahan Draft",
        submit_help="Perubahan hanya berlaku pada draft. Setelah rekap dikunci, data tidak bisa diedit lewat halaman ini.",
        submit_label="Simpan Perubahan",
        submit_icon="bi-pencil-square",
        edit_batch=batch,
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def manual_billing_batch_detail(batch_id):
    from app.models.finance import ManualBillingBatch
    from app.services.billing_input_source_service import build_input_source_context
    from app.services.manual_backfill_billing_service import (
        MANUAL_BACKFILL_STATUS_DRAFT,
        MANUAL_BACKFILL_STATUS_LOCKED,
        build_manual_backfill_duplicate_guard_context,
        get_manual_backfill_status_context,
        get_manual_backfill_bill_to_context,
    )

    batch = ManualBillingBatch.query.filter_by(
        id=batch_id,
        branch_id=current_user.branch_id,
    ).first_or_404()

    catering_total = sum(float(item.subtotal or 0) for item in batch.items if item.item_type == "CATERING")
    warung_total = sum(float(item.subtotal or 0) for item in batch.items if item.item_type == "WARUNG_DEBT")
    other_total = sum(float(item.subtotal or 0) for item in batch.items if item.item_type not in {"CATERING", "WARUNG_DEBT"})
    status_context = get_manual_backfill_status_context(batch.status)
    duplicate_guard = build_manual_backfill_duplicate_guard_context(batch)
    from app.services.billing_trace_service import build_manual_billing_batch_trace_context
    billing_trace = build_manual_billing_batch_trace_context(batch)

    return render_template(
        "finance/manual_billing_batch_detail.html",
        batch=batch,
        input_source_context=build_input_source_context(batch.input_source),
        status_context=status_context,
        bill_to_context=get_manual_backfill_bill_to_context(batch),
        duplicate_guard=duplicate_guard,
        billing_trace=billing_trace,
        lock_idempotency_key=uuid4().hex,
        create_invoice_idempotency_key=uuid4().hex,
        can_edit=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status == MANUAL_BACKFILL_STATUS_DRAFT
            and not batch.invoice_id
        ),
        can_void=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status in {MANUAL_BACKFILL_STATUS_DRAFT, MANUAL_BACKFILL_STATUS_LOCKED}
            and not batch.invoice_id
        ),
        can_lock=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status == MANUAL_BACKFILL_STATUS_DRAFT
            and not batch.invoice_id
            and not duplicate_guard["has_conflicts"]
        ),
        can_create_invoice=(
            batch.input_source == "MANUAL_BACKFILL"
            and batch.status == MANUAL_BACKFILL_STATUS_LOCKED
            and not batch.invoice_id
            and not duplicate_guard["has_conflicts"]
        ),
        is_locked=batch.status == MANUAL_BACKFILL_STATUS_LOCKED,
        catering_total=catering_total,
        warung_total=warung_total,
        other_total=other_total,
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>/print")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def print_manual_billing_batch(batch_id):
    from app.models.finance import ManualBillingBatch
    from app.services.billing_input_source_service import INPUT_SOURCE_MANUAL_BACKFILL
    from app.services.manual_backfill_billing_service import build_manual_backfill_print_context

    batch = ManualBillingBatch.query.filter_by(
        id=batch_id,
        branch_id=current_user.branch_id,
        input_source=INPUT_SOURCE_MANUAL_BACKFILL,
    ).first_or_404()

    context = build_manual_backfill_print_context(batch)
    return render_template(
        "finance/print_manual_billing_batch.html",
        company_settings=get_company_settings(current_user.branch_id),
        **context,
    )


@finance_bp.route("/manual-billing/batches/<int:batch_id>/lock", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def lock_manual_billing_batch_route(batch_id):
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        lock_manual_backfill_batch_record,
    )

    idempotency_key = (request.form.get("idempotency_key") or "").strip() or uuid4().hex
    try:
        idempotency_record, reserved = reserve_idempotency_key(
            scope="FINANCE_MANUAL_BACKFILL_LOCK",
            key=idempotency_key,
            branch_id=current_user.branch_id,
            user_id=current_user.id,
            request_payload={"batch_id": batch_id},
        )
    except IdempotencyConflictError:
        flash("Submit lock rekap berbeda memakai idempotency key yang sama. Muat ulang halaman lalu coba lagi.", "warning")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))

    if not reserved:
        flash("Submit lock rekap ini sudah pernah diproses.", "info")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))

    try:
        batch = lock_manual_backfill_batch_record(
            batch_id=batch_id,
            branch_id=current_user.branch_id,
            locked_by=current_user.id,
        )
        mark_idempotency_completed(
            idempotency_record,
            reference_type="MANUAL_BILLING_BATCH",
            reference_id=batch.id,
            response_payload={"batch_id": batch.id, "status": getattr(batch, "status", None)},
            commit=True,
        )
        flash(f"Rekap manual dari buku {batch.batch_number} berhasil dikunci.", "success")
    except ManualBackfillBillingError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5947")
        flash(f"Gagal mengunci rekap manual dari buku: {exc}", "danger")

    return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))


@finance_bp.route("/manual-billing/batches/<int:batch_id>/void", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def void_manual_billing_batch_route(batch_id):
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        void_manual_backfill_batch_record,
    )
    from app.services.approval_service import ApprovalError, ensure_action_has_approval

    reason = (request.form.get("void_reason") or request.form.get("reason") or "").strip()
    if not reason:
        flash("Alasan void wajib diisi agar bisa diajukan ke maker-checker.", "warning")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))

    try:
        approved, approval_request, approval_message = ensure_action_has_approval(
            branch_id=current_user.branch_id,
            action_key="MANUAL_BACKFILL_VOID",
            reference_type="MANUAL_BILLING_BATCH",
            reference_id=batch_id,
            requested_by=current_user.id,
            requested_reason=reason,
            payload={"batch_id": batch_id, "reason": reason},
        )
    except ApprovalError as exc:
        flash(str(exc), "warning")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))

    if not approved:
        flash(f"{approval_message} Request #{approval_request.id}.", "info")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))

    try:
        batch = void_manual_backfill_batch_record(
            batch_id=batch_id,
            branch_id=current_user.branch_id,
            voided_by=current_user.id,
            reason=reason,
        )
        flash(f"Rekap manual dari buku {batch.batch_number} berhasil dibatalkan sebelum menjadi invoice/piutang.", "success")
    except ManualBackfillBillingError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:5973")
        flash(f"Gagal membatalkan rekap manual dari buku: {exc}", "danger")

    return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))


@finance_bp.route("/manual-billing/batches/<int:batch_id>/create-invoice", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_manual_backfill_invoice_route(batch_id):
    from app.services.manual_backfill_billing_service import (
        ManualBackfillBillingError,
        create_invoice_from_manual_backfill_batch_record,
    )

    notes = (request.form.get("notes") or "").strip() or None
    idempotency_key = (request.form.get("idempotency_key") or "").strip() or uuid4().hex

    try:
        idempotency_record, reserved = reserve_idempotency_key(
            scope="FINANCE_MANUAL_BACKFILL_CREATE_INVOICE",
            key=idempotency_key,
            branch_id=current_user.branch_id,
            user_id=current_user.id,
            request_payload={"batch_id": batch_id, "notes": notes or ""},
        )
    except IdempotencyConflictError:
        flash("Submit create invoice berbeda memakai idempotency key yang sama. Muat ulang halaman lalu coba lagi.", "warning")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))

    if not reserved:
        flash("Submit create invoice ini sudah pernah diproses.", "info")
        return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))

    try:
        batch, invoice = create_invoice_from_manual_backfill_batch_record(
            batch_id=batch_id,
            branch_id=current_user.branch_id,
            created_by=current_user.id,
            notes=notes,
        )
        mark_idempotency_completed(
            idempotency_record,
            reference_type="INVOICE",
            reference_id=invoice.id,
            response_payload={"batch_id": batch.id, "invoice_id": invoice.id},
            commit=True,
        )
        flash(f"Rekap manual dari buku {batch.batch_number} berhasil dibuat menjadi invoice {invoice.invoice_number} dan piutang aktif.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    except ManualBackfillBillingError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6000")
        flash(f"Gagal membuat invoice dari rekap manual dari buku: {exc}", "danger")

    return redirect(url_for("finance.manual_billing_batch_detail", batch_id=batch_id))


@finance_bp.route("/manual-billing/create", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def create_manual_billing_invoice_route():
    from app.services.manual_billing_service import ManualBillingError, create_manual_billing_invoice_record

    mandor_id = (request.form.get("mandor_id") or "").strip()
    period_start_value = (request.form.get("period_start") or "").strip()
    period_end_value = (request.form.get("period_end") or "").strip()
    client_pic_id = request.form.get("client_pic_id", type=int)
    notes = request.form.get("notes")

    period_start = _period_parse_date(period_start_value)
    period_end = _period_parse_date(period_end_value)

    if not mandor_id or not period_start or not period_end:
        flash(f"{T.sub_client} dan periode wajib diisi.", "warning")
        return redirect(url_for("finance.manual_billing"))

    try:
        batch, invoice = create_manual_billing_invoice_record(
            branch_id=current_user.branch_id,
            mandor_id=int(mandor_id),
            period_start=period_start,
            period_end=period_end,
            client_pic_id=client_pic_id,
            created_by=current_user.id,
            notes=notes,
        )
        flash(f"Rekap billing manual {batch.batch_number} berhasil dibuat menjadi invoice {invoice.invoice_number}.", "success")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    except ManualBillingError as exc:
        flash(str(exc), "warning")
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:6038")
        flash(f"Gagal membuat invoice dari rekap tagihan {T.sub_client_lower}: {exc}", "danger")

    return redirect(url_for(
        "finance.manual_billing",
        mandor_id=mandor_id,
        period_start=period_start_value,
        period_end=period_end_value,
    ))
