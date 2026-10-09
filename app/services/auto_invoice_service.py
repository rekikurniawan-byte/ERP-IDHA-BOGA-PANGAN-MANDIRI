"""Invoice periode: pembangun baris bersama + invoice otomatis per siklus kontrak (Fase 6).

Satu sumber aturan tagih untuk invoice periode manual (Finance > Invoice
Periode) dan invoice otomatis jam 06.00:
- porsi = pesanan terkunci dikurangi kekurangan kirim yang belum diganti,
- revisi tambah setelah lock, ongkir per pengiriman berbayar, hutang warung
  pekerja yang belum lunas,
- tidak ada baris yang tertagih dua kali (cek sumber baris di invoice lain).

Invoice otomatis (keputusan owner 2026-10-06 / 2026-10-09):
- satu invoice per sub client, atas nama pihak yang ditagih,
- hanya pengiriman yang SUDAH DITERIMA; yang belum ikut invoice berikutnya,
- pratinjau H-1 jam 07.00, terbit 06.00 di hari potong siklus kontrak,
- jatuh tempo dari kontrak, jurnal piutang otomatis, notifikasi ke pihak
  yang ditagih + salinan ke pihak satunya, peringatan merah bila gagal.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.extensions import db
from app.models.contract import CustomerContract
from app.models.credit import BILLING_CASH, PARTY_MANDOR
from app.models.delivery import Delivery, DeliveryDetail
from app.models.finance import Invoice, InvoiceItem
from app.models.master import Mandor
from app.models.operational import DailyOrder
from app.services.atomic_transaction_service import atomic_business_action
from app.services.notification_service import create_or_update_notification
from app.utils.clock import now_wib, today_wib
from app.utils.money import money

logger = logging.getLogger(__name__)

PERIOD_INVOICE_SOURCE = "PERIOD_INVOICE"
AUTO_INVOICE_TAG = "[Invoice otomatis]"
AUTO_INVOICE_FAILED_TYPE = "AUTO_INVOICE_FAILED"
SETTLED_STATUSES = ("PAID", "CANCELLED", "CANCELED", "CLOSED")


class AutoInvoiceError(ValueError):
    """Invoice satu sub client tidak bisa diterbitkan; pesannya aman ditampilkan."""


# --- pembangun baris (dipakai invoice periode manual & otomatis) ------------

def _safe_label(obj) -> str:
    if not obj:
        return "-"
    for attr in ("name", "full_name", "mandor_name", "worker_name", "location_name", "item_name"):
        value = getattr(obj, attr, None)
        if value:
            return str(value)
    return f"ID {getattr(obj, 'id', '-')}"


def is_after_lock_increase(revision) -> bool:
    revision_type = str(getattr(revision, "revision_type", "") or "").upper()
    direction = str(getattr(revision, "revision_direction", "") or "").upper()
    return direction == "INCREASE" and revision_type.startswith("AFTER_LOCK")


def invoice_item_exists(source_type, source_id) -> bool:
    if not source_type or not source_id:
        return False
    return InvoiceItem.query.filter_by(source_type=source_type, source_id=source_id).first() is not None


def generate_invoice_number(invoice_date: date) -> str:
    prefix = f"INV-{invoice_date.strftime('%Y%m%d')}"
    counter = Invoice.query.filter(Invoice.invoice_number.like(f"{prefix}-%")).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not Invoice.query.filter_by(invoice_number=number).first():
            return number
        counter += 1


def detail_sessions_received(detail) -> bool:
    """Setiap sesi berporsi di baris order ini sudah punya tanda terima."""
    for meal, qty in (("LUNCH", detail.lunch_qty), ("DINNER", detail.dinner_qty)):
        if int(qty or 0) <= 0:
            continue
        rows = (
            DeliveryDetail.query.join(Delivery, DeliveryDetail.delivery_id == Delivery.id)
            .filter(
                DeliveryDetail.daily_order_detail_id == detail.id,
                Delivery.status != "CANCELLED",
                Delivery.notes.like(f"%delivery_type={meal}%"),
            )
            .all()
        )
        if not any(row.receipt is not None for row in rows):
            return False
    return True


def build_period_invoice_lines(mandor_id, period_start, period_end, branch_id, *, require_receipt=False):
    """Baris invoice periode satu sub client (belum pernah tertagih di invoice lain).

    require_receipt=True (invoice otomatis): baris order yang salah satu sesinya
    belum diterima dilewati seluruhnya -- catering, revisi, dan ongkirnya ikut
    invoice berikutnya.
    """
    from app.models.canteen import WorkerDebt
    from app.services.canteen_service import get_debt_paid_amount, get_debt_remaining_amount
    from app.services.mandor_invoice_helper_service import (
        billable_base_quantities,
        delivery_fee_invoice_lines,
        shortage_note,
    )

    mandor_id = int(mandor_id)
    lines = []

    orders = (
        DailyOrder.query.filter(
            DailyOrder.branch_id == branch_id,
            DailyOrder.status == "LOCKED",
            DailyOrder.order_date >= period_start,
            DailyOrder.order_date <= period_end,
        )
        .order_by(DailyOrder.order_date.asc(), DailyOrder.id.asc())
        .all()
    )

    for order in orders:
        old_order_invoice = Invoice.query.filter_by(
            branch_id=branch_id,
            source_type="DAILY_ORDER",
            source_order_id=order.id,
            mandor_id=mandor_id,
        ).first()

        for detail in order.details:
            if int(detail.mandor_id) != mandor_id:
                continue
            if require_receipt and not detail_sessions_received(detail):
                continue

            mandor_name = _safe_label(getattr(detail, "mandor", None))
            location_name = _safe_label(getattr(detail, "delivery_location", None))

            lunch_qty, dinner_qty, short_qty = billable_base_quantities(detail, is_after_lock_increase)
            total_qty = lunch_qty + dinner_qty
            price = money(getattr(detail, "price_per_portion", 0) or 0)
            subtotal = total_qty * price

            if total_qty > 0 and subtotal >= 0:
                if not old_order_invoice and not invoice_item_exists("ORDER_DETAIL", detail.id):
                    lines.append({
                        "item_type": "CATERING",
                        "description": (
                            f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                            f"Terkunci: Siang {lunch_qty}, Sore {dinner_qty}"
                            f"{shortage_note(short_qty)}"
                        ),
                        "qty": total_qty,
                        "unit_price": price,
                        "subtotal": subtotal,
                        "source_type": "ORDER_DETAIL",
                        "source_id": detail.id,
                    })

            for revision in getattr(detail, "revisions", []) or []:
                if not is_after_lock_increase(revision):
                    continue
                lunch_change = int(getattr(revision, "lunch_qty_change", 0) or 0)
                dinner_change = int(getattr(revision, "dinner_qty_change", 0) or 0)
                qty_change = lunch_change + dinner_change
                if qty_change <= 0:
                    continue
                revision_price = getattr(revision, "price_per_portion", None)
                revision_price = money(price if revision_price is None else revision_price)
                if not old_order_invoice and not invoice_item_exists("ORDER_REVISION", revision.id):
                    lines.append({
                        "item_type": "REVISION_INCREASE",
                        "description": (
                            f"{order.order_number} | PIC {mandor_name} | {location_name} | "
                            f"Revisi tambah: Lunch +{lunch_change}, Dinner +{dinner_change}"
                        ),
                        "qty": qty_change,
                        "unit_price": revision_price,
                        "subtotal": qty_change * revision_price,
                        "source_type": "ORDER_REVISION",
                        "source_id": revision.id,
                    })

            if not old_order_invoice:
                for fee_line in delivery_fee_invoice_lines(order, detail):
                    if not invoice_item_exists(fee_line["source_type"], detail.id):
                        lines.append(fee_line)

    debts = WorkerDebt.query.filter_by(branch_id=branch_id).order_by(WorkerDebt.id.asc()).all()
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
        if not sale_date or sale_date < period_start or sale_date > period_end:
            continue
        remaining = money(get_debt_remaining_amount(debt) or 0)
        if remaining <= 0 or invoice_item_exists("WORKER_DEBT", debt.id):
            continue
        paid = money(get_debt_paid_amount(debt) or 0)
        lines.append({
            "item_type": "WARUNG_DEBT",
            "description": (
                f"Hutang warung pekerja {_safe_label(worker)} | "
                f"Hutang {float(debt.debt_amount or 0):,.0f} | Dibayar {paid:,.0f} | Sisa {remaining:,.0f}"
            ),
            "qty": 1,
            "unit_price": remaining,
            "subtotal": remaining,
            "source_type": "WORKER_DEBT",
            "source_id": debt.id,
        })

    return lines


# --- siklus kontrak ----------------------------------------------------------

def is_cutoff_day(contract: CustomerContract, on_date: date) -> bool:
    """Hari potong siklus tagihan kontrak ini jatuh tepat pada on_date."""
    from app.services.contract_rules_service import next_cycle_cutoff

    return next_cycle_cutoff(contract, on_date - timedelta(days=1)) == on_date


def _contracts_with_cutoff(branch_id: int, cutoff_date: date) -> list[CustomerContract]:
    """Kontrak aktif cabang ini yang hari potongnya cutoff_date.

    Kontrak yang berakhir sebelum hari potong tetap ditagih untuk sisa
    pengirimannya pada hari potong pertama setelah kontrak dimulai.
    """
    contracts = CustomerContract.query.filter(
        CustomerContract.branch_id == branch_id,
        CustomerContract.status == "ACTIVE",
        CustomerContract.start_date < cutoff_date,
    ).all()
    return [contract for contract in contracts if is_cutoff_day(contract, cutoff_date)]


def _billable_mandors(contract: CustomerContract) -> list[Mandor]:
    """Sub client client kontrak ini yang ditagih periodik (bukan bayar di muka)."""
    from app.services.credit_control_service import resolve_billing_party

    rows = []
    for mandor in Mandor.query.filter_by(branch_id=contract.branch_id, client_id=contract.client_id).order_by(Mandor.name.asc()):
        _, _, account = resolve_billing_party(contract.branch_id, contract.client_id, mandor.id)
        if getattr(account, "billing_mode", None) == BILLING_CASH:
            continue  # prabayar: invoice dibuat otomatis setelah pengiriman diterima
        rows.append(mandor)
    return rows


def _invoice_period(contract: CustomerContract, mandor: Mandor, cutoff_date: date) -> tuple[date, date]:
    """(awal, akhir) periode yang tercetak di invoice; baris ditarik sejak awal kontrak."""
    period_end = cutoff_date - timedelta(days=1)
    last = (
        Invoice.query.filter(
            Invoice.branch_id == contract.branch_id,
            Invoice.mandor_id == mandor.id,
            Invoice.source_type == PERIOD_INVOICE_SOURCE,
            Invoice.period_end.isnot(None),
            Invoice.period_end < period_end,
        )
        .order_by(Invoice.period_end.desc())
        .first()
    )
    period_start = (last.period_end + timedelta(days=1)) if last else contract.start_date
    return max(period_start, contract.start_date), period_end


def _client_of(contract: CustomerContract):
    from app.models.master import Client

    return db.session.get(Client, contract.client_id)


def plan_invoices(branch_id: int, cutoff_date: date) -> list[dict[str, Any]]:
    """Rencana invoice untuk hari potong ini (tanpa menulis apa pun) -- dipakai pratinjau & penerbitan."""
    from app.services.credit_control_service import invoice_billing_terms
    from app.services.invoice_identity_service import invoice_contact_snapshot
    from app.services.tax_service import pbjt_for_lines

    plans = []
    for contract in _contracts_with_cutoff(branch_id, cutoff_date):
        client = _client_of(contract)
        for mandor in _billable_mandors(contract):
            period_start, period_end = _invoice_period(contract, mandor, cutoff_date)
            existing = Invoice.query.filter_by(
                branch_id=branch_id,
                source_type=PERIOD_INVOICE_SOURCE,
                mandor_id=mandor.id,
                period_end=period_end,
            ).first()
            lines = build_period_invoice_lines(
                mandor.id, contract.start_date, period_end, branch_id, require_receipt=True
            )
            total = sum((money(line["subtotal"] or 0) for line in lines), Decimal("0"))
            pbjt = pbjt_for_lines(lines, branch_id, cutoff_date) if total > 0 else Decimal("0")
            billing = invoice_billing_terms(cutoff_date, branch_id, client, mandor)
            _, contact_error = invoice_contact_snapshot(
                client, mandor, getattr(contract, "client_pic_id", None), billing["bill_to_type"]
            )
            plans.append({
                "contract": contract,
                "client": client,
                "mandor": mandor,
                "period_start": period_start,
                "period_end": period_end,
                "lines": lines,
                "total": total,
                "pbjt": pbjt,
                "grand_total": total + pbjt,
                "bill_to_type": billing["bill_to_type"],
                "bill_to_name": billing["bill_to_name"],
                "due_date": billing["due_date"],
                "already_issued": existing,
                "error": contact_error,
            })
    return plans


# --- penerbitan ----------------------------------------------------------------

def _portal_recipients(mandor: Mandor) -> tuple[list, list]:
    """(akun portal sub client, akun portal client) untuk notifikasi invoice."""
    from app.models.master import User
    from app.models.system import PortalUserMapping

    mappings = PortalUserMapping.query.filter(
        PortalUserMapping.is_active.is_(True),
        db.or_(
            PortalUserMapping.mandor_id == mandor.id,
            db.and_(PortalUserMapping.client_id == mandor.client_id, PortalUserMapping.mandor_id.is_(None)),
        ),
    ).all()
    sub_ids = {row.user_id for row in mappings if row.mandor_id == mandor.id}
    client_ids = {row.user_id for row in mappings if row.mandor_id is None} - sub_ids

    def users(ids):
        if not ids:
            return []
        return User.query.filter(User.id.in_(ids), User.is_active.is_(True)).all()

    return users(sub_ids), users(client_ids)


def _rupiah(value) -> str:
    return f"Rp{float(value or 0):,.0f}".replace(",", ".")


def _notify_invoice_issued(invoice: Invoice, mandor: Mandor) -> None:
    sub_users, client_users = _portal_recipients(mandor)
    billed_to_sub = invoice.bill_to_type == "MANDOR"
    billed, copies = (sub_users, client_users) if billed_to_sub else (client_users, sub_users)
    due = invoice.due_date.strftime("%d-%m-%Y") if invoice.due_date else "-"
    period = (
        f"{invoice.period_start.strftime('%d-%m-%Y')} s/d {invoice.period_end.strftime('%d-%m-%Y')}"
        if invoice.period_start and invoice.period_end else "-"
    )
    for user in billed:
        create_or_update_notification(
            branch_id=invoice.branch_id,
            notification_type="INVOICE_ISSUED",
            title=f"Tagihan baru {invoice.invoice_number}",
            message=(
                f"Tagihan {mandor.name} periode {period}: {_rupiah(invoice.total_amount)}. "
                f"Jatuh tempo {due}."
            ),
            target_user_id=user.id,
            priority="WARNING",
            reference_type="INVOICE",
            reference_id=invoice.id,
            generated_key=f"invoice-issued-{invoice.id}-{user.id}",
            commit=False,
        )
    for user in copies:
        create_or_update_notification(
            branch_id=invoice.branch_id,
            notification_type="INVOICE_COPY",
            title=f"Salinan tagihan {invoice.invoice_number}",
            message=(
                f"Tagihan {mandor.name} periode {period}: {_rupiah(invoice.total_amount)}, "
                f"ditagihkan ke {invoice.client_name_snapshot}. Jatuh tempo {due}."
            ),
            target_user_id=user.id,
            priority="INFO",
            reference_type="INVOICE",
            reference_id=invoice.id,
            generated_key=f"invoice-copy-{invoice.id}-{user.id}",
            commit=False,
        )


def issue_planned_invoice(plan: dict[str, Any], *, invoice_date: date) -> Invoice:
    """Terbitkan satu invoice dari rencana. Tidak commit; gagal -> AutoInvoiceError."""
    from app.services.accounting_service import create_invoice_journal_for_invoice
    from app.services.billing_input_source_service import INPUT_SOURCE_REALTIME
    from app.services.invoice_identity_service import build_company_bank_snapshot, invoice_contact_snapshot

    contract, client, mandor = plan["contract"], plan["client"], plan["mandor"]
    if plan["error"]:
        raise AutoInvoiceError(plan["error"])
    if not plan["lines"] or plan["total"] <= 0:
        raise AutoInvoiceError("Tidak ada pengiriman diterima yang belum ditagih.")
    if any(money(line["unit_price"] or 0) <= 0 for line in plan["lines"] if line["item_type"] == "CATERING"):
        raise AutoInvoiceError("Ada baris catering berharga Rp0; periksa harga per porsi pesanan.")

    contact, contact_error = invoice_contact_snapshot(
        client, mandor, getattr(contract, "client_pic_id", None), plan["bill_to_type"]
    )
    if contact_error:
        raise AutoInvoiceError(contact_error)

    invoice = Invoice(
        branch_id=contract.branch_id,
        invoice_number=generate_invoice_number(invoice_date),
        invoice_date=invoice_date,
        due_date=plan["due_date"],
        period_start=plan["period_start"],
        period_end=plan["period_end"],
        bill_to_type=plan["bill_to_type"],
        client_id=client.id,
        mandor_id=mandor.id,
        **contact,
        **build_company_bank_snapshot(contract.branch_id),
        client_name_snapshot=plan["bill_to_name"],
        client_code_snapshot=getattr(client, "client_code", None),
        expected_payment_percent=100,
        total_amount=plan["total"],
        paid_amount=0,
        remaining_amount=plan["total"],
        status="DRAFT",
        notes=(
            f"{AUTO_INVOICE_TAG} Siklus kontrak {contract.contract_number}, periode "
            f"{plan['period_start'].strftime('%d-%m-%Y')} s/d {plan['period_end'].strftime('%d-%m-%Y')}. "
            f"PIC lapangan: {mandor.name}. Hanya pengiriman yang sudah diterima; "
            f"pengiriman yang belum diterima ikut invoice berikutnya."
        ),
        source_type=PERIOD_INVOICE_SOURCE,
        source_order_id=None,
        input_source=INPUT_SOURCE_REALTIME,
        created_by=contract.created_by,
    )
    db.session.add(invoice)
    db.session.flush()
    for line in plan["lines"]:
        db.session.add(InvoiceItem(
            invoice_id=invoice.id,
            item_type=line["item_type"],
            description=line["description"],
            qty=line["qty"],
            unit_price=line["unit_price"],
            subtotal=line["subtotal"],
            source_type=line["source_type"],
            source_id=line["source_id"],
            input_source=INPUT_SOURCE_REALTIME,
        ))
    db.session.flush()
    # PBJT ditambahkan di atas harga bila sudah aktif (Fase 8); bagian dari jurnal yang sama.
    from app.services.tax_service import apply_pbjt_to_invoice

    apply_pbjt_to_invoice(invoice)

    try:
        ok, message, _journal = create_invoice_journal_for_invoice(
            invoice=invoice, created_by=contract.created_by, commit=False
        )
    except Exception as error:  # akun COA kurang, jurnal tidak seimbang, dll.
        logger.exception("Jurnal invoice otomatis gagal untuk %s", mandor.name)
        raise AutoInvoiceError(f"Jurnal piutang gagal dibuat: {error}") from error
    if not ok:
        # Piutang tanpa jurnal = buku pembantu tidak cocok dengan buku besar.
        raise AutoInvoiceError(f"Jurnal piutang gagal dibuat: {message}")

    _notify_invoice_issued(invoice, mandor)
    _resolve_failures(contract.branch_id, mandor.id)
    return invoice


def _resolve_failures(branch_id: int, mandor_id: int) -> None:
    """Invoice sub client ini sudah terbit: peringatan gagal sebelumnya selesai."""
    from app.models.system import Notification

    Notification.query.filter(
        Notification.branch_id == branch_id,
        Notification.notification_type == AUTO_INVOICE_FAILED_TYPE,
        Notification.generated_key.like(f"auto-invoice-failed-{mandor_id}-%"),
        Notification.status.in_(("UNREAD", "READ")),
    ).update({Notification.status: "RESOLVED"}, synchronize_session=False)


def _notify_failure(branch_id: int, plan: dict[str, Any], reason: str, cutoff_date: date) -> None:
    mandor = plan["mandor"]
    for role in ("ADMIN", "OWNER"):
        create_or_update_notification(
            branch_id=branch_id,
            notification_type=AUTO_INVOICE_FAILED_TYPE,
            title=f"Invoice gagal terbit: {mandor.name}",
            message=(
                f"Invoice otomatis {mandor.name} (hari potong {cutoff_date.strftime('%d-%m-%Y')}) "
                f"tidak terbit: {reason}"
            ),
            target_role=role,
            priority="CRITICAL",
            action_url="/finance/auto-invoices",
            generated_key=f"auto-invoice-failed-{mandor.id}-{cutoff_date.isoformat()}-{role}",
            commit=False,
        )


def _period_date(period_key, now) -> date:
    if period_key:
        try:
            return date.fromisoformat(str(period_key)[:10])
        except ValueError:
            pass
    return (now or now_wib()).date()


def run_auto_period_invoices(branch_id=None, period_key=None, now=None, *, commit=True) -> dict[str, Any]:
    """Tugas 06.00: terbitkan invoice semua sub client yang hari potongnya hari ini."""
    cutoff_date = _period_date(period_key, now)
    issued, failed, skipped = [], [], []

    def work():
        for plan in plan_invoices(branch_id, cutoff_date):
            mandor = plan["mandor"]
            if plan["already_issued"] is not None:
                skipped.append({"mandor": mandor.name, "reason": "sudah terbit"})
                continue
            if not plan["lines"] or plan["total"] <= 0:
                skipped.append({"mandor": mandor.name, "reason": "tidak ada pengiriman diterima yang belum ditagih"})
                continue
            savepoint = db.session.begin_nested()
            try:
                invoice = issue_planned_invoice(plan, invoice_date=cutoff_date)
                savepoint.commit()
                issued.append({"mandor": mandor.name, "invoice": invoice.invoice_number, "total": str(invoice.total_amount)})
            except AutoInvoiceError as error:
                savepoint.rollback()
                failed.append({"mandor": mandor.name, "reason": str(error)})
                _notify_failure(branch_id, plan, str(error), cutoff_date)

        if issued or failed:
            total = sum(Decimal(row["total"]) for row in issued)
            for role in ("ADMIN", "OWNER"):
                create_or_update_notification(
                    branch_id=branch_id,
                    notification_type="AUTO_INVOICE_RECAP",
                    title=f"Invoice otomatis {cutoff_date.strftime('%d-%m-%Y')}",
                    message=(
                        f"{len(issued)} invoice terbit, total {_rupiah(total)}."
                        + (f" {len(failed)} gagal terbit — periksa peringatan merah." if failed else "")
                    ),
                    target_role=role,
                    priority="WARNING" if failed else "INFO",
                    action_url="/finance/auto-invoices",
                    generated_key=f"auto-invoice-recap-{cutoff_date.isoformat()}-{role}",
                    commit=False,
                )

    if commit:
        with atomic_business_action(
            module="FINANCE",
            action="AUTO_PERIOD_INVOICES",
            description=f"Invoice otomatis hari potong {cutoff_date.isoformat()}",
            branch_id=branch_id,
            metadata={"cutoff_date": cutoff_date.isoformat()},
        ):
            work()
    else:
        work()
        db.session.flush()

    return {"cutoff_date": cutoff_date.isoformat(), "issued": issued, "failed": failed, "skipped": skipped}


def run_auto_invoice_preview(branch_id=None, period_key=None, now=None, *, commit=True) -> dict[str, Any]:
    """Tugas 07.00: pratinjau invoice yang terbit besok, ke admin & owner."""
    tomorrow = _period_date(period_key, now) + timedelta(days=1)
    plans = [plan for plan in plan_invoices(branch_id, tomorrow) if plan["already_issued"] is None]
    billable = [plan for plan in plans if plan["lines"] and plan["total"] > 0]
    ready = [plan for plan in billable if not plan["error"]]
    problems = [plan for plan in billable if plan["error"]]
    total = sum((plan["grand_total"] for plan in ready), Decimal("0"))

    def work():
        if not plans:
            return
        for role in ("ADMIN", "OWNER"):
            create_or_update_notification(
                branch_id=branch_id,
                notification_type="AUTO_INVOICE_PREVIEW",
                title=f"Besok terbit {len(ready)} invoice",
                message=(
                    f"Invoice otomatis {tomorrow.strftime('%d-%m-%Y')} jam 06.00: {len(ready)} invoice, "
                    f"total {_rupiah(total)}."
                    + (f" {len(problems)} sub client bermasalah, perbaiki hari ini." if problems else "")
                ),
                target_role=role,
                priority="WARNING" if problems else "INFO",
                action_url=f"/finance/auto-invoices?date={tomorrow.isoformat()}",
                generated_key=f"auto-invoice-preview-{tomorrow.isoformat()}-{role}",
                commit=False,
            )

    if commit:
        with atomic_business_action(
            module="FINANCE",
            action="AUTO_INVOICE_PREVIEW",
            description=f"Pratinjau invoice otomatis {tomorrow.isoformat()}",
            branch_id=branch_id,
            audit_success=False,
        ):
            work()
    else:
        work()
        db.session.flush()

    return {"cutoff_date": tomorrow.isoformat(), "ready": len(ready), "problems": len(problems), "total": str(total)}


REMINDER_OFFSETS = ((3, "H-3"), (0, "H"), (-7, "H+7"))


def run_invoice_payment_reminders(branch_id=None, period_key=None, now=None, *, commit=True) -> dict[str, Any]:
    """Tugas 08.00: pengingat bayar H-3, H, H+7 untuk invoice yang belum lunas."""
    today = _period_date(period_key, now)
    sent = []

    def work():
        for offset, label in REMINDER_OFFSETS:
            due = today + timedelta(days=offset)
            invoices = Invoice.query.filter(
                Invoice.branch_id == branch_id,
                Invoice.due_date == due,
                Invoice.remaining_amount > 0,
                ~Invoice.status.in_(SETTLED_STATUSES),
            ).all()
            for invoice in invoices:
                mandor = db.session.get(Mandor, invoice.mandor_id) if invoice.mandor_id else None
                if mandor is None:
                    continue
                sub_users, client_users = _portal_recipients(mandor)
                billed = sub_users if invoice.bill_to_type == "MANDOR" else client_users
                text = {
                    "H-3": f"Tagihan {invoice.invoice_number} jatuh tempo 3 hari lagi ({due.strftime('%d-%m-%Y')}).",
                    "H": f"Tagihan {invoice.invoice_number} jatuh tempo hari ini.",
                    "H+7": f"Tagihan {invoice.invoice_number} sudah lewat 7 hari dari jatuh tempo.",
                }[label]
                message = f"{text} Sisa {_rupiah(invoice.remaining_amount)}."
                for user in billed:
                    create_or_update_notification(
                        branch_id=branch_id,
                        notification_type="INVOICE_PAYMENT_REMINDER",
                        title=f"Pengingat bayar {label}",
                        message=message,
                        target_user_id=user.id,
                        priority="WARNING" if label != "H-3" else "INFO",
                        reference_type="INVOICE",
                        reference_id=invoice.id,
                        generated_key=f"invoice-reminder-{invoice.id}-{label}-{user.id}",
                        commit=False,
                    )
                if label == "H+7":
                    create_or_update_notification(
                        branch_id=branch_id,
                        notification_type="INVOICE_PAYMENT_REMINDER",
                        title=f"Tunggakan {invoice.invoice_number}",
                        message=f"{message} Ditagihkan ke {invoice.client_name_snapshot}.",
                        target_role="ADMIN",
                        priority="WARNING",
                        reference_type="INVOICE",
                        reference_id=invoice.id,
                        generated_key=f"invoice-reminder-{invoice.id}-{label}-admin",
                        commit=False,
                    )
                sent.append({"invoice": invoice.invoice_number, "label": label})

    if commit:
        with atomic_business_action(
            module="FINANCE",
            action="INVOICE_PAYMENT_REMINDERS",
            description=f"Pengingat bayar {today.isoformat()}",
            branch_id=branch_id,
            audit_success=False,
        ):
            work()
    else:
        work()
        db.session.flush()

    return {"date": today.isoformat(), "sent": sent}


def unresolved_failure_count(branch_id: int) -> int:
    """Jumlah peringatan 'invoice gagal terbit' yang belum ditangani (untuk dashboard)."""
    from app.models.system import Notification

    return Notification.query.filter(
        Notification.branch_id == branch_id,
        Notification.notification_type == AUTO_INVOICE_FAILED_TYPE,
        Notification.target_role == "ADMIN",
        Notification.status.in_(("UNREAD", "READ")),
    ).count()
