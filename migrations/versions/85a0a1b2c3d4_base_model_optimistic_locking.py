"""Add optimistic locking version_id to BaseModel tables.

Revision ID: 85a0a1b2c3d4
Revises: 84a0a1b2c3d4
Create Date: 2026-07-26
"""
from alembic import op
import sqlalchemy as sa


revision = "85a0a1b2c3d4"
down_revision = "84a0a1b2c3d4"
branch_labels = None
depends_on = None


VERSIONED_TABLES = (
    "accounts",
    "advance_settlements",
    "advance_transactions",
    "asset_financing_contracts",
    "asset_installment_payments",
    "asset_installment_schedules",
    "audit_logs",
    "bank_accounts",
    "branch_settings",
    "branches",
    "canteen_external_receivable_payments",
    "canteen_external_receivables",
    "canteen_sale_items",
    "canteen_sales",
    "cash_bank_adjustments",
    "cash_bank_opening_balances",
    "cash_bank_transactions",
    "cash_bank_transfers",
    "cash_daily",
    "cash_expenses",
    "client_pics",
    "clients",
    "daily_order_details",
    "daily_orders",
    "damaged_items",
    "debt_payments",
    "deliveries",
    "delivery_details",
    "delivery_locations",
    "delivery_receipts",
    "digital_attachments",
    "drivers",
    "employee_assignments",
    "employee_attendance",
    "employee_salary_history",
    "employee_skills",
    "employees",
    "field_counterparties",
    "field_transaction_attachments",
    "field_transaction_links",
    "field_transaction_review_logs",
    "field_transaction_settlements",
    "field_transactions",
    "fixed_asset_depreciation_configs",
    "fixed_asset_depreciations",
    "fixed_asset_purchases",
    "fixed_assets",
    "invoice_items",
    "invoices",
    "item_cost_profiles",
    "item_request_details",
    "item_requests",
    "items",
    "journal_details",
    "journals",
    "mandors",
    "manual_billing_batch_items",
    "manual_billing_batches",
    "manual_payable_payments",
    "manual_payables",
    "manual_receivable_payments",
    "manual_receivables",
    "menus",
    "notifications",
    "operational_expenses",
    "order_hpp_snapshot_allocations",
    "order_hpp_snapshot_components",
    "order_hpp_snapshot_lines",
    "order_hpp_snapshots",
    "order_hpp_stock_consumption_lines",
    "order_hpp_stock_consumptions",
    "order_revisions",
    "order_snapshots",
    "overhead_profiles",
    "packaging_profiles",
    "payments",
    "payroll_details",
    "payrolls",
    "period_closings",
    "procurement_items",
    "procurements",
    "production_details",
    "productions",
    "recipe_headers",
    "recipe_items",
    "recipe_version_items",
    "recipe_versions",
    "stock_adjustments",
    "stock_movements",
    "supplier_bills",
    "supplier_payments",
    "suppliers",
    "transport_vehicle_expenses",
    "unit_conversions",
    "users",
    "worker_debts",
    "workers",
)


def upgrade():
    for table_name in VERSIONED_TABLES:
        op.add_column(
            table_name,
            sa.Column("version_id", sa.Integer(), nullable=False, server_default="1"),
        )


def downgrade():
    for table_name in reversed(VERSIONED_TABLES):
        op.drop_column(table_name, "version_id")
