from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.services.portal_closing_visibility_service import build_portal_closing_visibility
from app.services.portal_debt_visibility_service import build_portal_worker_debt_read_model
from app.services.portal_experience_service import build_portal_complaint_model, build_portal_contract_model
from app.services.portal_financial_visibility_service import (
    build_portal_invoice_read_model,
    build_portal_payment_history_read_model,
)
from app.services.portal_integrated_foundation_service import (
    build_portal_approval_model,
    build_portal_calendar_model,
    build_portal_document_model,
    build_portal_notification_model,
    build_portal_return_model,
    build_portal_subscription_model,
)
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, build_portal_external_scope
from app.services.portal_order_draft_service import build_portal_order_status_context
from app.services.user_management_service import (
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_MANDOR,
    ROLE_PORTAL_PT,
)


MONEY_ZERO = Decimal("0")


def _money(value: Any) -> Decimal:
    if value is None:
        return MONEY_ZERO
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _status_key(value: Any) -> str:
    return str(value or "").strip().upper() or "-"


def _display_integration_status(value: Any) -> str:
    key = _status_key(value)
    labels = {
        "ADD_ONLY": "Menunggu Admin",
        "READ_EXISTING": "Terhubung",
        "OWNERSHIP_GUARDED": "Akses Dibatasi",
        "TARGETED": "Sesuai Akun",
        "PORTAL_PT_SCOPE": "Akses PT",
        "PORTAL_CLIENT_SCOPE": "Akses Perusahaan",
        "PORTAL_MANDOR_SCOPE": "Akses Mandor",
        "PORTAL_DELEGATE_SCOPE": "Akses Delegasi",
        "PORTAL_CUSTOMER_SCOPE": "Akses Pelanggan",
        "PORTAL_CUSTOMER_PENDING_SCOPE": "Akses Pelanggan",
        "NO_ACTIVE_PORTAL_MAPPING": "Belum Terhubung",
        "NOT_PORTAL_EXTERNAL_ROLE": "Internal",
    }
    return labels.get(key, str(value or "-").replace("_", " ").title())


def _date_or_none(value: Any):
    if isinstance(value, datetime):
        return value.date()
    return value if isinstance(value, date) else None


def _date_label(value: Any) -> str:
    parsed = _date_or_none(value)
    return parsed.strftime("%d-%m-%Y") if parsed else "-"


def _display_status(value: Any) -> str:
    key = _status_key(value)
    labels = {
        "WAITING_ADMIN": "Menunggu Admin",
        "PENDING_ADMIN_CONFIRMATION": "Menunggu Admin",
        "CONFIRMED": "Dikonfirmasi",
        "REJECTED": "Ditolak",
        "ADMIN_CONFIRMED": "Dikonfirmasi Admin",
        "LOCKED": "Dikunci",
        "PRODUCTION": "Produksi",
        "PRODUCTION_DONE": "Produksi Selesai",
        "DELIVERY": "Pengiriman",
        "DELIVERED": "Terkirim",
        "DRAFT": "Konsep",
        "ACTIVE": "Aktif",
        "PARTIAL": "Bayar Sebagian",
        "PAID": "Lunas",
        "OPEN": "Terbuka",
        "CLOSED": "Ditutup",
        "SUBMITTED": "Diajukan",
        "APPROVED": "Disetujui",
        "CANCELLED": "Dibatalkan",
    }
    return labels.get(key, key.replace("_", " ").title() if key else "-")


def _role_family(role: str | None) -> str:
    role = _status_key(role)
    if role == ROLE_PORTAL_CUSTOMER:
        return "customer"
    if role == ROLE_PORTAL_MANDOR:
        return "mandor"
    if role == ROLE_PORTAL_PT:
        return "pt"
    if role == ROLE_PORTAL_CLIENT:
        return "client"
    if role == ROLE_PORTAL_DELEGATE:
        return "delegate"
    return "internal"


def _home_endpoint(role: str | None) -> str:
    return {
        ROLE_PORTAL_CUSTOMER: "portal.customer_dashboard",
        ROLE_PORTAL_MANDOR: "portal.mandor_dashboard",
        ROLE_PORTAL_PT: "portal.pt_dashboard",
        ROLE_PORTAL_CLIENT: "portal.client_dashboard",
        ROLE_PORTAL_DELEGATE: "portal.delegate_dashboard",
    }.get(role, "portal.my_dashboard")


def _primary_order_endpoint(role: str | None) -> str | None:
    return {
        ROLE_PORTAL_CUSTOMER: "portal.customer_order",
        ROLE_PORTAL_MANDOR: "portal.mandor_order",
        ROLE_PORTAL_PT: "portal.pt_order",
    }.get(role)


def _invoice_endpoint(role: str | None) -> str:
    return {
        ROLE_PORTAL_CUSTOMER: "portal.customer_invoices",
        ROLE_PORTAL_MANDOR: "portal.mandor_invoices",
        ROLE_PORTAL_PT: "portal.pt_invoices",
    }.get(role, "portal.invoices")


def _payment_endpoint(role: str | None) -> str:
    return {
        ROLE_PORTAL_CUSTOMER: "portal.customer_payments",
        ROLE_PORTAL_MANDOR: "portal.mandor_payments",
    }.get(role, "portal.payments")


def _debt_endpoint(role: str | None) -> str:
    if role == ROLE_PORTAL_MANDOR:
        return "portal.mandor_canteen_debts"
    return "portal.debts"


def _contract_endpoint(role: str | None) -> str | None:
    return "portal.pt_contracts" if role == ROLE_PORTAL_PT else None


def _subscription_endpoint(role: str | None) -> str | None:
    return {
        ROLE_PORTAL_MANDOR: "portal.mandor_subscriptions",
        ROLE_PORTAL_PT: "portal.pt_subscriptions",
    }.get(role)


def _action(label: str, endpoint: str | None, icon: str, tone: str, caption: str, *, enabled: bool = True) -> dict:
    return {
        "label": label,
        "endpoint": endpoint,
        "icon": icon,
        "tone": tone,
        "caption": caption,
        "enabled": bool(endpoint and enabled),
    }


def _build_quick_actions(role: str | None, scope) -> list[dict]:
    actions = []
    order_endpoint = _primary_order_endpoint(role)
    order_enabled = bool(scope.allowed and ACCESS_DRAFT_ORDER in getattr(scope, "access_levels", set()))
    if role == ROLE_PORTAL_CUSTOMER:
        order_enabled = False

    actions.append(
        _action(
            "Pesan Catering",
            order_endpoint,
            "bi-bag-plus",
            "green",
            "Draft pesanan masuk ke antrean admin, bukan langsung produksi.",
            enabled=order_enabled,
        )
    )
    actions.append(
        _action(
            "Tagihan",
            _invoice_endpoint(role),
            "bi-receipt",
            "blue",
            "Tagihan diambil dari data invoice perusahaan.",
            enabled=role != ROLE_PORTAL_CUSTOMER,
        )
    )
    actions.append(
        _action(
            "Pembayaran",
            _payment_endpoint(role),
            "bi-credit-card",
            "orange",
            "Riwayat pembayaran dan unggah bukti.",
            enabled=True,
        )
    )
    if role in {ROLE_PORTAL_MANDOR, ROLE_PORTAL_PT, ROLE_PORTAL_CLIENT, ROLE_PORTAL_DELEGATE}:
        actions.append(
            _action(
                "Hutang",
                _debt_endpoint(role),
                "bi-wallet2",
                "purple",
                "Hutang pekerja sesuai data mandor.",
                enabled=role != ROLE_PORTAL_CUSTOMER,
            )
        )
    if role == ROLE_PORTAL_PT:
        actions.append(
            _action(
                "Kontrak",
                _contract_endpoint(role),
                "bi-file-earmark-text",
                "slate",
                "Kontrak perusahaan yang aktif.",
                enabled=True,
            )
        )
    if role in {ROLE_PORTAL_MANDOR, ROLE_PORTAL_PT}:
        actions.append(
            _action(
                "Langganan",
                _subscription_endpoint(role),
                "bi-calendar2-week",
                "green",
                "Pola pesanan berulang.",
                enabled=True,
            )
        )
    if role == ROLE_PORTAL_CUSTOMER:
        actions.append(
            _action(
                "Komplain",
                "portal.customer_complaints",
                "bi-chat-square-text",
                "red",
                "Keluhan masuk ke layanan admin.",
                enabled=True,
            )
        )
        actions.append(
            _action(
                "Retur",
                "portal.customer_returns",
                "bi-arrow-counterclockwise",
                "orange",
                "Laporan retur untuk diperiksa admin.",
                enabled=True,
            )
        )

    actions.extend(
        [
            _action("Notifikasi", "portal.notifications", "bi-bell", "blue", "Pemberitahuan akun."),
            _action("Dokumen", "portal.documents", "bi-folder2-open", "slate", "Arsip bukti dan dokumen."),
            _action("Kalender", "portal.calendar", "bi-calendar-event", "purple", "Draft, jatuh tempo tagihan, pengiriman, kontrak."),
            _action("Persetujuan", "portal.approvals", "bi-shield-check", "green", "ApprovalRequest yang dibuat user."),
        ]
    )
    return actions


def _build_kpis(role: str | None, models: dict) -> list[dict]:
    orders = models["orders"]
    invoices = models["invoices"]["totals"]
    payments = models["payments"]["totals"]
    debts = models["debts"]["totals"]
    notifications = models["notifications"]["totals"]
    documents = models["documents"]["totals"]
    approvals = models["approvals"]["totals"]
    contracts = models["contracts"]["totals"]
    complaints = models["complaints"]["totals"]
    returns = models["returns"]["totals"]

    kpis = [
        {
            "label": "Pesanan",
            "value": orders.get("total", 0),
            "caption": f"{orders.get('pending', 0)} menunggu admin",
            "icon": "bi-bag-check",
            "tone": "green",
        },
        {
            "label": "Tagihan",
            "value": invoices.get("invoice_count", 0),
            "caption": f"Sisa tagihan {invoices.get('active_outstanding_amount', MONEY_ZERO)}",
            "icon": "bi-receipt",
            "tone": "blue",
            "money_caption": True,
        },
        {
            "label": "Pembayaran",
            "value": payments.get("payment_count", 0),
            "caption": f"Total {payments.get('payment_amount', MONEY_ZERO)}",
            "icon": "bi-credit-card",
            "tone": "orange",
            "money_caption": True,
        },
        {
            "label": "Notifikasi",
            "value": notifications.get("unread", 0),
            "caption": f"{notifications.get('total', 0)} total",
            "icon": "bi-bell",
            "tone": "red" if notifications.get("unread", 0) else "slate",
        },
    ]

    if role in {ROLE_PORTAL_MANDOR, ROLE_PORTAL_PT, ROLE_PORTAL_CLIENT, ROLE_PORTAL_DELEGATE}:
        kpis.append(
            {
                "label": "Hutang",
                "value": debts.get("active_debt_count", 0),
                "caption": f"Sisa {debts.get('active_remaining_amount', MONEY_ZERO)}",
                "icon": "bi-wallet2",
                "tone": "purple",
                "money_caption": True,
            }
        )
    if role == ROLE_PORTAL_PT:
        kpis.append(
            {
                "label": "Kontrak",
                "value": contracts.get("active_count", 0),
                "caption": f"{contracts.get('contract_count', 0)} total",
                "icon": "bi-file-earmark-text",
                "tone": "slate",
            }
        )
    if role == ROLE_PORTAL_CUSTOMER:
        kpis.extend(
            [
                {
                    "label": "Komplain",
                    "value": complaints.get("open_count", 0),
                    "caption": f"{complaints.get('complaint_count', 0)} total",
                    "icon": "bi-chat-square-text",
                    "tone": "red" if complaints.get("open_count", 0) else "slate",
                },
                {
                    "label": "Retur",
                    "value": returns.get("open", 0),
                    "caption": f"{returns.get('total', 0)} total",
                    "icon": "bi-arrow-counterclockwise",
                    "tone": "orange",
                },
            ]
        )

    kpis.append(
        {
            "label": "Dokumen",
            "value": documents.get("total", 0),
            "caption": f"{documents.get('payment_proof', 0)} bukti bayar",
            "icon": "bi-folder2-open",
            "tone": "slate",
        }
    )
    kpis.append(
        {
            "label": "Persetujuan",
            "value": approvals.get("submitted", 0),
            "caption": f"{approvals.get('total', 0)} permintaan",
            "icon": "bi-shield-check",
            "tone": "green",
        }
    )
    return kpis


def _focus_card(label: str, value: Any, caption: str, icon: str, tone: str, endpoint: str | None = None) -> dict:
    return {
        "label": label,
        "value": value,
        "caption": caption,
        "icon": icon,
        "tone": tone,
        "endpoint": endpoint,
        "enabled": bool(endpoint),
    }


def _build_role_focus(role: str | None, models: dict) -> list[dict]:
    orders = models["orders"]
    invoices = models["invoices"]["totals"]
    payments = models["payments"]["totals"]
    debts = models["debts"]["totals"]
    contracts = models["contracts"]["totals"]
    complaints = models["complaints"]["totals"]
    returns = models["returns"]["totals"]
    calendar = models["calendar"]["totals"]
    scope = models["scope"]

    if role == ROLE_PORTAL_CUSTOMER:
        return [
            _focus_card(
                "Order Saya",
                orders.get("total", 0),
                f"{orders.get('pending', 0)} menunggu admin, {orders.get('in_delivery', 0)} dalam pengiriman.",
                "bi-bag-check",
                "green",
                "portal.customer_tracking",
            ),
            _focus_card(
                "Pembayaran",
                invoices.get("payable_invoice_count", invoices.get("invoice_count", 0)),
                f"Sisa tagihan {invoices.get('active_outstanding_amount', MONEY_ZERO)}",
                "bi-credit-card",
                "orange",
                "portal.customer_payments",
            ),
            _focus_card(
                "Layanan",
                complaints.get("open_count", 0),
                f"{returns.get('open', 0)} retur terbuka, {complaints.get('awaiting_response_count', 0)} perlu respons.",
                "bi-headset",
                "red" if complaints.get("open_count", 0) else "slate",
                "portal.customer_complaints",
            ),
            _focus_card(
                "Agenda",
                calendar.get("today", 0),
                f"{calendar.get('next_7_days', 0)} agenda 7 hari ke depan.",
                "bi-calendar-event",
                "purple",
                "portal.calendar",
            ),
        ]

    if role == ROLE_PORTAL_MANDOR:
        return [
            _focus_card(
                "Order Mandor",
                orders.get("total", 0),
                f"{orders.get('confirmed', 0)} sudah dikonfirmasi, {orders.get('rejected', 0)} ditolak.",
                "bi-bag-plus",
                "green",
                "portal.order_status",
            ),
            _focus_card(
                "Tagihan",
                invoices.get("invoice_count", 0),
                f"Sisa tagihan {invoices.get('active_outstanding_amount', MONEY_ZERO)}",
                "bi-receipt",
                "blue",
                "portal.mandor_invoices",
            ),
            _focus_card(
                "Hutang Pekerja",
                debts.get("active_debt_count", 0),
                f"Sisa {debts.get('active_remaining_amount', MONEY_ZERO)}",
                "bi-wallet2",
                "purple",
                "portal.mandor_canteen_debts",
            ),
            _focus_card(
                "Pembayaran",
                payments.get("payment_count", 0),
                f"Riwayat bayar {payments.get('payment_amount', MONEY_ZERO)}",
                "bi-credit-card",
                "orange",
                "portal.mandor_payments",
            ),
        ]

    if role == ROLE_PORTAL_PT:
        return [
            _focus_card(
                "Akses Mandor",
                len(getattr(scope, "mandor_ids", [])),
                "Mandor yang terhubung ke perusahaan.",
                "bi-diagram-3",
                "green",
                "portal.pt_mandors",
            ),
            _focus_card(
                "Piutang",
                invoices.get("active_invoice_count", invoices.get("invoice_count", 0)),
                f"Sisa tagihan {invoices.get('active_outstanding_amount', MONEY_ZERO)}",
                "bi-cash-stack",
                "orange",
                "portal.pt_receivables",
            ),
            _focus_card(
                "Kontrak",
                contracts.get("active_count", 0),
                f"{contracts.get('expiring_soon_count', 0)} hampir berakhir, {contracts.get('expired_count', 0)} kedaluwarsa.",
                "bi-file-earmark-text",
                "slate",
                "portal.pt_contracts",
            ),
            _focus_card(
                "Tagihan",
                invoices.get("invoice_count", 0),
                f"{invoices.get('overdue_count', 0)} terlambat.",
                "bi-receipt",
                "blue",
                "portal.pt_invoices",
            ),
        ]

    return [
        _focus_card("Akses", models["data_sources"][0]["count"] if "data_sources" in models else 0, "Akses akun aktif.", "bi-shield-check", "slate"),
        _focus_card("Tagihan", invoices.get("invoice_count", 0), "Data tagihan perusahaan.", "bi-receipt", "blue", _invoice_endpoint(role)),
        _focus_card("Dokumen", models["documents"]["totals"].get("total", 0), "Arsip bukti dan dokumen.", "bi-folder2-open", "slate", "portal.documents"),
    ]


def _build_alerts(role: str | None, scope, models: dict) -> list[dict]:
    alerts = []
    invoices = models["invoices"]["totals"]
    orders = models["orders"]
    notifications = models["notifications"]["totals"]
    complaints = models["complaints"]["totals"]
    approvals = models["approvals"]["totals"]
    contracts = models["contracts"]["totals"]

    if not scope.allowed:
        alerts.append(
            {
                "level": "danger",
                "title": "Akun belum terhubung",
                "message": scope.reason or "Hubungi admin agar akun tersambung ke data yang benar.",
                "icon": "bi-shield-exclamation",
            }
        )
    if role == ROLE_PORTAL_CUSTOMER:
        alerts.append(
            {
                "level": "warning",
                "title": "Aturan bayar dulu aktif",
                "message": "Pelanggan umum belum boleh membuat order operasional sebelum pembayaran terverifikasi.",
                "icon": "bi-lock",
            }
        )
    if _money(invoices.get("active_outstanding_amount")) > MONEY_ZERO:
        alerts.append(
            {
                "level": "warning",
                "title": "Sisa tagihan aktif",
                "message": "Ada tagihan aktif pada akun ini.",
                "icon": "bi-receipt",
                "endpoint": _invoice_endpoint(role),
            }
        )
    if _as_int(invoices.get("payment_mismatch_count")) > 0:
        alerts.append(
            {
                "level": "danger",
                "title": "Pembayaran tidak cocok",
                "message": "Ada invoice dengan nilai terbayar berbeda dari total pembayaran. Perlu diperiksa finance.",
                "icon": "bi-exclamation-octagon",
                "endpoint": _invoice_endpoint(role),
            }
        )
    if _as_int(orders.get("pending")) > 0:
        alerts.append(
            {
                "level": "info",
                "title": "Pesanan menunggu admin",
                "message": "Pesanan sudah masuk dan menunggu konfirmasi admin.",
                "icon": "bi-hourglass-split",
            }
        )
    if _as_int(orders.get("rejected")) > 0:
        alerts.append(
            {
                "level": "warning",
                "title": "Pesanan ditolak",
                "message": "Ada pesanan yang ditolak. Lihat catatan admin.",
                "icon": "bi-x-circle",
            }
        )
    if _as_int(notifications.get("critical")) > 0:
        alerts.append(
            {
                "level": "danger",
                "title": "Notifikasi kritis",
                "message": "Ada notifikasi prioritas tinggi yang belum ditindaklanjuti.",
                "icon": "bi-bell-fill",
                "endpoint": "portal.notifications",
            }
        )
    if _as_int(complaints.get("open_count")) > 0:
        alerts.append(
            {
                "level": "warning",
                "title": "Komplain terbuka",
                "message": "Ada komplain yang masih diproses.",
                "icon": "bi-chat-square-text",
                "endpoint": "portal.customer_complaints" if role == ROLE_PORTAL_CUSTOMER else None,
            }
        )
    if _as_int(approvals.get("submitted")) > 0:
        alerts.append(
            {
                "level": "info",
                "title": "Approval menunggu",
                "message": "Ada permintaan persetujuan yang masih diajukan.",
                "icon": "bi-shield-check",
                "endpoint": "portal.approvals",
            }
        )
    if role == ROLE_PORTAL_PT and _as_int(contracts.get("active_count")) == 0:
        alerts.append(
            {
                "level": "warning",
                "title": "Belum ada kontrak aktif",
                "message": "PT belum memiliki kontrak aktif dalam akses portal ini.",
                "icon": "bi-file-earmark-text",
                "endpoint": "portal.pt_contracts",
            }
        )
    return alerts[:8]


def _order_timeline_rows(order_model: dict, limit: int = 5) -> list[dict]:
    rows = []
    for order in order_model.get("rows", [])[:limit]:
        rows.append(
            {
                "type": "ORDER",
                "title": f"{order.get('meal_type', '-')} - {order.get('location_name', '-')}",
                "subtitle": f"{order.get('portion_qty', 0)} porsi | {order.get('internal_order_number', '-')}",
                "status": order.get("stage", "-"),
                "date_label": _date_label(order.get("order_date")),
                "icon": "bi-bag-check",
                "tone": "green",
            }
        )
    return rows


def _invoice_timeline_rows(invoice_model: dict, limit: int = 5) -> list[dict]:
    rows = []
    for invoice in invoice_model.get("invoices", [])[:limit]:
        rows.append(
            {
                "type": "INVOICE",
                "title": invoice.get("invoice_number", "-"),
                "subtitle": f"Sisa {invoice.get('remaining_amount', MONEY_ZERO)}",
                "status": invoice.get("status", "-"),
                "date_label": _date_label(invoice.get("due_date")),
                "icon": "bi-receipt",
                "tone": "blue",
                "endpoint": "portal.invoice_payment_instruction",
                "endpoint_args": {"invoice_id": invoice.get("invoice_id")},
            }
        )
    return rows


def _notification_timeline_rows(notification_model: dict, limit: int = 5) -> list[dict]:
    rows = []
    for notification in notification_model.get("rows", [])[:limit]:
        rows.append(
            {
                "type": "NOTIFICATION",
                "title": notification.get("title", "-"),
                "subtitle": notification.get("message", "-"),
                "status": notification.get("priority", "-"),
                "date_label": _date_label(notification.get("created_at")),
                "icon": "bi-bell",
                "tone": "red" if notification.get("priority") == "CRITICAL" else "slate",
                "url": notification.get("action_url"),
            }
        )
    return rows


def _calendar_timeline_rows(calendar_model: dict, limit: int = 5) -> list[dict]:
    rows = []
    for event in calendar_model.get("rows", [])[:limit]:
        rows.append(
            {
                "type": event.get("type", "CALENDAR"),
                "title": event.get("title", "-"),
                "subtitle": event.get("source", "-"),
                "status": event.get("status", "-"),
                "date_label": _date_label(event.get("date")),
                "icon": "bi-calendar-event",
                "tone": "purple",
            }
        )
    return rows


def _build_timeline(models: dict) -> list[dict]:
    rows = []
    rows.extend(_order_timeline_rows(models["orders"], limit=4))
    rows.extend(_invoice_timeline_rows(models["invoices"], limit=4))
    rows.extend(_notification_timeline_rows(models["notifications"], limit=4))
    rows.extend(_calendar_timeline_rows(models["calendar"], limit=4))
    return rows[:12]


def _status_distribution(order_model: dict, invoice_model: dict, debt_model: dict) -> list[dict]:
    order_statuses = Counter(row.get("stage", "-") for row in order_model.get("rows", []))
    invoice_statuses = Counter(row.get("status", "-") for row in invoice_model.get("invoices", []))
    debt_statuses = Counter(row.get("status", "-") for row in debt_model.get("debts", []))
    rows = []
    for label, counter, icon, tone in [
        ("Pesanan", order_statuses, "bi-bag-check", "green"),
        ("Tagihan", invoice_statuses, "bi-receipt", "blue"),
        ("Hutang", debt_statuses, "bi-wallet2", "purple"),
    ]:
        rows.append(
            {
                "label": label,
                "icon": icon,
                "tone": tone,
                "total": sum(counter.values()),
                "items": [{"status": _display_status(status), "count": count} for status, count in counter.most_common(5)],
            }
        )
    return rows


def _build_data_sources(role: str | None, models: dict) -> list[dict]:
    return [
        {
            "label": "Akses",
            "source": "Akun portal dan master data",
            "status": _display_integration_status(models["scope"].scope_mode),
            "count": len(getattr(models["scope"], "client_ids", []))
            + len(getattr(models["scope"], "mandor_ids", []))
            + len(getattr(models["scope"], "delivery_location_ids", [])),
        },
        {
            "label": "Order",
            "source": "Draft portal ke order harian",
            "status": _display_integration_status("ADD_ONLY"),
            "count": models["orders"].get("total", 0),
        },
        {
            "label": "Finance",
            "source": "Invoice, pembayaran, piutang",
            "status": _display_integration_status("READ_EXISTING"),
            "count": models["invoices"]["totals"].get("invoice_count", 0),
        },
        {
            "label": "Document",
            "source": "Bukti digital",
            "status": _display_integration_status("OWNERSHIP_GUARDED"),
            "count": models["documents"]["totals"].get("total", 0),
        },
        {
            "label": "Notification",
            "source": "Pusat notifikasi",
            "status": _display_integration_status("TARGETED"),
            "count": models["notifications"]["totals"].get("total", 0),
        },
        {
            "label": "Approval",
            "source": "Daftar persetujuan",
            "status": _display_integration_status("READ_EXISTING"),
            "count": models["approvals"]["totals"].get("total", 0),
        },
        {
            "label": "Role",
            "source": "Hak akses akun",
            "status": role or "-",
            "count": 1,
        },
    ]


def _build_empty_state(role: str | None, scope, models: dict) -> dict:
    if not scope.allowed:
        return {
            "title": "Akses belum tersambung",
            "message": scope.reason or "User belum punya mapping portal aktif.",
            "action_endpoint": None,
            "action_label": "Hubungi admin",
        }
    if role == ROLE_PORTAL_CUSTOMER:
        return {
            "title": "Portal pelanggan siap",
            "message": "Pesanan pelanggan umum akan aktif setelah pembayaran awal diselesaikan.",
            "action_endpoint": "portal.customer_complaints",
            "action_label": "Kirim komplain",
        }
    if models["orders"].get("total", 0) == 0 and _primary_order_endpoint(role):
        return {
            "title": "Belum ada pesanan",
            "message": "Buat pesanan pertama. Admin tetap harus konfirmasi sebelum diproses.",
            "action_endpoint": _primary_order_endpoint(role),
            "action_label": "Buat Pesanan",
        }
    return {
        "title": "Semua data dalam akses sudah terbaca",
        "message": "Tidak ada item prioritas tambahan dari tampilan portal saat ini.",
        "action_endpoint": "portal.notifications",
        "action_label": "Cek Notifikasi",
    }


def _build_role_narrative(role: str | None) -> dict:
    role = _status_key(role)
    narratives = {
        ROLE_PORTAL_CUSTOMER: {
            "headline": "Pelanggan umum melihat order, pembayaran, komplain, dan retur tanpa membuka data keuangan internal.",
            "guard": "Bayar dulu aktif. Pesanan belum masuk produksi sebelum pembayaran diverifikasi.",
            "integration": "Komplain, retur, dan bukti pembayaran tersimpan dalam satu data perusahaan.",
        },
        ROLE_PORTAL_MANDOR: {
            "headline": "Mandor mengelola order, pekerja, hutang warung, tagihan, dan pembayaran dalam akses mandor.",
            "guard": "Pesanan tetap menunggu admin sebelum masuk produksi dan pengiriman.",
            "integration": "Pesanan, pekerja, hutang, invoice, dan pembayaran tetap memakai data perusahaan yang sama.",
        },
        ROLE_PORTAL_PT: {
            "headline": "PT melihat seluruh mandor, invoice, piutang, kontrak, closing, dan langganan perusahaan.",
            "guard": "PT melihat dan membayar tagihan tanpa mengubah data keuangan secara langsung.",
            "integration": "Kontrak, invoice, mandor, dan lokasi tetap memakai data perusahaan yang sama.",
        },
        ROLE_PORTAL_CLIENT: {
            "headline": "Client/PIC melihat tagihan, pembayaran, dan dokumen yang terhubung ke akunnya.",
            "guard": "Akses dibatasi sesuai perusahaan yang tersambung.",
            "integration": "Data keuangan tetap satu dengan sistem utama.",
        },
        ROLE_PORTAL_DELEGATE: {
            "headline": "Delegasi hanya melihat data yang didelegasikan secara eksplisit.",
            "guard": "Tidak ada akses melebar ke perusahaan lain.",
            "integration": "Batas akses mengikuti pengaturan admin.",
        },
    }
    return narratives.get(
        role,
        {
            "headline": "Portal membaca data perusahaan untuk ringkasan dan monitoring.",
            "guard": "Halaman ringkasan tidak mengubah transaksi.",
            "integration": "Semua angka berasal dari data perusahaan yang sama.",
        },
    )


def build_portal_command_center(user) -> dict:
    """Build a role-aware portal command center from existing ERP data only.

    This service deliberately creates no records and owns no transaction boundary.
    Portal pages use it to make the user-facing experience richer while keeping
    ERP existing as the single source of truth.
    """
    role = getattr(user, "role", None)
    scope = build_portal_external_scope(user)
    models = {
        "scope": scope,
        "orders": build_portal_order_status_context(user, limit=25),
        "invoices": build_portal_invoice_read_model(user, limit=25),
        "payments": build_portal_payment_history_read_model(user, limit=25),
        "debts": build_portal_worker_debt_read_model(user, limit=25),
        "notifications": build_portal_notification_model(user, limit=25),
        "documents": build_portal_document_model(user, limit=25),
        "approvals": build_portal_approval_model(user, limit=25),
        "calendar": build_portal_calendar_model(user, days=45),
        "complaints": build_portal_complaint_model(user, limit=25),
        "returns": build_portal_return_model(user, limit=25),
        "subscriptions": build_portal_subscription_model(user, limit=25),
        "contracts": build_portal_contract_model(user, limit=25),
        "closing": build_portal_closing_visibility(user),
    }
    return {
        "role": role,
        "role_family": _role_family(role),
        "home_endpoint": _home_endpoint(role),
        "scope_mode": scope.scope_mode,
        "scope_allowed": bool(scope.allowed),
        "scope_reason": scope.reason,
        "narrative": _build_role_narrative(role),
        "quick_actions": _build_quick_actions(role, scope),
        "kpis": _build_kpis(role, models),
        "role_focus": _build_role_focus(role, models),
        "alerts": _build_alerts(role, scope, models),
        "timeline": _build_timeline(models),
        "status_distribution": _status_distribution(models["orders"], models["invoices"], models["debts"]),
        "data_sources": _build_data_sources(role, models),
        "empty_state": _build_empty_state(role, scope, models),
        "models": models,
    }
