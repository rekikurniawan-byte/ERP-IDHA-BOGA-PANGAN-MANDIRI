from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import current_user
from app.utils.clock import today_wib, to_wib
from app.utils.decorators import role_required
from app.services.audit_log_service import record_audit_log
from app.services.ops_navigation_service import uses_ops_ui

from app.models.operational import DailyOrder, DailyOrderDetail, OrderHppSnapshot, OrderHppStockConsumption
from app.models.production import Production
from app.models.delivery import Delivery, DeliveryDetail
from app.models.master import Mandor, DeliveryLocation, User
from app.services.operational_service import (
    get_or_create_daily_order,
    add_or_update_order_detail,
    add_increase_after_lock,
    lock_daily_order,
    revise_order_detail,
    update_order_hpp_defaults,
)

from app.services.production_service import generate_production_from_order
from app.services.delivery_service import (
    get_delivery_summary_for_order,
    get_delivery_next_actions_for_order,
    get_ready_delivery_next_actions_for_order,
)

from app.services.order_hpp_snapshot_service import (
    create_order_hpp_snapshot,
    get_active_hpp_master_data,
    get_order_meal_summary,
)
from app.services.hpp_stock_consumption_service import (
    build_hpp_stock_consumption_dry_run,
    commit_hpp_stock_consumption,
    get_existing_stock_consumption,
)
from app.services.catering_report_service import (
    build_daily_catering_log,
    build_monthly_catering_recap,
    get_active_mandors,
    parse_date,
    parse_month,
)
from app.services.global_filter_service import (
    build_filter_bar_context,
    resolve_date_filter,
    apply_date_range_to_query,
)
from app.utils.terms import T


operational_bp = Blueprint("operational", __name__, url_prefix="/operational")


def _is_active_record(record):
    """
    Filter aman untuk master data aktif.
    Support beberapa kemungkinan field:
    - is_active = True/False
    - status = ACTIVE/INACTIVE
    """
    if hasattr(record, "is_active"):
        return bool(record.is_active)

    if hasattr(record, "status"):
        return str(record.status).upper() in ["ACTIVE", "AKTIF"]

    return True


def _belongs_to_user_branch(record):
    """
    Filter aman untuk cabang.
    Beberapa tabel punya branch_id langsung.
    DeliveryLocation tidak punya branch_id, jadi dicek lewat mandor.branch_id.
    """
    user_branch_id = current_user.branch_id

    if hasattr(record, "branch_id"):
        return record.branch_id == user_branch_id

    if hasattr(record, "mandor") and record.mandor:
        if hasattr(record.mandor, "branch_id"):
            return record.mandor.branch_id == user_branch_id

    if hasattr(record, "mandor_id") and record.mandor_id:
        mandor = Mandor.query.get(record.mandor_id)
        if mandor and hasattr(mandor, "branch_id"):
            return mandor.branch_id == user_branch_id

    return True


def get_form_master_data():
    mandors = [
        mandor for mandor in Mandor.query.order_by(Mandor.name.asc()).all()
        if _is_active_record(mandor) and _belongs_to_user_branch(mandor)
    ]

    locations = [
        location for location in DeliveryLocation.query.order_by(DeliveryLocation.location_name.asc()).all()
        if _is_active_record(location) and _belongs_to_user_branch(location)
    ]

    return mandors, locations


def _detail_price(mandor_id, delivery_location_id, lunch_qty, dinner_qty):
    """Harga dan ongkir yang dikunci ke baris order baru, plus cek minimal porsi.

    Mengembalikan dict berisi price, price_source, lunch_delivery_fee,
    dinner_delivery_fee -- atau (None, pesan_error). Admin tidak mengetik
    harga; OWNER boleh mengisi harga lain untuk pesanan ini.
    """
    from app.services.pricing_service import min_portion_error, order_trip_fees, resolve_order_price

    mandor = Mandor.query.get(mandor_id)
    client = getattr(mandor, "client", None)
    minimum_error = min_portion_error(
        current_user.branch_id, client, [("siang", lunch_qty), ("malam", dinner_qty)]
    )
    if minimum_error:
        return None, minimum_error
    price, source, error = resolve_order_price(
        branch_id=current_user.branch_id,
        mandor_id=mandor_id,
        actor_role=current_user.role,
        requested_price=request.form.get("price_per_portion"),
    )
    if error:
        return None, error
    lunch_fee, dinner_fee, error = order_trip_fees(
        current_user.branch_id, client, DeliveryLocation.query.get(delivery_location_id), lunch_qty, dinner_qty
    )
    if error:
        return None, error
    return {
        "price_per_portion": price,
        "price_source": source,
        "lunch_delivery_fee": lunch_fee,
        "dinner_delivery_fee": dinner_fee,
    }, None


def _after_detail_saved(daily_order, detail, price, source):
    """Catatan OWNER yang mengubah harga, dan peringatan kalau harga di bawah HPP."""
    from app.services.pricing_service import SOURCE_OWNER, order_hpp_warning, quote_price_for_mandor

    if source == SOURCE_OWNER and detail is not None:
        quote = quote_price_for_mandor(current_user.branch_id, detail.mandor_id)
        listed = f" (daftar harga Rp {quote.price:,.0f})." if quote else " (daftar harga belum diatur)."
        record_audit_log(
            module="PRICING",
            event_type="ORDER_PRICE_OVERRIDE",
            action="UPDATE",
            table_name="daily_order_details",
            record_id=detail.id,
            description=f"OWNER memakai harga Rp {price:,.0f}/porsi untuk order {daily_order.order_number}{listed}",
            metadata={"daily_order_id": daily_order.id, "mandor_id": detail.mandor_id},
        )
    warning = order_hpp_warning(daily_order, price)
    if warning:
        flash(warning, "warning")


def _prepayment_plan(mandor_id, pricing, lunch_qty, dinner_qty):
    """Pelanggan UMUM wajib bayar saat pesanan diinput admin.

    Mengembalikan (rencana, pesan_error). Rencana None = bukan pelanggan umum.
    OWNER boleh meloloskan tanpa pembayaran lunas; itu dicatat di audit log.
    """
    from decimal import Decimal, InvalidOperation

    from app.services.pricing_service import is_general_client

    mandor = Mandor.query.get(mandor_id)
    if not is_general_client(getattr(mandor, "client", None)):
        return None, None
    total = (
        Decimal(str(pricing["price_per_portion"])) * (int(lunch_qty or 0) + int(dinner_qty or 0))
        + Decimal(str(pricing["lunch_delivery_fee"] or 0))
        + Decimal(str(pricing["dinner_delivery_fee"] or 0))
    )
    raw_amount = (request.form.get("prepayment_amount") or "").strip()
    try:
        amount = Decimal(raw_amount.replace(",", "")) if raw_amount else Decimal("0")
    except InvalidOperation:
        return None, "Nominal pembayaran tidak valid."
    if amount > total:
        return None, f"Nominal pembayaran melebihi total pesanan Rp {total:,.0f}."
    override = False
    if amount < total:
        if current_user.role != "OWNER":
            return None, (
                f"Pelanggan umum wajib bayar di muka: total Rp {total:,.0f}, dibayar Rp {amount:,.0f}. "
                "Isi pembayaran lengkap, atau minta OWNER meloloskan."
            )
        override = True
    return {
        "total": total,
        "amount": amount,
        "override": override,
        "payment_method": request.form.get("prepayment_method"),
        "bank_account_id": request.form.get("prepayment_bank_account_id", type=int),
        "reference_number": (request.form.get("prepayment_reference") or "").strip() or None,
    }, None


def _save_detail_with_prepayment(daily_order, plan, **detail_kwargs):
    """Baris order + pembayarannya dalam satu transaksi: gagal satu, gagal semua."""
    from app.services.atomic_transaction_service import atomic_business_action
    from app.services.prepaid_order_service import PrepaymentError, record_detail_prepayment

    try:
        with atomic_business_action(
            module="OPERATIONAL",
            action="GENERAL_ORDER_WITH_PREPAYMENT",
            description=f"Pesanan pelanggan umum + pembayaran di muka, order {daily_order.order_number}.",
            reference_type="daily_order_details",
            user_id=current_user.id,
            branch_id=current_user.branch_id,
            metadata={"total": str(plan["total"]), "amount": str(plan["amount"]), "override": plan["override"]},
        ):
            success, message, detail = add_or_update_order_detail(daily_order=daily_order, commit=False, **detail_kwargs)
            if not success:
                raise PrepaymentError(message)
            if plan["amount"] > 0:
                record_detail_prepayment(
                    detail=detail,
                    amount=plan["amount"],
                    payment_method=plan["payment_method"],
                    created_by=current_user.id,
                    bank_account_id=plan["bank_account_id"],
                    reference_number=plan["reference_number"],
                )
            if plan["override"]:
                record_audit_log(
                    module="OPERATIONAL",
                    event_type="PREPAYMENT_OVERRIDE",
                    action="CREATE",
                    table_name="daily_order_details",
                    record_id=detail.id,
                    description=(
                        f"OWNER meloloskan pesanan pelanggan umum di order {daily_order.order_number} "
                        f"sebelum lunas: total Rp {plan['total']:,.0f}, dibayar Rp {plan['amount']:,.0f}."
                    ),
                    commit=False,
                )
    except PrepaymentError as error:
        return False, str(error), None
    return True, f"{message} Pembayaran di muka Rp {plan['amount']:,.0f} dicatat sebagai uang muka.", detail


def _general_increase_error(mandor_id):
    """Tambah porsi pesanan pelanggan umum belum dibayar di muka: hanya OWNER.

    Tambahan yang diloloskan OWNER tetap tertagih di invoice otomatis sebagai
    sisa tagihan, jadi tidak ada porsi yang lolos tanpa ditagih.
    """
    from app.services.pricing_service import is_general_client

    mandor = Mandor.query.get(mandor_id)
    if is_general_client(getattr(mandor, "client", None)) and current_user.role != "OWNER":
        return (
            "Tambah porsi pesanan pelanggan umum harus dibayar di muka. "
            "Buat pesanan baru dengan pembayaran, atau minta OWNER."
        )
    return None


def _price_quotes(mandors):
    from app.services.pricing_service import price_quotes_by_mandor

    return price_quotes_by_mandor(current_user.branch_id, mandors)


def _bank_accounts():
    from app.models.finance import BankAccount

    return (
        BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True)
        .order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc())
        .all()
    )


def validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
    location = DeliveryLocation.query.get(delivery_location_id)

    if not location:
        return False

    return location.mandor_id == mandor_id




# === PRODUCTION_LOG_CATERING_REKAP_BULANAN_READONLY ===
@operational_bp.route("/daily-log")
@role_required("ADMIN", "FINANCE", "ADMIN_OPERASIONAL")
def daily_catering_log():
    today = today_wib()
    selected_date_value = request.args.get("date", today.strftime("%Y-%m-%d")).strip()
    selected_date = parse_date(selected_date_value, today)

    if selected_date_value and selected_date_value != selected_date.strftime("%Y-%m-%d"):
        flash("Tanggal log catering tidak valid. Sistem menampilkan tanggal hari ini.", "warning")
        selected_date_value = selected_date.strftime("%Y-%m-%d")

    report = build_daily_catering_log(
        branch_id=current_user.branch_id,
        target_date=selected_date,
    )

    return render_template(
        "operational/daily_log.html",
        report=report,
        selected_date=selected_date,
        selected_date_value=selected_date.strftime("%Y-%m-%d"),
    )


@operational_bp.route("/monthly-recap")
@role_required("ADMIN", "FINANCE")
def monthly_catering_recap():
    today = today_wib()
    selected_mandor_id = request.args.get("mandor_id", "").strip()

    # Backward compatibility: if an old ?month=YYYY-MM URL is opened,
    # translate it into the new custom date range once, then keep the
    # Global Filter Bar V2 contract as the visible UI.
    legacy_month_value = request.args.get("month", "").strip()
    mutable_args = request.args.copy()
    if legacy_month_value and not mutable_args.get("start_date") and not mutable_args.get("end_date"):
        legacy_year, legacy_month = parse_month(legacy_month_value, today)
        legacy_start, legacy_end = date(legacy_year, legacy_month, 1), date(legacy_year, legacy_month, 1)
        from calendar import monthrange
        legacy_end = date(legacy_year, legacy_month, monthrange(legacy_year, legacy_month)[1])
        mutable_args["period_preset"] = "custom"
        mutable_args["start_date"] = legacy_start.isoformat()
        mutable_args["end_date"] = legacy_end.isoformat()

    date_filter = resolve_date_filter(
        mutable_args,
        start_key="start_date",
        end_key="end_date",
        preset_key="period_preset",
        default_preset="this_month",
        today=today,
    )

    range_anchor = date_filter.start_date or today
    year, month = range_anchor.year, range_anchor.month

    mandor_id = None
    if selected_mandor_id:
        try:
            mandor_id = int(selected_mandor_id)
        except (TypeError, ValueError):
            mandor_id = None
            selected_mandor_id = ""
            flash(f"Filter {T.sub_client_lower} tidak valid. Filter {T.sub_client_lower} diabaikan.", "warning")

    mandors = get_active_mandors(current_user.branch_id)
    if mandor_id and all(int(mandor.id) != mandor_id for mandor in mandors):
        flash(f"{T.sub_client}/PIC lapangan tidak sesuai cabang user. Filter {T.sub_client_lower} diabaikan.", "warning")
        mandor_id = None
        selected_mandor_id = ""

    report = build_monthly_catering_recap(
        branch_id=current_user.branch_id,
        year=year,
        month=month,
        mandor_id=mandor_id,
        start_date=date_filter.start_date,
        end_date=date_filter.end_date,
    )

    mandor_options = [{"value": "", "label": f"Semua {T.sub_client_lower}"}] + [
        {"value": str(mandor.id), "label": mandor.name}
        for mandor in mandors
    ]
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("operational.monthly_catering_recap"),
        reset_url=url_for("operational.monthly_catering_recap"),
        title="Filter Rekap Catering",
        description=f"Pilih preset atau tanggal custom untuk rekap catering, lalu filter {T.sub_client_lower}/PIC jika dibutuhkan.",
        preset_name="period_preset",
        start_name="start_date",
        end_name="end_date",
        extra_selects=[{
            "name": "mandor_id",
            "label": f"{T.sub_client} / PIC",
            "value": str(mandor_id or ""),
            "options": mandor_options,
        }],
    )

    return render_template(
        "operational/monthly_recap.html",
        report=report,
        mandors=mandors,
        selected_mandor_id=str(mandor_id or ""),
        month_value=report["month_value"],
        filter_bar=filter_bar,
    )

_DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_MONTHS_ID = ["", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]


def _format_id_date_full(d: date) -> str:
    return f"{_DAYS_ID[d.weekday()]}, {d.day} {_MONTHS_ID[d.month]} {d.year}"



def _order_form_context():
    """Data pilihan pop-up Input Order: sama persis dengan halaman create_order."""
    mandors, locations = get_form_master_data()
    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)
    return {
        "form_mandors": mandors,
        "form_locations": locations,
        "price_quotes": _price_quotes(mandors),
        "bank_accounts": _bank_accounts(),
        "menus": menus,
        "packaging_profiles": packaging_profiles,
        "overhead_profiles": overhead_profiles,
    }

@operational_bp.route("/orders")
@role_required("ADMIN", "ADMIN_OPERASIONAL")
def orders():
    if uses_ops_ui(current_user):
        daily_orders = DailyOrder.query.filter_by(
            branch_id=current_user.branch_id
        ).order_by(DailyOrder.order_date.desc(), DailyOrder.id.desc()).all()
        return render_template("ops/orders.html", daily_orders=daily_orders)

    today = today_wib()
    tomorrow = today + timedelta(days=1)
    today_formatted = _format_id_date_full(today)

    today_order = DailyOrder.query.filter_by(
        branch_id=current_user.branch_id,
        order_date=today
    ).first()

    tomorrow_order = DailyOrder.query.filter_by(
        branch_id=current_user.branch_id,
        order_date=tomorrow
    ).first()

    def _build_card_meta(order):
        if not order:
            return None
        lunch = sum(d.lunch_qty for d in order.details)
        dinner = sum(d.dinner_qty for d in order.details)
        total = sum(d.total_qty for d in order.details)
        locations = len(order.details)

        # Cek produksi
        prods = Production.query.filter_by(
            branch_id=order.branch_id,
            production_date=order.order_date
        ).all()
        has_production = len(prods) > 0
        production_done = has_production and all(p.status == "COMPLETED" for p in prods)

        # Cek pengiriman
        detail_ids = [d.id for d in order.details]
        has_delivery = False
        delivery_done = False
        if detail_ids:
            deliv_details = DeliveryDetail.query.filter(
                DeliveryDetail.daily_order_detail_id.in_(detail_ids)
            ).all()
            if deliv_details:
                has_delivery = True
                deliv_ids = list(set(dd.delivery_id for dd in deliv_details))
                delivs = Delivery.query.filter(Delivery.id.in_(deliv_ids)).all()
                delivery_done = bool(delivs) and all(d.status in ("DELIVERED", "COMPLETED") for d in delivs)

        step_konsep = "done" if order.is_locked else "active"
        step_kunci = "done" if order.is_locked else "pending"
        step_prod = "done" if production_done else ("active" if has_production else "pending")
        step_kirim = "done" if delivery_done else ("active" if has_delivery else "pending")

        return {
            "order": order,
            "lunch_qty": lunch,
            "dinner_qty": dinner,
            "total_qty": total,
            "locations_count": locations,
            "has_production": has_production,
            "step_konsep": step_konsep,
            "step_kunci": step_kunci,
            "step_prod": step_prod,
            "step_kirim": step_kirim,
        }

    today_card = _build_card_meta(today_order)
    tomorrow_card = _build_card_meta(tomorrow_order)

    from app.services.ops_timeline_service import build_session_timeline, get_order_lock_countdowns
    timeline = build_session_timeline(current_user.branch_id, today)
    today_countdowns = get_order_lock_countdowns(today_order, on_date=today, branch_id=current_user.branch_id)
    tomorrow_countdowns = get_order_lock_countdowns(tomorrow_order, on_date=tomorrow, branch_id=current_user.branch_id)

    overdue_unlocked_count = DailyOrder.query.filter(
        DailyOrder.branch_id == current_user.branch_id,
        DailyOrder.order_date < today,
        DailyOrder.is_locked == False,
        DailyOrder.status != "CANCELLED",
    ).count()

    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    status_filter = (request.args.get("status") or "ALL").upper().strip()
    if status_filter not in ["ALL", "DRAFT", "LOCKED", "OVERDUE"]:
        status_filter = "ALL"

    query = DailyOrder.query.filter_by(branch_id=current_user.branch_id)
    if status_filter == "OVERDUE":
        query = query.filter(DailyOrder.order_date < today, DailyOrder.is_locked == False, DailyOrder.status != "CANCELLED")
    else:
        query = apply_date_range_to_query(query, DailyOrder.order_date, date_filter)
        if status_filter == "DRAFT":
            query = query.filter(DailyOrder.is_locked == False)
        elif status_filter == "LOCKED":
            query = query.filter(DailyOrder.is_locked == True)

    page = request.args.get("page", 1, type=int)
    pagination = query.order_by(DailyOrder.order_date.desc(), DailyOrder.id.desc()).paginate(
        page=page, per_page=20, error_out=False
    )
    daily_orders = pagination.items

    order_dates = list(set(o.order_date for o in daily_orders))
    existing_prod_dates = set()
    if order_dates:
        prods_batch = Production.query.filter(
            Production.branch_id == current_user.branch_id,
            Production.production_date.in_(order_dates)
        ).with_entities(Production.production_date).all()
        existing_prod_dates = set(p[0] for p in prods_batch)

    table_orders = []
    for order in daily_orders:
        lunch = sum(d.lunch_qty for d in order.details)
        dinner = sum(d.dinner_qty for d in order.details)
        total = sum(d.total_qty for d in order.details)
        is_today = (order.order_date == today)
        is_tomorrow = (order.order_date == tomorrow)
        is_overdue = (order.order_date < today and not order.is_locked and order.status != "CANCELLED")
        day_name = _DAYS_ID[order.order_date.weekday()]
        has_prod = order.order_date in existing_prod_dates

        table_orders.append({
            "order": order,
            "lunch_qty": lunch,
            "dinner_qty": dinner,
            "total_qty": total,
            "locations_count": len(order.details),
            "is_today": is_today,
            "is_tomorrow": is_tomorrow,
            "is_overdue": is_overdue,
            "day_name": day_name,
            "has_production": has_prod,
        })

    date_groups = {}
    for item in table_orders:
        d = item["order"].order_date
        if d not in date_groups:
            date_groups[d] = {"count": 0, "total_qty": 0}
        date_groups[d]["count"] += 1
        date_groups[d]["total_qty"] += item["total_qty"]

    for item in table_orders:
        item["date_summary"] = date_groups[item["order"].order_date]

    status_options = [
        {"value": "ALL", "label": "Semua Status"},
        {"value": "DRAFT", "label": "Konsep (Belum Kunci)"},
        {"value": "LOCKED", "label": "Terkunci"},
        {"value": "OVERDUE", "label": "Lewat Tanggal Belum Kunci"},
    ]
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("operational.orders"),
        reset_url=url_for("operational.orders"),
        title="Filter Order Harian",
        description="Filter berdasarkan rentang tanggal dan status order.",
        status_name="status",
        status_value=status_filter,
        status_options=status_options,
    )

    return render_template(
        "operational/orders.html",
        today=today,
        tomorrow=tomorrow,
        today_formatted=today_formatted,
        today_card=today_card,
        tomorrow_card=tomorrow_card,
        today_countdowns=today_countdowns,
        tomorrow_countdowns=tomorrow_countdowns,
        timeline=timeline,
        overdue_unlocked_count=overdue_unlocked_count,
        table_orders=table_orders,
        pagination=pagination,
        daily_orders=daily_orders,
        filter_bar=filter_bar,
        **_order_form_context(),
    )


@operational_bp.route("/orders/create", methods=["GET", "POST"])
@role_required("ADMIN", "ADMIN_OPERASIONAL")
def create_order():
    mandors, locations = get_form_master_data()
    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)

    if request.method == "POST":
        order_date = datetime.strptime(request.form.get("order_date"), "%Y-%m-%d").date()
        mandor_id = int(request.form.get("mandor_id"))
        delivery_location_id = int(request.form.get("delivery_location_id"))
        lunch_qty = int(request.form.get("lunch_qty") or 0)
        dinner_qty = int(request.form.get("dinner_qty") or 0)
        notes = request.form.get("notes")

        if not validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
            flash(f"{T.location} tidak sesuai dengan {T.sub_client_lower} yang dipilih.", "warning")
            return redirect(url_for("operational.create_order"))

        pricing, price_error = _detail_price(mandor_id, delivery_location_id, lunch_qty, dinner_qty)
        if not price_error:
            prepayment, price_error = _prepayment_plan(mandor_id, pricing, lunch_qty, dinner_qty)
        if price_error:
            flash(price_error, "warning")
            return redirect(url_for("operational.create_order"))

        daily_order = get_or_create_daily_order(
            branch_id=current_user.branch_id,
            order_date=order_date,
            created_by=current_user.id,
            notes=notes
        )

        if daily_order.is_locked:
            flash(
                "Order untuk tanggal ini sudah dikunci. Gunakan tombol Tambah Revisi Setelah Lock dari halaman Kelola Order.",
                "warning"
            )
            return redirect(url_for("operational.order_detail", order_id=daily_order.id))

        defaults_success, defaults_message = update_order_hpp_defaults(daily_order, request.form)
        if not defaults_success:
            flash(defaults_message, "warning")
            return redirect(url_for("operational.create_order"))

        detail_kwargs = dict(
            mandor_id=mandor_id,
            delivery_location_id=delivery_location_id,
            lunch_qty=lunch_qty,
            dinner_qty=dinner_qty,
            notes=notes,
            actor_role=current_user.role,
            **pricing,
        )
        if prepayment is None:
            success, message, detail = add_or_update_order_detail(daily_order=daily_order, **detail_kwargs)
        else:
            success, message, detail = _save_detail_with_prepayment(daily_order, prepayment, **detail_kwargs)

        flash(message, "success" if success else "warning")
        if success:
            _after_detail_saved(daily_order, detail, pricing["price_per_portion"], pricing["price_source"])
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "ops/order_form.html" if uses_ops_ui(current_user) else "operational/order_form.html",
        mandors=mandors,
        price_quotes=_price_quotes(mandors),
        bank_accounts=_bank_accounts(),
        locations=locations,
        daily_order=None,
        form_action=url_for("operational.create_order"),
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
        show_hpp_defaults=True,
    )

@operational_bp.route("/orders/<int:order_id>/add-detail", methods=["GET", "POST"])
@role_required("ADMIN", "ADMIN_OPERASIONAL")
def add_order_detail(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if daily_order.is_locked:
        flash(f"Order sudah dikunci. Tambah lokasi/{T.sub_client_lower} biasa tidak bisa dilakukan. Gunakan revisi tambah jika diperlukan.", "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    mandors, locations = get_form_master_data()

    if request.method == "POST":
        mandor_id = int(request.form.get("mandor_id"))
        delivery_location_id = int(request.form.get("delivery_location_id"))
        lunch_qty = int(request.form.get("lunch_qty") or 0)
        dinner_qty = int(request.form.get("dinner_qty") or 0)
        notes = request.form.get("notes")

        if not validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
            flash(f"{T.location} tidak sesuai dengan {T.sub_client_lower} yang dipilih.", "warning")
            return redirect(url_for("operational.add_order_detail", order_id=daily_order.id))

        pricing, price_error = _detail_price(mandor_id, delivery_location_id, lunch_qty, dinner_qty)
        if not price_error:
            prepayment, price_error = _prepayment_plan(mandor_id, pricing, lunch_qty, dinner_qty)
        if price_error:
            flash(price_error, "warning")
            return redirect(url_for("operational.add_order_detail", order_id=daily_order.id))

        detail_kwargs = dict(
            mandor_id=mandor_id,
            delivery_location_id=delivery_location_id,
            lunch_qty=lunch_qty,
            dinner_qty=dinner_qty,
            notes=notes,
            actor_role=current_user.role,
            **pricing,
        )
        if prepayment is None:
            success, message, detail = add_or_update_order_detail(daily_order=daily_order, **detail_kwargs)
        else:
            success, message, detail = _save_detail_with_prepayment(daily_order, prepayment, **detail_kwargs)

        flash(message, "success" if success else "warning")
        if success:
            _after_detail_saved(daily_order, detail, pricing["price_per_portion"], pricing["price_source"])
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "ops/order_form.html" if uses_ops_ui(current_user) else "operational/order_form.html",
        mandors=mandors,
        price_quotes=_price_quotes(mandors),
        bank_accounts=_bank_accounts(),
        locations=locations,
        daily_order=daily_order,
        form_action=url_for("operational.add_order_detail", order_id=daily_order.id)
    )


@operational_bp.route("/orders/<int:order_id>/add-increase-after-lock", methods=["GET", "POST"])
@role_required("ADMIN", "ADMIN_OPERASIONAL")
def add_increase_after_lock_route(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if not daily_order.is_locked:
        flash(f"Order belum dikunci. Gunakan tambah lokasi/{T.sub_client_lower} biasa.", "warning")
        return redirect(url_for("operational.add_order_detail", order_id=daily_order.id))

    mandors, locations = get_form_master_data()

    if request.method == "POST":
        mandor_id = int(request.form.get("mandor_id"))
        delivery_location_id = int(request.form.get("delivery_location_id"))
        lunch_qty = int(request.form.get("lunch_qty") or 0)
        dinner_qty = int(request.form.get("dinner_qty") or 0)
        notes = request.form.get("notes") or "Penambahan order setelah lock"

        if not validate_location_belongs_to_mandor(mandor_id, delivery_location_id):
            flash(f"{T.location} tidak sesuai dengan {T.sub_client_lower} yang dipilih.", "warning")
            return redirect(url_for("operational.add_increase_after_lock_route", order_id=daily_order.id))

        pricing, price_error = _detail_price(mandor_id, delivery_location_id, lunch_qty, dinner_qty)
        if not price_error:
            price_error = _general_increase_error(mandor_id)
        if price_error:
            flash(price_error, "warning")
            return redirect(url_for("operational.add_increase_after_lock_route", order_id=daily_order.id))

        success, message, detail = add_increase_after_lock(
            daily_order=daily_order,
            mandor_id=mandor_id,
            delivery_location_id=delivery_location_id,
            lunch_qty=lunch_qty,
            dinner_qty=dinner_qty,
            reason=notes,
            created_by=current_user.id,
            actor_role=current_user.role,
            **pricing,
        )

        if success:
            _after_detail_saved(daily_order, detail, pricing["price_per_portion"], pricing["price_source"])
            production_success, production_message = generate_production_from_order(
                daily_order,
                current_user.id
            )

            if production_success:
                flash("Revisi tambah setelah dikunci berhasil disimpan dan rencana produksi ikut diperbarui.", "success")
            else:
                flash(f"Revisi tambah tersimpan, tetapi produksi belum tersinkron: {production_message}", "warning")
        else:
            flash(message, "warning")

        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "ops/order_form.html" if uses_ops_ui(current_user) else "operational/order_form.html",
        mandors=mandors,
        price_quotes=_price_quotes(mandors),
        bank_accounts=_bank_accounts(),
        locations=locations,
        daily_order=daily_order,
        form_action=url_for("operational.add_increase_after_lock_route", order_id=daily_order.id),
        is_after_lock=True
    )

@operational_bp.route("/orders/<int:order_id>")
@role_required("ADMIN", "DAPUR", "PENGANTAR", "ADMIN_OPERASIONAL")
def order_detail(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    total_lunch = sum(detail.lunch_qty for detail in daily_order.details)
    total_dinner = sum(detail.dinner_qty for detail in daily_order.details)
    total_locations = len(daily_order.details)
    unique_mandors = len(set(detail.mandor_id for detail in daily_order.details))

    lunch_delivery_data = get_delivery_summary_for_order(
        daily_order=daily_order,
        delivery_type="LUNCH"
    )

    dinner_delivery_data = get_delivery_summary_for_order(
        daily_order=daily_order,
        delivery_type="DINNER"
    )

    hpp_snapshots = OrderHppSnapshot.query.filter_by(
        daily_order_id=daily_order.id,
        branch_id=current_user.branch_id,
    ).order_by(OrderHppSnapshot.id.desc()).all()

    latest_hpp_snapshot = hpp_snapshots[0] if hpp_snapshots else None

    delivery_next_actions = get_delivery_next_actions_for_order(daily_order)
    delivery_ready_actions = get_ready_delivery_next_actions_for_order(daily_order)

    from app.services.kitchen_recap_service import get_session_print_history
    lunch_print_status = get_session_print_history(daily_order, "LUNCH")
    dinner_print_status = get_session_print_history(daily_order, "DINNER")

    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)
    meal_summary = get_order_meal_summary(daily_order)
    form_mandors, form_locations = get_form_master_data()

    from app.services.ops_timeline_service import get_order_lock_countdowns
    order_countdowns = get_order_lock_countdowns(daily_order)

    # Butir 1: Riwayat Perubahan Porsi gabungan (OrderRevision + OrderQtyChange)
    # Temuan audit: OrderRevision.revision_time disimpan dalam UTC naif (datetime.utcnow),
    # sehingga dikonversi ke WIB lewat to_wib(). Sedangkan OrderQtyChange.changed_at disimpan WIB (now_wib).
    from app.services.auto_order_service import PORTION_ZERO_REASONS

    user_ids = {rev.created_by for detail in daily_order.details for rev in detail.revisions if rev.created_by}
    user_map = {}
    if user_ids:
        users = User.query.filter(User.id.in_(user_ids)).all()
        user_map = {u.id: (u.full_name or u.username) for u in users}

    portion_history = []
    for detail in daily_order.details:
        mandor_name = detail.mandor.name if detail.mandor else "-"
        location_name = detail.delivery_location.location_name if detail.delivery_location else "-"
        mandor_loc = f"{mandor_name} / {location_name}"

        # 1. OrderRevision (jalur revisi lama)
        for rev in detail.revisions:
            wib_dt = to_wib(rev.revision_time)
            changes = []
            if rev.lunch_qty_change != 0:
                changes.append(f"Siang {'+' if rev.lunch_qty_change > 0 else ''}{rev.lunch_qty_change}")
            if rev.dinner_qty_change != 0:
                changes.append(f"Sore {'+' if rev.dinner_qty_change > 0 else ''}{rev.dinner_qty_change}")
            change_label = ", ".join(changes) if changes else (rev.revision_direction or "-")

            if rev.lunch_qty_change != 0 and rev.dinner_qty_change != 0:
                sesi = "Siang & Sore"
            elif rev.lunch_qty_change != 0:
                sesi = "Siang"
            elif rev.dinner_qty_change != 0:
                sesi = "Sore"
            else:
                sesi = "-"

            user_disp = user_map.get(rev.created_by, f"User #{rev.created_by}" if rev.created_by else "-")
            portion_history.append({
                "timestamp": wib_dt,
                "time_str": wib_dt.strftime("%d/%m/%Y %H.%M") if wib_dt else "-",
                "mandor_location": mandor_loc,
                "mandor_name": mandor_name,
                "location_name": location_name,
                "session": sesi,
                "change_text": change_label,
                "source": "Revisi lama",
                "source_badge": "secondary",
                "price": rev.price_per_portion,  # harga yang dipakai menagih porsi tambahan setelah kunci
                "user_name": user_disp,
                "reason": rev.reason or "-",
            })

        # 2. OrderQtyChange (jalur ubah porsi baru)
        for qc in detail.qty_changes:
            wib_dt = qc.changed_at
            sesi = "Siang" if qc.meal_type == "LUNCH" else ("Sore" if qc.meal_type in ("DINNER", "SORE") else qc.meal_type)
            change_label = f"{sesi} {qc.old_qty} → {qc.new_qty}"

            if qc.source == "AUTO":
                src_label = "Otomatis 18.00"
                src_badge = "info"
            elif qc.source == "PORTAL":
                src_label = "Portal"
                src_badge = "primary"
            elif qc.source == "ADMIN":
                src_label = "Ubah Porsi Admin"
                src_badge = "warning"
            else:
                src_label = qc.source or "-"
                src_badge = "secondary"

            user_disp = (qc.user.full_name or qc.user.username) if qc.user else ("Sistem Penjadwal" if qc.source == "AUTO" else "-")
            reason_disp = qc.note or PORTION_ZERO_REASONS.get(qc.reason_code, qc.reason_code) or "-"

            portion_history.append({
                "timestamp": wib_dt,
                "time_str": wib_dt.strftime("%d/%m/%Y %H.%M") if wib_dt else "-",
                "mandor_location": mandor_loc,
                "mandor_name": mandor_name,
                "location_name": location_name,
                "session": sesi,
                "change_text": change_label,
                "source": src_label,
                "source_badge": src_badge,
                "price": None,  # ubah porsi memakai harga detail order
                "user_name": user_disp,
                "reason": reason_disp,
            })

    portion_history.sort(key=lambda x: x["timestamp"] if x["timestamp"] else datetime.min, reverse=True)

    template_name = "ops/order_detail.html" if uses_ops_ui(current_user) else "operational/order_detail.html"
    return render_template(
        template_name,
        daily_order=daily_order,
        total_lunch=total_lunch,
        total_dinner=total_dinner,
        total_locations=total_locations,
        unique_mandors=unique_mandors,
        lunch_delivery_data=lunch_delivery_data,
        dinner_delivery_data=dinner_delivery_data,
        delivery_next_actions=delivery_next_actions,
        delivery_ready_actions=delivery_ready_actions,
        hpp_snapshots=hpp_snapshots,
        latest_hpp_snapshot=latest_hpp_snapshot,
        lunch_print_status=lunch_print_status,
        dinner_print_status=dinner_print_status,
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
        meal_summary=meal_summary,
        form_mandors=form_mandors,
        form_locations=form_locations,
        order_countdowns=order_countdowns,
        portion_history=portion_history,
    )


@operational_bp.route("/orders/<int:order_id>/hpp-defaults", methods=["GET", "POST"])
@role_required("ADMIN")
def update_order_hpp_defaults_route(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)

    if request.method == "POST":
        success, message = update_order_hpp_defaults(daily_order, request.form)
        if success:
            record_audit_log(
                module="HPP",
                event_type="ORDER_HPP_DEFAULT_UPDATED",
                action="UPDATE",
                table_name="daily_orders",
                record_id=daily_order.id,
                description=f"Default menu/profil HPP order diperbarui: {daily_order.order_number}.",
            )
        flash(message, "success" if success else "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/order_hpp_defaults_form.html",
        daily_order=daily_order,
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
    )


@operational_bp.route("/orders/<int:order_id>/lock", methods=["POST"])
@role_required("ADMIN", "ADMIN_OPERASIONAL")
def lock_order(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    success, message = lock_daily_order(daily_order, current_user.id)

    if not success:
        flash(message, "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    production_success, production_message = generate_production_from_order(
        daily_order,
        current_user.id
    )

    record_audit_log(
        module="OPERATIONAL",
        event_type="ORDER_LOCKED",
        action="UPDATE",
        table_name="daily_orders",
        record_id=daily_order.id,
        description=f"Order di-lock: {daily_order.order_number}.",
        metadata={"production_created": production_success},
    )

    if production_success:
        flash("Order berhasil di-lock dan produksi otomatis dibuat.", "success")
    else:
        flash(f"Order berhasil di-lock, tetapi produksi belum dibuat: {production_message}", "warning")

    return redirect(url_for("operational.order_detail", order_id=daily_order.id))


@operational_bp.route("/orders/<int:order_id>/generate-production", methods=["POST"])
@role_required("ADMIN", "ADMIN_OPERASIONAL")
def generate_production(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    success, message = generate_production_from_order(daily_order, current_user.id)

    flash(message, "success" if success else "warning")
    return redirect(url_for("production.index"))


@operational_bp.route("/order-details/<int:detail_id>/revision", methods=["GET", "POST"])
@role_required("ADMIN", "ADMIN_OPERASIONAL")
def create_revision(detail_id):
    detail = DailyOrderDetail.query.get_or_404(detail_id)
    daily_order = detail.daily_order

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if request.method == "POST":
        revision_type = request.form.get("revision_type")
        revision_direction = request.form.get("revision_direction")
        lunch_qty_change = request.form.get("lunch_qty_change")
        dinner_qty_change = request.form.get("dinner_qty_change")
        reason = request.form.get("reason")

        if (revision_direction or "").upper() == "INCREASE":
            increase_error = _general_increase_error(detail.mandor_id)
            if increase_error:
                flash(increase_error, "warning")
                return redirect(url_for("operational.order_detail", order_id=daily_order.id))

        success, message = revise_order_detail(
            detail=detail,
            revision_type=revision_type,
            revision_direction=revision_direction,
            lunch_qty_change=lunch_qty_change,
            dinner_qty_change=dinner_qty_change,
            reason=reason,
            created_by=current_user.id
        )

        if success and daily_order.is_locked:
            production_success, production_message = generate_production_from_order(
                daily_order,
                current_user.id
            )

            if production_success:
                flash("Revisi berhasil disimpan dan produksi otomatis disinkronkan.", "success")
            else:
                flash(f"Revisi berhasil disimpan, tetapi produksi belum tersinkron: {production_message}", "warning")
        else:
            flash(message, "success" if success else "warning")

        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "ops/revision_form.html" if uses_ops_ui(current_user) else "operational/revision_form.html",
        detail=detail,
        daily_order=daily_order
    )



@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/create", methods=["GET", "POST"])
@role_required("ADMIN")
def create_order_hpp_snapshot_route(order_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if not daily_order.is_locked:
        flash("Snapshot HPP hanya bisa dibuat setelah order dikunci.", "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    menus, packaging_profiles, overhead_profiles = get_active_hpp_master_data(current_user.branch_id)
    meal_summary = get_order_meal_summary(daily_order)

    if request.method == "POST":
        success, message, snapshot = create_order_hpp_snapshot(
            daily_order=daily_order,
            form_data=request.form,
            created_by=current_user.id,
        )

        flash(message, "success" if success else "warning")
        if success and snapshot:
            record_audit_log(
                module="HPP",
                event_type="HPP_SNAPSHOT_CREATED",
                action="CREATE",
                table_name="order_hpp_snapshots",
                record_id=snapshot.id,
                description=f"Snapshot HPP dibuat untuk order {daily_order.order_number}.",
                metadata={"snapshot_number": snapshot.snapshot_number, "hpp_total": snapshot.hpp_total},
            )
            next_url = request.form.get("next")
            if next_url and next_url.startswith("/") and not next_url.startswith("//"):
                return redirect(next_url)
            return redirect(url_for("operational.order_hpp_snapshot_detail", order_id=daily_order.id, snapshot_id=snapshot.id))

        return redirect(url_for("operational.create_order_hpp_snapshot_route", order_id=daily_order.id))

    return render_template(
        "operational/order_hpp_snapshot_form.html",
        daily_order=daily_order,
        meal_summary=meal_summary,
        menus=menus,
        packaging_profiles=packaging_profiles,
        overhead_profiles=overhead_profiles,
    )


@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>")
@role_required("ADMIN")
def order_hpp_snapshot_detail(order_id, snapshot_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    return render_template(
        "operational/order_hpp_snapshot_detail.html",
        daily_order=daily_order,
        snapshot=snapshot,
    )

@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-dry-run")
@role_required("ADMIN")
def order_hpp_snapshot_stock_dry_run(order_id, snapshot_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    dry_run = build_hpp_stock_consumption_dry_run(snapshot)
    existing_consumption = get_existing_stock_consumption(snapshot.id)

    return render_template(
        "operational/order_hpp_stock_dry_run.html",
        daily_order=daily_order,
        snapshot=snapshot,
        dry_run=dry_run,
        existing_consumption=existing_consumption,
    )


@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-commit", methods=["POST"])
@role_required("ADMIN")
def order_hpp_snapshot_stock_commit(order_id, snapshot_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    success, message, consumption = commit_hpp_stock_consumption(
        snapshot=snapshot,
        committed_by=current_user.id,
        consumption_date=request.form.get("consumption_date"),
        notes=request.form.get("notes"),
    )

    flash(message, "success" if success else "warning")
    if success and consumption:
        record_audit_log(
            module="HPP",
            event_type="STOCK_CONSUMPTION_COMMITTED",
            action="CREATE",
            table_name="order_hpp_stock_consumptions",
            record_id=consumption.id,
            description=f"Pemakaian stok HPP di-commit untuk snapshot {snapshot.snapshot_number}.",
            metadata={"snapshot_id": snapshot.id, "total_cost": consumption.total_cost},
        )
        return redirect(url_for(
            "operational.order_hpp_stock_consumption_detail",
            order_id=daily_order.id,
            snapshot_id=snapshot.id,
            consumption_id=consumption.id,
        ))

    return redirect(url_for(
        "operational.order_hpp_snapshot_stock_dry_run",
        order_id=daily_order.id,
        snapshot_id=snapshot.id,
    ))


@operational_bp.route("/orders/<int:order_id>/hpp-snapshot/<int:snapshot_id>/stock-consumption/<int:consumption_id>")
@role_required("ADMIN")
def order_hpp_stock_consumption_detail(order_id, snapshot_id, consumption_id):
    daily_order = DailyOrder.query.get_or_404(order_id)

    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    snapshot = OrderHppSnapshot.query.get_or_404(snapshot_id)
    if snapshot.daily_order_id != daily_order.id or snapshot.branch_id != current_user.branch_id:
        flash("Snapshot HPP tidak sesuai order/cabang.", "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    consumption = OrderHppStockConsumption.query.get_or_404(consumption_id)
    if consumption.snapshot_id != snapshot.id or consumption.branch_id != current_user.branch_id:
        flash("Data pemakaian stok tidak sesuai snapshot/cabang.", "danger")
        return redirect(url_for("operational.order_hpp_snapshot_detail", order_id=daily_order.id, snapshot_id=snapshot.id))

    return render_template(
        "operational/order_hpp_stock_consumption_detail.html",
        daily_order=daily_order,
        snapshot=snapshot,
        consumption=consumption,
    )



@operational_bp.route("/orders/<int:order_id>/kitchen-recap/<string:sesi>")
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def kitchen_recap(order_id, sesi):
    from app.services.company_settings_service import get_company_settings
    from app.services.kitchen_recap_service import build_kitchen_recap_data, record_print_event

    daily_order = DailyOrder.query.get_or_404(order_id)
    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if not daily_order.is_locked:
        flash("Rekap Dapur hanya dapat dicetak setelah pesanan dikunci (locked).", "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    try:
        recap_data = build_kitchen_recap_data(daily_order, sesi)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    record_print_event(current_user, daily_order, sesi, "RECAP", "A4")
    company = get_company_settings(daily_order.branch_id)

    return render_template(
        "operational/kitchen_recap.html",
        recap=recap_data,
        company=company,
    )


@operational_bp.route("/kitchen-recap")
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def kitchen_recap_hub():
    """Halaman Rekap Dapur (pintu sub-tab Dapur)."""
    from app.services.company_settings_service import get_company_settings
    from app.services.kitchen_recap_service import build_kitchen_recap_data

    today = today_wib()
    date_str = request.args.get("date", today.strftime("%Y-%m-%d")).strip()
    selected_date = parse_date(date_str, today)
    sesi = (request.args.get("sesi") or "LUNCH").upper().strip()
    if sesi not in ("LUNCH", "DINNER"):
        sesi = "LUNCH"

    daily_order = DailyOrder.query.filter_by(
        branch_id=current_user.branch_id,
        order_date=selected_date,
    ).first()

    recap_data = None
    if daily_order and daily_order.is_locked:
        try:
            recap_data = build_kitchen_recap_data(daily_order, sesi)
        except ValueError:
            recap_data = None

    company = get_company_settings(current_user.branch_id)
    if not uses_ops_ui(current_user):
        if daily_order and daily_order.is_locked:
            return redirect(url_for("operational.kitchen_recap", order_id=daily_order.id, sesi=sesi))
        flash("Belum ada order terkunci untuk tanggal ini.", "info")
        return redirect(url_for("operational.orders"))

    return render_template(
        "ops/kitchen_recap.html",
        daily_order=daily_order,
        recap=recap_data,
        selected_date=selected_date,
        selected_sesi=sesi,
        company=company,
    )


@operational_bp.route("/orders/<int:order_id>/container-labels/<string:sesi>")
@role_required("ADMIN", "DAPUR", "PENGANTAR", "ADMIN_OPERASIONAL")
def container_labels(order_id, sesi):
    from app.services.company_settings_service import get_company_settings
    from app.services.kitchen_recap_service import build_container_labels_data, record_print_event

    daily_order = DailyOrder.query.get_or_404(order_id)
    if daily_order.branch_id != current_user.branch_id:
        flash("Data order tidak sesuai cabang user.", "danger")
        return redirect(url_for("operational.orders"))

    if not daily_order.is_locked:
        flash("Label wadah hanya dapat dicetak setelah pesanan dikunci (locked).", "warning")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    paper_size = request.args.get("size", "58mm").lower().strip()
    if paper_size not in ("58mm", "80mm", "a4"):
        paper_size = "58mm"

    try:
        labels_data = build_container_labels_data(daily_order, sesi, paper_size)
    except ValueError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("operational.order_detail", order_id=daily_order.id))

    record_print_event(current_user, daily_order, sesi, "LABEL", paper_size)
    company = get_company_settings(daily_order.branch_id)

    return render_template(
        "operational/container_labels.html",
        labels_data=labels_data,
        paper_size=paper_size,
        company=company,
    )


@operational_bp.route("/menu-schedule", methods=["GET"])
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def menu_schedule():
    """Halaman Jadwal Menu mingguan (grid 7 hari x Siang/Malam)."""
    from datetime import datetime
    from app.models.master import Menu
    from app.services.menu_schedule_service import (
        get_monday_of_week,
        get_weekly_schedule_matrix,
    )

    week_str = request.args.get("week")
    start_monday = None
    if week_str:
        try:
            start_monday = datetime.strptime(week_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            start_monday = None

    monday = get_monday_of_week(start_monday)
    matrix = get_weekly_schedule_matrix(current_user.branch_id, monday)

    active_menus = (
        Menu.query.filter_by(branch_id=current_user.branch_id, is_active=True)
        .order_by(Menu.menu_name.asc())
        .all()
    )

    template_name = "ops/menu_schedule.html" if uses_ops_ui(current_user) else "operational/menu_schedule.html"
    return render_template(
        template_name,
        matrix=matrix,
        active_menus=active_menus,
        current_monday=monday,
    )


@operational_bp.route("/menu-schedule/save", methods=["POST"])
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def save_menu_schedule_slot():
    """Simpan menu dan catatan untuk slot tanggal & sesi tertentu."""
    from datetime import datetime
    from app.services.menu_schedule_service import MenuScheduleError, save_menu_schedule

    date_str = request.form.get("menu_date")
    meal_type = request.form.get("meal_type")
    menu_id_raw = request.form.get("menu_id")
    notes = request.form.get("notes")
    week_ref = request.form.get("week_ref")

    if not date_str or not meal_type:
        flash("Tanggal dan sesi makan wajib ditentukan.", "danger")
        return redirect(url_for("operational.menu_schedule", week=week_ref))

    try:
        menu_date = datetime.strptime(date_str.strip(), "%Y-%m-%d").date()
    except ValueError:
        flash("Format tanggal tidak valid.", "danger")
        return redirect(url_for("operational.menu_schedule", week=week_ref))

    menu_id = int(menu_id_raw) if menu_id_raw and menu_id_raw.isdigit() else None

    try:
        save_menu_schedule(
            branch_id=current_user.branch_id,
            menu_date=menu_date,
            meal_type=meal_type,
            menu_id=menu_id,
            notes=notes,
            acted_by=current_user.id,
        )
        flash("Jadwal menu berhasil disimpan.", "success")
    except MenuScheduleError as err:
        flash(str(err), "warning")

    return redirect(url_for("operational.menu_schedule", week=week_ref or date_str))


@operational_bp.route("/menu-schedule/copy-last-week", methods=["POST"])
@role_required("ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def copy_last_week_menu_schedule():
    """Salin seluruh jadwal menu dari minggu sebelumnya ke minggu ini."""
    from datetime import datetime
    from app.services.menu_schedule_service import (
        copy_previous_week_schedule,
        get_monday_of_week,
    )

    target_week_str = request.form.get("target_week")
    start_monday = None
    if target_week_str:
        try:
            start_monday = datetime.strptime(target_week_str.strip(), "%Y-%m-%d").date()
        except ValueError:
            start_monday = None

    monday = get_monday_of_week(start_monday)
    count = copy_previous_week_schedule(
        branch_id=current_user.branch_id,
        target_monday=monday,
        acted_by=current_user.id,
    )

    if count > 0:
        flash(f"Berhasil menyalin {count} jadwal menu dari minggu sebelumnya.", "success")
    else:
        flash("Tidak ada jadwal di minggu sebelumnya untuk disalin.", "info")

    return redirect(url_for("operational.menu_schedule", week=monday.strftime("%Y-%m-%d")))


@operational_bp.route("/order-details/<int:detail_id>/change-qty", methods=["POST"])
@role_required("ADMIN", "OWNER", "ADMIN_OPERASIONAL")
def change_order_detail_qty(detail_id):
    """Ubah porsi oleh admin/owner (setelah lock wajib menyertakan alasan)."""
    from app.services.auto_order_service import update_order_qty_from_admin

    detail = DailyOrderDetail.query.get_or_404(detail_id)
    if detail.daily_order.branch_id != current_user.branch_id and current_user.role != "OWNER":
        flash("Data order tidak sesuai cabang pengguna.", "danger")
        return redirect(url_for("operational.orders"))

    meal_type = (request.form.get("meal_type") or "").strip().upper()
    new_qty_str = request.form.get("new_qty")
    reason = (request.form.get("reason") or "").strip()
    reason_code = (request.form.get("reason_code") or "").strip() or None

    try:
        new_qty = int(new_qty_str)
    except (ValueError, TypeError):
        flash("Jumlah porsi harus berupa angka bulat.", "danger")
        return redirect(url_for("operational.order_detail", order_id=detail.daily_order_id))

    success, message, _ = update_order_qty_from_admin(
        user=current_user,
        detail_id=detail.id,
        meal_type=meal_type,
        new_qty=new_qty,
        reason=reason,
        reason_code=reason_code,
    )

    flash(message, "success" if success else "danger")
    return redirect(url_for("operational.order_detail", order_id=detail.daily_order_id))


@operational_bp.route("/order-qty-changes", methods=["GET"])
@role_required("OWNER", "ADMIN", "DAPUR", "ADMIN_OPERASIONAL")
def order_qty_changes():
    """Halaman riwayat perubahan porsi (Fase 5) dengan filter."""
    from app.services.auto_order_service import list_order_qty_changes, PORTION_ZERO_REASONS
    from app.services.catering_report_service import get_active_mandors, parse_date

    today = today_wib()
    start_date_val = request.args.get("start_date", "").strip()
    end_date_val = request.args.get("end_date", "").strip()
    mandor_id_val = request.args.get("mandor_id", "").strip()
    source_val = request.args.get("source", "").strip()

    start_date = parse_date(start_date_val, None) if start_date_val else None
    end_date = parse_date(end_date_val, None) if end_date_val else None
    mandor_id = int(mandor_id_val) if mandor_id_val.isdigit() else None
    source = source_val.upper() if source_val in ("AUTO", "PORTAL", "ADMIN") else None

    branch_id = current_user.branch_id if current_user.role != "OWNER" else (request.args.get("branch_id", type=int) or current_user.branch_id)

    changes = list_order_qty_changes(
        branch_id=branch_id,
        start_date=start_date,
        end_date=end_date,
        mandor_id=mandor_id,
        source=source,
        limit=200,
    )
    mandors = get_active_mandors(branch_id)

    template_name = "ops/order_qty_changes.html" if uses_ops_ui(current_user) else "operational/order_qty_changes.html"
    return render_template(
        template_name,
        changes=changes,
        mandors=mandors,
        selected_mandor_id=mandor_id,
        selected_source=source,
        start_date=start_date_val,
        end_date=end_date_val,
        reason_labels=PORTION_ZERO_REASONS,
    )
