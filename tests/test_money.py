"""Uang dihitung dengan Decimal dua desimal (app/utils/money.py)."""
from decimal import Decimal

import pytest

from app.utils.money import money


def test_float_diubah_lewat_repr_tanpa_sisa_biner():
    assert money(0.1) == Decimal("0.10")
    assert money(0.1) + money(0.2) == Decimal("0.30")  # float: 0.30000000000000004


def test_pembulatan_setengah_ke_atas_dua_desimal():
    assert money("1000.005") == Decimal("1000.01")
    assert money(Decimal("2.345")) == Decimal("2.35")


def test_kosong_jadi_nol_dan_teks_rusak_ditolak():
    assert money(None) == Decimal("0.00")
    assert money("") == Decimal("0.00")
    with pytest.raises(ValueError):
        money("abc")
