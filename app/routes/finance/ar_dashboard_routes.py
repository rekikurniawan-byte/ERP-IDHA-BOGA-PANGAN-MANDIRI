# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403
from app.utils.terms import T


def _finance_ar_percent(paid, total):
    try:
        total = float(total or 0)
        paid = float(paid or 0)

        if total <= 0:
            return 0

        return round((paid / total) * 100, 2)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:2524")
        return 0


def _finance_format_date(value):
    if not value:
        return "-"

    try:
        return value.strftime("%d-%m-%Y")
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:2534")
        return str(value)


def build_invoice_ar_warning(invoice):
    from datetime import date

    try:
        from app.models.finance import InvoiceCollectionLog
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:2543")
        InvoiceCollectionLog = None

    today = date.today()

    total = float(invoice.total_amount or 0)
    paid = float(invoice.paid_amount or 0)
    remaining = float(invoice.remaining_amount or 0)
    paid_percent = _finance_ar_percent(paid, total)
    expected_percent = float(getattr(invoice, "expected_payment_percent", 100) or 100)

    latest_log = None

    if InvoiceCollectionLog:
        latest_log = InvoiceCollectionLog.query.filter_by(
            invoice_id=invoice.id
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

    base = {
        "stage": "NORMAL",
        "stage_label": "Normal",
        "level": "NORMAL",
        "badge_class": "status-progress",
        "message": "-",
        "action": "-",
        "paid_percent": paid_percent,
        "expected_percent": expected_percent,
        "latest_status": latest_log.collection_status if latest_log else "-",
        "latest_date": _finance_format_date(latest_log.follow_up_date) if latest_log else "-",
        "latest_pic": latest_log.contact_person if latest_log and latest_log.contact_person else "-",
        "latest_note": latest_log.response_note if latest_log and latest_log.response_note else "-"
    }

    # HYGIENE5C_AR_CANCELLED
    if str(invoice.status or "").upper() in ["CANCELLED", "CANCELED"]:
        base.update({
            "stage": "CANCELLED",
            "stage_label": "Dibatalkan",
            "level": "ARSIP",
            "badge_class": "status-cancelled",
            "message": "Invoice ini dibatalkan dan tidak dihitung sebagai piutang aktif.",
            "action": "Tidak perlu follow up penagihan."
        })
        return base

    if remaining <= 0 or str(invoice.status).upper() == "PAID":
        base.update({
            "stage": "PAID",
            "stage_label": "Lunas",
            "level": "AMAN",
            "badge_class": "status-locked",
            "message": "Invoice sudah lunas.",
            "action": "Tidak perlu follow up penagihan."
        })
        return base

    if latest_log and latest_log.collection_status == "PROMISE_TO_PAY":
        promise = _finance_format_date(latest_log.promise_date)
        base.update({
            "stage": "PROMISE_TO_PAY",
            "stage_label": "Janji Bayar",
            "level": "PANTAU",
            "badge_class": "status-progress",
            "message": f"{T.client} sudah ada janji bayar tanggal {promise}.",
            "action": "Pantau sesuai tanggal janji bayar."
        })
        return base

    if not invoice.due_date:
        base.update({
            "stage": "NO_DUE_DATE",
            "stage_label": "Cek Jatuh Tempo",
            "level": "CEK",
            "badge_class": "status-draft",
            "message": "Invoice belum memiliki tanggal jatuh tempo.",
            "action": "Lengkapi tanggal jatuh tempo invoice."
        })
        return base

    days_to_due = (invoice.due_date - today).days
    days_from_invoice = (today - invoice.invoice_date).days if invoice.invoice_date else 0

    if days_to_due < 0:
        overdue_days = abs(days_to_due)

        if overdue_days <= 7:
            base.update({
                "stage": "OVERDUE_1_7",
                "stage_label": "Overdue",
                "level": "WARNING",
                "badge_class": "status-cancelled",
                "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
                "action": f"Follow up overdue ke PIC {T.client_lower}."
            })
            return base

        if overdue_days <= 14:
            base.update({
                "stage": "OVERDUE_8_14",
                "stage_label": "Kirim Rekap Piutang",
                "level": "TINGGI",
                "badge_class": "status-cancelled",
                "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
                "action": "Kirim Statement of Account / Rekap Piutang."
            })
            return base

        if overdue_days <= 30:
            base.update({
                "stage": "OVERDUE_15_30",
                "stage_label": "Surat Tagihan",
                "level": "SERIUS",
                "badge_class": "status-cancelled",
                "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
                "action": "Kirim surat tagihan resmi dan minta janji bayar."
            })
            return base

        base.update({
            "stage": "OVERDUE_30_PLUS",
            "stage_label": "Eskalasi Owner",
            "level": "KRITIS",
            "badge_class": "status-cancelled",
            "message": f"Invoice telat {overdue_days} hari dan belum lunas.",
            "action": "Eskalasi ke owner untuk keputusan penagihan."
        })
        return base

    if days_to_due <= 3:
        base.update({
            "stage": "DUE_SOON",
            "stage_label": "Reminder Jatuh Tempo",
            "level": "REMINDER",
            "badge_class": "status-draft",
            "message": f"Jatuh tempo dalam {days_to_due} hari.",
            "action": f"Kirim reminder jatuh tempo ke PIC {T.client_lower}."
        })
        return base

    if days_from_invoice >= 7 and paid <= 0:
        base.update({
            "stage": "NO_PAYMENT_7_DAYS",
            "stage_label": "Butuh Follow Up",
            "level": "FOLLOW_UP",
            "badge_class": "status-draft",
            "message": "Invoice sudah 7 hari dibuat/dikirim tetapi belum ada pembayaran.",
            "action": "Follow up konfirmasi proses pembayaran."
        })
        return base

    if paid > 0 and paid_percent < expected_percent:
        base.update({
            "stage": "BELOW_EXPECTED_PAYMENT",
            "stage_label": "Pantau Sisa Piutang",
            "level": "PANTAU",
            "badge_class": "status-progress",
            "message": f"Pembayaran baru {paid_percent}% dari total, target minimal {expected_percent}%.",
            "action": "Pantau sisa pembayaran dan follow up jika mendekati jatuh tempo."
        })
        return base

    if paid > 0 and remaining > 0:
        base.update({
            "stage": "PARTIAL",
            "stage_label": "Bayar Sebagian",
            "level": "PANTAU",
            "badge_class": "status-progress",
            "message": "Invoice sudah dibayar sebagian tetapi belum lunas.",
            "action": "Follow up pelunasan sisa tagihan."
        })
        return base

    base.update({
        "stage": "NORMAL_UNPAID",
        "stage_label": "Belum Jatuh Tempo",
        "level": "NORMAL",
        "badge_class": "status-progress",
        "message": f"Belum jatuh tempo. Sisa {days_to_due} hari.",
        "action": "Pantau sampai mendekati jatuh tempo."
    })
    return base


@finance_bp.app_template_global()
def finance_ar_warning(invoice):
    return build_invoice_ar_warning(invoice)


# === PATCH_RECEIVABLES_DASHBOARD_STEP12C1 ===
# === PATCH_RECEIVABLES_FILTER_STEP12C2B ===
# === FINAL_FILTER_COUNT_SYNC_STEP12C2C ===
# === TAHAP_10_10_ENHANCE_EXISTING_RECEIVABLES ===
def _build_receivables_dashboard_context(args):
    from collections import defaultdict
    from datetime import date
    from app.models.finance import Invoice, InvoiceCollectionLog
    from app.models.master import Branch, Client, Mandor
    from app.services.finance_receivables_service import (
        BILL_TO_TYPE_CHOICES,
        INACTIVE_INVOICE_STATUSES,
        invoice_matches_receivable_filters,
        invoice_party_context,
        parse_date_filter,
        normalize_bill_to_type_filter,
        normalize_status_filter,
        receivable_status_choices_from_invoices,
    )

    selected_filter = (args.get("filter") or "ALL").strip().upper()
    selected_client_id = (args.get("client_id") or "").strip()
    selected_bill_to_type = normalize_bill_to_type_filter(args.get("bill_to_type"))
    selected_status = normalize_status_filter(args.get("status"))
    selected_period_from_raw = (args.get("period_from") or "").strip()
    selected_period_to_raw = (args.get("period_to") or "").strip()
    selected_period_from = parse_date_filter(selected_period_from_raw)
    selected_period_to = parse_date_filter(selected_period_to_raw)

    branch_options = []
    if getattr(current_user, "role", "") == "OWNER":
        branches = Branch.query.filter_by(is_active=True).order_by(Branch.name.asc()).all()
        if not branches:
            branches = Branch.query.order_by(Branch.name.asc()).all()
    else:
        branches = Branch.query.filter_by(id=current_user.branch_id).all()

    for branch in branches:
        branch_options.append({"value": str(branch.id), "label": branch.name or f"Cabang {branch.id}"})

    allowed_branch_ids = {int(row["value"]) for row in branch_options if str(row.get("value", "")).isdigit()}
    requested_branch_id = (args.get("branch_id") or "").strip()
    selected_branch_id = current_user.branch_id
    if requested_branch_id.isdigit() and int(requested_branch_id) in allowed_branch_ids:
        selected_branch_id = int(requested_branch_id)
    elif selected_branch_id not in allowed_branch_ids and allowed_branch_ids:
        selected_branch_id = sorted(allowed_branch_ids)[0]

    filter_labels = {
        "ALL": "Semua Piutang",
        "OVERDUE": "Overdue",
        "DUE_SOON": "Due Soon",
        "FOLLOW_UP": "Butuh Follow Up",
        "PARTIAL_MONITOR": "Pantau Sisa Piutang",
    }

    if selected_filter not in filter_labels:
        selected_filter = "ALL"

    def match_filter(stage, filter_key):
        stage = stage or ""

        if filter_key == "ALL":
            return True

        if filter_key == "OVERDUE":
            return stage.startswith("OVERDUE")

        if filter_key == "DUE_SOON":
            return stage == "DUE_SOON"

        if filter_key == "FOLLOW_UP":
            return stage in [
                "NO_PAYMENT_7_DAYS",
                "FOLLOW_UP",
                "PROMISE_TO_PAY",
                "OVERDUE_1_7",
                "OVERDUE_8_14",
                "OVERDUE_15_30",
                "OVERDUE_30_PLUS",
            ]

        if filter_key == "PARTIAL_MONITOR":
            return stage in [
                "BELOW_EXPECTED_PAYMENT",
                "PARTIAL",
            ]

        return True

    priority_map = {
        "OVERDUE_30_PLUS": 1,
        "OVERDUE_15_30": 2,
        "OVERDUE_8_14": 3,
        "OVERDUE_1_7": 4,
        "DUE_SOON": 5,
        "NO_PAYMENT_7_DAYS": 6,
        "PROMISE_TO_PAY": 7,
        "BELOW_EXPECTED_PAYMENT": 8,
        "PARTIAL": 9,
        "NORMAL_UNPAID": 10,
        "NORMAL": 11,
        "PAID": 99,
    }

    invoices = Invoice.query.filter(
        Invoice.branch_id == selected_branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status.notin_(list(INACTIVE_INVOICE_STATUSES)),
    ).order_by(
        Invoice.due_date.asc(),
        Invoice.id.asc()
    ).all()

    # Jalur transaksi (Kontrak/Umum): ringkasan dari semua piutang, daftar mengikuti filter.
    from app.services.pricing_service import PATH_FILTER_CHOICES, invoice_path_breakdown, requested_path

    path_breakdown = invoice_path_breakdown(invoices)
    selected_path = requested_path(args.get("path"))
    if selected_path:
        invoices = [invoice for invoice in invoices if invoice.customer_path == selected_path]

    client_ids = {invoice.client_id for invoice in invoices if invoice.client_id}
    mandor_ids = {invoice.mandor_id for invoice in invoices if invoice.mandor_id}
    client_map = {client.id: client for client in Client.query.filter(Client.id.in_(client_ids)).all()} if client_ids else {}
    mandor_map = {mandor.id: mandor for mandor in Mandor.query.filter(Mandor.id.in_(mandor_ids)).all()} if mandor_ids else {}

    all_rows = []
    client_stats = {}
    party_stats_all = {}

    for invoice in invoices:
        party = invoice_party_context(invoice, client_map=client_map, mandor_map=mandor_map)

        if not invoice_matches_receivable_filters(
            invoice,
            party,
            bill_to_type=selected_bill_to_type,
            status=selected_status,
            period_from=selected_period_from,
            period_to=selected_period_to,
        ):
            continue

        latest_log = InvoiceCollectionLog.query.filter_by(
            branch_id=selected_branch_id,
            invoice_id=invoice.id
        ).order_by(
            InvoiceCollectionLog.follow_up_date.desc(),
            InvoiceCollectionLog.id.desc()
        ).first()

        ar = build_invoice_ar_warning(invoice)
        stage = ar.get("stage") or "NORMAL"
        priority = priority_map.get(stage, 50)

        if invoice.client_id:
            client_key = str(invoice.client_id)
            client_name = party.get("client_name") or f"{T.client} ID {invoice.client_id}"
        else:
            client_key = "NO_CLIENT"
            client_name = f"Tanpa {T.client} / Pihak Bebas"

        remaining = float(invoice.remaining_amount or 0)

        row = {
            "invoice": invoice,
            "client_key": client_key,
            "client_name": client_name,
            "mandor_name": party.get("mandor_name") or "-",
            "party": party,
            "party_key": party.get("key"),
            "party_name": party.get("name") or "-",
            "bill_to_type_label": party.get("type_label") or "-",
            "input_source_label": party.get("input_source_label") or "-",
            "latest_log": latest_log,
            "ar": ar,
            "priority": priority,
            "remaining": remaining,
        }

        all_rows.append(row)

        if client_key not in client_stats:
            client_stats[client_key] = {
                "value": client_key,
                "label": client_name,
                "invoice_count": 0,
                "remaining_total": 0,
            }

        client_stats[client_key]["invoice_count"] += 1
        client_stats[client_key]["remaining_total"] += remaining

        party_key = party.get("key") or f"UNKNOWN:{party.get('name', '-') }"
        if party_key not in party_stats_all:
            party_stats_all[party_key] = {
                "party_key": party_key,
                "party_name": party.get("name") or "-",
                "bill_to_type_label": party.get("type_label") or "-",
                "invoice_count": 0,
                "remaining_total": 0,
            }
        party_stats_all[party_key]["invoice_count"] += 1
        party_stats_all[party_key]["remaining_total"] += remaining

    if selected_client_id:
        base_rows_for_filter_count = [row for row in all_rows if row["client_key"] == selected_client_id]
    else:
        base_rows_for_filter_count = all_rows

    filter_stats = {
        key: {"value": key, "label": label, "count": 0, "total": 0}
        for key, label in filter_labels.items()
    }

    for row in base_rows_for_filter_count:
        stage = row["ar"].get("stage") or "NORMAL"
        remaining = float(row["remaining"] or 0)

        for key in filter_stats.keys():
            if match_filter(stage, key):
                filter_stats[key]["count"] += 1
                filter_stats[key]["total"] += remaining

    rows = [
        row for row in base_rows_for_filter_count
        if match_filter(row["ar"].get("stage"), selected_filter)
    ]

    rows.sort(key=lambda row: (
        row["priority"],
        row["invoice"].due_date or date(2999, 12, 31),
        row["invoice"].id
    ))

    stage_counter = defaultdict(int)
    party_recap = {}

    total_receivable = 0
    overdue_count = 0
    due_soon_count = 0
    follow_up_count = 0

    for row in rows:
        invoice = row["invoice"]
        ar = row["ar"]
        stage = ar.get("stage") or "NORMAL"
        stage_label = ar.get("stage_label") or "-"
        remaining = float(invoice.remaining_amount or 0)

        total_receivable += remaining
        stage_counter[stage_label] += 1

        if stage.startswith("OVERDUE"):
            overdue_count += 1

        if stage == "DUE_SOON":
            due_soon_count += 1

        if stage in [
            "NO_PAYMENT_7_DAYS",
            "FOLLOW_UP",
            "PROMISE_TO_PAY",
            "BELOW_EXPECTED_PAYMENT",
            "PARTIAL",
        ]:
            follow_up_count += 1

        party_key = row["party_key"]
        if party_key not in party_recap:
            party_recap[party_key] = {
                "party_name": row["party_name"],
                "bill_to_type_label": row["bill_to_type_label"],
                "invoice_count": 0,
                "remaining_total": 0,
            }

        party_recap[party_key]["invoice_count"] += 1
        party_recap[party_key]["remaining_total"] += remaining

    stage_rows = [
        {"stage": stage, "count": count}
        for stage, count in sorted(stage_counter.items(), key=lambda item: item[0])
    ]

    party_rows = sorted(
        party_recap.values(),
        key=lambda row: row["remaining_total"],
        reverse=True
    )

    # Backward-compatible alias for older template/tests that still read client_rows.
    client_rows = party_rows

    client_options = sorted(
        client_stats.values(),
        key=lambda row: row["remaining_total"],
        reverse=True
    )

    selected_client_name = ""
    if selected_client_id:
        selected_client_name = client_stats.get(selected_client_id, {}).get("label", "")

    summary = {
        "invoice_count": len(rows),
        "total_receivable": total_receivable,
        "overdue_count": overdue_count,
        "due_soon_count": due_soon_count,
        "follow_up_count": follow_up_count,
    }

    filter_options = [
        filter_stats["ALL"],
        filter_stats["OVERDUE"],
        filter_stats["DUE_SOON"],
        filter_stats["FOLLOW_UP"],
        filter_stats["PARTIAL_MONITOR"],
    ]

    selected_branch_name = next((row["label"] for row in branch_options if row["value"] == str(selected_branch_id)), "")

    return {
        "rows": rows,
        "stage_rows": stage_rows,
        "party_rows": party_rows,
        "client_rows": client_rows,
        "summary": summary,
        "filter_options": filter_options,
        "client_options": client_options,
        "branch_options": branch_options,
        "bill_to_type_choices": BILL_TO_TYPE_CHOICES,
        "status_options": receivable_status_choices_from_invoices(invoices),
        "selected_filter": selected_filter,
        "selected_filter_label": filter_labels[selected_filter],
        "selected_client_id": selected_client_id,
        "selected_client_name": selected_client_name,
        "selected_branch_id": str(selected_branch_id),
        "selected_branch_name": selected_branch_name,
        "selected_bill_to_type": selected_bill_to_type,
        "selected_status": selected_status,
        "selected_period_from": selected_period_from_raw,
        "selected_period_to": selected_period_to_raw,
        "path_breakdown": path_breakdown,
        "selected_path": selected_path,
        "path_choices": PATH_FILTER_CHOICES,
        "path_filter_endpoint": "finance.receivables",
        "filter_query": {
            "filter": selected_filter,
            "client_id": selected_client_id,
            "branch_id": selected_branch_id,
            "bill_to_type": selected_bill_to_type,
            "status": selected_status,
            "period_from": selected_period_from_raw,
            "period_to": selected_period_to_raw,
            "path": selected_path,
        },
    }


# === PRODUCTION_CASH_BANK_LEDGER_ROUTE ===


# === PRODUCTION_AP_AGING_DETAIL_REPORTS ===
