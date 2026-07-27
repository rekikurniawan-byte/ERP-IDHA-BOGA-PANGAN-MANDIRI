# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.routes.finance.invoice_communication_routes import build_invoice_whatsapp_context

def _invoice_print_float(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1899")
        return 0


def _invoice_print_parse_meals(description):
    import re

    description = description or ""

    def find_qty(*labels):
        for label in labels:
            match = re.search(rf"{label}\s*([+-]?\s*\d+(?:[.,]\d+)?)", description, re.IGNORECASE)
            if match:
                return match.group(1).replace(" ", "")
        return "-"

    return {
        "breakfast": find_qty("Sarapan", "Pagi", "Breakfast"),
        "lunch": find_qty("Lunch", "Siang"),
        "dinner": find_qty("Dinner", "Sore"),
    }


def _invoice_print_parse_lunch_dinner(description):
    meals = _invoice_print_parse_meals(description)
    return meals["lunch"], meals["dinner"]


def _invoice_print_parse_money(value):
    value = str(value or "").strip()

    if not value:
        return 0

    # Deskripsi lama memakai format 10,000 / 1,015 / 8,985.
    # Untuk kebutuhan cetak, koma/titik pada deskripsi dianggap pemisah ribuan.
    cleaned = value.replace(".", "").replace(",", "")

    try:
        return float(cleaned)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1939")
        return 0


def _invoice_print_extract_money(description, label):
    import re

    description = description or ""
    pattern = rf"{label}\s*([0-9.,]+)"
    match = re.search(pattern, description, re.IGNORECASE)

    if not match:
        return 0

    return _invoice_print_parse_money(match.group(1))


def _invoice_print_parse_common_description(description):
    description = description or ""
    parts = [part.strip() for part in description.split("|")]

    return {
        "order_number": parts[0] if len(parts) > 0 and parts[0] else "-",
        "mandor": parts[1] if len(parts) > 1 and parts[1] else "-",
        "location": parts[2] if len(parts) > 2 and parts[2] else "-",
        "note": parts[3] if len(parts) > 3 and parts[3] else description,
    }


def _invoice_print_parse_worker_debt(description):
    import re

    description = description or ""

    worker_name = "-"
    worker_match = re.search(r"pekerja\s+([^|]+)", description, re.IGNORECASE)

    if worker_match:
        worker_name = worker_match.group(1).strip()

    debt_amount = _invoice_print_extract_money(description, "Hutang")
    paid_amount = _invoice_print_extract_money(description, "Dibayar")
    remaining_amount = _invoice_print_extract_money(description, "Sisa")

    return {
        "worker_name": worker_name,
        "debt_amount": debt_amount,
        "paid_amount": paid_amount,
        "remaining_amount": remaining_amount,
        "note": description,
    }



def _invoice_print_format_date(value):
    if not value:
        return "-"

    try:
        return value.strftime("%d-%m-%Y")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:1999")
        return str(value)


def _invoice_print_resolve_daily_order_detail(source_id):
    """Resolve invoice item source detail so invoice print does not show blank
    order/mandor/location/lunch/dinner when the item is linked to a daily order.
    """
    if not source_id:
        return {}

    try:
        from app.models.operational import DailyOrderDetail

        detail = DailyOrderDetail.query.get(source_id)
        if not detail:
            return {}

        daily_order = getattr(detail, "daily_order", None)
        mandor = getattr(detail, "mandor", None)
        location = getattr(detail, "delivery_location", None)

        return {
            "order_number": getattr(daily_order, "order_number", None) or f"Detail Order #{detail.id}",
            "order_date": _invoice_print_format_date(getattr(daily_order, "order_date", None)),
            "mandor": getattr(mandor, "name", None) or "-",
            "location": getattr(location, "location_name", None) or "-",
            "breakfast": "-",
            "lunch": str(int(getattr(detail, "lunch_qty", 0) or 0)),
            "dinner": str(int(getattr(detail, "dinner_qty", 0) or 0)),
            "qty": _invoice_print_float(getattr(detail, "total_qty", 0)),
            "unit_price": _invoice_print_float(getattr(detail, "price_per_portion", 0)),
            "source_label": "Order Harian",
            "source_meta": f"Tanggal {_invoice_print_format_date(getattr(daily_order, 'order_date', None))}",
            "note": getattr(detail, "notes", None) or getattr(daily_order, "notes", None) or "Catering harian",
        }
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:2035")
        return {}

def build_invoice_print_operational_data(invoice):
    data = {
        "catering": [],
        "revision": [],
        "warung": [],
        "other": [],
        "totals": {
            "catering": 0,
            "revision": 0,
            "warung": 0,
            "other": 0,
            "grand": _invoice_print_float(invoice.total_amount),
            "paid": _invoice_print_float(invoice.paid_amount),
            "remaining": _invoice_print_float(invoice.remaining_amount),
        }
    }

    for item in invoice.items:
        item_type = (getattr(item, "item_type", "") or "").upper()
        description = getattr(item, "description", "") or ""
        subtotal = _invoice_print_float(getattr(item, "subtotal", 0))
        qty = _invoice_print_float(getattr(item, "qty", 0))
        unit_price = _invoice_print_float(getattr(item, "unit_price", 0))

        common = _invoice_print_parse_common_description(description)
        meals = _invoice_print_parse_meals(description)
        lunch, dinner = meals["lunch"], meals["dinner"]
        breakfast = meals["breakfast"]
        source_type = (getattr(item, "source_type", None) or "").upper()
        source_id = getattr(item, "source_id", None)
        source_detail = {}

        if source_type == "DAILY_ORDER_DETAIL":
            source_detail = _invoice_print_resolve_daily_order_detail(source_id)

        resolved_qty = qty or _invoice_print_float(source_detail.get("qty"))
        resolved_unit_price = unit_price or _invoice_print_float(source_detail.get("unit_price"))

        base_row = {
            "item": item,
            "description": description,
            "qty": resolved_qty,
            "unit_price": resolved_unit_price,
            "subtotal": subtotal,
            "source_type": source_type or getattr(item, "source_type", None),
            "source_id": source_id,
            "source_label": source_detail.get("source_label") or "",
            "source_meta": source_detail.get("source_meta") or "",
            "order_date": source_detail.get("order_date") or "",
        }

        if item_type == "CATERING":
            row = dict(base_row)
            row.update({
                "order_number": common["order_number"] if common["order_number"] != "-" else source_detail.get("order_number", "-"),
                "mandor": common["mandor"] if common["mandor"] != "-" else source_detail.get("mandor", "-"),
                "location": common["location"] if common["location"] != "-" else source_detail.get("location", "-"),
                "note": common["note"] if common["note"] != description else source_detail.get("note", common["note"]),
                "breakfast": breakfast if breakfast != "-" else source_detail.get("breakfast", "-"),
                "lunch": lunch if lunch != "-" else source_detail.get("lunch", "-"),
                "dinner": dinner if dinner != "-" else source_detail.get("dinner", "-"),
            })

            data["catering"].append(row)
            data["totals"]["catering"] += subtotal

        elif item_type == "REVISION_INCREASE":
            row = dict(base_row)
            row.update({
                "order_number": common["order_number"] if common["order_number"] != "-" else source_detail.get("order_number", "-"),
                "mandor": common["mandor"] if common["mandor"] != "-" else source_detail.get("mandor", "-"),
                "location": common["location"] if common["location"] != "-" else source_detail.get("location", "-"),
                "note": common["note"] if common["note"] != description else source_detail.get("note", common["note"]),
                "breakfast": breakfast if breakfast != "-" else source_detail.get("breakfast", "-"),
                "lunch": lunch if lunch != "-" else source_detail.get("lunch", "-"),
                "dinner": dinner if dinner != "-" else source_detail.get("dinner", "-"),
            })

            data["revision"].append(row)
            data["totals"]["revision"] += subtotal

        elif item_type == "WARUNG_DEBT":
            debt = _invoice_print_parse_worker_debt(description)

            row = dict(base_row)
            row.update(debt)

            if not row["remaining_amount"]:
                row["remaining_amount"] = subtotal

            data["warung"].append(row)
            data["totals"]["warung"] += subtotal

        else:
            row = dict(base_row)
            row.update({
                "item_type": item_type or "-",
            })

            data["other"].append(row)
            data["totals"]["other"] += subtotal

    return data


@finance_bp.route("/invoices/<int:invoice_id>/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def invoice_print(invoice_id):
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

    client_name = "-"
    mandor_name = "-"

    if invoice.client_id:
        client = Client.query.get(invoice.client_id)
        client_name = client.name if client else f"Client ID {invoice.client_id}"

    if invoice.mandor_id:
        mandor = Mandor.query.get(invoice.mandor_id)
        mandor_name = mandor.name if mandor else f"Mandor ID {invoice.mandor_id}"

    company_settings = get_company_settings(current_user.branch_id)
    official_identity = get_invoice_official_identity(invoice)
    whatsapp = build_invoice_whatsapp_context(invoice)
    print_data = build_invoice_print_operational_data(invoice)

    return render_template(
        "finance/invoice_print.html",
        invoice=invoice,
        payments=payments,
        bill_to=get_invoice_bill_to(invoice),
        official_identity=official_identity,
        client_name=client_name,
        mandor_name=mandor_name,
        whatsapp=whatsapp,
        print_data=print_data,
        company_settings=company_settings
    )


# === PATCH_WHATSAPP_INVOICE_STEP11C1 ===
