"""Jam WIB.

Cap waktu di database disimpan UTC tanpa zona (datetime.utcnow: created_at,
jam terima kiriman, jam berangkat, jam selesai masak). Target SLA dan batas
pesan adalah jam dinding WIB (tanggal + jam). Bandingkan dan tampilkan
setelah dikonversi ke WIB; Indonesia tidak memakai jam musim panas, jadi
selisihnya selalu 7 jam.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

WIB_OFFSET = timedelta(hours=7)
WIB = timezone(WIB_OFFSET, "WIB")


def to_wib(value):
    """datetime UTC (naif) -> datetime WIB (naif). Tanggal/None dikembalikan apa adanya."""
    if value is None or not isinstance(value, datetime):
        return value
    if value.tzinfo is not None:
        return value.astimezone(WIB).replace(tzinfo=None)
    return value + WIB_OFFSET


def now_wib():
    return datetime.utcnow() + WIB_OFFSET


def today_wib():
    return now_wib().date()


def format_wib(value, fmt="%d/%m/%Y %H.%M"):
    """Untuk template: {{ row.created_at|wib }} -> 04/10/2026 11.34."""
    if value is None or value == "":
        return "-"
    if isinstance(value, datetime):
        return to_wib(value).strftime(fmt)
    if isinstance(value, date):
        return value.strftime(fmt.split(" ")[0])
    return str(value)
