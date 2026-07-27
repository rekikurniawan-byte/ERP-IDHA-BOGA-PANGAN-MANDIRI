from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_customer_payment_form_and_route_are_wired_for_idempotency():
    detail_route_source = _read("app/routes/finance/invoice_detail_routes.py")
    payment_route_source = _read("app/routes/finance/payment_routes.py")
    template_source = _read("app/templates/finance/invoice_detail.html")

    assert "payment_form_idempotency_key=uuid4().hex" in detail_route_source
    assert 'scope="FINANCE_CUSTOMER_PAYMENT_CREATE"' in payment_route_source
    assert "reserve_idempotency_key(" in payment_route_source
    assert "mark_idempotency_completed(" in payment_route_source
    assert 'name="idempotency_key"' in template_source
    assert "{{ payment_form_idempotency_key }}" in template_source


def test_supplier_payment_form_and_route_are_wired_for_idempotency():
    route_source = _read("app/routes/finance/payables_routes.py")
    template_source = _read("app/templates/finance/supplier_bill_detail.html")

    assert "supplier_payment_form_idempotency_key=uuid4().hex" in route_source
    assert 'scope="FINANCE_SUPPLIER_PAYMENT_CREATE"' in route_source
    assert "reserve_idempotency_key(" in route_source
    assert "mark_idempotency_completed(" in route_source
    assert 'name="idempotency_key"' in template_source
    assert "{{ supplier_payment_form_idempotency_key }}" in template_source


def test_manual_backfill_and_stock_fulfill_are_wired_for_idempotency():
    manual_route_source = _read("app/routes/finance/manual_billing_routes.py")
    manual_template_source = _read("app/templates/finance/manual_billing_batch_detail.html")
    logistics_route_source = _read("app/routes/logistics/item_request_routes.py")
    logistics_template_source = _read("app/templates/logistics/item_request_detail.html")

    assert 'scope="FINANCE_MANUAL_BACKFILL_LOCK"' in manual_route_source
    assert 'scope="FINANCE_MANUAL_BACKFILL_CREATE_INVOICE"' in manual_route_source
    assert "{{ lock_idempotency_key }}" in manual_template_source
    assert "{{ create_invoice_idempotency_key }}" in manual_template_source
    assert 'scope="LOGISTICS_ITEM_REQUEST_FULFILL"' in logistics_route_source
    assert "{{ fulfill_idempotency_key }}" in logistics_template_source


def test_manual_backfill_void_is_wired_for_maker_checker():
    route_source = _read("app/routes/finance/manual_billing_routes.py")
    template_source = _read("app/templates/finance/manual_billing_batch_detail.html")

    assert "ensure_action_has_approval(" in route_source
    assert '"MANUAL_BACKFILL_VOID"' in route_source
    assert '"MANUAL_BILLING_BATCH"' in route_source
    assert 'name="void_reason"' in template_source


def test_accounting_batch_actions_are_wired_for_idempotency():
    base_route_source = _read("app/routes/accounting_routes.py")
    journal_route_source = _read("app/routes/accounting/journal_routes.py")
    report_route_source = _read("app/routes/accounting/report_routes.py")
    posting_route_source = _read("app/routes/accounting/posting_routes.py")
    closing_route_source = _read("app/routes/accounting/closing_routes.py")
    journal_template_source = _read("app/templates/accounting/journal_index.html")
    closing_template_source = _read("app/templates/accounting/period_closing.html")

    assert "def _reserve_accounting_idempotency" in base_route_source
    assert "ACCOUNTING_GENERATE_PERIOD_INVOICE_JOURNALS" in journal_route_source
    assert "ACCOUNTING_GENERATE_PAYMENT_JOURNALS" in journal_route_source
    assert "ACCOUNTING_GENERATE_PROCUREMENT_JOURNALS" in report_route_source
    assert "ACCOUNTING_GENERATE_HPP_PRODUCTION_JOURNALS" in posting_route_source
    assert "ACCOUNTING_GENERATE_WARUNG_PAYMENT_CORRECTION_JOURNALS" in posting_route_source
    assert "ACCOUNTING_PERIOD_CLOSING_POST" in closing_route_source
    assert "{{ idempotency_keys.period_invoice }}" in journal_template_source
    assert "{{ idempotency_keys.procurement }}" in journal_template_source
    assert "{{ post_idempotency_key }}" in closing_template_source
