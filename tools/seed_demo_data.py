"""Isi database kosong dengan data demo yang rapi, lewat alur aplikasi yang asli.

Bukan SQL langsung: setiap data dibuat lewat halaman yang sama dengan yang dipakai
pengguna (test client Flask, login per peran), jadi jurnal, buku kas/bank, stok,
piutang, dan hutang terbentuk otomatis dan selalu seimbang.

Jam disimulasikan hari demi hari dengan time-machine: pesanan bulan lalu benar-benar
dibuat, dimasak, diantar, dan diterima pada jam bulan lalu. Stempel waktu, SLA,
grafik, dan laporan terlihat seperti operasi sungguhan.

Tanggal relatif terhadap hari dijalankan (--today, bawaan hari ini): skenario
acuan (saldo awal 1 Agustus, "hari ini" Sabtu 3 Oktober 2026) digeser per minggu
penuh supaya hari dalam minggu tetap, lalu operasi biasa diteruskan sampai
kemarin. Hari ini: pesanan sudah dikunci dan bahan sudah keluar, produksi dan
pengiriman belum (tugas dapur & pengantar terlihat); pesanan hari kerja
berikutnya + draf portal menunggu.

Isi demo (area OKI Pulp & Paper, Air Sugihan - Ogan Komering Ilir, 1 cabang):
- 3 PT kontrak (4 mandor/lokasi) + 3 pelanggan umum (bayar di muka).
- Operasi Senin-Sabtu sekitar 9 minggu sampai kemarin (satu hari libur):
  order, produksi, pengiriman (sesekali kurang kirim/terlambat), pemakaian stok,
  pembelian tunai & hutang, warung, biaya listrik/air/BBM, gaji, penyusutan,
  invoice bulanan, pembayaran (lunas/sebagian/belum), komplain, kontrak.
- Titik GPS untuk dapur dan semua lokasi antar; ongkir pelanggan umum per km
  (Rp 2.000/km, minimal Rp 10.000, gratis mulai 10 porsi), tanpa minimal porsi.
- Pengajuan kerja sama dari halaman publik (baru, sudah dihubungi, jadi kontrak).
- Akun: 1 per peran internal (Owner, Admin, Dapur, Pengantar) + 1 per portal
  (PT, Mandor, Pelanggan Umum).

Pakai (database kosong yang baru di-migrate + bootstrap owner):
    DEMO_OWNER_PASSWORD=... python tools/seed_demo_data.py --db <nama_db> --confirm [--today 2026-10-03]

Password akun selain owner: DEMO_USER_PASSWORD (bawaan "IdhaBoga#2026").
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import sys
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "tools"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from pilot_dry_run import DryRun, _png  # noqa: E402  (pola langkah yang sama dengan gladi)

WIB = timezone(timedelta(hours=7))
BASE_NOW = date(2026, 10, 3)          # "hari ini" skenario acuan (Sabtu)
SHIFT = timedelta(0)                  # diisi configure_dates(): kelipatan 7 hari


def d(year, month, day):
    """Tanggal skenario acuan, digeser ke periode yang sedang dijalankan."""
    return date(year, month, day) + SHIFT


def configure_dates(today):
    global SHIFT, OPEN_DATE, FIRST_DAY, LAST_DAY, NOW_DAY, HOLIDAYS, BUMI_START
    SHIFT = timedelta(days=7 * ((today - BASE_NOW).days // 7))
    OPEN_DATE = d(2026, 8, 1)         # saldo awal per tanggal ini
    FIRST_DAY = d(2026, 8, 3)         # Senin pertama operasi
    HOLIDAYS = {d(2026, 8, 17)}
    BUMI_START = d(2026, 9, 1)        # PT baru mulai sebulan kemudian (grafik tumbuh)
    NOW_DAY = today
    LAST_DAY = today - timedelta(days=1)


MONTHS_ID = ("Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus",
             "September", "Oktober", "November", "Desember")


def tanggal(day):
    return f"{day.day} {MONTHS_ID[day.month - 1]} {day.year}"


configure_dates(BASE_NOW)

USER_PASSWORD = os.environ.get("DEMO_USER_PASSWORD", "IdhaBoga#2026")
OWNER_PASSWORD = os.environ.get("DEMO_OWNER_PASSWORD", "")

# Sejak Blueprint V2 hanya ada 4 peran internal (OWNER dibuat bootstrap);
# FINANCE/ACCOUNTING/LOGISTICS/HR/CUSTOMER_SUCCESS dikerjakan ADMIN.
STAFF = (
    ("Rahmat Hidayat", "admin", "ADMIN"),
    ("Bu Tini", "dapur", "DAPUR"),
    ("Pak Ujang", "pengantar", "PENGANTAR"),
)

# PT kontrak -> mandor -> lokasi, porsi rata-rata siang/sore.
CONTRACT_SITES = (
    ("PT Maju Konstruksi", "MAJU", "Mandor Budi", "Proyek Perluasan Mill", 60, 45),
    ("PT Maju Konstruksi", "MAJU", "Mandor Joko", "Mes Pekerja Sektor 3", 30, 0),
    ("PT Sinar Beton Utama", "SINAR", "Mandor Asep", "Batching Plant Air Sugihan", 35, 25),
    ("PT Bumi Persada Logistik", "BUMI", "Mandor Hendra", "Depo Logistik Simpang Tiga", 26, 20),
)
# Pelanggan umum: (nama, zona, lokasi, alamat, hari order (0=Senin), porsi siang, akun portal?)
GENERAL = (
    ("Ibu Rina", "Dekat (< 5 km)", "Rumah Bu Rina", "Perumahan Karyawan Blok C2, Air Sugihan", (2,), 15, "portal.customer.local"),
    ("Kantor Notaris Sari", "Dekat (< 5 km)", "Kantor Notaris Sari", "Jl. Lintas Timur No. 3, Simpang Tiga", (1, 4), 20, None),
    # Di bawah 10 porsi: tetap dilayani, ongkir jarak dibayar di muka.
    ("Pak Dedi", "Jauh (5-15 km)", "Kantor Pak Dedi", "Ruko Pasar Sungai Baung No. 5", (5,), 6, None),
)

# Titik GPS (lat, lng). Dapur dekat kawasan OKI Pulp & Paper, Air Sugihan.
KITCHEN_POINT = ("-2.9850000", "105.7280000")
LOCATION_POINTS = {
    "Proyek Perluasan Mill": ("-2.9712400", "105.7468100"),
    "Mes Pekerja Sektor 3": ("-2.9921300", "105.7533800"),
    "Batching Plant Air Sugihan": ("-3.0144200", "105.7097600"),
    "Depo Logistik Simpang Tiga": ("-2.9437500", "105.7032900"),
    "Rumah Bu Rina": ("-2.9796100", "105.7354200"),
    "Kantor Notaris Sari": ("-2.9558700", "105.7221500"),
    "Kantor Pak Dedi": ("-3.0302800", "105.7680400"),
}


def point_fields(location):
    lat, lng = LOCATION_POINTS[location]
    return {"latitude": lat, "longitude": lng, "gps_accuracy": "12", "location_photos": location_photo(location)}


def location_photo(label):
    """Foto contoh titik serah terima (wajib sejak 2026-10-05): gambar JPEG berlabel."""
    from PIL import Image, ImageDraw

    seed = sum(ord(ch) for ch in label)
    image = Image.new("RGB", (960, 640), (60 + seed % 50, 90 + seed % 40, 70 + seed % 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 470, 960, 640), fill=(28, 25, 23))
    draw.rectangle((380, 180, 580, 470), fill=(194, 65, 12))  # pintu/pos serah terima
    draw.text((40, 500), f"Titik serah terima: {label}", fill=(245, 240, 232))
    draw.text((40, 540), "Foto contoh data demo", fill=(200, 190, 180))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    buffer.seek(0)
    return (buffer, re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") + ".jpg")


def menu_photo(label):
    """Foto contoh menu catering: gambar JPEG berlabel piring & hidangan dibuat Pillow."""
    from PIL import Image, ImageDraw

    seed = sum(ord(ch) for ch in label)
    image = Image.new("RGB", (960, 640), (140 + seed % 60, 110 + seed % 40, 70 + seed % 30))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 480, 960, 640), fill=(44, 38, 34))
    draw.ellipse((280, 140, 680, 480), fill=(245, 245, 240), outline=(210, 205, 195), width=8)
    draw.ellipse((340, 200, 620, 430), fill=(200 + seed % 30, 80 + seed % 40, 30))
    draw.text((40, 510), f"Menu: {label}", fill=(245, 240, 232))
    draw.text((40, 550), "Foto contoh data demo katering", fill=(200, 190, 180))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    buffer.seek(0)
    return (buffer, re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") + ".jpg")

# Bahan per porsi (dipakai dapur) dan harga beli.
INGREDIENTS = {
    "Beras": ("kg", Decimal("0.12"), 14500),
    "Ayam Potong": ("kg", Decimal("0.07"), 37000),
    "Telur Ayam": ("kg", Decimal("0.04"), 28000),
    "Minyak Goreng": ("liter", Decimal("0.015"), 19500),
    "Gas LPG 12 kg": ("tabung", Decimal("0.0067"), 215000),
    "Box Nasi": ("pcs", Decimal("1"), 700),
}
WARUNG = {  # nama: (satuan, harga beli, harga jual)
    "Air Mineral 600 ml": ("botol", 2500, 4000),
    "Kopi Sachet": ("sachet", 1500, 3000),
    "Mi Instan": ("bungkus", 2800, 5000),
}


def at(day, hh, mm=0):
    return datetime.combine(day, time(hh, mm), tzinfo=WIB)


def op_days():
    day = FIRST_DAY
    while day <= LAST_DAY:
        if day.weekday() < 6 and day not in HOLIDAYS:
            yield day
        day += timedelta(days=1)


class Demo(DryRun):
    """DryRun dengan jam simulasi dan keluaran ringkas (hanya langkah gagal)."""

    def __init__(self, app):
        super().__init__(app)
        self.clock = None
        self.failures = []

    def travel(self, moment):
        import time_machine

        if self.clock:
            self.clock.stop()
        self.clock = time_machine.travel(moment, tick=False)
        self.clock.start()

    def stop_clock(self):
        if self.clock:
            self.clock.stop()
            self.clock = None

    def client(self, username=None):
        client = super().client(username)
        client.demo_user_id = None
        if username:
            from app.models.master import User

            client.demo_user_id = self.q(lambda: User.query.filter_by(username=username).one().id)
        return client

    def step(self, client, label, url, data=None, expect=("success", "info"), method="POST", **kwargs):
        import contextlib

        # Tandatangani ulang sesi dengan jam simulasi saat ini. Cookie yang
        # ditandatangani pada jam yang "lebih depan" ditolak (umur < 0), jadi
        # login diset ulang tiap langkah alih-alih mengandalkan cookie lama.
        if getattr(client, "demo_user_id", None):
            with client.session_transaction() as session:
                session["_user_id"] = str(client.demo_user_id)
                session["_fresh"] = True
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            response, ok = super().step(client, label, url, data=data, expect=expect, method=method, **kwargs)
        if not ok:
            self.failures.append((self.stage, label, buffer.getvalue().strip()))
            print(f"  [GAGAL] {self.stage} | {buffer.getvalue().strip()}")
        return response, ok


# --- persiapan ---------------------------------------------------------------------

def stage_setup(run):
    from app.models.master import Client, Mandor, User
    from app.models.pricing import DeliveryZone

    run.stage = "Persiapan"
    run.travel(at(OPEN_DATE - timedelta(days=1), 9))
    own = run.client("owner")
    branch_id = run.q(lambda: User.query.filter_by(username="owner").one().branch_id)
    guard = {"sensitive_action_confirmed": "1", "sensitive_reason": "Penyiapan data demo cabang", "confirm_password": OWNER_PASSWORD}

    run.step(own, "Pengaturan perusahaan", "/settings/company", data={
        "company_name": "PT Idha Boga Pangan Mandiri", "company_subtitle": "Catering Proyek & Harian",
        "company_address": "Jl. Lintas Timur Km 3, Desa Bukit Batu, Kec. Air Sugihan, Kab. Ogan Komering Ilir, Sumatera Selatan",
        "company_phone": "0812-1111-2222",
        "company_email": "idhabogapanganmandiri@gmail.com", "company_npwp": "01.234.567.8-901.000",
        "payment_bank_name": "BCA", "payment_account_number": "1234567890", "payment_account_name": "PT Idha Boga Pangan Mandiri",
        "invoice_footer": "Terima kasih atas kepercayaan Anda.", "invoice_terms": "Pembayaran paling lambat sesuai termin kontrak.",
        "invoice_authorized_name": "Idha Rahmawati", "invoice_authorized_position": "Direktur",
        "term_client": "PT", "term_sub_client": "Mandor", "term_location": "Lokasi Proyek", "term_worker": "Pekerja",
        "module_warung": "1", "module_worker_debt": "1",
        "document_prefix_invoice": "INV", "document_prefix_payment": "PAY", "document_prefix_order": "ORD",
        "document_prefix_delivery": "DLV", "document_prefix_journal": "JRN", **guard})

    for full_name, username, role in STAFF:
        run.step(own, f"Akun {role}", "/settings/users/create", data={
            "full_name": full_name, "username": username, "role": role, "branch_id": branch_id, "is_active": "on",
            "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD, **guard})

    # Tiap rekening punya akun buku besar sendiri: BCA -> 1002 Bank 1, Mandiri -> 1003 Bank 2.
    for bank, number, coa in (("BCA", "1234567890", ""), ("Mandiri", "1400012345678", "1003")):
        run.step(own, f"Rekening {bank}", "/master/bank-accounts/create", data={
            "bank_name": bank, "account_number": number, "account_name": "PT Idha Boga Pangan Mandiri",
            "coa_account_code": coa, "is_active": "on"})

    for name, code in {(row[0], row[1]) for row in CONTRACT_SITES}:
        run.step(own, f"PT {name}", "/master/clients/create", data={
            "client_code": code, "name": name, "phone": "0711-899-110", "customer_path": "KONTRAK",
            "address": "Kawasan OKI Pulp & Paper, Air Sugihan", "is_active": "on"})
    clients = run.q(lambda: {c.name: c.id for c in Client.query.all()})
    for name, pic in (("PT Maju Konstruksi", "Wati Susanti"), ("PT Sinar Beton Utama", "Hendra Gunawan"), ("PT Bumi Persada Logistik", "Lina Marlina")):
        run.step(own, f"PIC {pic}", f"/master/clients/{clients[name]}/pics/create", data={
            "pic_name": pic, "pic_phone": "0816-2200-3300", "pic_email": "finance@example.co.id", "pic_position": "Finance"})

    price_from = (OPEN_DATE - timedelta(days=1)).isoformat()
    run.step(own, "Harga standar 18.000", "/settings/pricing/price", data={"price_per_portion": "18000", "effective_from": price_from, "notes": "Harga umum 2026"})
    run.step(own, "Harga kontrak PT Maju 16.000", "/settings/pricing/price", data={"client_id": clients["PT Maju Konstruksi"], "price_per_portion": "16000", "effective_from": price_from, "notes": "Kontrak 2026"})
    run.step(own, "Harga kontrak PT Sinar 17.000", "/settings/pricing/price", data={"client_id": clients["PT Sinar Beton Utama"], "price_per_portion": "17000", "effective_from": price_from, "notes": "Kontrak 2026"})
    # Keputusan owner 2026-10-04: tanpa minimal porsi; di bawah 10 porsi bayar ongkir jarak.
    run.step(own, "Tanpa minimal porsi", "/settings/pricing/min-portions", data={"min_portions": "1"})
    run.step(own, "Ongkir jarak dari dapur", "/settings/pricing/distance-fee", data={
        "latitude": KITCHEN_POINT[0], "longitude": KITCHEN_POINT[1], "origin_label": "Dapur Idha Boga",
        "per_km": "2000", "minimum": "10000", "road_factor": "1.3"})
    for zone in ("Dekat (< 5 km)", "Jauh (5-15 km)"):
        run.step(own, f"Zona {zone}", "/settings/pricing/zones", data={"name": zone})
    zones = run.q(lambda: {z.name: z.id for z in DeliveryZone.query.filter_by(branch_id=branch_id).all()})
    run.step(own, "Ongkir dekat", "/settings/pricing/delivery-fee", data={"zone_id": zones["Dekat (< 5 km)"], "fee": "10000", "effective_from": price_from})
    run.step(own, "Ongkir jauh", "/settings/pricing/delivery-fee", data={"zone_id": zones["Jauh (5-15 km)"], "fee": "25000", "effective_from": price_from})
    run.step(own, "Gratis ongkir 10 porsi", "/settings/pricing/free-delivery", data={"free_delivery_min_portions": "10"})

    adm = run.client("admin")
    for client_name, _code, mandor, location, _l, _d in CONTRACT_SITES:
        run.step(adm, f"Mandor {mandor}", "/master/mandors/create", data={
            "client_id": clients[client_name], "name": mandor, "phone": "0813-5500-1200", "is_active": "on"})
        mandor_id = run.q(lambda: Mandor.query.filter_by(name=mandor).one().id)
        run.step(adm, f"Lokasi {location}", "/master/locations/create", data={
            "mandor_id": mandor_id, "location_name": location, "description": "Gerbang utama, lapor ke pos satpam", "is_active": "on",
            **point_fields(location)})
    for driver, plate in (("Pak Ujang", "BG 8123 OK"), ("Pak Karim", "BG 8471 OK")):
        run.step(adm, f"Pengantar {driver}", "/master/drivers/create", data={"name": driver, "phone": "0814-7700-2100", "license_number": plate, "is_active": "on"})

    # Akun portal: satu PT, satu mandor, satu pelanggan umum (daftar sendiri).
    budi = run.q(lambda: Mandor.query.filter_by(name="Mandor Budi").one().id)
    portal = {"branch_id": branch_id, "is_active": "on", "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD, **guard}
    run.step(own, "Portal PT", "/settings/users/create", data={
        "full_name": "Wati Susanti (PT Maju)", "username": "portal.pt.local", "email": "portal.pt.demo@idhaboga.local", "role": "PORTAL_CLIENT",
        "portal_client_id": clients["PT Maju Konstruksi"], **portal})
    run.step(own, "Portal Mandor", "/settings/users/create", data={
        "full_name": "Mandor Budi", "username": "portal.mandor.local", "email": "portal.mandor.demo@idhaboga.local", "role": "PORTAL_SUBCLIENT", "portal_mandor_id": budi, **portal})

    anon = run.client()
    for index, (name, zone, location, address, _days, _qty, username) in enumerate(GENERAL):
        if username:
            run.step(anon, f"Pelanggan umum daftar: {name}", "/portal/register", data={
                "full_name": name, "phone": f"0815-7000-{index}{index}{index}{index}", "email": "customer.demo@idhaboga.local", "username": username, "branch_id": branch_id,
                "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD, "location_name": location,
                "delivery_zone_id": zones[zone], "address": address, "notes": "Pagar hitam, sebelah musala",
                **point_fields(location)})
            continue
        run.step(own, f"Pelanggan umum {name}", "/master/clients/create", data={
            "name": name, "phone": f"0815-7000-{index}{index}{index}{index}", "customer_path": "UMUM", "address": address, "is_active": "on"})
        client_id = run.q(lambda: Client.query.filter_by(name=name).one().id)
        run.step(adm, f"Kontak {name}", "/master/mandors/create", data={"client_id": client_id, "name": name, "phone": "0815-7000-1111", "is_active": "on"})
        mandor_id = run.q(lambda: Mandor.query.filter_by(name=name, client_id=client_id).one().id)
        run.step(adm, f"Lokasi {location}", "/master/locations/create", data={
            "mandor_id": mandor_id, "location_name": location, "description": address, "delivery_zone_id": zones[zone], "is_active": "on",
            **point_fields(location)})

    for name, (unit, _per, _price) in INGREDIENTS.items():
        category = "PACKAGING" if name == "Box Nasi" else ("GAS" if name.startswith("Gas") else "RAW_MATERIAL")
        minimum = {"Beras": "60", "Ayam Potong": "20", "Telur Ayam": "10", "Minyak Goreng": "10", "Gas LPG 12 kg": "3", "Box Nasi": "400"}[name]
        run.step(adm, f"Barang {name}", "/master/items/create", data={
            "item_name": name, "category": category, "unit": unit, "minimum_stock": minimum, "is_stock_tracked": "on", "is_active": "on"})
    for name, (unit, _buy, sell) in WARUNG.items():
        run.step(adm, f"Barang warung {name}", "/master/items/create", data={
            "item_name": name, "category": "MERCHANDISE", "unit": unit, "minimum_stock": "30", "selling_price": str(sell),
            "is_stock_tracked": "on", "is_active": "on"})
    for unit_from, unit_to, multiplier, note in (("karung", "kg", "25", "Beras karung 25 kg"),
                                                 ("dus", "botol", "24", "Air mineral 600 ml isi 24"),
                                                 ("renteng", "sachet", "10", "Kopi sachet per renteng"),
                                                 ("dus", "bungkus", "40", "Mi instan isi 40"),
                                                 ("pak", "pcs", "50", "Box nasi per pak")):
        run.step(adm, f"Konversi {unit_from} -> {unit_to}", "/master/unit-conversions", data={
            "unit_from": unit_from, "unit_to": unit_to, "multiplier": multiplier, "notes": note})
    for supplier, kind, terms in (("Toko Sumber Rejeki", "RAW_MATERIAL", "14"), ("Agen Gas Makmur", "GAS", "7"), ("CV Kemasan Jaya", "PACKAGING", "30")):
        run.step(own, f"Supplier {supplier}", "/master/suppliers/create", data={
            "supplier_name": supplier, "supplier_type": kind, "default_payment_terms_days": terms, "contact_person": "Bagian Penjualan",
            "phone": "0711-883-440", "address": "Pasar Simpang Tiga, OKI", "is_active": "on"})

    for mandor, workers in (("Mandor Budi", ("Slamet", "Wawan", "Rudi")), ("Mandor Asep", ("Dadang", "Ujang Sopandi"))):
        mandor_id = run.q(lambda: Mandor.query.filter_by(name=mandor).one().id)
        for worker in workers:
            run.step(adm, f"Pekerja {worker}", "/master/workers/create", data={
                "full_name": worker, "mandor_id": mandor_id, "phone": "0817-2200-1100", "status": "ACTIVE"})

    run.stop_clock()
    return refs(run)


def refs(run):
    from app.models.finance import BankAccount
    from app.models.master import Client, Item, Mandor, Supplier, User

    def load():
        return {
            "branch_id": User.query.filter_by(username="owner").one().branch_id,
            "bca": BankAccount.query.filter_by(account_number="1234567890").one().id,
            "mandiri": BankAccount.query.filter_by(account_number="1400012345678").one().id,
            "items": {i.item_name: i.id for i in Item.query.all()},
            "suppliers": {s.supplier_name: s.id for s in Supplier.query.all()},
            "clients": {c.name: c.id for c in Client.query.all()},
            "mandors": {m.name: m.id for m in Mandor.query.all()},
        }
    return run.q(load)


def stage_hr_and_costing(run, ref):
    run.stage = "SDM & HPP"
    run.travel(at(OPEN_DATE - timedelta(days=1), 13))
    own = run.client("owner")
    for name, salary, skills, joined in (
        ("Bu Tini", 4200000, "Kepala dapur", "2024-02-01"), ("Ani Suryani", 3300000, "Juru masak", "2024-05-13"),
        ("Rizky Pratama", 3100000, "Juru masak", "2025-01-06"), ("Mbak Yuli", 2900000, "Pengemasan", "2025-03-03"),
        ("Pak Karim", 3300000, "Pengantar", "2024-08-19"), ("Siti Rahayu", 3800000, "Admin SDM", "2024-02-01"),
    ):
        run.step(own, f"Karyawan {name}", "/hr/employees/create", data={
            "full_name": name, "join_date": joined, "phone": "0818-6600-1200", "salary_amount": str(salary), "skills": skills})

    DEMO_MENUS = (
        ("Nasi Ayam Bumbu Kuning", "LUNCH", "18000", "Ayam goreng bumbu kuning empuk dengan tahu, tempe, lalap segar, dan sambal terasi."),
        ("Nasi Telur Balado", "DINNER", "18000", "Telur balado bumbu cabai segar pedas manis dengan tumis buncis tempe dan kerupuk."),
        ("Nasi Rendang Sapi", "LUNCH", "24000", "Rendang daging sapi empuk kaya rempah khas Minang dengan daun singkong rebus."),
        ("Nasi Ikan Bakar Sambal Kecap", "DINNER", "20000", "Ikan nila bakar bumbu rempah harum disajikan dengan sambal kecap pedas segar."),
        ("Nasi Ayam Bakar Madu", "LUNCH", "19000", "Ayam bakar oles madu gurih legit dengan sambal bajak dan tempe bacem."),
    )
    for menu, kind, price, desc in DEMO_MENUS:
        buf, filename = menu_photo(menu)
        run.step(own, f"Menu {menu}", "/costing/menus/create", data={
            "menu_name": menu, "menu_type": kind, "default_selling_price": price, "description": desc, "is_active": "on",
            "menu_photos": (buf, filename),
        })
    run.step(own, "Profil kemasan box", "/costing/packaging-profiles/create", data={"profile_name": "Box nasi + sendok", "cost_per_portion": "900", "is_active": "on"})
    run.step(own, "Profil overhead dapur", "/costing/overhead-profiles/create", data={
        "profile_name": "Overhead dapur standar", "gas_cost_per_portion": "1450", "electricity_cost_per_portion": "350",
        "water_cost_per_portion": "150", "labor_cost_per_portion": "2400", "spices_cost_per_portion": "600",
        "other_cost_per_portion": "200", "overhead_percentage": "0", "is_active": "on"})
    for name, (unit, per, price) in INGREDIENTS.items():
        run.step(own, f"Harga pokok {name}", f"/master/items/{ref['items'][name]}/cost-profile", data={
            "base_unit": unit, "purchase_unit": unit, "purchase_qty": "1", "conversion_factor": "1",
            "standard_purchase_price": str(price), "yield_percentage": "100", "waste_percentage": "3" if name != "Box Nasi" else "0",
            "cost_source": "STANDARD", "notes": f"Harga pasar {MONTHS_ID[(OPEN_DATE - timedelta(days=1)).month - 1]} {OPEN_DATE.year}"})

    from app.models.master import Menu
    from app.services.menu_schedule_service import get_monday_of_week, save_menu_schedule

    menus = run.q(lambda: {m.menu_name: m.id for m in Menu.query.all()})
    for menu, items in (("Nasi Ayam Bumbu Kuning", (("Beras", "0.12"), ("Ayam Potong", "0.09"), ("Minyak Goreng", "0.015"))),
                        ("Nasi Telur Balado", (("Beras", "0.12"), ("Telur Ayam", "0.08"), ("Minyak Goreng", "0.02")))):
        url = f"/costing/menus/{menus[menu]}/recipe"
        header = {"action": "save_header", "recipe_name": f"Resep {menu}", "base_portion": "1",
                  "version_label": "v1", "version_note": "Resep baku dapur", "is_active": "on"}
        run.step(own, f"Resep {menu} (konsep)", url, data={**header, "recipe_status": "DRAFT"})
        for item, qty in items:
            unit = INGREDIENTS[item][0]
            run.step(own, f"Resep {menu}: {item}", url, data={
                "action": "add_item", "item_id": ref["items"][item], "qty_per_portion": qty, "unit": unit, "item_notes": ""})
        run.step(own, f"Resep {menu} final", url, data={**header, "recipe_status": "FINAL"})

    # Jadwal menu 2 minggu untuk cabang demo
    monday = get_monday_of_week(NOW_DAY)
    lunch_cycle = [menus.get("Nasi Ayam Bumbu Kuning"), menus.get("Nasi Rendang Sapi"), menus.get("Nasi Ayam Bakar Madu")]
    lunch_cycle = [m for m in lunch_cycle if m]
    dinner_cycle = [menus.get("Nasi Telur Balado"), menus.get("Nasi Ikan Bakar Sambal Kecap")]
    dinner_cycle = [m for m in dinner_cycle if m]

    for day_offset in range(14):
        target_date = monday + timedelta(days=day_offset)
        if lunch_cycle:
            m_id = lunch_cycle[day_offset % len(lunch_cycle)]
            run.q(lambda d=target_date, mid=m_id: save_menu_schedule(
                branch_id=ref["branch_id"], menu_date=d, meal_type="LUNCH", menu_id=mid,
                notes=f"Menu siang {d.strftime('%d-%m-%Y')}", commit=True
            ))
        if dinner_cycle:
            m_id = dinner_cycle[day_offset % len(dinner_cycle)]
            run.q(lambda d=target_date, mid=m_id: save_menu_schedule(
                branch_id=ref["branch_id"], menu_date=d, meal_type="DINNER", menu_id=mid,
                notes=f"Menu malam {d.strftime('%d-%m-%Y')}", commit=True
            ))
    run.stop_clock()


def stage_opening(run, ref):
    run.stage = "Saldo awal"
    run.travel(at(OPEN_DATE - timedelta(days=1), 16))
    own = run.client("owner")
    base = "/accounting/opening-balance"
    run.step(own, "Tanggal mulai", f"{base}/start-date", data={"start_date": OPEN_DATE.isoformat()})
    run.step(own, "Kas & bank", f"{base}/cash-bank", data={
        "cash": "8000000", f"bank_{ref['bca']}": "65000000", f"bank_{ref['mandiri']}": "15000000"})
    for client, ref_no, amount, days in (("PT Maju Konstruksi", "NT-0712", "2400000", 24), ("PT Bumi Persada Logistik", "NT-0688", "1150000", 40)):
        run.step(own, f"Piutang lama {client}", f"{base}/receivables/add", data={
            "client_id": ref["clients"][client], "reference": ref_no,
            "invoice_date": (OPEN_DATE - timedelta(days=days)).isoformat(), "amount": amount})
    run.step(own, "Hutang lama Toko Sumber Rejeki", f"{base}/payables/add", data={
        "supplier_id": ref["suppliers"]["Toko Sumber Rejeki"], "reference": "F-0731",
        "bill_date": (OPEN_DATE - timedelta(days=6)).isoformat(), "due_date": (OPEN_DATE + timedelta(days=6)).isoformat(), "amount": "3200000"})
    opening_stock = {"Beras": ("300", "14000"), "Ayam Potong": ("40", "36000"), "Telur Ayam": ("30", "27500"),
                     "Minyak Goreng": ("60", "19000"), "Gas LPG 12 kg": ("8", "210000"), "Box Nasi": ("2000", "650"),
                     "Air Mineral 600 ml": ("240", "2500"), "Kopi Sachet": ("200", "1500"), "Mi Instan": ("160", "2800")}
    for item, (qty, cost) in opening_stock.items():
        run.step(own, f"Stok awal {item}", f"{base}/stock/add", data={"item_id": ref["items"][item], "qty": qty, "unit_cost": cost})
    run.step(own, "Aset peralatan dapur", f"{base}/assets/add", data={
        "name": "Kompor, wajan & peralatan dapur", "category": "KITCHEN_EQUIPMENT", "purchase_date": "2024-03-01",
        "purchase_value": "48000000", "accumulated": "11200000", "useful_life_years": "5"})
    run.step(own, "Aset mobil pengantar", f"{base}/assets/add", data={
        "name": "Mobil boks pengantar BG 8123 OK", "category": "VEHICLE", "purchase_date": "2023-06-01",
        "purchase_value": "165000000", "accumulated": "44000000", "useful_life_years": "8"})
    run.step(own, "Kunci saldo awal", f"{base}/lock", data={
        "sensitive_reason": f"Saldo awal sesuai hitung fisik dan rekening koran {tanggal(OPEN_DATE - timedelta(days=1))}", "confirm_password": OWNER_PASSWORD})
    run.stop_clock()


def stage_contracts(run, ref):
    from app.models.master import ClientPic

    run.stage = "Kontrak"
    run.travel(at(OPEN_DATE - timedelta(days=1), 17))
    own = run.client("owner")
    pics = run.q(lambda: {p.client_id: p.id for p in ClientPic.query.filter_by(is_active=True).all()})
    for client, title, start, end, terms, limit in (
        ("PT Maju Konstruksi", "Katering Proyek Perluasan Mill & Mes", d(2026, 1, 1), d(2026, 12, 31), "net 14", "150000000"),
        # Habis 12 hari setelah "hari ini": pengingat H-30 dan H-7 terlihat.
        ("PT Sinar Beton Utama", "Katering Batching Plant Air Sugihan", d(2025, 10, 16), d(2026, 10, 15), "net 30", "90000000"),
        ("PT Bumi Persada Logistik", "Katering Depo Logistik Simpang Tiga", BUMI_START, d(2027, 8, 31), "net 30", "60000000"),
    ):
        client_id = ref["clients"][client]
        run.step(own, f"Kontrak {client}", "/customer-success/contracts", data={
            "client_id": client_id, "client_pic_id": pics[client_id], "title": title, "start_date": start.isoformat(), "end_date": end.isoformat(),
            "payment_terms": terms, "credit_limit": limit, "status": "ACTIVE", "notes": "Kontrak tertulis, harga per porsi"})
    run.stop_clock()


# --- operasi harian ------------------------------------------------------------------

class Plan:
    """Rencana porsi dan sisa stok simulasi supaya pembelian masuk akal."""

    def __init__(self, seed=20261003):
        self.rng = random.Random(seed)
        self.stock = {"Beras": Decimal(300), "Ayam Potong": Decimal(40), "Telur Ayam": Decimal(30),
                      "Minyak Goreng": Decimal(60), "Gas LPG 12 kg": Decimal(8), "Box Nasi": Decimal(2000),
                      "Air Mineral 600 ml": Decimal(240), "Kopi Sachet": Decimal(200), "Mi Instan": Decimal(160)}

    def portions(self, day, base):
        if not base:
            return 0
        wobble = self.rng.randint(-int(base * 0.12), int(base * 0.12))
        weekend = -int(base * 0.15) if day.weekday() == 5 else 0
        return max(10, base + wobble + weekend)


def place_contract_orders(run, plan, ref, day, adm):
    from app.models.master import DeliveryLocation

    total = 0
    for _client, _code, mandor, location, lunch, dinner in CONTRACT_SITES:
        if mandor == "Mandor Hendra" and day < BUMI_START:
            continue
        lunch_qty, dinner_qty = plan.portions(day, lunch), plan.portions(day, dinner)
        loc = run.q(lambda: DeliveryLocation.query.filter_by(location_name=location).one().id)
        run.step(adm, f"Order {day} {location}", "/operational/orders/create", data={
            "order_date": day.isoformat(), "mandor_id": ref["mandors"][mandor], "delivery_location_id": loc,
            "lunch_qty": lunch_qty, "dinner_qty": dinner_qty, "notes": ""})
        total += lunch_qty + dinner_qty
    return total


def general_total(run, ref, mandor_id, location_id, lunch, day):
    from app.models.master import DeliveryLocation, Mandor
    from app.services.pricing_service import order_trip_fees, quote_price_for_mandor

    def calc():
        quote = quote_price_for_mandor(ref["branch_id"], mandor_id, day)
        mandor = Mandor.query.get(mandor_id)
        lunch_fee, dinner_fee, _ = order_trip_fees(ref["branch_id"], mandor.client, DeliveryLocation.query.get(location_id), lunch, 0, day)
        return int(Decimal(str(quote.price)) * lunch + Decimal(str(lunch_fee or 0)) + Decimal(str(dinner_fee or 0)))
    return run.q(calc)


def place_general_orders(run, plan, ref, day, adm):
    from app.models.master import DeliveryLocation, User
    from app.models.system import DigitalAttachment, PortalOrderDraft

    total = 0
    for name, _zone, location, _address, weekdays, base, username in GENERAL:
        if day.weekday() not in weekdays:
            continue
        # Tanpa minimal porsi: pesanan kecil (Pak Dedi) membayar ongkir jarak.
        qty = max(1, base + plan.rng.randint(-3, 5))
        loc = run.q(lambda: (lambda row: {"id": row.id, "mandor_id": row.mandor_id})(DeliveryLocation.query.filter_by(location_name=location).one()))
        amount = general_total(run, ref, loc["mandor_id"], loc["id"], qty, day)
        if username:
            # Lewat portal: pesan -> unggah bukti -> keuangan verifikasi & catat -> admin konfirmasi.
            customer = run.client(username)
            page = customer.get("/portal/orders/draft").get_data(as_text=True)
            key = re.search(r'name="idempotency_key" value="([^"]+)"', page)
            run.step(customer, f"Portal {name} pesan {day}", "/portal/orders/draft", data={
                "idempotency_key": key.group(1) if key else uuid.uuid4().hex, "order_date": day.isoformat(), "meal_type": "LUNCH",
                "delivery_location_id": loc["id"], "portion_qty": qty, "delivery_time": "11:30",
                "contact_name": name, "contact_phone": "0815-7000-0000", "notes": "Tidak pedas"})
            draft = run.q(lambda: (lambda u: PortalOrderDraft.query.filter_by(user_id=u.id, order_date=day).order_by(PortalOrderDraft.id.desc()).first())(
                User.query.filter_by(username=username).one()))
            draft_id, due = draft.id, int(Decimal(str(draft.price_per_portion or 0)) * draft.portion_qty + Decimal(str(draft.delivery_fee or 0)))
            run.step(customer, f"Bukti bayar {name}", f"/portal/orders/draft/{draft_id}/payment-proof", data={
                "paid_amount": str(due), "notes": "Transfer BCA", "proof_file": (io.BytesIO(_png()), "bukti-transfer.png")},
                content_type="multipart/form-data")
            attachment = run.q(lambda: DigitalAttachment.query.filter_by(reference_type="PORTAL_ORDER_DRAFT", reference_id=draft_id)
                               .order_by(DigitalAttachment.id.desc()).first().id)
            fin = run.client("admin")
            run.step(fin, "Verifikasi bukti", f"/finance/portal-payment-proofs/{attachment}/decide", data={"decision": "VERIFIED", "notes": "Mutasi BCA cocok"})
            run.step(fin, "Catat uang muka", f"/finance/portal-payment-proofs/{attachment}/record-prepayment", data={
                "payment_date": (day - timedelta(days=1)).isoformat(), "amount": str(due), "payment_method": "TRANSFER",
                "bank_account_id": ref["bca"], "reference_number": f"TRF{attachment:05d}", "notes": "Pesanan portal", "idempotency_key": uuid.uuid4().hex})
            run.step(adm, "Konfirmasi draft", f"/portal/admin/order-drafts/{draft_id}/confirm", data={"review_note": "Pembayaran sudah diterima"})
        else:
            method = "TRANSFER" if name.startswith("Kantor") else "CASH"
            run.step(adm, f"Order umum {name} {day}", "/operational/orders/create", data={
                "order_date": day.isoformat(), "mandor_id": loc["mandor_id"], "delivery_location_id": loc["id"],
                "lunch_qty": qty, "dinner_qty": 0, "notes": "", "prepayment_amount": str(amount), "prepayment_method": method,
                "prepayment_bank_account_id": ref["bca"] if method == "TRANSFER" else "", "prepayment_reference": ""})
        total += qty
    return total


def operate_day(run, plan, ref, day, portions, finish=True):
    from app.models.delivery import Delivery, DeliveryDetail
    from app.models.operational import DailyOrder
    from app.models.production import Production, ProductionDetail

    adm, dapur, antar = run.client("admin"), run.client("dapur"), run.client("pengantar")
    run.travel(at(day, 6, 15))
    order_id = run.q(lambda: DailyOrder.query.filter_by(order_date=day).one().id)
    run.step(adm, f"Kunci order {day}", f"/operational/orders/{order_id}/lock", data={})

    # Snapshot HPP pesanan (menu siang/sore + profil biaya): sumber "Profit
    # Estimasi" dan laporan margin.
    if "hpp" not in ref:
        from app.models.master import Menu, OverheadProfile, PackagingProfile

        ref["hpp"] = run.q(lambda: {
            "lunch_menu_id": Menu.query.filter_by(menu_name="Nasi Ayam Bumbu Kuning").one().id,
            "dinner_menu_id": Menu.query.filter_by(menu_name="Nasi Telur Balado").one().id,
            "packaging_profile_id": PackagingProfile.query.one().id,
            "overhead_profile_id": OverheadProfile.query.one().id,
        })
    run.travel(at(day, 6, 20))
    run.step(adm, f"Snapshot HPP {day}", f"/operational/orders/{order_id}/hpp-snapshot/create", data={
        **ref["hpp"], "target_margin_percentage": "30", "notes": "Menu harian"})

    # Bahan keluar untuk produksi hari ini.
    run.travel(at(day, 7, 0))
    for item, (_unit, per, _price) in INGREDIENTS.items():
        qty = (per * portions).quantize(Decimal("0.01"))
        if item == "Gas LPG 12 kg":
            qty = Decimal(max(1, round(float(per * portions))))
        if qty <= 0:
            continue
        plan.stock[item] -= qty
        run.step(adm, f"Bahan keluar {item}", "/logistics/stock-out", data={
            "item_id": ref["items"][item], "movement_date": day.isoformat(), "qty": str(qty), "usage_purpose": "PRODUKSI"})
    if not finish:
        return  # "hari ini": produksi & pengiriman masih tugas dapur/pengantar

    for kind, hh, mm in (("LUNCH", 10, 5), ("DINNER", 15, 40)):
        run.travel(at(day, hh, mm))
        for production_id in run.q(lambda: [p.id for p in Production.query.filter_by(production_date=day, production_type=kind).all()]):
            planned = run.q(lambda: int(sum(row.planned_qty for row in ProductionDetail.query.filter_by(production_id=production_id).all())))
            run.step(dapur, f"Realisasi {kind} {day}", f"/production/{production_id}/realization",
                     data={"actual_qty": planned, "status": "COMPLETED", "notes": ""})

    for kind, (go_h, go_m), (rx_h, rx_m) in (("LUNCH", (10, 40), (11, 20)), ("DINNER", (16, 35), (17, 15))):
        run.travel(at(day, go_h, go_m - 10))
        run.step(antar, f"Buat pengiriman {kind}", f"/delivery/create-from-order/{order_id}/{kind}", data={})
        delivery_id = run.q(lambda: (lambda row: row and row.id)(
            Delivery.query.filter(Delivery.delivery_date == day, Delivery.notes.like(f"delivery_type={kind};%")).first()))
        if not delivery_id:
            continue
        run.travel(at(day, go_h, go_m))
        run.step(antar, f"Berangkat {kind}", f"/delivery/{delivery_id}/dispatch", data={})
        details = run.q(lambda: [(row.id, int(row.planned_qty or 0)) for row in DeliveryDetail.query.filter_by(delivery_id=delivery_id).all()])
        for index, (detail_id, planned) in enumerate(details):
            late = plan.rng.random() < 0.06
            minute = rx_m + index * 7 + (45 if late else 0)
            run.travel(at(day, rx_h + minute // 60, minute % 60))
            short = plan.rng.choice((1, 2)) if plan.rng.random() < 0.05 else 0
            run.step(antar, f"Terima {kind}", f"/delivery/details/{detail_id}/receive", data={
                "delivered_qty": planned - short, "receiver_name": plan.rng.choice(("Pak Satpam", "Mandor", "Bu Admin Site", "Staf Gudang")),
                "notes": "Porsi kurang, box rusak di jalan" if short else ""},
                expect=("success", "info", "warning"))


def warung_day(run, plan, ref, day):
    from app.models.master import Worker

    adm = run.client("admin")
    for hh, method in ((12, "CASH"), (16, "QRIS" if day.weekday() % 2 == 0 else "CASH")):
        run.travel(at(day, hh, plan.rng.randint(5, 50)))
        cart = []
        for name, (_unit, _buy, sell) in WARUNG.items():
            qty = plan.rng.randint(2, 7)
            if plan.stock[name] - qty < 20:
                continue
            plan.stock[name] -= qty
            cart.append({"item_id": ref["items"][name], "item_name": name, "qty": qty, "price": sell, "is_custom": False})
        if cart:
            run.step(adm, f"Warung {method}", "/canteen/quick", data={
                "buyer_type": "GENERAL_BUYER", "payment_method": method, "sale_type": method,
                "cash_bank_account_id": ref["bca"] if method == "QRIS" else "", "cart_json": json.dumps(cart), "notes": "Penjualan warung"})
    if day.weekday() == 4:  # Jumat: pekerja ngutang
        run.travel(at(day, 17, 30))
        workers = run.q(lambda: [w.id for w in Worker.query.all()])
        for worker_id in plan.rng.sample(workers, 2):
            cart = [{"item_id": ref["items"]["Mi Instan"], "item_name": "Mi Instan", "qty": 3, "price": 5000, "is_custom": False},
                    {"item_id": ref["items"]["Kopi Sachet"], "item_name": "Kopi Sachet", "qty": 4, "price": 3000, "is_custom": False}]
            plan.stock["Mi Instan"] -= 3
            plan.stock["Kopi Sachet"] -= 4
            run.step(adm, "Warung hutang pekerja", "/canteen/quick", data={
                "buyer_type": "REGISTERED_WORKER", "worker_id": worker_id, "payment_method": "DEBT", "sale_type": "DEBT",
                "cart_json": json.dumps(cart), "notes": "Kasbon pekerja"})
    daily_cash(run, ref, day)


def daily_cash(run, ref, day):
    """Tutup kas warung harian: saldo awal = saldo akhir kemarin, hitung fisik di laci."""
    from app.services.daily_cash_service import build_reference_totals, get_last_closing_balance

    run.travel(at(day, 20, 30))
    totals = run.q(lambda: build_reference_totals(ref["branch_id"], day))
    opening = run.q(lambda: get_last_closing_balance(ref["branch_id"], day)) or 0
    closing = float(opening) + float(totals["cash_sales_total"]) + float(totals["debt_payment_total"])
    # Sesekali laci kurang uang kembalian Rp 2.000 (tercatat sebagai selisih).
    actual = closing - (2000 if day.day % 9 == 0 else 0)
    run.step(run.client("admin"), "Tutup kas warung", "/finance/daily-cash", data={
        "cash_date": day.isoformat(), "opening_balance": f"{float(opening):.0f}",
        "cash_sales": f"{float(totals['cash_sales_total']):.0f}", "debt_payments": f"{float(totals['debt_payment_total']):.0f}",
        "other_income": "0", "expenses": "0", "actual_cash": f"{actual:.0f}", "status": "CLOSED",
        "notes": "Selisih uang kembalian" if actual != closing else "Cocok dengan hitung fisik"})


def purchase_day(run, plan, ref, day, upcoming_portions):
    """Senin & Kamis: belanja bahan untuk 3-4 hari ke depan + stok warung."""
    adm = run.client("admin")
    run.travel(at(day, 8, 0))
    need = {}
    for item, (_unit, per, _price) in INGREDIENTS.items():
        target = per * upcoming_portions * Decimal("1.25")
        if item == "Box Nasi":
            target = Decimal(upcoming_portions) * Decimal("1.3")
        gap = target - plan.stock[item]
        if gap > 0:
            need[item] = gap
    groups = (
        ("Toko Sumber Rejeki", "CREDIT", ("Beras", "Telur Ayam", "Minyak Goreng")),
        (None, "BANK", ("Ayam Potong",)),
        ("Agen Gas Makmur", "CREDIT", ("Gas LPG 12 kg",)),
        ("CV Kemasan Jaya", "CREDIT", ("Box Nasi",)),
    )
    for supplier, mode, names in groups:
        rows = [(name, need[name]) for name in names if name in need]
        if not rows:
            continue
        item_ids, qtys, prices = [], [], []
        for name, gap in rows:
            unit_price = INGREDIENTS[name][2] + plan.rng.choice((0, 0, 250, 500, -250))
            qty = gap.quantize(Decimal("1"), rounding="ROUND_UP")
            if name == "Box Nasi":
                qty = (qty / 500).quantize(Decimal("1"), rounding="ROUND_UP") * 500
            plan.stock[name] += qty
            item_ids.append(str(ref["items"][name]))
            qtys.append(str(qty))
            prices.append(str(unit_price))
        data = {"procurement_date": day.isoformat(), "item_id[]": item_ids, "qty[]": qtys, "unit_price[]": prices}
        if mode == "CREDIT":
            terms = {"Toko Sumber Rejeki": 14, "Agen Gas Makmur": 7, "CV Kemasan Jaya": 30}[supplier]
            data.update({"purchase_type": "CREDIT", "supplier_id": str(ref["suppliers"][supplier]),
                         "supplier_bill_due_date": (day + timedelta(days=terms)).isoformat(), "purchase_place": supplier})
        else:
            data.update({"purchase_type": "CASH", "payment_account_type": "BANK", "bank_account_id": str(ref["bca"]),
                         "purchase_place": "Pasar Simpang Tiga"})
        run.step(adm, f"Belanja {supplier or 'pasar'} {day}", "/logistics/purchases/create", data=data)

    if day.weekday() == 0:  # stok warung seminggu sekali, tunai
        rows = [(name, 120) for name in WARUNG if plan.stock[name] < 140]
        if rows:
            for name, qty in rows:
                plan.stock[name] += qty
            run.step(adm, "Belanja stok warung", "/logistics/purchases/create", data={
                "procurement_date": day.isoformat(), "purchase_type": "CASH", "payment_account_type": "CASH",
                "purchase_place": "Grosir Sinar Jaya",
                "item_id[]": [str(ref["items"][n]) for n, _ in rows], "qty[]": [str(q) for _, q in rows],
                "unit_price[]": [str(WARUNG[n][1]) for n, _ in rows]})


def pay_due_supplier_bills(run, ref, day):
    from app.models.finance import SupplierBill

    rows = run.q(lambda: [(b.id, b.bill_number, int(b.remaining_amount or 0)) for b in SupplierBill.query.filter(
        SupplierBill.due_date <= day, SupplierBill.remaining_amount > 0).all()])
    if not rows:
        return
    own = run.client("admin")
    run.travel(at(day, 14, 0))
    for bill_id, number, remaining in rows:
        run.step(own, f"Bayar hutang {number}", f"/finance/supplier-bills/{bill_id}/payments/create", data={
            "idempotency_key": uuid.uuid4().hex, "payment_date": day.isoformat(), "payment_method": "TRANSFER",
            "bank_account_id": ref["bca"], "amount": str(remaining), "notes": "Pelunasan sesuai jatuh tempo"})


def month_end(run, ref, month_last_day):
    """Gaji, penyusutan, listrik/air untuk bulan yang berakhir."""
    from app.models.accounting import FixedAsset, FixedAssetDepreciationConfig
    from app.models.hr import Payroll
    from app.services.fixed_asset_depreciation_service import ASSET_CATEGORY_ACCUMULATED_ACCOUNT

    run.stage = f"Tutup bulan {month_last_day:%m-%Y}"
    own, adm = run.client("owner"), run.client("admin")
    run.travel(at(month_last_day, 15, 0))
    for category, amount, vendor in (("ELECTRICITY", "2450000", "PLN"), ("WATER", "620000", "PDAM Tirta Bhagasasi")):
        run.step(adm, f"Biaya {category}", "/finance/operational-expenses/create", data={
            "expense_date": month_last_day.isoformat(), "expense_category": category, "amount": amount,
            "payment_method": "TRANSFER", "bank_account_id": ref["bca"], "vendor_name": vendor,
            "reference_number": f"{category[:3]}-{month_last_day:%y%m}", "notes": f"Tagihan {month_last_day:%B %Y}"})
    run.step(adm, "Biaya admin bank", "/finance/cash-bank-adjustments", data={
        "adjustment_date": month_last_day.isoformat(), "account_type": "BANK", "bank_account_id": ref["bca"],
        "adjustment_category": "BIAYA_BANK", "adjustment_type": "DECREASE", "amount": "12500", "reason": "Biaya administrasi bulanan"})

    run.travel(at(month_last_day, 16, 0))
    run.step(own, "Buat payroll", "/hr/payrolls/generate", data={"period_month": month_last_day.month, "period_year": month_last_day.year})
    payroll_id = run.q(lambda: Payroll.query.filter_by(period_month=month_last_day.month, period_year=month_last_day.year).one().id)
    run.step(own, "Final payroll", f"/hr/payrolls/{payroll_id}/finalize", data={})
    run.step(own, "Jurnal payroll", f"/hr/payrolls/{payroll_id}/post-journal", data={})

    assets = run.q(lambda: [(a.id, str(a.asset_category or "OTHER").upper(),
                             FixedAssetDepreciationConfig.query.filter_by(fixed_asset_id=a.id).first() is not None)
                            for a in FixedAsset.query.all()])
    for asset_id, category, configured in assets:
        if not configured:
            run.step(own, f"Atur penyusutan aset #{asset_id}", f"/finance/fixed-asset-depreciation/{asset_id}/configure", data={
                "depreciation_start_date": OPEN_DATE.isoformat(), "useful_life_months": "96" if category == "VEHICLE" else "60",
                "residual_value": "0", "accumulated_account_code": ASSET_CATEGORY_ACCUMULATED_ACCOUNT.get(category, "2101"),
                "status": "CONFIGURED", "notes": "Garis lurus"})
        run.step(own, f"Penyusutan aset #{asset_id}", f"/finance/fixed-asset-depreciation/{asset_id}/post", data={
            "period_month": month_last_day.month, "period_year": month_last_day.year})
    return payroll_id


def pay_payroll(run, ref, payroll_id, day):
    run.travel(at(day, 9, 0))
    run.step(run.client("owner"), "Bayar gaji", f"/hr/payrolls/{payroll_id}/pay", data={"payment_method": "TRANSFER", "bank_account_id": ref["bca"]})


def bill_month(run, ref, first, last, bill_day):
    from app.models.master import ClientPic, Mandor

    run.stage = f"Tagihan {first:%m-%Y}"
    adm = run.client("admin")
    run.travel(at(bill_day, 9, 30))
    for _client, _code, mandor, _loc, _l, _d in CONTRACT_SITES:
        if mandor == "Mandor Hendra" and last < BUMI_START:
            continue
        mandor_id = ref["mandors"][mandor]
        pic = run.q(lambda: ClientPic.query.filter_by(client_id=Mandor.query.get(mandor_id).client_id, is_active=True).first().id)
        run.step(adm, f"Invoice {mandor} {first:%m}", "/finance/invoices/generate-period/save", data={
            "mandor_id": mandor_id, "client_pic_id": pic, "period_start": first.isoformat(), "period_end": last.isoformat()})


def receive_payment(run, ref, day, mandor, fraction, method="TRANSFER", source="PERIOD_INVOICE", note=""):
    from app.models.finance import Invoice

    run.travel(at(day, 13, 20))
    mandor_id = ref["mandors"][mandor] if mandor else None

    def find():
        query = Invoice.query.filter(Invoice.remaining_amount > 0)
        query = query.filter_by(mandor_id=mandor_id, source_type=source) if mandor_id else query.filter_by(source_type=source)
        row = query.order_by(Invoice.invoice_date.asc(), Invoice.id.asc()).first()
        return row and (row.id, row.invoice_number, int(row.remaining_amount))
    found = run.q(find)
    if not found:
        return
    invoice_id, number, remaining = found
    amount = remaining if fraction >= 1 else int(remaining * fraction / 1000) * 1000
    run.step(run.client("admin"), f"Pembayaran {number}", f"/finance/invoices/{invoice_id}/payments/create", data={
        "idempotency_key": uuid.uuid4().hex, "payment_date": day.isoformat(), "payment_method": method,
        "bank_account_id": ref["bca"] if method == "TRANSFER" else "", "amount": str(amount), "notes": note})


def special_events(run, ref, day, plan):
    """Kejadian sekali waktu supaya setiap modul punya isi."""
    own, adm = run.client("owner"), run.client("admin")
    if day == d(2026, 9, 7):
        run.travel(at(day, 16, 30))
        run.step(adm, "Setor kas ke bank", "/finance/cash-bank-transfers", data={
            "transfer_date": day.isoformat(), "from_account_type": "CASH", "to_account_type": "BANK", "to_bank_account_id": ref["bca"],
            "amount": "2000000", "reference_number": "SETOR-0907", "notes": "Setor kelebihan kas ke BCA"})
    if day == d(2026, 9, 8):
        request_items(run, ref, day, plan, (("Beras", "5"), ("Telur Ayam", "2")), fulfill=True)
    if day == d(2026, 9, 11):
        run.travel(at(day, 13, 10))
        cart = [{"item_id": ref["items"]["Kopi Sachet"], "item_name": "Kopi Sachet", "qty": 6, "price": 3000, "is_custom": False},
                {"item_id": ref["items"]["Mi Instan"], "item_name": "Mi Instan", "qty": 2, "price": 5000, "is_custom": False}]
        plan.stock["Kopi Sachet"] -= 6
        plan.stock["Mi Instan"] -= 2
        run.step(adm, "Bon warung pembeli luar", "/canteen/quick", data={
            "buyer_type": "EXTERNAL_COMPANY_WORKER", "buyer_name": "Pak Rudi", "buyer_company": "CV Las Mandiri",
            "buyer_phone": "0812-3333-4444", "payment_method": "DEBT", "sale_type": "DEBT", "cart_json": json.dumps(cart),
            "notes": "Tukang las proyek sebelah, bayar akhir bulan"})
    if day == d(2026, 9, 16):
        run.travel(at(day, 8, 15))
        plan.stock["Telur Ayam"] -= Decimal("0.5")
        run.step(adm, "Barang rusak", "/logistics/damaged/create", data={
            "item_id": ref["items"]["Telur Ayam"], "movement_date": day.isoformat(), "qty": "0.5",
            "damage_reason": "Pecah saat bongkar", "damage_location": "Gudang dapur", "notes": "1 tray jatuh"})
    if day == d(2026, 9, 17):
        field_expense(run, day, "KITCHEN_OPERATION_EXPENSE", "185000", "Toko Plastik Jaya", "Plastik wrap & es batu", post=True)
    if day == d(2026, 9, 25):
        from app.models.canteen import CanteenExternalReceivable

        receivable = run.q(lambda: (lambda r: r and (r.id, int(r.remaining_amount)))(CanteenExternalReceivable.query.first()))
        if receivable:
            run.travel(at(day, 16, 0))
            run.step(adm, "Pelunasan bon warung", f"/canteen/external-receivables/{receivable[0]}/payment", data={
                "payment_date": day.isoformat(), "amount": str(receivable[1]), "payment_method": "CASH", "notes": "Lunas"})
    if day == d(2026, 8, 4):
        run.travel(at(day, 10, 0))
        from app.models.finance import SupplierBill

        old_bill = run.q(lambda: SupplierBill.query.filter_by(procurement_id=None).first().id)
        run.step(adm, "Bayar hutang lama", f"/finance/supplier-bills/{old_bill}/payments/create", data={
            "idempotency_key": uuid.uuid4().hex, "payment_date": day.isoformat(), "payment_method": "TRANSFER",
            "bank_account_id": ref["bca"], "amount": "3200000", "notes": f"Pelunasan hutang {MONTHS_ID[(OPEN_DATE - timedelta(days=1)).month - 1]}"})
    if day == d(2026, 8, 12):
        receive_payment(run, ref, day, None, 1, source="OPENING_BALANCE", note="Pelunasan nota NT-0712")
    if day == d(2026, 8, 20):
        run.travel(at(day, 11, 0))
        run.step(own, "Beli freezer", "/finance/fixed-asset-purchases/create", data={
            "purchase_date": day.isoformat(), "asset_mode": "NEW", "asset_name": "Freezer box 500 L", "asset_category": "KITCHEN_EQUIPMENT",
            "asset_account_code": "1101", "amount": "12500000", "residual_value": "500000", "useful_life_years": "5",
            "payment_method": "BANK", "bank_account_id": ref["bca"], "vendor_name": "Toko Elektronik Sentosa",
            "reference_number": "INV-SNT-0820", "notes": "Penyimpanan ayam & sayur"})
    if day == d(2026, 9, 3):
        receive_payment(run, ref, day, None, 1, source="OPENING_BALANCE", note="Pelunasan nota NT-0688")
    if day == d(2026, 9, 10):
        run.travel(at(day, 15, 0))
        customer = run.client("portal.customer.local")
        run.step(customer, "Komplain portal", "/portal/customer/complaints", data={
            "category": "LATE_DELIVERY", "title": "Pesanan datang terlambat",
            "description": f"Pesanan tanggal {tanggal(day - timedelta(days=1))} tiba pukul 12.10, padahal jam makan siang 11.30."})
    if day == d(2026, 9, 15):
        run.travel(at(day, 16, 0))
        run.step(own, "Prive pemilik", "/finance/owner-capital", data={
            "transaction_date": day.isoformat(), "kind": "TARIK", "account_type": "BANK", "bank_account_id": ref["bca"],
            "amount": "2500000", "notes": "Keperluan pribadi"})
    if day == d(2026, 9, 22):
        run.travel(at(day, 14, 0))
        run.step(adm, "Komplain PT Sinar", "/customer-success/complaints", data={
            "client_id": ref["clients"]["PT Sinar Beton Utama"], "mandor_id": ref["mandors"]["Mandor Asep"],
            "category": "PORTION_SHORTAGE", "title": "Kurang 2 porsi makan siang",
            "description": "Pengiriman siang ke batching plant kurang 2 porsi, box penyok."})
    if day == d(2026, 9, 5):
        run.travel(at(day, 10, 0))
        run.step(own, "Kontrak cicilan mobil", "/finance/fixed-asset-installments/create", data={
            "contract_date": day.isoformat(), "asset_mode": "NEW", "asset_name": "Mobil pickup Grand Max", "asset_category": "VEHICLE",
            "asset_account_code": "1102", "liability_account_code": "2001", "interest_expense_account_code": "5008",
            "admin_expense_account_code": "5008", "financing_provider": "BCA Finance", "vendor_name": "Dealer Daihatsu Kayuagung",
            "principal_amount": "96000000", "total_interest_amount": "7680000", "total_admin_amount": "1500000",
            "installment_count": "24", "first_due_date": d(2026, 10, 1).isoformat(), "notes": "DP dibayar dealer terpisah"})


def request_items(run, ref, day, plan, lines, fulfill):
    """Dapur minta barang ke gudang; admin menyetujui dan (opsional) menyerahkan."""
    from app.models.logistics import ItemRequest

    run.travel(at(day, 7, 40))
    run.step(run.client("dapur"), f"Permintaan barang {day}", "/logistics/item-requests/create", data={
        "request_date": day.isoformat(), "purpose": "Kebutuhan produksi sore", "notes": "Tambahan untuk masak sore",
        "item_id[]": [ref["items"][name] for name, _ in lines], "requested_qty[]": [qty for _, qty in lines],
        "detail_notes[]": ["" for _ in lines]})
    if not fulfill:
        return
    request_id = run.q(lambda: ItemRequest.query.order_by(ItemRequest.id.desc()).first().id)
    adm = run.client("admin")
    run.travel(at(day, 8, 0))
    run.step(adm, "Setujui permintaan", f"/logistics/item-requests/{request_id}/approve", data={"owner_note": "Silakan ambil"})
    run.travel(at(day, 8, 10))
    run.step(adm, "Serahkan barang", f"/logistics/item-requests/{request_id}/fulfill", data={
        "fulfill_note": "Diambil Bu Tini", "idempotency_key": uuid.uuid4().hex})
    for name, qty in lines:
        plan.stock[name] -= Decimal(qty)


def field_expense(run, day, event_type, amount, party, notes, post):
    """Transaksi lapangan tunai: dicatat, diperiksa, lalu (opsional) dijurnal."""
    from app.models.field_transaction import FieldTransaction

    adm = run.client("admin")
    run.travel(at(day, 14, 20))
    run.step(adm, f"Transaksi lapangan {notes}", "/field-transactions/create", data={
        "business_event_type": event_type, "transaction_direction": "OUT", "transaction_date": day.isoformat(),
        "entry_date": day.isoformat(), "amount": amount, "payment_method": "CASH", "field_channel": "MANUAL",
        "site_location": "Dapur Air Sugihan", "party_snapshot_name": party, "notes": notes})
    if not post:
        return
    transaction_id = run.q(lambda: FieldTransaction.query.order_by(FieldTransaction.id.desc()).first().id)
    run.travel(at(day, 16, 45))
    run.step(adm, "Transaksi lapangan siap dijurnal", f"/field-transactions/{transaction_id}/review-status", data={
        "to_review_status": "READY_TO_POST", "note": "Nota lengkap"})
    run.step(adm, "Jurnal transaksi lapangan", f"/field-transactions/{transaction_id}/post", data={})


def stage_operations(run, ref):
    from app.models.accounting import AssetFinancingContract, AssetInstallmentSchedule

    plan = Plan()
    days = list(op_days())
    payrolls = {}
    for index, day in enumerate(days):
        run.stage = f"Operasi {day}"
        # Sesi dibuat SESUDAH jam simulasi diatur: cookie yang ditandatangani di
        # "masa depan" ditolak (itsdangerous: umur tanda tangan < 0).
        run.travel(at(day - timedelta(days=1), 19, 0))
        adm = run.client("admin")
        portions = place_contract_orders(run, plan, ref, day, adm)
        portions += place_general_orders(run, plan, ref, day, adm)

        if day.weekday() in (0, 3):
            upcoming = portions * (3 if day.weekday() == 0 else 4)
            purchase_day(run, plan, ref, day, upcoming)
        operate_day(run, plan, ref, day, portions)
        warung_day(run, plan, ref, day)
        pay_due_supplier_bills(run, ref, day)
        special_events(run, ref, day, plan)

        if day.weekday() == 0:  # BBM mingguan
            run.travel(at(day, 17, 0))
            run.step(adm, "BBM mingguan", "/finance/transport-expenses/create", data={
                "expense_date": day.isoformat(), "expense_type": "VEHICLE_FUEL", "amount": str(plan.rng.choice((350000, 400000, 425000))),
                "payment_method": "CASH", "vehicle_label": "BG 8123 OK", "vendor_name": "SPBU Simpang Tiga", "notes": "BBM pengiriman"})

        # Bulan berjalan (hari terakhir data) belum ditutup: gaji, penyusutan,
        # listrik/air baru dicatat setelah bulannya berakhir.
        next_day = days[index + 1] if index + 1 < len(days) else None
        if next_day is not None and next_day.month != day.month:
            payrolls[day.month] = month_end(run, ref, day)

        # Hari kerja pertama bulan baru: tagihan bulan lalu, gaji bulan lalu dibayar.
        if index and days[index - 1].month != day.month:
            prev_first = date(days[index - 1].year, days[index - 1].month, 1)
            bill_month(run, ref, prev_first, days[index - 1], day)
            pay_payroll(run, ref, payrolls[days[index - 1].month], day)

        # Pembayaran pelanggan kontrak untuk tagihan bulan-bulan sebelumnya.
        for when, mandor, fraction, method in (
            (d(2026, 9, 14), "Mandor Budi", 1, "TRANSFER"), (d(2026, 9, 18), "Mandor Joko", 0.5, "TRANSFER"),
            (d(2026, 9, 28), "Mandor Joko", 1, "CASH"), (d(2026, 9, 29), "Mandor Asep", 1, "TRANSFER"),
            (d(2026, 10, 2), "Mandor Budi", 0.6, "TRANSFER"),
        ):
            if day == when:
                receive_payment(run, ref, day, mandor, fraction, method, note="Pembayaran tagihan bulanan")

        if day == d(2026, 9, 30):  # kasbon pekerja dibayar akhir bulan
            from app.models.canteen import WorkerDebt

            run.travel(at(day, 17, 45))
            open_debts = lambda: [(d.id, int(d.debt_amount) - int(sum(p.amount for p in d.payments)))
                                  for d in WorkerDebt.query.filter(WorkerDebt.status != "PAID").all()]
            for debt_id, remaining in [row for row in run.q(open_debts) if row[1] > 0][:4]:
                run.step(adm, "Bayar kasbon", f"/canteen/debts/{debt_id}/payment", data={
                    "payment_date": day.isoformat(), "amount": str(remaining), "payment_method": "CASH", "notes": "Potong upah mingguan"})
        if day == d(2026, 10, 1):
            schedule = run.q(lambda: (lambda c: c and (c.id, AssetInstallmentSchedule.query.filter_by(contract_id=c.id).order_by(AssetInstallmentSchedule.installment_no).first().id))(
                AssetFinancingContract.query.first()))
            if schedule:
                run.travel(at(day, 11, 0))
                run.step(run.client("owner"), "Cicilan pertama mobil", f"/finance/fixed-asset-installments/{schedule[0]}/pay/{schedule[1]}", data={
                    "payment_date": day.isoformat(), "payment_method": "BANK", "bank_account_id": ref["bca"], "reference_number": "BCAF-0001", "notes": "Cicilan ke-1"})
        if index % 10 == 0:
            print(f"  {day}: {portions} porsi, {len(run.failures)} langkah gagal sejauh ini")
    run.stop_clock()
    return plan


def next_op_day(day):
    day += timedelta(days=1)
    while day.weekday() == 6 or day in HOLIDAYS:
        day += timedelta(days=1)
    return day


def stage_today(run, ref, plan):
    """Keadaan 'hari ini': pesanan hari ini dikunci (produksi & pengiriman belum),
    pesanan hari kerja berikutnya + draf portal menunggu, kontrak diperiksa."""
    from app.models.master import DeliveryLocation

    run.stage = "Hari ini"
    if NOW_DAY.weekday() != 6 and NOW_DAY not in HOLIDAYS:
        run.travel(at(NOW_DAY - timedelta(days=1), 19, 0))
        adm = run.client("admin")
        portions = place_contract_orders(run, plan, ref, NOW_DAY, adm)
        portions += place_general_orders(run, plan, ref, NOW_DAY, adm)
        operate_day(run, plan, ref, NOW_DAY, portions, finish=False)

    run.travel(at(NOW_DAY, 8, 30))
    adm = run.client("admin")
    monday = next_op_day(NOW_DAY)  # hari kerja berikutnya
    for _client, _code, mandor, location, lunch, dinner in CONTRACT_SITES[1:]:
        loc = run.q(lambda: DeliveryLocation.query.filter_by(location_name=location).one().id)
        run.step(adm, f"Order berikutnya {location}", "/operational/orders/create", data={
            "order_date": monday.isoformat(), "mandor_id": ref["mandors"][mandor], "delivery_location_id": loc,
            "lunch_qty": lunch, "dinner_qty": dinner, "notes": ""})
    budi = run.client("portal.mandor.local")
    tol = run.q(lambda: DeliveryLocation.query.filter_by(location_name="Proyek Perluasan Mill").one().id)
    for meal, qty in (("LUNCH", 62), ("DINNER", 44)):
        page = budi.get("/portal/orders/draft").get_data(as_text=True)
        key = re.search(r'name="idempotency_key" value="([^"]+)"', page)
        run.step(budi, f"Draft Mandor Budi {meal}", "/portal/orders/draft", data={
            "idempotency_key": key.group(1) if key else uuid.uuid4().hex, "order_date": monday.isoformat(), "meal_type": meal,
            "delivery_location_id": tol, "portion_qty": qty, "delivery_time": "11:30" if meal == "LUNCH" else "17:30",
            "contact_name": "Mandor Budi", "contact_phone": "0813-5500-1200", "notes": "Tambah sambal terpisah"})
    rina = run.client("portal.customer.local")
    rumah = run.q(lambda: DeliveryLocation.query.filter_by(location_name="Rumah Bu Rina").one().id)
    page = rina.get("/portal/orders/draft").get_data(as_text=True)
    key = re.search(r'name="idempotency_key" value="([^"]+)"', page)
    run.step(rina, "Draft Ibu Rina (belum bayar)", "/portal/orders/draft", data={
        "idempotency_key": key.group(1) if key else uuid.uuid4().hex, "order_date": next_op_day(next_op_day(monday)).isoformat(),
        "meal_type": "LUNCH", "delivery_location_id": rumah, "portion_qty": 18, "delivery_time": "11:30",
        "contact_name": "Ibu Rina", "contact_phone": "0815-7000-0000", "notes": "Arisan keluarga"})
    run.step(adm, "Periksa kontrak", "/customer-success/contracts/check")
    # Antrean hari ini: permintaan barang menunggu persetujuan, nota lapangan menunggu diperiksa.
    if NOW_DAY.weekday() != 6:
        request_items(run, ref, NOW_DAY, plan, (("Minyak Goreng", "2"),), fulfill=False)
    field_expense(run, NOW_DAY, "SITE_OPERATION_EXPENSE", "75000", "Warung Bu Darmi", "Air galon untuk pekerja proyek", post=False)
    stage_extras(run, ref, monday)
    stage_partnerships(run)
    run.stop_clock()


def stage_extras(run, ref, next_day):
    """Modul yang tidak tersentuh operasi harian: kredit, koreksi saldo awal,
    rekap manual dari buku, piutang/hutang manual lapangan, revisi order,
    dan tutup buku bulan pertama."""
    from calendar import monthrange

    from app.models.credit import CreditAccount
    from app.models.field_transaction import FieldTransaction, ManualPayable, ManualReceivable
    from app.models.finance import ManualBillingBatch
    from app.models.operational import DailyOrder, DailyOrderDetail
    from app.models.master import DeliveryLocation

    run.stage = "Modul lain"
    guard = {"sensitive_action_confirmed": "1", "confirm_password": OWNER_PASSWORD}

    # Kontrol kredit: syarat kredit dua mandor, deposit jaminan, status pantau.
    run.travel(at(NOW_DAY, 9, 5))
    own = run.client("owner")
    run.step(own, "Syarat kredit Mandor Asep", f"/credit/sub-client/{ref['mandors']['Mandor Asep']}/settings", data={
        "billing_mode": "VIA_CLIENT", "credit_limit": "0", "payment_terms_days": "30", "deposit_percent": "0",
        "notes": "Mandor batching plant, tagihan lewat PT Sinar"})
    # Mandor Hendra mulai ditagih langsung (kredit pribadi) dengan deposit jaminan.
    run.step(own, "Syarat kredit langsung Mandor Hendra", f"/credit/sub-client/{ref['mandors']['Mandor Hendra']}/settings", data={
        "billing_mode": "DIRECT", "credit_limit": "15000000", "payment_terms_days": "14", "deposit_percent": "10",
        "id_number": "1602031204850007", "address": "Desa Simpang Tiga, Kec. Air Sugihan, OKI",
        "guarantor_name": "Sutini (istri)", "guarantor_phone": "0813-6700-9921", "guarantor_id_number": "1602034408880002",
        "notes": "Order tambahan di luar kontrak PT Bumi ditagih langsung"})
    hendra = run.q(lambda: CreditAccount.query.filter_by(party_id=ref["mandors"]["Mandor Hendra"]).first().id)
    run.step(run.client("admin"), "Deposit jaminan Mandor Hendra", f"/credit/accounts/{hendra}/deposit", data={
        "amount": "1500000", "deposit_date": NOW_DAY.isoformat(), "payment_method": "TRANSFER",
        "bank_account_id": ref["mandiri"], "reference_number": "TRF-HENDRA-01", "notes": "Deposit 10% dari limit"})
    asep = run.q(lambda: CreditAccount.query.filter_by(party_id=ref["mandors"]["Mandor Asep"]).first().id)
    run.step(own, "Status kredit Mandor Asep dipantau", f"/credit/accounts/{asep}/status", data={
        "status": "PANTAU", "reason": "Invoice September PT Sinar belum dibayar, pantau sampai jatuh tempo."})

    # Koreksi saldo awal: nota lama yang tercecer.
    run.step(own, "Koreksi saldo awal: nota lama PT Sinar", "/accounting/opening-balance/receivables/add", data={
        "client_id": ref["clients"]["PT Sinar Beton Utama"], "reference": "NT-0705",
        "invoice_date": (OPEN_DATE - timedelta(days=20)).isoformat(), "amount": "850000",
        "reason": "Nota lama ketemu di map arsip, belum tercatat saat saldo awal"})

    # Rekap manual dari buku: tamu luar sistem, dikunci lalu jadi invoice.
    adm = run.client("admin")
    for label, bill_to, name, phone, start_days, span, lunch, void in (
            ("Bengkel Las Harun", "PERORANGAN", "Pak Harun (Bengkel Las Harun)", "0812-7344-1020", 20, 5, 8, False),
            ("Rombongan survei lahan", "KELOMPOK", "Rombongan Survei Lahan PT Rawa", "0813-7788-2001", 10, 2, 12, True)):
        start = NOW_DAY - timedelta(days=start_days)
        dates = [start + timedelta(days=i) for i in range(span)]
        run.step(adm, f"Rekap buku {label}", "/finance/manual-billing/input-buku", data={
            "bill_to_type": bill_to, "bill_to_name_snapshot": name, "bill_to_phone_snapshot": phone,
            "bill_to_address_snapshot": "Simpang Tiga, Air Sugihan", "bill_to_notes": "Dicatat di buku kas dapur",
            "period_start": dates[0].isoformat(), "period_end": dates[-1].isoformat(), "notes": f"Rekap buku {label}",
            "catering_date[]": [x.isoformat() for x in dates], "catering_breakfast_qty[]": ["0"] * span,
            "catering_lunch_qty[]": [str(lunch)] * span, "catering_dinner_qty[]": ["0"] * span,
            "catering_unit_price[]": ["18000"] * span, "catering_note[]": [""] * span,
            "warung_worker_name[]": [], "warung_amount[]": [], "warung_note[]": []})
        batch = run.q(lambda: ManualBillingBatch.query.filter_by(bill_to_name_snapshot=name).order_by(ManualBillingBatch.id.desc()).first().id)
        run.step(adm, f"Kunci rekap {label}", f"/finance/manual-billing/batches/{batch}/lock", data={})
        if void:
            # Batal setelah dikunci butuh persetujuan OWNER (maker-checker): menunggu di Persetujuan.
            run.step(adm, f"Ajukan batal rekap {label}", f"/finance/manual-billing/batches/{batch}/void", data={
                "void_reason": "Rombongan ternyata dibayar tunai di tempat, tercatat dobel"})
        else:
            run.step(adm, f"Invoice dari rekap {label}", f"/finance/manual-billing/batches/{batch}/create-invoice", data={
                "notes": "Tagihan dari rekap buku"})

    # Piutang & hutang manual dari lapangan, dengan pelunasan.
    for event, direction, party, phone, amount, days_ago, doc, pay_days, pay_amount, note in (
            ("MANUAL_RECEIVABLE_CREATED", "IN", "Koperasi Karyawan Sektor 2", "0812-7000-5511", "450000", 12, "receivable", 5, "200000",
             "Nasi kotak rapat koperasi, bayar akhir bulan"),
            ("UNFORMAL_VENDOR_PAYABLE", "OUT", "Pak Darto (sayur keliling)", "0813-6700-4421", "380000", 6, "payable", 4, "380000",
             "Sayur & cabai bon, bayar Jumat")):
        day = NOW_DAY - timedelta(days=days_ago)
        run.travel(at(day, 15, 10))
        adm = run.client("admin")
        run.step(adm, f"Lapangan: {party}", "/field-transactions/create", data={
            "business_event_type": event, "transaction_direction": direction, "transaction_date": day.isoformat(),
            "entry_date": day.isoformat(), "amount": amount, "field_channel": "MANUAL", "site_location": "Dapur Air Sugihan",
            "party_snapshot_name": party, "party_snapshot_phone": phone, "register_counterparty": "1",
            "new_counterparty_type": "LAINNYA", "notes": note})
        ft = run.q(lambda: FieldTransaction.query.filter_by(party_snapshot_name=party).order_by(FieldTransaction.id.desc()).first().id)
        run.step(adm, f"Dokumen {doc} manual {party}", f"/field-transactions/{ft}/manual-{doc}/create", data={
            "due_date": (day + timedelta(days=14)).isoformat(), "notes": note})
        model = ManualReceivable if doc == "receivable" else ManualPayable
        doc_id = run.q(lambda: model.query.filter_by(field_transaction_id=ft).one().id)
        pay_day = day + timedelta(days=pay_days)
        run.travel(at(pay_day, 10, 30))
        run.step(run.client("admin"), f"Bayar {doc} manual {party}", f"/field-transactions/manual-{doc}s/{doc_id}/payments/create", data={
            "payment_date": pay_day.isoformat(), "payment_method": "CASH", "amount": pay_amount, "notes": "Dibayar tunai"})

    # Revisi order: mandor minta tambah porsi lewat WhatsApp.
    run.travel(at(NOW_DAY, 11, 15))
    detail_id = run.q(lambda: (DailyOrderDetail.query.join(DailyOrder, DailyOrder.id == DailyOrderDetail.daily_order_id)
                   .join(DeliveryLocation, DeliveryLocation.id == DailyOrderDetail.delivery_location_id)
                   .filter(DailyOrder.order_date == next_day, DeliveryLocation.location_name == "Mes Pekerja Sektor 3")
                   .with_entities(DailyOrderDetail.id).scalar()))
    if detail_id:
        run.step(run.client("admin"), "Revisi order tambah 5 porsi", f"/operational/order-details/{detail_id}/revision", data={
            "revision_type": "WHATSAPP", "revision_direction": "INCREASE", "lunch_qty_change": "5", "dinner_qty_change": "0",
            "reason": "Mandor Joko: ada 5 pekerja baru masuk hari Senin"})

    # Tutup buku bulan pertama.
    run.travel(at(NOW_DAY, 16, 0))
    last = monthrange(OPEN_DATE.year, OPEN_DATE.month)[1]
    run.step(run.client("owner"), "Tutup buku bulan pertama", "/accounting/period-closing/post", data={
        "year": str(OPEN_DATE.year), "month": str(OPEN_DATE.month),
        "closing_date": OPEN_DATE.replace(day=last).isoformat(), "notes": "Tutup buku setelah rekonsiliasi bank",
        "sensitive_reason": "Tutup buku bulanan setelah rekonsiliasi", **guard})


# Pengajuan kerja sama dari halaman publik /kerja-sama/ajukan, lalu ditindaklanjuti owner.
PARTNERSHIPS = (
    (9, "PT Karya Rawa Mandiri", "Bapak Sugeng", "Site manager", "0812-7300-4410", "sugeng@karyarawa.co.id",
     "Perbaikan Tanggul Kanal Sektor 5", ("-2.9611200", "105.7884300"), 85, 90, "BOTH", 6, "MONTHLY",
     "Shift pagi & sore, jam istirahat 11.30. Sebagian pekerja tidak makan pedas.",
     (("CONTACTED", "Sudah telepon Pak Sugeng, minta survei lokasi Kamis."),
      ("SURVEY", "Survei selesai: akses lewat pos 2, perlu izin masuk area."),
      ("OFFERED", "Penawaran Rp 16.500/porsi siang & sore, termin bulanan."),
      ("WON", "Disetujui. Kontrak dibuat mulai bulan depan."))),
    (3, "CV Sumber Hijau Agro", "Ibu Ratna", "HRD", "0813-6611-2290", "",
     "Kebun Bibit Akasia Blok B", ("-3.0420500", "105.6915200"), 40, 40, "LUNCH", 3, "UNDECIDED",
     "Ingin coba 1 minggu dulu sebelum kontrak.",
     (("CONTACTED", "Ibu Ratna minta contoh menu seminggu, sudah dikirim lewat WhatsApp."),)),
    (0, "PT Lintas Timur Ekspedisi", "Pak Anton", "Kepala pool", "0811-7788-1200", "anton@lintastimur.id",
     "Pool Truk Simpang Tiga", ("-2.9399100", "105.7008700"), 25, 30, "DINNER", None, "WEEKLY",
     "Sopir datang bergantian, butuh makan sore jam 17.00.", ()),
)


def stage_partnerships(run):
    from app.models.partnership import PartnershipRequest

    run.stage = "Pengajuan kerja sama"
    for days_ago, company, contact, role, phone, email, project, point, workers, portions, meals, months, pay, notes, follow in PARTNERSHIPS:
        day = NOW_DAY - timedelta(days=days_ago)
        run.travel(at(day, 7 if not days_ago else 14, 10))
        visitor = run.client()
        run.step(visitor, f"Pengajuan {company}", "/kerja-sama/ajukan", data={
            "company_name": company, "contact_name": contact, "contact_role": role, "phone": phone, "email": email,
            "project_name": project, "project_address": f"{project}, Kec. Air Sugihan, OKI",
            "latitude": point[0], "longitude": point[1], "workers_count": workers, "portions_per_day": portions,
            "meals": meals, "start_date": (day + timedelta(days=21)).isoformat() if months else "",
            "duration_months": months or "", "payment_preference": pay, "notes": notes})
        request_id = run.q(lambda: PartnershipRequest.query.filter_by(company_name=company).one().id)
        for index, (status, note) in enumerate(follow):
            run.travel(at(min(day + timedelta(days=index + 1), NOW_DAY), 10 + index, 0))
            run.step(run.client("owner"), f"Tindak lanjut {company}: {status}",
                     f"/customer-success/partnerships/{request_id}/follow-up", data={"status": status, "note": note})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", required=True, help="Nama database tujuan (harus kosong selain akun owner).")
    parser.add_argument("--confirm", action="store_true", help="Wajib: menyatakan database ini boleh diisi data demo.")
    parser.add_argument("--today", type=date.fromisoformat, default=date.today(), help="'Hari ini' data demo (bawaan: hari ini).")
    parser.add_argument("--verify-only", action="store_true", help="Hanya jalankan pemeriksaan pembukuan pada database ini.")
    args = parser.parse_args()
    if not args.verify_only:
        if not args.confirm:
            raise SystemExit("Tambahkan --confirm: data demo akan ditulis ke database " + args.db)
        configure_dates(args.today)
        print(f"Periode demo: saldo awal {OPEN_DATE}, operasi {FIRST_DAY} s/d {LAST_DAY}, hari ini {NOW_DAY}.")
        if not OWNER_PASSWORD:
            raise SystemExit("Set DEMO_OWNER_PASSWORD (password akun owner hasil bootstrap).")

    from dotenv import dotenv_values

    base = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    os.environ["DATABASE_URL"] = base.rsplit("/", 1)[0] + "/" + args.db

    from app import create_app
    from app.models.master import User

    app = create_app()
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    run = Demo(app)
    if args.verify_only:
        problems = stage_verify(run)
        print("Pembukuan: semua pemeriksaan lolos." if not problems else f"Pembukuan: {len(problems)} pemeriksaan gagal.")
        raise SystemExit(1 if problems else 0)
    users = run.q(lambda: [u.username for u in User.query.all()])
    if users != ["owner"]:
        raise SystemExit(f"Database {args.db} tidak kosong (akun: {users[:5]}). Hanya untuk database baru + bootstrap owner.")

    try:
        ref = stage_setup(run)
        stage_hr_and_costing(run, ref)
        stage_opening(run, ref)
        stage_contracts(run, ref)
        plan = stage_operations(run, ref)
        stage_today(run, ref, plan)
    finally:
        run.stop_clock()
    problems = stage_verify(run)
    ok = len(run.steps) - len(run.failures)
    print(f"\nSelesai: {ok}/{len(run.steps)} langkah berhasil, {len(problems)} pemeriksaan pembukuan gagal.")
    raise SystemExit(1 if run.failures or problems else 0)


def stage_verify(run):
    """Pemeriksaan yang sama dengan gladi, tanpa saldo yang dihitung manual."""
    import csv

    from sqlalchemy import text

    from app.extensions import db
    from app.services.subledger_check_service import subledger_lines, unjournaled_stock_movements
    from tools.audit_financial_invariants import collect_results_from_database

    own = run.client("owner")  # sesi baru: jam sudah kembali ke waktu nyata
    problems = []

    def check(label, ok, detail):
        print(f"  [{'OK' if ok else 'GAGAL'}] {label}: {detail}")
        if not ok:
            problems.append(label)

    balances = run.q(lambda: [Decimal(value) for (value,) in db.session.execute(text(
        "SELECT COALESCE(SUM(d.debit), 0) - COALESCE(SUM(d.credit), 0) FROM journal_details d GROUP BY d.journal_id")).fetchall()])
    check("Setiap jurnal debit = kredit", all(value == 0 for value in balances), f"{len(balances)} jurnal")
    lines = run.q(lambda: [(line.label, line.ok, f"{line.ledger:,.0f}/{line.subledger:,.0f}") for line in subledger_lines()])
    check("Buku pembantu = buku besar", all(ok for _, ok, _ in lines), "; ".join(f"{label} {amounts}" for label, _, amounts in lines))
    unjournaled = run.q(lambda: len(unjournaled_stock_movements()))
    check("Semua pergerakan stok dijurnal", unjournaled == 0, f"{unjournaled} tanpa jurnal")
    violations = [v for result in collect_results_from_database() for v in result.violations]  # app sendiri
    check("Audit invarian keuangan", not violations, f"{len(violations)} pelanggaran {violations[:3]}")

    def csv_rows(url):
        rows = list(csv.reader(io.StringIO(own.get(url).get_data(as_text=True)), delimiter=";"))
        return [row for row in rows[2:] if len(row) > 4]

    risks = [row[5:8] for row in csv_rows("/accounting/data-health/export.csv") if row[4] == "RISIKO"]
    check("Cek Kesehatan Data tanpa RISIKO", not risks, f"{len(risks)} RISIKO {risks[:3]}")
    trial = run.text(own, "/accounting/reports/trial-balance/print")
    check("Neraca saldo seimbang", "Status Neraca BALANCE" in trial, "BALANCE" if "Status Neraca BALANCE" in trial else "tidak balance")
    return problems


if __name__ == "__main__":
    main()
