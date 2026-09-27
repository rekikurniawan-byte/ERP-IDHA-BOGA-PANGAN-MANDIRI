"""Batas data lama akuntansi tidak lagi tertanam di kode.

Dulu ACCOUNTING9B/9D_CUTOVER_* = 2/4: di database produksi baru, penjualan
warung #1-2 dan hutang pekerja #1-2 tidak dijurnal. Sekarang dibaca dari
ACCOUNTING_LEGACY_CUTOVER dengan bawaan 0.
"""
from types import SimpleNamespace

import pytest

from app.services.accounting_service import create_warung_debt_accrual_journal, legacy_cutover_id


def test_bawaannya_tidak_ada_data_yang_dilewati(app):
    with app.app_context():
        app.config["ACCOUNTING_LEGACY_CUTOVER"] = {}
        for kind in ("invoice", "worker_debt", "debt_payment", "canteen_sale"):
            assert legacy_cutover_id(kind) == 0


def test_database_lama_bisa_menyetel_batasnya(app):
    with app.app_context():
        app.config["ACCOUNTING_LEGACY_CUTOVER"] = {"worker_debt": 5}

        ok, message, _ = create_warung_debt_accrual_journal(SimpleNamespace(id=3), created_by=1)

        assert not ok and "cutover" in message


def test_hutang_pekerja_pertama_tidak_dilewati_di_database_baru(app):
    with app.app_context():
        app.config["ACCOUNTING_LEGACY_CUTOVER"] = {}

        # Lolos pengecekan cutover dan sampai ke validasi nominal -- dulu #1
        # langsung dilewati sebagai "data lama".
        with pytest.raises(Exception, match="Nominal hutang warung"):
            create_warung_debt_accrual_journal(SimpleNamespace(id=1, debt_amount=0), created_by=1)


def test_format_env(monkeypatch):
    import config

    monkeypatch.setenv("ACCOUNTING_LEGACY_CUTOVER", "invoice=2, worker_debt=2,rusak")

    assert config._cutover_env("ACCOUNTING_LEGACY_CUTOVER") == {"invoice": 2, "worker_debt": 2}
