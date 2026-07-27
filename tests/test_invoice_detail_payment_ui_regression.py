from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_invoice_detail_payment_history_uses_fixed_proof_column_contract():
    template = _read("app/templates/finance/invoice_detail.html")

    assert 'data-invoice-detail-page="true"' in template
    assert "payment-history-scroll" in template
    assert template.count("payment-history-scroll") == 1
    assert 'payment-history-table' in template
    assert 'payment-history-col-proof' in template
    assert 'class="payment-proof-cell"' in template
    assert "Upload bukti tambahan" not in template
    assert ">Upload bukti<" in template
    assert "Bukti Transfer Customer" not in template
    assert "Bukti Transfer" in template


def test_invoice_detail_payment_proof_css_overrides_global_table_locks():
    css = _read("app/static/css/style.css")
    base_template = _read("app/templates/layouts/base.html")
    guard_marker = "Invoice detail payment proof regression guard"
    global_table_lock = "table-layout: auto !important;"

    assert "20260727-table-action-v1" in base_template
    assert guard_marker in css
    assert css.rfind(guard_marker) > css.rfind(global_table_lock)
    assert (
        '.finance-page-shell[data-invoice-detail-page="true"] table.payment-history-table'
        in css
    )
    assert (
        '.finance-page-shell[data-invoice-detail-page="true"] .payment-history-scroll'
        in css
    )
    assert "width: 1640px !important;" in css
    assert "min-width: 1640px !important;" in css
    assert "table-layout: fixed !important;" in css
    assert "writing-mode: horizontal-tb !important;" in css
    assert "word-break: normal !important;" in css
    assert "payment-proof-upload-form.app-form" in css or "payment-proof-upload-form" in css
    assert "display: flex !important;" in css
    assert "flex-direction: column !important;" in css
    assert "grid-template-columns: minmax(0, 1fr) !important;" in css


def test_global_app_table_alignment_guard_runs_before_invoice_specific_guard():
    css = _read("app/static/css/style.css")
    global_marker = "Global table alignment regression guard"
    invoice_marker = "Invoice detail payment proof regression guard"

    assert global_marker in css
    assert invoice_marker in css
    assert css.rfind(global_marker) < css.rfind(invoice_marker)
    assert "table.app-table:not(.payment-history-table) thead th" in css
    assert "table.app-table:not(.payment-history-table) tbody td" in css
    assert "text-align: left !important;" in css
    assert "vertical-align: middle !important;" in css
    assert "td.text-end" in css
    assert "text-align: right !important;" in css
    assert "td:has(.btn)" in css
    assert "display: inline-flex !important;" in css


def test_cash_bank_ledger_action_column_has_room_for_reconcile_controls():
    template = _read("app/templates/finance/cash_bank_ledger.html")
    css = _read("app/static/css/style.css")

    assert "cash-bank-ledger-action-cell" in template
    assert "cash-bank-ledger-actions" in template
    assert "cash-bank-ledger-reconcile-form" in template
    assert "cash-bank-ledger-action-cell" in css
    assert "width: 220px !important;" in css
    assert "form.cash-bank-ledger-reconcile-form" in css
    assert "grid-template-columns: minmax(0, 1fr) auto !important;" in css
