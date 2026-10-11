"""Peta navigasi portal: satu sumber untuk tab bawah, sub-tab, dan daftar Akun.

Aturan owner (2026-10-11): setiap halaman portal hanya punya SATU pintu.
- Tab bawah: Beranda, Pesanan/Operasional, Tagihan, Akun.
- Halaman di dalam satu tab muncul sebagai sub-tab di atas halaman (bukan
  tombol tambahan di Beranda atau di Akun).
- Halaman pendukung (alamat, kontrak, dokumen, dll.) hanya ada di Akun.
- Notifikasi hanya lewat ikon lonceng di header.
Tombol di dalam isi halaman hanya boleh membuka *rincian satu baris*
(mis. kartu invoice -> rincian invoice itu), bukan halaman daftar lain.
"""

from __future__ import annotations

from flask import url_for

from app.utils.terms import term

ROLE_PORTAL_CUSTOMER = "PORTAL_CUSTOMER"
ROLE_PORTAL_SUBCLIENT = "PORTAL_SUBCLIENT"
ROLE_PORTAL_CLIENT = "PORTAL_CLIENT"

HOME_ENDPOINTS = [
    "portal.my_dashboard",
    "portal.customer_dashboard",
    "portal.mandor_dashboard",
    "portal.pt_dashboard",
    "portal.client_dashboard",
    "portal.dashboard",
]


def _seg(label, endpoint, also=()):
    """Satu sub-tab: label, endpoint utama, dan endpoint lain yang ikut menyalakannya."""
    return {"label": label, "endpoint": endpoint, "endpoints": [endpoint, *also]}


def _link(label, icon, endpoint, description, also=()):
    return {"label": label, "icon": icon, "endpoint": endpoint, "description": description,
            "endpoints": [endpoint, *also]}


def portal_navigation_map(role, *, worker_debt_on=False, direct_ordering=False):
    """Peta mentah per peran (tanpa URL) supaya bisa dites tanpa request."""
    sub_client = term("sub_client")
    worker = term("worker")
    if role == ROLE_PORTAL_CUSTOMER:
        orders_label = "Pesanan"
        orders = [
            _seg("Pesan", "portal.customer_order", ("portal.draft_order",)),
            _seg("Pesanan Saya", "portal.customer_tracking", ("portal.customer_order_history", "portal.order_status")),
            _seg("Jadwal", "portal.calendar"),
        ]
        billing = [
            _seg("Tagihan & Pembayaran", "portal.customer_payments",
                 ("portal.customer_invoices", "portal.invoice_payment_instruction", "portal.payments", "portal.invoices")),
        ]
        account = [
            _link("Alamat Antar", "location_on", "portal.addresses", "Alamat, titik peta, dan foto lokasi"),
            _link("Komplain & Bantuan", "support_agent", "portal.customer_complaints", "Laporkan porsi kurang, terlambat, atau salah"),
            _link("Dokumen", "folder_open", "portal.documents", "Bukti bayar dan berkas lain"),
            _link("Persetujuan", "task_alt", "portal.approvals", "Permintaan yang menunggu keputusan"),
        ]
    elif role == ROLE_PORTAL_SUBCLIENT:
        orders_label = "Pesanan"
        orders = [
            _seg("Pesan", "portal.mandor_order", ("portal.draft_order",)),
            _seg("Status", "portal.order_status"),
            _seg("Jadwal", "portal.calendar"),
        ]
        billing = [
            _seg("Tagihan", "portal.mandor_invoices",
                 ("portal.invoice_payment_instruction", "portal.mandor_catering_debts", "portal.invoices")),
            _seg("Riwayat Bayar", "portal.mandor_payments", ("portal.payments",)),
        ]
        if worker_debt_on:
            billing.append(_seg(f"Kasbon {worker}", "portal.mandor_canteen_debts",
                                ("portal.mandor_installments", "portal.debts")))
        account = [
            _link("Kontrak & Surat", "contract", "portal.portal_contracts", "Kontrak aktif dan tanda tangan OTP",
                  ("portal.portal_contract_documents",)),
        ]
        if worker_debt_on:
            account.append(_link(f"Data {worker}", "groups", "portal.mandor_workers", f"{worker} di bawah akun Anda"))
        account += [
            _link("Alamat Antar", "location_on", "portal.addresses", "Alamat, titik peta, dan foto lokasi"),
            _link("Dokumen", "folder_open", "portal.documents", "Bukti bayar dan berkas lain"),
            _link("Persetujuan", "task_alt", "portal.approvals", "Permintaan yang menunggu keputusan"),
        ]
    elif role == ROLE_PORTAL_CLIENT:
        orders_label = "Operasional"
        orders = [
            _seg(sub_client, "portal.pt_mandors"),
            _seg("Jadwal", "portal.calendar"),
        ]
        if direct_ordering:
            orders += [
                _seg("Pesan Langsung", "portal.pt_order", ("portal.draft_order",)),
                _seg("Status Pesanan", "portal.order_status"),
            ]
        billing = [
            _seg("Tagihan", "portal.pt_invoices",
                 ("portal.invoice_payment_instruction", "portal.pt_receivables", "portal.invoices")),
            _seg("Riwayat Bayar", "portal.pt_payments", ("portal.payments",)),
        ]
        account = [
            _link("Kontrak & Surat", "contract", "portal.portal_contracts", "Kontrak, adendum, dan tanda tangan OTP",
                  ("portal.pt_contracts", "portal.portal_contract_documents")),
            _link("Alamat Antar", "location_on", "portal.addresses", f"Lokasi antar {sub_client.lower()}"),
            _link("Dokumen", "folder_open", "portal.documents", "Bukti bayar dan berkas lain"),
            _link("Persetujuan", "task_alt", "portal.approvals", "Permintaan yang menunggu keputusan"),
        ]
    else:
        orders_label = "Draf"
        orders = [_seg("Antrean Draf", "portal.admin_order_drafts")]
        billing = [
            _seg("Invoice", "portal.invoices", ("portal.invoice_payment_instruction",)),
            _seg("Pembayaran", "portal.payments"),
        ]
        account = [
            _link("Dokumen", "folder_open", "portal.documents", "Berkas portal"),
            _link("Persetujuan", "task_alt", "portal.approvals", "Permintaan portal"),
        ]
    return {
        "tabs": [
            {"key": "home", "label": "Beranda", "icon": "home", "endpoint": "portal.my_dashboard", "segments": []},
            {"key": "orders", "label": orders_label, "icon": "groups" if role == ROLE_PORTAL_CLIENT else "restaurant",
             "endpoint": orders[0]["endpoint"], "segments": orders},
            {"key": "billing", "label": "Tagihan", "icon": "receipt_long", "endpoint": billing[0]["endpoint"], "segments": billing},
            {"key": "account", "label": "Akun", "icon": "person", "endpoint": "portal.profile", "segments": []},
        ],
        "account_links": account,
    }


def build_portal_navigation(role, endpoint, *, worker_debt_on=False, direct_ordering=False):
    """Navigasi siap pakai untuk template: URL, tab aktif, sub-tab, dan daftar Akun."""
    nav = portal_navigation_map(role, worker_debt_on=worker_debt_on, direct_ordering=direct_ordering)
    account_endpoints = {"portal.profile"}
    for link in nav["account_links"]:
        account_endpoints.update(link["endpoints"])
        link["url"] = url_for(link["endpoint"])
        link["active"] = endpoint in link["endpoints"]
    active_key = None
    for tab in nav["tabs"]:
        tab["url"] = url_for(tab["endpoint"])
        for segment in tab["segments"]:
            segment["url"] = url_for(segment["endpoint"])
            segment["active"] = endpoint in segment["endpoints"]
        if tab["key"] == "home" and endpoint in HOME_ENDPOINTS:
            active_key = "home"
        elif tab["key"] == "account" and endpoint in account_endpoints:
            active_key = "account"
        elif any(segment["active"] for segment in tab["segments"]):
            active_key = active_key or tab["key"]
    for tab in nav["tabs"]:
        tab["active"] = tab["key"] == active_key
    active_tab = next((tab for tab in nav["tabs"] if tab["active"]), None)
    nav["segments"] = active_tab["segments"] if active_tab and len(active_tab["segments"]) > 1 else []
    # Halaman pendukung di bawah Akun mendapat tombol kembali ke Akun (bukan pintu baru).
    # Halaman rincian (mis. surat satu kontrak) punya tombol kembali sendiri ke daftarnya.
    nav["account_child"] = endpoint in {link["endpoint"] for link in nav["account_links"]}
    nav["active_key"] = active_key
    return nav
