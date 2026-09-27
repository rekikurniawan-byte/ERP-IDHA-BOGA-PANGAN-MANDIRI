"""Istilah bisnis per cabang (keputusan owner 2026-09-26).

Sistem dipakai untuk pelanggan katering di luar proyek. Kata yang terlihat
pengguna untuk Client, Sub Client, Lokasi Antar, dan Pekerja dibaca dari
Pengaturan Perusahaan cabang itu; bawaannya kata umum.
"""
import pytest

from app.services.company_settings_service import SETTING_KEYS, get_company_settings_schema
from app.utils import terms
from app.utils.terms import DEFAULT_TERMS, TERM_SETTING_KEYS, term


def test_istilah_bawaan_adalah_kata_umum():
    assert DEFAULT_TERMS == {
        "client": "Client",
        "sub_client": "Sub Client",
        "location": "Lokasi Antar",
        "worker": "Pekerja",
    }
    assert term("sub_client") == "Sub Client"
    assert term("client", lower=True) == "client"


def test_istilah_yang_disetel_cabang_dipakai(monkeypatch):
    monkeypatch.setattr(terms, "_branch_settings", lambda branch_id: {
        "term_client": "Yayasan", "term_sub_client": "Kelas", "term_location": "", "term_worker": "Siswa",
    })
    assert term("client", branch_id=7) == "Yayasan"
    assert term("sub_client", branch_id=7) == "Kelas"
    assert term("sub_client", lower=True, branch_id=7) == "kelas"
    # Isian kosong = bawaan.
    assert term("location", branch_id=7) == "Lokasi Antar"
    assert term("worker", branch_id=7) == "Siswa"


def test_huruf_kecil_menjaga_singkatan(monkeypatch):
    monkeypatch.setattr(terms, "_branch_settings", lambda branch_id: {
        "term_client": "PT", "term_sub_client": "RS Cabang",
    })
    assert term("client", lower=True, branch_id=1) == "PT"
    assert term("sub_client", lower=True, branch_id=1) == "RS cabang"


def test_tanpa_cabang_memakai_bawaan():
    # Di luar request (tugas latar, CLI) tidak ada cabang pengguna.
    assert term("sub_client") == "Sub Client"


def test_istilah_tak_dikenal_ditolak():
    with pytest.raises(KeyError):
        term("mandor")


def test_label_tingkat_modul_dirangkai_saat_ditampilkan(monkeypatch):
    # Label tingkat modul dibuat sebelum ada pengguna. Nilainya tetap str
    # bawaan (aman untuk JSON dan perbandingan), tapi saat dicetak memakai
    # istilah cabang yang sedang login.
    import json

    from markupsafe import escape

    from app.utils.terms import L

    label = L("Panjar Operasional {sub_client}")
    assert isinstance(label, str)
    assert json.loads(json.dumps(label)) == "Panjar Operasional Sub Client"

    monkeypatch.setattr(terms, "_current_branch_id", lambda: 7)
    monkeypatch.setattr(terms, "_branch_settings", lambda branch_id: {"term_sub_client": "Mandor"})
    assert str(label) == "Panjar Operasional Mandor"
    assert f"{label}" == "Panjar Operasional Mandor"
    assert str(escape(label)) == "Panjar Operasional Mandor"


def test_istilah_bisa_diatur_dari_pengaturan_perusahaan():
    # Form pengaturan dibangun dari skema, jadi keempat istilah otomatis
    # tampil, tersimpan, dan hanya OWNER yang bisa membuka halamannya.
    for key in TERM_SETTING_KEYS.values():
        assert key in SETTING_KEYS
    titles = [section["title"] for section in get_company_settings_schema()]
    assert "Istilah" in titles
