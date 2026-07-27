# Split from app.routes.finance_routes. Keep root imports/helpers as shared context.
from app.routes.finance_routes import *  # noqa: F401,F403

@finance_bp.route("/invoices/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_invoices_csv():
    from app.services.finance_export_service import build_invoice_export_response
    return build_invoice_export_response(current_user.branch_id)


@finance_bp.route("/payment-history/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_payment_history_csv():
    from app.services.finance_export_service import build_payment_history_export_response
    return build_payment_history_export_response(current_user.branch_id)


@finance_bp.route("/cash-bank-ledger/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_cash_bank_ledger_csv():
    from app.services.finance_export_service import build_cash_bank_ledger_export_response
    return build_cash_bank_ledger_export_response(current_user.branch_id, request.args.to_dict(flat=True))


# === PRODUCTION_FINANCE_ADVANCED_CSV_EXPORT_ROUTES ===
@finance_bp.route("/receivables/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_receivables_csv():
    from app.services.finance_export_service import build_receivables_export_response
    branch_id = current_user.branch_id
    requested_branch_id = (request.args.get("branch_id") or "").strip()
    if getattr(current_user, "role", "") == "OWNER" and requested_branch_id.isdigit():
        branch_id = int(requested_branch_id)
    return build_receivables_export_response(branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/supplier-bills/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_supplier_bills_csv():
    from app.services.finance_export_service import build_supplier_bills_export_response
    return build_supplier_bills_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/receivables/statement/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_receivables_statement_csv():
    from app.services.finance_export_service import build_receivables_statement_export_response
    return build_receivables_statement_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/accounts-payable-aging/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_accounts_payable_aging_csv():
    from app.services.finance_export_service import build_ap_aging_export_response
    return build_ap_aging_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/supplier-payable-card/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_supplier_payable_card_csv():
    from app.services.finance_export_service import build_supplier_payable_card_export_response
    return build_supplier_payable_card_export_response(current_user.branch_id, request.args.to_dict(flat=True))


@finance_bp.route("/invoice-profit-report/export.csv")
@role_required("OWNER", "ADMIN", "FINANCE")
def export_invoice_profit_report_csv():
    from app.services.finance_export_service import build_invoice_profit_export_response
    return build_invoice_profit_export_response(current_user.branch_id, request.args.to_dict(flat=True))


# === PRODUCTION_FINANCE_PRINT_READY_REPORT_ROUTES ===
@finance_bp.route("/cash-bank-ledger/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_cash_bank_ledger():
    from app.services.finance_print_service import build_cash_bank_ledger_print_context
    context = build_cash_bank_ledger_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_cash_bank_ledger.html", **context)


@finance_bp.route("/accounts-payable-aging/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_accounts_payable_aging():
    from app.services.finance_print_service import build_ap_aging_print_context
    context = build_ap_aging_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_accounts_payable_aging.html", **context)


@finance_bp.route("/supplier-payable-card/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_supplier_payable_card():
    from app.services.finance_print_service import build_supplier_payable_card_print_context
    context = build_supplier_payable_card_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_supplier_payable_card.html", **context)


@finance_bp.route("/invoice-profit-report/print")
@role_required("OWNER", "ADMIN", "FINANCE")
def print_invoice_profit_report():
    from app.services.finance_print_service import build_invoice_profit_print_context
    context = build_invoice_profit_print_context(current_user.branch_id, request.args.to_dict(flat=True))
    return render_template("finance/print_invoice_profit_report.html", **context)
