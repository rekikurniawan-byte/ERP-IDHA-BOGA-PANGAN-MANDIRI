from __future__ import annotations

from collections import OrderedDict
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from flask import url_for

from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
from app.models.finance import CashBankTransaction, Invoice, Payment, SupplierBill, SupplierPayment
from app.models.logistics import Procurement
from app.models.operational import DailyOrder
from app.services.digital_attachment_service import count_reference_attachments
from app.services.stock_service import get_stock_summary


SEVERITY_META = {
    "CRITICAL": {
        "label": "Prioritas Tinggi",
        "badge_class": "bg-danger-subtle text-danger border",
        "card_class": "border-danger-subtle",
        "icon": "bi-exclamation-triangle",
    },
    "WARNING": {
        "label": "Perlu Dicek",
        "badge_class": "bg-warning-subtle text-warning border",
        "card_class": "border-warning-subtle",
        "icon": "bi-exclamation-circle",
    },
    "INFO": {
        "label": "Informasi",
        "badge_class": "bg-info-subtle text-info border",
        "card_class": "border-info-subtle",
        "icon": "bi-info-circle",
    },
}


SECTION_LABELS = OrderedDict([
    ("receivable", {"title": "Invoice & Piutang", "icon": "bi-receipt", "description": "Reminder tagihan client/perusahaan yang perlu difollow up."}),
    ("payable", {"title": "Hutang Supplier", "icon": "bi-truck", "description": "Reminder supplier bill yang akan jatuh tempo atau sudah overdue."}),
    ("stock", {"title": "Stok & Bahan", "icon": "bi-box-seam", "description": "Reminder stok kritis dan stok habis."}),
    ("hpp_order", {"title": "Order & HPP", "icon": "bi-clipboard-data", "description": "Reminder order locked yang belum lengkap HPP/snapshot/stok produksi."}),
    ("delivery", {"title": "Delivery", "icon": "bi-send-check", "description": "Reminder pengiriman yang belum diterima atau belum punya bukti digital."}),
    ("digital_proof", {"title": "Bukti Digital", "icon": "bi-paperclip", "description": "Reminder nota, bukti transfer, dan bukti serah terima yang belum dilampirkan."}),
    ("cash_bank", {"title": "Kas/Bank", "icon": "bi-bank", "description": "Reminder transaksi kas/bank yang belum direkonsiliasi."}),
])


def _to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _days_text(target_date: Optional[date], today: date) -> str:
    if not target_date:
        return "Tanpa tanggal"
    diff = (target_date - today).days
    if diff < 0:
        return f"Overdue {abs(diff)} hari"
    if diff == 0:
        return "Jatuh tempo hari ini"
    return f"Jatuh tempo {diff} hari lagi"


def _status_due(target_date: Optional[date], today: date, due_days: int) -> Optional[str]:
    if not target_date:
        return "WARNING"
    diff = (target_date - today).days
    if diff < 0:
        return "CRITICAL"
    if diff <= due_days:
        return "WARNING"
    return None


def _safe_url(endpoint: str, **kwargs) -> str:
    try:
        return url_for(endpoint, **kwargs)
    except Exception:
        return "#"


def _reminder(
    *,
    section: str,
    severity: str,
    title: str,
    message: str,
    reference_label: str = "-",
    due_date: Optional[date] = None,
    amount: Optional[float] = None,
    action_url: str = "#",
    action_label: str = "Buka Detail",
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    severity = severity if severity in SEVERITY_META else "INFO"
    return {
        "section": section,
        "severity": severity,
        "severity_meta": SEVERITY_META[severity],
        "title": title,
        "message": message,
        "reference_label": reference_label,
        "due_date": due_date,
        "amount": _to_float(amount) if amount is not None else None,
        "action_url": action_url,
        "action_label": action_label,
        "metadata": metadata or {},
    }


def _append(reminders: Dict[str, List[Dict[str, Any]]], item: Dict[str, Any]) -> None:
    reminders.setdefault(item["section"], []).append(item)


def _build_receivable_reminders(branch_id: int, today: date, due_days: int, reminders: Dict[str, List[Dict[str, Any]]], limit: int) -> None:
    invoices = Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.remaining_amount > 0,
        Invoice.status != "PAID",
    ).order_by(Invoice.due_date.asc(), Invoice.id.asc()).limit(100).all()

    for invoice in invoices:
        severity = _status_due(invoice.due_date, today, due_days)
        if not severity:
            continue
        _append(reminders, _reminder(
            section="receivable",
            severity=severity,
            title=f"Invoice {invoice.invoice_number} perlu follow-up",
            message=f"Sisa piutang {invoice.remaining_amount:,.0f}. {_days_text(invoice.due_date, today)}.",
            reference_label=invoice.invoice_number,
            due_date=invoice.due_date,
            amount=invoice.remaining_amount,
            action_url=_safe_url("finance.invoice_detail", invoice_id=invoice.id),
            action_label="Buka Invoice",
            metadata={"status": invoice.status, "paid_amount": invoice.paid_amount},
        ))
        if len(reminders.get("receivable", [])) >= limit:
            break


def _build_payable_reminders(branch_id: int, today: date, due_days: int, reminders: Dict[str, List[Dict[str, Any]]], limit: int) -> None:
    bills = SupplierBill.query.filter(
        SupplierBill.branch_id == branch_id,
        SupplierBill.remaining_amount > 0,
        SupplierBill.status != "PAID",
    ).order_by(SupplierBill.due_date.asc(), SupplierBill.id.asc()).limit(100).all()

    for bill in bills:
        severity = _status_due(bill.due_date, today, due_days)
        if not severity:
            continue
        _append(reminders, _reminder(
            section="payable",
            severity=severity,
            title=f"Hutang {bill.supplier_name} perlu dicek",
            message=f"Sisa hutang {bill.remaining_amount:,.0f}. {_days_text(bill.due_date, today)}.",
            reference_label=bill.bill_number,
            due_date=bill.due_date,
            amount=bill.remaining_amount,
            action_url=_safe_url("finance.supplier_bill_detail", bill_id=bill.id),
            action_label="Buka Hutang",
            metadata={"status": bill.status, "paid_amount": bill.paid_amount},
        ))
        if len(reminders.get("payable", [])) >= limit:
            break


def _build_stock_reminders(branch_id: int, reminders: Dict[str, List[Dict[str, Any]]], limit: int) -> None:
    summary = get_stock_summary(branch_id)
    rows = [row for row in summary.get("rows", []) if row.get("stock_status") in ["LOW", "OUT"]]
    rows.sort(key=lambda row: (0 if row.get("stock_status") == "OUT" else 1, str(row.get("item").item_name if row.get("item") else "")))

    for row in rows[:limit]:
        item = row.get("item")
        if not item:
            continue
        is_out = row.get("stock_status") == "OUT"
        _append(reminders, _reminder(
            section="stock",
            severity="CRITICAL" if is_out else "WARNING",
            title=f"Stok {item.item_name} {'habis' if is_out else 'rendah'}",
            message=f"Stok saat ini {row.get('stock_qty', 0):g} {item.unit}. Minimum stok {item.minimum_stock:g} {item.unit}.",
            reference_label=item.item_code,
            amount=row.get("stock_qty", 0),
            action_url=_safe_url("logistics.item_card", item_id=item.id),
            action_label="Buka Kartu Stok",
            metadata={"minimum_stock": item.minimum_stock, "status": row.get("stock_status")},
        ))


def _build_hpp_order_reminders(branch_id: int, today: date, reminders: Dict[str, List[Dict[str, Any]]], limit: int) -> None:
    orders = DailyOrder.query.filter(
        DailyOrder.branch_id == branch_id,
        DailyOrder.is_locked == True,
    ).order_by(DailyOrder.order_date.desc(), DailyOrder.id.desc()).limit(120).all()

    count = 0
    for order in orders:
        snapshots = list(getattr(order, "hpp_snapshots", []) or [])
        if not snapshots:
            _append(reminders, _reminder(
                section="hpp_order",
                severity="WARNING",
                title=f"Order {order.order_number} belum punya Snapshot HPP",
                message="Order sudah locked, tapi HPP snapshot belum dibuat. Margin dan pemakaian bahan belum bisa dipastikan.",
                reference_label=order.order_number,
                due_date=order.order_date,
                action_url=_safe_url("operational.order_detail", order_id=order.id),
                action_label="Buka Order",
                metadata={"order_status": order.status, "is_locked": order.is_locked},
            ))
            count += 1
        else:
            latest = sorted(snapshots, key=lambda snap: snap.id, reverse=True)[0]
            if not getattr(latest, "stock_consumption", None):
                _append(reminders, _reminder(
                    section="hpp_order",
                    severity="INFO",
                    title=f"Snapshot HPP {latest.snapshot_number} belum commit stok",
                    message="Snapshot sudah ada, tapi pemakaian bahan produksi belum di-commit ke stok. Lakukan dry-run dulu sebelum commit.",
                    reference_label=latest.snapshot_number,
                    due_date=order.order_date,
                    action_url=_safe_url("operational.order_hpp_snapshot_detail", order_id=order.id, snapshot_id=latest.id),
                    action_label="Buka Snapshot",
                    metadata={"order_number": order.order_number, "snapshot_status": latest.status},
                ))
                count += 1

        if count >= limit:
            break

    # Reminder default menu hanya untuk order dekat hari ini supaya tidak terlalu ramai.
    upcoming = DailyOrder.query.filter(
        DailyOrder.branch_id == branch_id,
        DailyOrder.order_date >= today,
        DailyOrder.order_date <= today + timedelta(days=7),
    ).order_by(DailyOrder.order_date.asc(), DailyOrder.id.asc()).limit(50).all()

    for order in upcoming:
        total_lunch = sum(_to_float(getattr(detail, "lunch_qty", 0)) for detail in order.details)
        total_dinner = sum(_to_float(getattr(detail, "dinner_qty", 0)) for detail in order.details)
        missing = []
        if total_lunch > 0 and not order.lunch_menu_id:
            missing.append("menu siang")
        if total_dinner > 0 and not order.dinner_menu_id:
            missing.append("menu sore")
        if (total_lunch + total_dinner) > 0 and not order.packaging_profile_id:
            missing.append("profil kemasan")
        if (total_lunch + total_dinner) > 0 and not order.overhead_profile_id:
            missing.append("profil overhead")
        if missing:
            _append(reminders, _reminder(
                section="hpp_order",
                severity="WARNING",
                title=f"Default HPP order {order.order_number} belum lengkap",
                message=f"Lengkapi {', '.join(missing)} agar prediksi bahan dan snapshot HPP tidak perlu input manual berulang.",
                reference_label=order.order_number,
                due_date=order.order_date,
                action_url=_safe_url("operational.order_hpp_defaults", order_id=order.id),
                action_label="Atur Default HPP",
                metadata={"missing": missing},
            ))
            if len(reminders.get("hpp_order", [])) >= limit:
                break


def _build_delivery_reminders(branch_id: int, today: date, reminders: Dict[str, List[Dict[str, Any]]], limit: int) -> None:
    deliveries = Delivery.query.filter(
        Delivery.branch_id == branch_id,
        Delivery.delivery_date <= today,
    ).order_by(Delivery.delivery_date.desc(), Delivery.id.desc()).limit(80).all()

    count = 0
    for delivery in deliveries:
        for detail in delivery.details:
            receipt = detail.receipt
            if not receipt:
                _append(reminders, _reminder(
                    section="delivery",
                    severity="WARNING",
                    title=f"Delivery {delivery.delivery_number} belum ada penerimaan",
                    message=f"Lokasi {detail.delivery_location.location_name if detail.delivery_location else '-'} belum punya receipt penerimaan.",
                    reference_label=delivery.delivery_number,
                    due_date=delivery.delivery_date,
                    action_url=_safe_url("delivery.detail", delivery_id=delivery.id),
                    action_label="Buka Delivery",
                    metadata={"planned_qty": detail.planned_qty, "delivered_qty": detail.delivered_qty},
                ))
                count += 1
            else:
                proof_count = count_reference_attachments(
                    module="DELIVERY",
                    reference_type="DELIVERY_RECEIPT",
                    reference_id=receipt.id,
                    branch_id=branch_id,
                )
                if proof_count <= 0:
                    _append(reminders, _reminder(
                        section="delivery",
                        severity="INFO",
                        title=f"Receipt delivery {delivery.delivery_number} belum punya bukti digital",
                        message="Penerimaan sudah dicatat, tapi foto/surat jalan/bukti terima belum dilampirkan.",
                        reference_label=delivery.delivery_number,
                        due_date=delivery.delivery_date,
                        action_url=_safe_url("delivery.detail", delivery_id=delivery.id),
                        action_label="Buka Delivery",
                        metadata={"receipt_id": receipt.id},
                    ))
                    count += 1
            if count >= limit:
                return


def _build_digital_proof_reminders(branch_id: int, reminders: Dict[str, List[Dict[str, Any]]], limit: int) -> None:
    count = 0

    procurements = Procurement.query.filter_by(branch_id=branch_id).order_by(Procurement.procurement_date.desc(), Procurement.id.desc()).limit(80).all()
    for procurement in procurements:
        proof_count = count_reference_attachments(
            module="PROCUREMENT",
            reference_type="PROCUREMENT",
            reference_id=procurement.id,
            branch_id=branch_id,
        )
        if proof_count <= 0:
            _append(reminders, _reminder(
                section="digital_proof",
                severity="INFO",
                title=f"Pembelian {procurement.procurement_number} belum punya nota digital",
                message=f"Tempat belanja: {procurement.purchase_place or procurement.supplier_name or '-'}.",
                reference_label=procurement.procurement_number,
                due_date=procurement.procurement_date,
                amount=procurement.total_amount,
                action_url=_safe_url("logistics.purchase_detail", procurement_id=procurement.id),
                action_label="Buka Pembelian",
            ))
            count += 1
        if count >= limit:
            return

    payments = Payment.query.filter_by(branch_id=branch_id).order_by(Payment.payment_date.desc(), Payment.id.desc()).limit(80).all()
    for payment in payments:
        method = str(payment.payment_method or "").upper()
        if method not in ["TRANSFER", "BANK", "QRIS"]:
            continue
        proof_count = count_reference_attachments(
            module="CUSTOMER_PAYMENT",
            reference_type="PAYMENT",
            reference_id=payment.id,
            branch_id=branch_id,
        )
        if proof_count <= 0:
            _append(reminders, _reminder(
                section="digital_proof",
                severity="WARNING",
                title=f"Payment customer {payment.payment_number} belum punya bukti transfer",
                message="Pembayaran transfer sebaiknya punya screenshot/bukti transfer untuk audit.",
                reference_label=payment.payment_number,
                due_date=payment.payment_date,
                amount=payment.amount,
                action_url=_safe_url("finance.invoice_detail", invoice_id=payment.invoice_id),
                action_label="Buka Invoice",
            ))
            count += 1
        if count >= limit:
            return

    supplier_payments = SupplierPayment.query.filter_by(branch_id=branch_id).order_by(SupplierPayment.payment_date.desc(), SupplierPayment.id.desc()).limit(80).all()
    for payment in supplier_payments:
        method = str(payment.payment_method or "").upper()
        if method not in ["TRANSFER", "BANK", "QRIS"]:
            continue
        proof_count = count_reference_attachments(
            module="SUPPLIER_PAYMENT",
            reference_type="SUPPLIER_PAYMENT",
            reference_id=payment.id,
            branch_id=branch_id,
        )
        if proof_count <= 0:
            _append(reminders, _reminder(
                section="digital_proof",
                severity="WARNING",
                title=f"Payment supplier {payment.payment_number} belum punya bukti transfer",
                message="Pembayaran supplier via transfer sebaiknya punya bukti digital.",
                reference_label=payment.payment_number,
                due_date=payment.payment_date,
                amount=payment.amount,
                action_url=_safe_url("finance.supplier_bill_detail", bill_id=payment.supplier_bill_id),
                action_label="Buka Hutang Supplier",
            ))
            count += 1
        if count >= limit:
            return


def _build_cash_bank_reminders(branch_id: int, reminders: Dict[str, List[Dict[str, Any]]], limit: int) -> None:
    transactions = CashBankTransaction.query.filter(
        CashBankTransaction.branch_id == branch_id,
        CashBankTransaction.is_reconciled == False,
    ).order_by(CashBankTransaction.transaction_date.desc(), CashBankTransaction.id.desc()).limit(limit).all()

    for trx in transactions:
        _append(reminders, _reminder(
            section="cash_bank",
            severity="INFO",
            title="Transaksi kas/bank belum rekonsiliasi",
            message=f"{trx.transaction_type} {trx.account_type} sebesar {trx.amount:,.0f}. {trx.description}",
            reference_label=f"Ledger #{trx.id}",
            due_date=trx.transaction_date,
            amount=trx.amount,
            action_url=_safe_url("finance.cash_bank_ledger"),
            action_label="Buka Ledger",
            metadata={"reference_type": trx.reference_type, "reference_id": trx.reference_id},
        ))


def build_live_reminder_center(branch_id: int, *, due_days: int = 7, limit_per_section: int = 15) -> Dict[str, Any]:
    """Build live reminders from active transactional data.

    Read-only. Fungsi ini tidak membuat row notifications, tidak commit database,
    dan tidak mengubah transaksi apa pun.
    """
    today = date.today()
    try:
        due_days = max(0, min(int(due_days), 60))
    except Exception:
        due_days = 7
    try:
        limit_per_section = max(5, min(int(limit_per_section), 50))
    except Exception:
        limit_per_section = 15

    reminders: Dict[str, List[Dict[str, Any]]] = {key: [] for key in SECTION_LABELS.keys()}

    _build_receivable_reminders(branch_id, today, due_days, reminders, limit_per_section)
    _build_payable_reminders(branch_id, today, due_days, reminders, limit_per_section)
    _build_stock_reminders(branch_id, reminders, limit_per_section)
    _build_hpp_order_reminders(branch_id, today, reminders, limit_per_section)
    _build_delivery_reminders(branch_id, today, reminders, limit_per_section)
    _build_digital_proof_reminders(branch_id, reminders, limit_per_section)
    _build_cash_bank_reminders(branch_id, reminders, limit_per_section)

    section_rows = []
    total = 0
    severity_counts = {"CRITICAL": 0, "WARNING": 0, "INFO": 0}

    for key, meta in SECTION_LABELS.items():
        items = reminders.get(key, [])
        for item in items:
            severity_counts[item["severity"]] += 1
        total += len(items)
        section_rows.append({
            "key": key,
            "title": meta["title"],
            "icon": meta["icon"],
            "description": meta["description"],
            "items": items,
            "count": len(items),
            "critical_count": sum(1 for item in items if item["severity"] == "CRITICAL"),
            "warning_count": sum(1 for item in items if item["severity"] == "WARNING"),
            "info_count": sum(1 for item in items if item["severity"] == "INFO"),
        })

    if severity_counts["CRITICAL"] > 0:
        overall_status = "PRIORITAS TINGGI"
        overall_badge = "bg-danger-subtle text-danger border"
    elif severity_counts["WARNING"] > 0:
        overall_status = "PERLU DICEK"
        overall_badge = "bg-warning-subtle text-warning border"
    elif severity_counts["INFO"] > 0:
        overall_status = "ADA INFO"
        overall_badge = "bg-info-subtle text-info border"
    else:
        overall_status = "AMAN"
        overall_badge = "bg-success-subtle text-success border"

    return {
        "today": today,
        "due_days": due_days,
        "limit_per_section": limit_per_section,
        "overall_status": overall_status,
        "overall_badge": overall_badge,
        "summary": {
            "total": total,
            "critical": severity_counts["CRITICAL"],
            "warning": severity_counts["WARNING"],
            "info": severity_counts["INFO"],
            "section_count": len(section_rows),
        },
        "sections": section_rows,
    }


def build_empty_live_reminder_center(*, due_days: int = 7, runtime_warning: Optional[str] = None) -> Dict[str, Any]:
    """Return a safe empty reminder center when live reminder calculation fails.

    Read-only fallback. Dipakai supaya halaman Reminder Live tidak menjadi 500
    kalau ada satu query reminder yang belum cocok dengan database aktif.
    """
    today = date.today()
    try:
        due_days = max(0, min(int(due_days), 60))
    except Exception:
        due_days = 7

    section_rows = []
    for key, meta in SECTION_LABELS.items():
        section_rows.append({
            "key": key,
            "title": meta["title"],
            "icon": meta["icon"],
            "description": meta["description"],
            "items": [],
            "count": 0,
            "critical_count": 0,
            "warning_count": 0,
            "info_count": 0,
        })

    return {
        "today": today,
        "due_days": due_days,
        "limit_per_section": 0,
        "overall_status": "PERLU DICEK" if runtime_warning else "AMAN",
        "overall_badge": "bg-warning-subtle text-warning border" if runtime_warning else "bg-success-subtle text-success border",
        "runtime_warning": runtime_warning,
        "summary": {
            "total": 0,
            "critical": 0,
            "warning": 0,
            "info": 0,
            "section_count": len(section_rows),
        },
        "sections": section_rows,
    }

def build_live_reminder_badge_summary(branch_id: int, *, due_days: int = 7) -> Dict[str, Any]:
    """Build a compact reminder badge summary for dashboard/sidebar.

    Read-only. Fungsi ini hanya membaca data aktif dan tidak menyimpan row
    notifications agar database utama tetap clean.
    """
    center = build_live_reminder_center(
        branch_id,
        due_days=due_days,
        limit_per_section=15,
    )

    priority_sections = [
        {
            "key": section["key"],
            "title": section["title"],
            "count": section["count"],
            "critical_count": section["critical_count"],
            "warning_count": section["warning_count"],
            "info_count": section["info_count"],
            "icon": section["icon"],
        }
        for section in center.get("sections", [])
        if section.get("count", 0) > 0
    ]

    priority_sections.sort(
        key=lambda row: (
            -int(row.get("critical_count", 0)),
            -int(row.get("warning_count", 0)),
            -int(row.get("count", 0)),
            str(row.get("title", "")),
        )
    )

    summary = center.get("summary", {})
    total = int(summary.get("total", 0) or 0)
    critical = int(summary.get("critical", 0) or 0)
    warning = int(summary.get("warning", 0) or 0)
    info = int(summary.get("info", 0) or 0)

    if critical > 0:
        badge_class = "bg-danger-subtle text-danger border"
        icon = "bi-exclamation-triangle"
        label = "Prioritas Tinggi"
    elif warning > 0:
        badge_class = "bg-warning-subtle text-warning border"
        icon = "bi-exclamation-circle"
        label = "Perlu Dicek"
    elif info > 0:
        badge_class = "bg-info-subtle text-info border"
        icon = "bi-info-circle"
        label = "Ada Info"
    else:
        badge_class = "bg-success-subtle text-success border"
        icon = "bi-check2-circle"
        label = "Aman"

    return {
        "total": total,
        "critical": critical,
        "warning": warning,
        "info": info,
        "badge_class": badge_class,
        "icon": icon,
        "label": label,
        "top_sections": priority_sections[:3],
        "action_url": _safe_url("settings.live_reminders"),
        "today": center.get("today"),
        "read_only": True,
    }

