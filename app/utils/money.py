"""Uang dihitung dengan Decimal dua desimal, bukan float.

float tidak bisa menyimpan 0,1 dengan tepat; penjumlahan panjang (jurnal,
invoice, uang muka) bisa melenceng satu-dua sen dan membuat debit != kredit.
Kolom uang di database sudah Numeric(18, 2); fungsi ini menjaga perhitungannya
tetap Decimal sampai disimpan. Untuk tampilan, filter `rupiah` tetap cukup.
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def money(value):
    """Decimal dua desimal dari angka/teks/None. Nilai tak terbaca -> ValueError."""
    if value is None or value == "":
        return ZERO
    if isinstance(value, Decimal):
        return value.quantize(CENT, rounding=ROUND_HALF_UP)
    if isinstance(value, float):
        # repr float terpendek ("0.1", bukan 0.1000000000000000055...).
        value = repr(value)
    try:
        return Decimal(str(value).strip()).quantize(CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation as error:
        raise ValueError(f"Nominal uang tidak valid: {value!r}") from error


def money_sum(values):
    return sum((money(value) for value in values), ZERO)
