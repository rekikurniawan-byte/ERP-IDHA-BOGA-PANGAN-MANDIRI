"""Smoke-render GET routes that require dynamic URL parameters.

The regular route smoke audit covers static GET routes. This companion audit
uses sample IDs from the configured local database so split-route/template
regressions in detail pages are caught before a user clicks through the UI.
It only sends GET requests and treats 4xx as non-fatal because missing sample
data can legitimately produce 404/403. HTTP 5xx and exceptions are failures.
"""

from __future__ import annotations

from pathlib import Path
import sys
from typing import Any, Callable

from flask import url_for
from werkzeug.routing import BuildError

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app  # noqa: E402
from app.models.accounting import AssetFinancingContract, FixedAsset, FixedAssetPurchase, Journal, PeriodClosing  # noqa: E402
from app.models.canteen import CashDaily, CanteenExternalReceivable, WorkerDebt  # noqa: E402
from app.models.delivery import Delivery, DeliveryDetail  # noqa: E402
from app.models.field_transaction import FieldTransaction, FieldTransactionAttachment  # noqa: E402
from app.models.finance import (  # noqa: E402
    AdvanceTransaction,
    BankAccount,
    CashBankTransaction,
    OperationalExpense,
    Payment,
    SupplierBill,
    TransportVehicleExpense,
)
from app.models.hr import Payroll  # noqa: E402
from app.models.logistics import ItemRequest, Procurement  # noqa: E402
from app.models.master import (  # noqa: E402
    Client,
    DeliveryLocation,
    Driver,
    Employee,
    Item,
    Mandor,
    Menu,
    OverheadProfile,
    PackagingProfile,
    Supplier,
    User,
    Worker,
)
from app.models.operational import DailyOrder, DailyOrderDetail, OrderHppSnapshot, OrderHppStockConsumption  # noqa: E402
from app.models.production import Production  # noqa: E402
from app.models.system import AuditLog, DigitalAttachment  # noqa: E402
from app.services.digital_attachment_service import get_attachment_file_path  # noqa: E402


REPORT_PATH = Path("RINCIAN_AUDIT_DYNAMIC_ROUTE_RENDER_SMOKE_ERP_IDHA_BOGA.md")

SKIP_ENDPOINTS = {
    "static",
    "settings.download_backup_confirm",
}


def _first(model, branch_id: int | None = None):
    query = model.query
    if branch_id is not None and hasattr(model, "branch_id"):
        query = query.filter(model.branch_id == branch_id)
    return query.order_by(model.id.asc()).first()


def _first_id(model, branch_id: int | None = None) -> int | None:
    row = _first(model, branch_id)
    return row.id if row else None


def _get_owner_user():
    return (
        User.query.filter_by(role="OWNER", is_active=True).order_by(User.id.asc()).first()
        or User.query.filter_by(is_active=True).order_by(User.id.asc()).first()
    )


def _usable_digital_attachment_id(
    branch_id: int | None = None,
    *,
    module: str | None = None,
    reference_type: str | None = None,
) -> int | None:
    query = DigitalAttachment.query.filter(DigitalAttachment.is_deleted.is_(False))
    if branch_id is not None:
        query = query.filter(DigitalAttachment.branch_id == branch_id)
    if module:
        query = query.filter(DigitalAttachment.module == module)
    if reference_type:
        query = query.filter(DigitalAttachment.reference_type == reference_type)
    for attachment in query.order_by(DigitalAttachment.id.asc()).all():
        try:
            get_attachment_file_path(attachment)
            return attachment.id
        except FileNotFoundError:
            continue
    return None


def _usable_field_attachment_id(branch_id: int | None = None) -> int | None:
    query = FieldTransactionAttachment.query
    if branch_id is not None:
        query = query.join(FieldTransaction, FieldTransaction.id == FieldTransactionAttachment.field_transaction_id)
        query = query.filter(FieldTransaction.branch_id == branch_id)
    for attachment_link in query.order_by(FieldTransactionAttachment.id.asc()).all():
        digital_attachment = getattr(attachment_link, "digital_attachment", None)
        if not digital_attachment or getattr(digital_attachment, "is_deleted", False):
            continue
        try:
            get_attachment_file_path(digital_attachment)
            return attachment_link.id
        except FileNotFoundError:
            continue
    return None


def _snapshot_values(branch_id: int | None = None) -> dict[str, Any] | None:
    snapshot = _first(OrderHppSnapshot, branch_id)
    if not snapshot:
        return None
    return {"order_id": snapshot.daily_order_id, "snapshot_id": snapshot.id}


def _consumption_values(branch_id: int | None = None) -> dict[str, Any] | None:
    consumption = _first(OrderHppStockConsumption, branch_id)
    if not consumption:
        return None
    return {
        "order_id": consumption.daily_order_id,
        "snapshot_id": consumption.snapshot_id,
        "consumption_id": consumption.id,
    }


def _endpoint_values(endpoint: str, branch_id: int | None = None) -> dict[str, Any] | None:
    endpoint_map: dict[str, Callable[[], dict[str, Any] | None]] = {
        "accounting.journal_detail": lambda: {"journal_id": _first_id(Journal, branch_id)},
        "accounting.print_journal_detail": lambda: {"journal_id": _first_id(Journal, branch_id)},
        "accounting.period_closing_detail": lambda: {"closing_id": _first_id(PeriodClosing, branch_id)},
        "canteen.debt_payment": lambda: {"debt_id": _first_id(WorkerDebt, branch_id)},
        "canteen.external_receivable_payment": lambda: {"receivable_id": _first_id(CanteenExternalReceivable, branch_id)},
        "costing.edit_menu": lambda: {"menu_id": _first_id(Menu)},
        "costing.menu_recipe": lambda: {"menu_id": _first_id(Menu)},
        "costing.edit_overhead_profile": lambda: {"profile_id": _first_id(OverheadProfile, branch_id)},
        "costing.edit_packaging_profile": lambda: {"profile_id": _first_id(PackagingProfile, branch_id)},
        "delivery.detail": lambda: {"delivery_id": _first_id(Delivery, branch_id)},
        "delivery.receive": lambda: {"detail_id": _first_id(DeliveryDetail)},
        "field_transactions.detail": lambda: {"transaction_id": _first_id(FieldTransaction, branch_id)},
        "field_transactions.edit": lambda: {"transaction_id": _first_id(FieldTransaction, branch_id)},
        "finance.advance_detail": lambda: {"advance_id": _first_id(AdvanceTransaction, branch_id)},
        "finance.cash_bank_transaction_detail": lambda: {"transaction_id": _first_id(CashBankTransaction, branch_id)},
        "finance.daily_cash_detail": lambda: {"cash_id": _first_id(CashDaily, branch_id)},
        "finance.fixed_asset_depreciation_configure": lambda: {"asset_id": _first_id(FixedAsset, branch_id)},
        "finance.fixed_asset_installment_detail": lambda: {"contract_id": _first_id(AssetFinancingContract, branch_id)},
        "finance.fixed_asset_purchase_detail": lambda: {"purchase_id": _first_id(FixedAssetPurchase, branch_id)},
        "finance.invoice_detail": lambda: {"invoice_id": _first_id_by_model_name("Invoice", branch_id)},
        "finance.invoice_print": lambda: {"invoice_id": _first_id_by_model_name("Invoice", branch_id)},
        "finance.invoice_profit_detail": lambda: {"invoice_id": _first_id_by_model_name("Invoice", branch_id)},
        "finance.invoice_whatsapp_send": lambda: {"invoice_id": _first_id_by_model_name("Invoice", branch_id)},
        "finance.manual_billing_batch_detail": lambda: {"batch_id": _first_id_by_model_name("ManualBillingBatch", branch_id)},
        "finance.edit_manual_billing_backfill_batch": lambda: {"batch_id": _first_id_by_model_name("ManualBillingBatch", branch_id)},
        "finance.print_manual_billing_batch": lambda: {"batch_id": _first_id_by_model_name("ManualBillingBatch", branch_id)},
        "finance.operational_expense_detail": lambda: {"expense_id": _first_id(OperationalExpense, branch_id)},
        "finance.payment_receipt": lambda: {"payment_id": _first_id(Payment, branch_id)},
        "finance.supplier_bill_detail": lambda: {"bill_id": _first_id(SupplierBill, branch_id)},
        "finance.transport_expense_detail": lambda: {"expense_id": _first_id(TransportVehicleExpense, branch_id)},
        "hr.edit_employee": lambda: {"employee_id": _first_id(Employee, branch_id)},
        "hr.payroll_detail": lambda: {"payroll_id": _first_id(Payroll, branch_id)},
        "logistics.item_request_detail": lambda: {"request_id": _first_id(ItemRequest, branch_id)},
        "logistics.item_card": lambda: {"item_id": _first_id(Item)},
        "logistics.purchase_detail": lambda: {"procurement_id": _first_id(Procurement, branch_id)},
        "master.edit_bank_account": lambda: {"account_id": _first_id(BankAccount, branch_id)},
        "master.edit_client": lambda: {"client_id": _first_id(Client, branch_id)},
        "master.edit_driver": lambda: {"driver_id": _first_id(Driver, branch_id)},
        "master.edit_fixed_asset": lambda: {"asset_id": _first_id(FixedAsset, branch_id)},
        "master.edit_item_cost_profile": lambda: {"item_id": _first_id(Item)},
        "master.edit_item": lambda: {"item_id": _first_id(Item)},
        "master.edit_location": lambda: {"location_id": _first_id(DeliveryLocation, branch_id)},
        "master.edit_mandor": lambda: {"mandor_id": _first_id(Mandor, branch_id)},
        "master.edit_supplier": lambda: {"supplier_id": _first_id(Supplier, branch_id)},
        "master.edit_worker": lambda: {"worker_id": _first_id(Worker, branch_id)},
        "operational.create_revision": lambda: {"detail_id": _first_id(DailyOrderDetail)},
        "operational.order_detail": lambda: {"order_id": _first_id(DailyOrder, branch_id)},
        "operational.add_order_detail": lambda: {"order_id": _first_id(DailyOrder, branch_id)},
        "operational.add_increase_after_lock_route": lambda: {"order_id": _first_id(DailyOrder, branch_id)},
        "operational.update_order_hpp_defaults_route": lambda: {"order_id": _first_id(DailyOrder, branch_id)},
        "operational.order_hpp_snapshot_detail": lambda: _snapshot_values(branch_id),
        "operational.order_hpp_stock_consumption_detail": lambda: _consumption_values(branch_id),
        "operational.order_hpp_snapshot_stock_dry_run": lambda: _snapshot_values(branch_id),
        "operational.create_order_hpp_snapshot_route": lambda: {"order_id": _first_id(DailyOrder, branch_id)},
        "production.detail": lambda: {"production_id": _first_id(Production, branch_id)},
        "settings.audit_log_detail": lambda: {"log_id": _first_id(AuditLog, branch_id)},
        "settings.digital_attachment_detail": lambda: {"attachment_id": _usable_digital_attachment_id(branch_id)},
        "settings.edit_user_page": lambda: {"user_id": _first_id(User)},
        "settings.reset_user_password_page": lambda: {"user_id": _first_id(User)},
        "sop.role_sop": lambda: {"slug": "finance"},
    }

    field_attachment_endpoints = {
        "field_transactions.download_attachment",
        "field_transactions.view_attachment",
    }
    if endpoint in field_attachment_endpoints:
        return {"attachment_id": _usable_field_attachment_id(branch_id)}

    attachment_endpoint_map = {
        "delivery.download_attachment": ("DELIVERY", "DELIVERY_RECEIPT"),
        "delivery.view_attachment": ("DELIVERY", "DELIVERY_RECEIPT"),
        "finance.download_customer_payment_attachment": ("CUSTOMER_PAYMENT", "PAYMENT"),
        "finance.view_customer_payment_attachment": ("CUSTOMER_PAYMENT", "PAYMENT"),
        "finance.download_supplier_payment_attachment": ("SUPPLIER_PAYMENT", "SUPPLIER_PAYMENT"),
        "finance.view_supplier_payment_attachment": ("SUPPLIER_PAYMENT", "SUPPLIER_PAYMENT"),
        "logistics.download_procurement_attachment": ("PROCUREMENT", "PROCUREMENT"),
        "logistics.view_procurement_attachment": ("PROCUREMENT", "PROCUREMENT"),
        "settings.download_digital_attachment": (None, None),
        "settings.view_digital_attachment": (None, None),
    }
    if endpoint in attachment_endpoint_map:
        module, reference_type = attachment_endpoint_map[endpoint]
        return {"attachment_id": _usable_digital_attachment_id(branch_id, module=module, reference_type=reference_type)}

    builder = endpoint_map.get(endpoint)
    return builder() if builder else None


def _first_id_by_model_name(model_name: str, branch_id: int | None = None) -> int | None:
    from app.models.finance import Invoice, ManualBillingBatch

    models = {
        "Invoice": Invoice,
        "ManualBillingBatch": ManualBillingBatch,
    }
    return _first_id(models[model_name], branch_id)


def _eligible_rules(app):
    for rule in sorted(app.url_map.iter_rules(), key=lambda item: item.rule):
        if rule.endpoint in SKIP_ENDPOINTS:
            continue
        if "GET" not in rule.methods:
            continue
        if not rule.arguments:
            continue
        yield rule


def _has_none(values: dict[str, Any] | None) -> bool:
    return not values or any(value is None for value in values.values())


def run_smoke():
    app = create_app()
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    rows = []

    with app.app_context():
        user = _get_owner_user()
        if not user:
            raise RuntimeError("Tidak ada user aktif untuk dynamic route render smoke.")

        with app.test_request_context():
            with app.test_client() as client:
                with client.session_transaction() as session:
                    session["_user_id"] = str(user.id)
                    session["_fresh"] = True

                for rule in _eligible_rules(app):
                    values = _endpoint_values(rule.endpoint, getattr(user, "branch_id", None))
                    if _has_none(values):
                        rows.append({
                            "endpoint": rule.endpoint,
                            "rule": rule.rule,
                            "status": "SKIP",
                            "detail": "Tidak ada sample data lokal untuk parameter route.",
                        })
                        continue

                    status = "PASS"
                    detail = ""
                    try:
                        url = url_for(rule.endpoint, **values)
                        response = client.get(url, follow_redirects=False)
                        detail = f"HTTP {response.status_code}"
                        if response.status_code >= 500:
                            status = "FAIL"
                    except BuildError as exc:
                        status = "FAIL"
                        detail = f"BuildError: {exc}"
                    except Exception as exc:  # noqa: BLE001 - audit must capture unexpected render failures.
                        status = "FAIL"
                        detail = f"{exc.__class__.__name__}: {exc}"

                    rows.append({
                        "endpoint": rule.endpoint,
                        "rule": rule.rule,
                        "status": status,
                        "detail": detail,
                    })

    return rows


def render_report(rows):
    failed = [row for row in rows if row["status"] == "FAIL"]
    skipped = [row for row in rows if row["status"] == "SKIP"]
    lines = [
        "# Audit Dynamic Route Render Smoke ERP Idha Boga",
        "",
        "Audit ini melakukan GET render pada route berparameter memakai sample ID dari database lokal.",
        "",
        "## Ringkasan",
        "",
        "| Metrik | Nilai |",
        "| --- | ---: |",
        f"| Total route dinamis | {len(rows)} |",
        f"| Gagal | {len(failed)} |",
        f"| Skip tanpa sample data | {len(skipped)} |",
        "",
        "## Detail",
        "",
        "| Status | Endpoint | Rule | Detail |",
        "| --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(f"| {row['status']} | `{row['endpoint']}` | `{row['rule']}` | {row['detail']} |")
    lines.append("")
    return "\n".join(lines)


def main():
    rows = run_smoke()
    report = render_report(rows)
    REPORT_PATH.write_text(report, encoding="utf-8")
    failed = [row for row in rows if row["status"] == "FAIL"]
    skipped = [row for row in rows if row["status"] == "SKIP"]
    print(f"Dynamic route render smoke written: {REPORT_PATH.resolve()}")
    print(f"Routes checked: {len(rows)}")
    print(f"Failed: {len(failed)}")
    print(f"Skipped: {len(skipped)}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
