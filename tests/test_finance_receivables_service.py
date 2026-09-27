from datetime import date
from types import SimpleNamespace

from app.services.finance_receivables_service import (
    invoice_matches_period,
    invoice_matches_receivable_filters,
    invoice_party_context,
    normalize_bill_to_type_filter,
    parse_date_filter,
)


def test_invoice_party_context_supports_manual_backfill_free_party_snapshot():
    invoice = SimpleNamespace(
        bill_to_type="KELOMPOK",
        client_id=None,
        mandor_id=None,
        client_name_snapshot="Kelompok Pak Yatno",
        input_source="MANUAL_BACKFILL",
    )

    party = invoice_party_context(invoice)

    assert party["type"] == "KELOMPOK"
    assert party["type_label"] == "Kelompok"
    assert party["name"] == "Kelompok Pak Yatno"
    assert party["input_source_label"] == "Manual Backfill"


def test_invoice_party_context_keeps_legacy_mandor_invoice_compatible():
    invoice = SimpleNamespace(
        bill_to_type="MANDOR",
        client_id=3,
        mandor_id=7,
        client_name_snapshot="",
        input_source="REALTIME",
    )
    client = SimpleNamespace(id=3, name="PT APG")
    mandor = SimpleNamespace(id=7, name="Pak Tarom")

    party = invoice_party_context(invoice, client_map={3: client}, mandor_map={7: mandor})

    assert party["type"] == "MANDOR_EXISTING"
    assert party["type_label"] == "Sub Client"
    assert party["name"] == "Pak Tarom"
    assert party["client_name"] == "PT APG"
    assert party["input_source_label"] == "Realtime"


def test_receivable_filters_use_bill_to_status_and_period_overlap():
    invoice = SimpleNamespace(
        bill_to_type="CLIENT_LAIN",
        status="PARTIALLY_PAID",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 31),
        invoice_date=date(2026, 8, 1),
        client_name_snapshot="Client Luar Buku",
        client_id=None,
        mandor_id=None,
        input_source="MANUAL_BACKFILL",
    )
    party = invoice_party_context(invoice)

    assert invoice_matches_receivable_filters(
        invoice,
        party,
        bill_to_type="CLIENT_LAIN",
        status="PARTIALLY_PAID",
        period_from=date(2026, 7, 15),
        period_to=date(2026, 8, 5),
    )
    assert not invoice_matches_receivable_filters(invoice, party, bill_to_type="MANDOR_EXISTING")
    assert not invoice_matches_receivable_filters(invoice, party, status="DRAFT")
    assert not invoice_matches_period(invoice, period_from=date(2026, 8, 1), period_to=date(2026, 8, 31))


def test_normalizers_accept_expected_aliases_and_date_formats():
    assert normalize_bill_to_type_filter("mandor") == "MANDOR_EXISTING"
    assert normalize_bill_to_type_filter("client") == "CLIENT_EXISTING"
    assert normalize_bill_to_type_filter("client lain") == "CLIENT_LAIN"
    assert parse_date_filter("2026-07-31") == date(2026, 7, 31)
    assert parse_date_filter("31-07-2026") == date(2026, 7, 31)
