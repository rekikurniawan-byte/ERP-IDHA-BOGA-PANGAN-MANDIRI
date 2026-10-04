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
    assert "Unggah bukti tambahan" not in template
    assert ">Unggah bukti<" in template
    assert "Bukti Transfer Customer" not in template
    assert "Bukti Transfer" in template


def test_invoice_detail_payment_history_table_is_styled_by_page_css():
    """Tabel riwayat bayar punya kolom bukti yang lebar; gayanya ada di
    pages.css, bukan lagi tumpukan !important di akhir style.css."""
    pages_css = _read("app/static/css/app/pages.css")

    assert ".payment-history-table" in pages_css
    assert ".payment-proof-cell" in pages_css


def test_cash_bank_ledger_action_column_has_room_for_reconcile_controls():
    template = _read("app/templates/finance/cash_bank_ledger.html")
    pages_css = _read("app/static/css/app/pages.css")

    assert "cash-bank-ledger-action-cell" in template
    assert "cash-bank-ledger-actions" in template
    assert "cash-bank-ledger-reconcile-form" in template
    assert ".cash-bank-ledger-action-cell" in pages_css
    assert ".cash-bank-ledger-reconcile-form" in pages_css
