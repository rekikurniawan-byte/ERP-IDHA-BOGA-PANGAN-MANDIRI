"""Angka ke kata Bahasa Indonesia untuk dokumen uang (slip gaji, kwitansi)."""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

_SATUAN = ["", "satu", "dua", "tiga", "empat", "lima", "enam", "tujuh", "delapan", "sembilan", "sepuluh", "sebelas"]


def _words(n: int) -> str:
    if n < 12:
        return _SATUAN[n]
    if n < 20:
        return f"{_SATUAN[n - 10]} belas"
    if n < 100:
        return f"{_SATUAN[n // 10]} puluh {_words(n % 10)}".strip()
    if n < 200:
        return f"seratus {_words(n - 100)}".strip()
    if n < 1000:
        return f"{_SATUAN[n // 100]} ratus {_words(n % 100)}".strip()
    if n < 2000:
        return f"seribu {_words(n - 1000)}".strip()
    for size, name in ((10**12, "triliun"), (10**9, "miliar"), (10**6, "juta"), (10**3, "ribu")):
        if n >= size:
            return f"{_words(n // size)} {name} {_words(n % size)}".strip()
    return ""


def terbilang(value) -> str:
    """12500 -> 'Dua belas ribu lima ratus rupiah'."""
    amount = int(Decimal(str(value or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if amount == 0:
        return "Nol rupiah"
    prefix = "minus " if amount < 0 else ""
    text = f"{prefix}{_words(abs(amount))} rupiah"
    return " ".join(text.split()).capitalize()
