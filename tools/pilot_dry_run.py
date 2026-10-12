"""Gladi pilot satu cabang: jalankan deployment/PILOT_SATU_CABANG.md dengan data demo.

Semua langkah lewat halaman aslinya (test client Flask, login per peran), dari
OWNER mengisi pengaturan sampai invoice lunas, lalu memeriksa hasilnya: saldo
buku besar dibanding hitungan manual, audit rekonsiliasi, Cek Kesehatan Data,
Tutup Harian, neraca saldo, audit log, dan ops-check.

Hanya untuk database gladi -- nama database wajib mengandung "pilot" atau
"gladi". Siapkan database kosong dulu:

    createdb -O idha_boga_user idha_boga_pilot
    DATABASE_URL=<url .../idha_boga_pilot> flask --app run db upgrade
    DATABASE_URL=<...> BOOTSTRAP_OWNER_PASSWORD='PilotOwner#2026' \
        flask --app run bootstrap --branch-code PILOT --branch-name "Cabang Pilot" \
        --owner-username owner.pilot --owner-name "Owner Pilot"
    python tools/pilot_dry_run.py --db idha_boga_pilot [--backup]

Pertama kali dipakai 2026-09-28; temuannya ada di deployment/GLADI_PILOT_2026-09-28.md.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import struct
import sys
import uuid
import zlib
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from app.utils.clock import today_wib

if not os.environ.get("PG_DUMP_PATH") and Path(r"C:\laragon\bin\postgresql\postgresql-11.0-1\bin\pg_dump.exe").exists():
    os.environ["PG_DUMP_PATH"] = r"C:\laragon\bin\postgresql\postgresql-11.0-1\bin\pg_dump.exe"

OWNER_PASSWORD = os.environ.get("PILOT_OWNER_PASSWORD", "PilotOwner#2026")
USER_PASSWORD = "PilotUser#2026"
TODAY = today_wib()
D1, D2 = TODAY + timedelta(days=1), TODAY + timedelta(days=2)
D3, D4, D5 = TODAY + timedelta(days=3), TODAY + timedelta(days=4), TODAY + timedelta(days=5)

# Hitungan manual skenario di bawah (harga standar 18.000, kontrak PT Maju 16.000,
# ongkir Dekat 10.000 / Jauh 25.000 / kontrak PT Sinar 15.000 per trip).
# Kurang kirim yang tidak diganti tidak ditagih (keputusan owner 2026-09-28):
# Gudang Cikarang (Joko) kurang 2 dari 25, Kantor Notaris (Sari) kurang 1 dari 20.
# Saldo awal (wizard satu pintu): kas 5.000.000, BCA 25.000.000, piutang lama PT Maju
# 1.500.000, stok Beras 150 x 14.000 + Minyak 70 x 20.000 = 3.500.000, peralatan
# 36.000.000 dengan akumulasi 6.000.000, hutang lama Toko Sumber Rejeki 2.000.000
# -> modal 63.000.000.
# Tahap D (satu langkah): beli Beras 50 x 15.000 tunai, Minyak 30 x 21.000 hutang;
# harga rata-rata Beras (2.100.000 + 750.000) / 200 = 14.250, Minyak
# (1.400.000 + 630.000) / 100 = 20.300; pakai Beras 40 = 570.000, Minyak rusak 2 =
# 40.600, opname Beras kurang 2 = 28.500.
EXPECTED_BALANCES = {
    "1001": Decimal("5150000"),     # 5.000.000 + 200.000 Joko + 205.000 Dedi - 750.000 beli - 500.000 hutang lama - 1.000.000 setor ke bank - 5.000 selisih + 2.000.000 modal
    "1002": Decimal("30328500"),    # 25.000.000 + 1.271.000 uang muka - 190.000 - 18.000 refund + 2.272.000 Budi + 1.500.000 piutang lama + 1.000.000 dari kas - 6.500 admin - 500.000 prive
    "1004": Decimal("1596000"),     # sisa Joko 368.000 - 200.000 + Asep 1.428.000 (piutang lama 1.500.000 sudah lunas)
    "1006": Decimal("4240900"),     # 3.500.000 + 750.000 + 630.000 - 570.000 - 40.600 - 28.500
    "1101": Decimal("36000000"),
    "2101": Decimal("-6000000"),
    "2002": Decimal("-2130000"),    # 2.000.000 lama - 500.000 dibayar + 630.000 beli hutang
    "2008": Decimal("0"),
    "3001": Decimal("-65000000"),   # 63.000.000 saldo awal + 2.000.000 setor
    "3003": Decimal("500000"),
    "5001": Decimal("570000"),
    "5008": Decimal("6500"),
    "5009": Decimal("74100"),       # 40.600 rusak + 28.500 opname + 5.000 selisih kas
    "4001": Decimal("-4008000"),    # 142 x 16.000 Budi + 23 x 16.000 Joko + 76 x 18.000 Asep
    "4002": Decimal("-1188000"),    # (15 + 12 + 19 + 10 + 10) x 18.000
    "4005": Decimal("-140000"),     # umum 10.000+25.000+10.000+10.000+25.000, kontrak 4 trip x 15.000
}

_ALERT = re.compile(r'class="[^"]*\balert-(success|info|warning|danger|error)\b[^"]*"[^>]*>(.*?)</div>', re.S)
_TAGS = re.compile(r"<[^>]+>")


class DryRun:
    def __init__(self, app):
        self.app = app
        self.stage = ""
        self.steps = []
        self.checks = []

    # --- infrastruktur ------------------------------------------------------
    def q(self, fn):
        """DB lookup di app context sendiri. Jangan panggil step() di dalam app context:
        request test client memakai ulang context yang aktif, sehingga user login
        request sebelumnya terbawa (g._login_user)."""
        with self.app.app_context():
            return fn()

    def client(self, username=None):
        from app.models.master import User

        client = self.app.test_client()
        if username:
            user_id = self.q(lambda: User.query.filter_by(username=username).one().id)
            with client.session_transaction() as session:
                session["_user_id"] = str(user_id)
                session["_fresh"] = True
        return client

    def step(self, client, label, url, data=None, expect=("success", "info"), method="POST", **kwargs):
        from flask import has_app_context

        assert not has_app_context(), "step() dipanggil di dalam app context"
        response = client.post(url, data=data, **kwargs) if method == "POST" else client.get(url, **kwargs)
        with client.session_transaction() as session:
            messages = list(session.pop("_flashes", []))
        if not messages and response.status_code in (200, 400) and method == "POST":
            for category, html in _ALERT.findall(response.get_data(as_text=True)):
                text = " ".join(_TAGS.sub(" ", html).split())
                if text:
                    messages.append((category, text[:240]))
        if method == "GET":
            ok = response.status_code == 200
        elif messages:
            ok = response.status_code in (200, 302, 400) and all(category in expect for category, _ in messages)
        else:
            ok = response.status_code in (200, 302)
        self.steps.append((self.stage, label, ok, response.status_code, messages))
        print(f"[{'OK ' if ok else 'ERR'}] {label} | " + " || ".join(f"{c}: {m}" for c, m in messages))
        return response, ok

    def check(self, label, ok, detail):
        self.checks.append((label, ok, detail))
        print(f"[{'LULUS' if ok else 'GAGAL'}] {label}: {detail}")

    def text(self, client, url):
        body = client.get(url).get_data(as_text=True)
        body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S)
        return " ".join(_TAGS.sub(" ", body).split())


def _png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    salt = uuid.uuid4().bytes
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"tEXt", b"salt\x00" + salt)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


def _photo():
    """Foto lokasi antar (wajib sejak 2026-10-05)."""
    return (io.BytesIO(_png()), "lokasi.png")


# --- tahap A: sebelum hari pertama --------------------------------------------

def stage_setup(run):
    from app.models.finance import BankAccount
    from app.models.master import Client, Mandor, User
    from app.models.pricing import DeliveryZone

    run.stage = "A. Sebelum hari pertama"
    own = run.client("owner.pilot")
    branch_id = run.q(lambda: User.query.filter_by(username="owner.pilot").one().branch_id)
    guard = {"sensitive_action_confirmed": "1", "sensitive_reason": "Gladi pilot: setup awal cabang", "confirm_password": OWNER_PASSWORD}

    run.step(own, "Pengaturan Perusahaan: identitas, rekening, istilah PT/Mandor, modul", "/settings/company", data={
        "company_name": "PT Idha Boga Pangan Mandiri", "company_subtitle": "Catering Proyek & Harian",
        "company_address": "Jl. Raya Cikarang No. 8, Bekasi", "company_phone": "0812-1111-2222",
        "company_email": "admin@idhaboga.test", "company_npwp": "01.234.567.8-901.000",
        "payment_bank_name": "BCA", "payment_account_number": "1234567890", "payment_account_name": "PT Idha Boga Pangan Mandiri",
        "invoice_footer": "Terima kasih.", "invoice_terms": "Pembayaran 14 hari setelah invoice.",
        "invoice_authorized_name": "Idha", "invoice_authorized_position": "Direktur",
        "term_client": "PT", "term_sub_client": "Mandor", "term_location": "Lokasi Proyek", "term_worker": "Pekerja",
        "module_warung": "1", "module_worker_debt": "1",
        "document_prefix_invoice": "INV", "document_prefix_payment": "PAY", "document_prefix_order": "ORD",
        "document_prefix_delivery": "DLV", "document_prefix_journal": "JRN", **guard})

    for full_name, username, role in (("Admin Pilot", "admin.pilot", "ADMIN"), ("Dapur Pilot", "dapur.pilot", "DAPUR"),
                                      ("Pengantar Pilot", "antar.pilot", "PENGANTAR")):
        run.step(own, f"Akun {role}: {username}", "/settings/users/create", data={
            "full_name": full_name, "username": username, "role": role, "branch_id": branch_id, "is_active": "on",
            "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD, **guard})
    adm = run.client("admin.pilot")

    for bank, number in (("BCA", "1234567890"), ("Mandiri", "1400012345678")):
        run.step(own, f"Rekening bank {bank}", "/master/bank-accounts/create", data={
            "bank_name": bank, "account_number": number, "account_name": "PT Idha Boga Pangan Mandiri", "is_active": "on"})
    for code, name in (("MAJU", "PT Maju Konstruksi"), ("SINAR", "PT Sinar Beton")):
        run.step(own, f"Client kontrak {name}", "/master/clients/create", data={
            "client_code": code, "name": name, "phone": "021-555-0101", "customer_path": "KONTRAK", "address": "Cikarang", "is_active": "on"})
    maju = run.q(lambda: Client.query.filter_by(name="PT Maju Konstruksi").one().id)
    sinar = run.q(lambda: Client.query.filter_by(name="PT Sinar Beton").one().id)
    for client_id, pic in ((maju, "Bu Wati"), (sinar, "Pak Hendra")):
        run.step(own, f"PIC resmi {pic}", f"/master/clients/{client_id}/pics/create", data={
            "pic_name": pic, "pic_phone": "0816000000", "pic_email": "pic@example.test", "pic_position": "Finance"})

    run.step(own, "Harga standar Rp18.000/porsi", "/settings/pricing/price", data={"price_per_portion": "18000", "effective_from": TODAY.isoformat(), "notes": "harga awal pilot"})
    run.step(own, "Harga kontrak PT Maju Rp16.000", "/settings/pricing/price", data={"client_id": maju, "price_per_portion": "16000", "effective_from": TODAY.isoformat(), "notes": "kontrak 2026"})
    run.step(own, "Simpan ulang harga yang sama (harus ditolak, tidak menumpuk)", "/settings/pricing/price",
             data={"price_per_portion": "18000", "effective_from": TODAY.isoformat()}, expect=("warning",))
    run.step(own, "Minimal pesan pelanggan umum 10 porsi", "/settings/pricing/min-portions", data={"min_portions": "10"})
    for zone in ("Dekat (< 5 km)", "Jauh (5-15 km)"):
        run.step(own, f"Zona {zone}", "/settings/pricing/zones", data={"name": zone})
    zones = run.q(lambda: {z.name: z.id for z in DeliveryZone.query.filter_by(branch_id=branch_id).all()})
    run.step(own, "Ongkir Dekat Rp10.000", "/settings/pricing/delivery-fee", data={"zone_id": zones["Dekat (< 5 km)"], "fee": "10000", "effective_from": TODAY.isoformat(), "notes": "tarif awal"})
    run.step(own, "Ongkir Jauh Rp25.000", "/settings/pricing/delivery-fee", data={"zone_id": zones["Jauh (5-15 km)"], "fee": "25000", "effective_from": TODAY.isoformat(), "notes": "tarif awal"})
    run.step(own, "Gratis ongkir mulai 100 porsi", "/settings/pricing/free-delivery", data={"free_delivery_min_portions": "100"})
    run.step(own, "Ongkir kontrak PT Sinar Rp15.000/trip", "/settings/pricing/delivery-fee", data={"client_id": sinar, "fee": "15000", "effective_from": TODAY.isoformat()})

    for client_id, name in ((maju, "Mandor Budi"), (maju, "Mandor Joko"), (sinar, "Mandor Asep")):
        run.step(adm, f"Mandor {name}", "/master/mandors/create", data={"client_id": client_id, "name": name, "phone": "0813000000", "is_active": "on"})
    for mandor, location in (("Mandor Budi", "Proyek Tol Km 12"), ("Mandor Joko", "Gudang Cikarang"), ("Mandor Asep", "Batching Plant Cibitung")):
        mandor_id = run.q(lambda: Mandor.query.filter_by(name=mandor).one().id)
        run.step(adm, f"Lokasi {location}", "/master/locations/create", data={"mandor_id": mandor_id, "location_name": location, "is_active": "on",
                                                                             "location_photos": _photo()})
    for driver in ("Pak Ujang", "Pak Karim"):
        run.step(adm, f"Pengantar {driver}", "/master/drivers/create", data={"name": driver, "phone": "0814000000", "license_number": "SIM-A", "is_active": "on"})

    budi = run.q(lambda: Mandor.query.filter_by(name="Mandor Budi").one().id)
    portal = {"branch_id": branch_id, "is_active": "on", "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD, **guard}
    run.step(own, "Akun Portal PT tanpa memilih PT (harus ditolak)", "/settings/users/create", data={
        "full_name": "Portal PT Maju", "username": "portal.maju", "email": "portal.maju@example.test", "role": "PORTAL_CLIENT", **portal}, expect=("warning",))
    run.step(own, "Akun Portal PT dihubungkan ke PT Maju", "/settings/users/create", data={
        "full_name": "Portal PT Maju", "username": "portal.maju", "email": "portal.maju@example.test", "role": "PORTAL_CLIENT", "portal_client_id": maju, **portal})
    run.step(own, "Akun Portal Mandor dihubungkan ke Mandor Budi", "/settings/users/create", data={
        "full_name": "Mandor Budi", "username": "mandor.budi", "email": "mandor.budi@example.test", "role": "PORTAL_SUBCLIENT", "portal_mandor_id": budi, **portal})

    anon = run.client()
    for index, (full_name, username, zone, location, address) in enumerate((
        ("Ibu Rina", "rina.cust", "Dekat (< 5 km)", "Rumah Bu Rina", "Perum Graha Asri Blok C2, Cikarang"),
        ("Pak Dedi", "dedi.cust", "Jauh (5-15 km)", "Kantor Pak Dedi", "Ruko Sentra Niaga No. 5, Cibitung"),
        ("Kantor Notaris Sari", "sari.cust", "Dekat (< 5 km)", "Kantor Notaris", "Jl. Kasuari No. 3, Cikarang"),
    )):
        run.step(anon, f"Pelanggan umum daftar sendiri: {full_name}", "/portal/register", data={
            "full_name": full_name, "phone": f"08157000{index}{index}{index}", "email": f"{username}@example.test",
            "username": username, "branch_id": branch_id, "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD,
            "location_name": location, "delivery_zone_id": zones[zone], "address": address, "notes": "gerbang biru",
            "location_photos": _photo()})

    for name, unit in (("Beras", "kg"), ("Minyak Goreng", "liter")):
        run.step(adm, f"Barang {name}", "/master/items/create", data={
            "item_name": name, "category": "RAW_MATERIAL", "unit": unit, "minimum_stock": "10", "is_stock_tracked": "on", "is_active": "on"})
    run.step(own, "Supplier Toko Sumber Rejeki", "/master/suppliers/create", data={
        "supplier_name": "Toko Sumber Rejeki", "supplier_type": "RAW_MATERIAL", "default_payment_terms_days": "14", "is_active": "on"})

    from app.models.master import Item, Supplier

    bca = run.q(lambda: BankAccount.query.filter_by(account_number="1234567890").one().id)
    mandiri = run.q(lambda: BankAccount.query.filter_by(account_number="1400012345678").one().id)
    beras = run.q(lambda: Item.query.filter_by(item_name="Beras").one().id)
    minyak = run.q(lambda: Item.query.filter_by(item_name="Minyak Goreng").one().id)
    supplier = run.q(lambda: Supplier.query.filter_by(supplier_name="Toko Sumber Rejeki").one().id)
    base = "/accounting/opening-balance"
    run.step(own, "Saldo Awal: tanggal mulai", f"{base}/start-date", data={"start_date": TODAY.isoformat()})
    run.step(own, "Saldo Awal: kas 5.000.000, BCA 25.000.000", f"{base}/cash-bank", data={
        "cash": "5.000.000", f"bank_{bca}": "25000000", f"bank_{mandiri}": "0"})
    run.step(own, "Saldo Awal: piutang lama PT Maju nota NT-081 Rp1.500.000", f"{base}/receivables/add", data={
        "client_id": maju, "reference": "NT-081", "invoice_date": (TODAY - timedelta(days=30)).isoformat(), "amount": "1500000"})
    run.step(own, "Saldo Awal: hutang lama Toko Sumber Rejeki Rp2.000.000", f"{base}/payables/add", data={
        "supplier_id": supplier, "reference": "F-0912", "bill_date": (TODAY - timedelta(days=10)).isoformat(),
        "due_date": (TODAY + timedelta(days=4)).isoformat(), "amount": "2000000"})
    run.step(own, "Saldo Awal: stok Beras 150 kg @14.000", f"{base}/stock/add", data={"item_id": beras, "qty": "150", "unit_cost": "14000"})
    run.step(own, "Saldo Awal: stok Minyak 70 L @20.000", f"{base}/stock/add", data={"item_id": minyak, "qty": "70", "unit_cost": "20000"})
    run.step(own, "Saldo Awal: stok Beras dua kali (harus ditolak)", f"{base}/stock/add", data={"item_id": beras, "qty": "1", "unit_cost": "1"},
             expect=("warning",))
    run.step(own, "Saldo Awal: peralatan dapur 36.000.000, akumulasi 6.000.000", f"{base}/assets/add", data={
        "name": "Kompor & peralatan dapur", "category": "KITCHEN_EQUIPMENT", "purchase_date": "2024-03-01",
        "purchase_value": "36000000", "accumulated": "6000000", "useful_life_years": "5"})
    run.step(adm, "ADMIN mengunci saldo awal (harus ditolak)", f"{base}/lock", data={
        "sensitive_reason": "saldo awal sesuai hitung fisik", "confirm_password": USER_PASSWORD}, expect=("danger",))
    run.step(own, "OWNER kunci dengan password salah (harus ditolak)", f"{base}/lock", data={
        "sensitive_reason": "saldo awal sesuai hitung fisik", "confirm_password": "salah"}, expect=("danger",))
    run.step(own, "OWNER kunci saldo awal", f"{base}/lock", data={
        "sensitive_reason": "saldo awal sesuai hitung fisik dan rekening koran", "confirm_password": OWNER_PASSWORD})
    return {"bca": bca, "beras": beras, "minyak": minyak, "supplier": supplier}


# --- tahap B: setiap hari -------------------------------------------------------

def _location(run, name):
    from app.models.master import DeliveryLocation

    return run.q(lambda: (lambda row: {"id": row.id, "mandor_id": row.mandor_id})(DeliveryLocation.query.filter_by(location_name=name).one()))


def _draft(run, username, day, meal):
    from app.models.master import User
    from app.models.system import PortalOrderDraft

    def load():
        user = User.query.filter_by(username=username).one()
        row = PortalOrderDraft.query.filter_by(user_id=user.id, order_date=day, meal_type=meal).first()
        if not row:
            return None
        return {"id": row.id, "status": row.status,
                "due": Decimal(str(row.price_per_portion or 0)) * row.portion_qty + Decimal(str(row.delivery_fee or 0))}
    return run.q(load)


def stage_orders(run, refs):
    from app.models.finance import AdvanceTransaction
    from app.models.system import DigitalAttachment

    run.stage = "B. Pesanan, bayar di muka, konfirmasi"
    adm, own = run.client("admin.pilot"), run.client("owner.pilot")

    for day, location, lunch, dinner in ((D1, "Proyek Tol Km 12", 40, 30), (D1, "Gudang Cikarang", 25, 0), (D1, "Batching Plant Cibitung", 20, 20),
                                         (D2, "Batching Plant Cibitung", 18, 18)):
        loc = _location(run, location)
        run.step(adm, f"Order kontrak {day:%d-%m} {location} siang {lunch} / malam {dinner}", "/operational/orders/create", data={
            "order_date": day.isoformat(), "mandor_id": loc["mandor_id"], "delivery_location_id": loc["id"],
            "lunch_qty": lunch, "dinner_qty": dinner, "notes": "gladi"})
    budi = run.client("mandor.budi")
    tol = _location(run, "Proyek Tol Km 12")
    for meal, qty in (("LUNCH", 42), ("DINNER", 30)):
        page = budi.get("/portal/orders/draft").get_data(as_text=True)
        key = re.search(r'name="idempotency_key" value="([^"]+)"', page)
        run.step(budi, f"Portal Mandor Budi pesan {D2:%d-%m} {meal} {qty} porsi", "/portal/orders/draft", data={
            "idempotency_key": key.group(1) if key else uuid.uuid4().hex, "order_date": D2.isoformat(), "meal_type": meal,
            "delivery_location_id": tol["id"], "portion_qty": qty, "delivery_time": "11:30" if meal == "LUNCH" else "17:30",
            "contact_name": "Mandor Budi", "contact_phone": "0813000000"})
        draft = _draft(run, "mandor.budi", D2, meal)
        run.step(adm, f"Admin konfirmasi pesanan Mandor Budi {meal} (kontrak: tanpa bayar di muka)",
                 f"/portal/admin/order-drafts/{draft['id']}/confirm", data={"review_note": "gladi"})

    rina = _location(run, "Rumah Bu Rina")
    run.step(adm, "Admin input pelanggan umum 8 porsi (harus ditolak: minimal 10)", "/operational/orders/create", data={
        "order_date": D2.isoformat(), "mandor_id": rina["mandor_id"], "delivery_location_id": rina["id"],
        "lunch_qty": 8, "dinner_qty": 0, "prepayment_amount": "154000", "prepayment_method": "CASH"}, expect=("warning", "danger"))

    for username, day, meal, location, qty in (("rina.cust", D1, "LUNCH", "Rumah Bu Rina", 15), ("dedi.cust", D1, "LUNCH", "Kantor Pak Dedi", 12),
                                               ("sari.cust", D1, "DINNER", "Kantor Notaris", 20), ("rina.cust", D2, "LUNCH", "Rumah Bu Rina", 10),
                                               ("sari.cust", D2, "DINNER", "Kantor Notaris", 10), ("dedi.cust", D2, "LUNCH", "Kantor Pak Dedi", 10)):
        customer = run.client(username)
        page = customer.get("/portal/orders/draft").get_data(as_text=True)
        key = re.search(r'name="idempotency_key" value="([^"]+)"', page)
        run.step(customer, f"Portal {username} pesan {day:%d-%m} {meal} {qty} porsi", "/portal/orders/draft", data={
            "idempotency_key": key.group(1) if key else uuid.uuid4().hex, "order_date": day.isoformat(), "meal_type": meal,
            "delivery_location_id": _location(run, location)["id"], "portion_qty": qty,
            "delivery_time": "11:30" if meal == "LUNCH" else "17:30", "contact_name": username, "contact_phone": "0815700000"})
        if (username, day) == ("rina.cust", D1):
            run.step(customer, "Portal pesan 5 porsi (harus ditolak: minimal 10)", "/portal/orders/draft", data={
                "idempotency_key": uuid.uuid4().hex, "order_date": day.isoformat(), "meal_type": "DINNER",
                "delivery_location_id": _location(run, location)["id"], "portion_qty": 5}, expect=("warning", "danger"))

    def pay(username, day, meal, amount, label):
        draft = _draft(run, username, day, meal)
        run.step(run.client(username), f"{username} unggah bukti bayar {label} Rp{amount:,}", f"/portal/orders/draft/{draft['id']}/payment-proof",
                 data={"paid_amount": str(amount), "sender_name": username, "notes": label, "proof_file": (io.BytesIO(_png()), "bukti.png")},
                 content_type="multipart/form-data")
        attachment = run.q(lambda: DigitalAttachment.query.filter_by(reference_type="PORTAL_ORDER_DRAFT", reference_id=draft["id"])
                           .order_by(DigitalAttachment.id.desc()).first().id)
        run.step(adm, f"Finance verifikasi bukti #{attachment}", f"/finance/portal-payment-proofs/{attachment}/decide",
                 data={"decision": "VERIFIED", "notes": "mutasi BCA cocok"})
        run.step(adm, f"Finance catat uang muka Rp{amount:,} (nominal yang masuk rekening)", f"/finance/portal-payment-proofs/{attachment}/record-prepayment", data={
            "payment_date": TODAY.isoformat(), "amount": str(amount), "payment_method": "TRANSFER", "bank_account_id": refs["bca"],
            "reference_number": f"TRF-{attachment}", "notes": label, "idempotency_key": uuid.uuid4().hex})
        return draft

    def confirm(username, day, meal, label="", expect=("success", "info"), client=None, **extra):
        draft = _draft(run, username, day, meal)
        run.step(client or adm, f"Konfirmasi draft #{draft['id']} {username} {label}".strip(), f"/portal/admin/order-drafts/{draft['id']}/confirm",
                 data={"review_note": "gladi", **extra}, expect=expect)

    pay("rina.cust", D1, "LUNCH", 280000, "lunas")
    confirm("rina.cust", D1, "LUNCH")
    confirm("dedi.cust", D1, "LUNCH", "(belum bayar: harus ditolak)", expect=("warning", "danger"))
    pay("dedi.cust", D1, "LUNCH", 200000, "sebagian")
    confirm("dedi.cust", D1, "LUNCH", "(kurang bayar: harus ditolak)", expect=("warning", "danger"))
    pay("dedi.cust", D1, "LUNCH", 41000, "pelunasan")
    confirm("dedi.cust", D1, "LUNCH", "(lunas)")
    pay("sari.cust", D1, "DINNER", 370000, "lunas")
    confirm("sari.cust", D1, "DINNER")
    pay("rina.cust", D2, "LUNCH", 190000, "lunas")
    confirm("rina.cust", D2, "LUNCH")

    sari = pay("sari.cust", D2, "DINNER", 190000, "lunas")
    run.step(adm, "Admin tolak draft Sari yang sudah dibayar (dapur penuh)", f"/portal/admin/order-drafts/{sari['id']}/reject",
             data={"review_note": "Dapur penuh tanggal ini"}, expect=("success", "warning"))

    confirm("dedi.cust", D2, "LUNCH", "ADMIN loloskan sebelum lunas (harus ditolak)", expect=("warning", "danger"), owner_override="1")
    draft = _draft(run, "dedi.cust", D2, "LUNCH")
    run.step(own, "OWNER loloskan tanpa alasan (harus ditolak)", f"/portal/admin/order-drafts/{draft['id']}/confirm",
             data={"review_note": "", "owner_override": "1"}, expect=("warning", "danger"))
    run.step(own, "OWNER loloskan dengan alasan", f"/portal/admin/order-drafts/{draft['id']}/confirm",
             data={"review_note": "Pelanggan langganan, bayar tunai saat diantar", "owner_override": "1"})

    advance = run.q(lambda: (lambda row: {"id": row.id, "remaining": int(row.remaining_amount or 0)})(
        AdvanceTransaction.query.filter(AdvanceTransaction.portal_order_draft_id == sari["id"]).one()))
    refund = {"settlement_type": "CLIENT_DP_REFUND", "settlement_date": TODAY.isoformat(), "amount": str(advance["remaining"]),
              "payment_method": "TRANSFER", "bank_account_id": refs["bca"], "notes": "Draft ditolak: dapur penuh"}
    run.step(adm, "ADMIN kembalikan uang muka (harus ditolak: hanya OWNER)", f"/finance/advances/{advance['id']}/settle", data=refund, expect=("danger", "warning"))
    run.step(own, f"OWNER kembalikan uang muka Rp{advance['remaining']:,}", f"/finance/advances/{advance['id']}/settle", data=refund)


def stage_operations(run, day, shortage=None):
    from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
    from app.models.operational import DailyOrder
    from app.models.production import Production, ProductionDetail

    shortage = shortage or {}
    run.stage = f"B. Operasional {day:%d-%m-%Y}"
    adm, dapur, antar = run.client("admin.pilot"), run.client("dapur.pilot"), run.client("antar.pilot")
    order_id = run.q(lambda: DailyOrder.query.filter_by(order_date=day).one().id)
    run.step(adm, f"Kunci order {day:%d-%m}", f"/operational/orders/{order_id}/lock", data={})

    for production_id, kind in run.q(lambda: [(p.id, p.production_type) for p in Production.query.filter_by(production_date=day).all()]):
        planned = run.q(lambda: int(sum(row.planned_qty for row in ProductionDetail.query.filter_by(production_id=production_id).all())))
        run.step(dapur, f"Dapur realisasi {kind} {planned} porsi", f"/production/{production_id}/realization",
                 data={"actual_qty": planned, "status": "COMPLETED", "notes": "gladi"})

    for kind in ("LUNCH", "DINNER"):
        run.step(antar, f"Pengantar buat pengiriman {kind}", f"/delivery/create-from-order/{order_id}/{kind}", data={})
        find = lambda: Delivery.query.filter(Delivery.delivery_date == day, Delivery.notes.like(f"delivery_type={kind};%")).first()
        delivery_id = run.q(lambda: (lambda row: row and row.id)(find()))
        if not delivery_id:
            continue
        run.step(antar, f"Pengantar berangkat {kind}", f"/delivery/{delivery_id}/dispatch", data={})
        details = run.q(lambda: [(row.id, row.delivery_location.location_name, int(row.planned_qty or 0))
                                 for row in DeliveryDetail.query.filter_by(delivery_id=delivery_id).all()])
        for detail_id, location, planned in details:
            received = planned - shortage.get(location, 0)
            run.step(antar, f"Tanda terima {kind} {location}: {received}/{planned}", f"/delivery/details/{detail_id}/receive", data={
                "delivered_qty": received, "receiver_name": f"Penerima {location}",
                "notes": "kurang porsi" if received < planned else ""},
                expect=("success", "info", "warning") if received < planned else ("success", "info"))
        assert run.q(lambda: all(DeliveryReceipt.query.filter_by(delivery_detail_id=d[0]).first() for d in details))


# --- tahap C: tagihan kontrak dan pembayaran ------------------------------------

def stage_billing(run, refs):
    from app.models.finance import Invoice
    from app.models.master import Client, ClientPic, Mandor

    run.stage = "C. Tagihan dan pembayaran"
    adm = run.client("admin.pilot")
    period = {"period_start": D1.isoformat(), "period_end": D2.isoformat()}

    def mandor(name):
        return run.q(lambda: Mandor.query.filter_by(name=name).one().id)

    for name in ("Mandor Budi", "Mandor Joko", "Mandor Asep"):
        mandor_id = mandor(name)
        pic = run.q(lambda: ClientPic.query.filter_by(client_id=Mandor.query.get(mandor_id).client_id, is_active=True).first().id)
        run.step(adm, f"Invoice periode {name}", "/finance/invoices/generate-period/save", data={"mandor_id": mandor_id, "client_pic_id": pic, **period})
    rina_mandor = run.q(lambda: Mandor.query.join(Client, Client.id == Mandor.client_id).filter(Client.name == "Ibu Rina").first().id)
    run.step(adm, "Invoice periode pelanggan umum (harus ditolak: sudah ditagih otomatis)", "/finance/invoices/generate-period/save",
             data={"mandor_id": rina_mandor, **period}, expect=("warning",))

    def invoice(name, **filters):
        mandor_id = mandor(name)
        return run.q(lambda: (lambda row: {"id": row.id, "total": int(row.total_amount), "number": row.invoice_number})(
            Invoice.query.filter_by(mandor_id=mandor_id, **filters).order_by(Invoice.id.desc()).first()))

    def pay(inv, amount, method, label, expect=("success", "info")):
        run.step(adm, f"Bayar {inv['number']} Rp{amount:,} {method} {label}".strip(), f"/finance/invoices/{inv['id']}/payments/create", data={
            "idempotency_key": uuid.uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": method,
            "bank_account_id": refs["bca"] if method == "TRANSFER" else "", "amount": str(amount), "notes": label}, expect=expect)

    budi = invoice("Mandor Budi", source_type="PERIOD_INVOICE")
    pay(budi, budi["total"] + 50000, "TRANSFER", "(lebih bayar: harus ditolak)", expect=("warning", "danger"))
    pay(budi, budi["total"], "TRANSFER", "(lunas)")
    pay(invoice("Mandor Joko", source_type="PERIOD_INVOICE"), 200000, "CASH", "(sebagian)")
    from app.models.master import User
    from app.services.prepaid_order_service import advances_to_refund

    own = run.client("owner.pilot")
    branch_id = run.q(lambda: User.query.filter_by(username="owner.pilot").one().branch_id)
    for advance_id, number, remaining in run.q(lambda: [(a.id, a.advance_number, int(a.remaining_amount)) for a, _reason in advances_to_refund(branch_id)]):
        run.step(own, f"OWNER kembalikan sisa uang muka {number} Rp{remaining:,} (kurang kirim)", f"/finance/advances/{advance_id}/settle", data={
            "settlement_type": "CLIENT_DP_REFUND", "settlement_date": TODAY.isoformat(), "amount": str(remaining),
            "payment_method": "TRANSFER", "bank_account_id": refs["bca"], "notes": "Kurang kirim 1 porsi, dikembalikan"})

    dedi_mandor = run.q(lambda: Mandor.query.join(Client, Client.id == Mandor.client_id).filter(Client.name == "Pak Dedi").first().name)
    dedi = invoice(dedi_mandor, source_type="DAILY_ORDER")
    pay(dedi, dedi["total"], "CASH", "(pesanan yang diloloskan OWNER, dibayar tunai saat antar)")


# --- tahap D: pembelian, stok, kas, modal (satu langkah) -----------------------
# Sesudah penagihan, supaya angka tagihan skenario di atas tidak berubah.

def stage_one_step(run, refs):
    from app.models.finance import Invoice, SupplierBill

    run.stage = "D. Pembelian, stok, kas, modal"
    own, adm = run.client("owner.pilot"), run.client("admin.pilot")
    purchase = {"procurement_date": TODAY.isoformat(), "purchase_place": "Pasar Cikarang"}
    run.step(adm, "Beli tunai Beras 50 kg @15.000 dari kas", "/logistics/purchases/create", data={
        **purchase, "purchase_type": "CASH", "payment_account_type": "CASH",
        "item_id[]": [str(refs["beras"])], "qty[]": ["50"], "unit_price[]": ["15000"]})
    run.step(adm, "Beli hutang Minyak 30 L @21.000 ke Toko Sumber Rejeki", "/logistics/purchases/create", data={
        **purchase, "purchase_type": "CREDIT", "supplier_id": str(refs["supplier"]), "supplier_bill_due_date": (TODAY + timedelta(days=14)).isoformat(),
        "item_id[]": [str(refs["minyak"])], "qty[]": ["30"], "unit_price[]": ["21000"]})
    old_bill = run.q(lambda: SupplierBill.query.filter(SupplierBill.procurement_id.is_(None)).one().id)
    run.step(own, "Bayar hutang lama Rp500.000 tunai", f"/finance/supplier-bills/{old_bill}/payments/create", data={
        "idempotency_key": uuid.uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": "CASH", "amount": "500000"})
    old_invoice = run.q(lambda: Invoice.query.filter_by(source_type="OPENING_BALANCE").one().id)
    run.step(adm, "PT Maju melunasi piutang lama Rp1.500.000 transfer", f"/finance/invoices/{old_invoice}/payments/create", data={
        "idempotency_key": uuid.uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": "TRANSFER",
        "bank_account_id": refs["bca"], "amount": "1500000", "notes": "piutang lama"})
    run.step(adm, "Stok keluar Beras 40 kg untuk produksi", "/logistics/stock-out", data={
        "item_id": refs["beras"], "movement_date": TODAY.isoformat(), "qty": "40", "usage_purpose": "PRODUKSI"})
    run.step(adm, "Minyak rusak 2 L", "/logistics/damaged/create", data={
        "item_id": refs["minyak"], "movement_date": TODAY.isoformat(), "qty": "2", "damage_reason": "jerigen bocor"})
    run.step(adm, "Audit stok Beras: fisik 158 kg (sistem 160)", "/logistics/audit/create", data={
        "item_id": refs["beras"], "audit_date": TODAY.isoformat(), "physical_stock": "158", "reason": "hitung fisik mingguan"})
    run.step(adm, "Setor kas ke BCA Rp1.000.000", "/finance/cash-bank-transfers", data={
        "transfer_date": TODAY.isoformat(), "from_account_type": "CASH", "to_account_type": "BANK",
        "to_bank_account_id": refs["bca"], "amount": "1000000"})
    adjustment = {"adjustment_date": TODAY.isoformat(), "account_type": "CASH", "adjustment_category": "SELISIH", "adjustment_type": "DECREASE"}
    run.step(adm, "Selisih kas kurang Rp5.000", "/finance/cash-bank-adjustments", data={**adjustment, "amount": "5000", "reason": "hitung kas sore"})
    run.step(adm, "Selisih kas Rp150.000 oleh ADMIN (harus ditolak)", "/finance/cash-bank-adjustments", data={
        **adjustment, "amount": "150000", "reason": "hitung kas sore"}, expect=("danger",))
    run.step(adm, "Biaya admin BCA Rp6.500", "/finance/cash-bank-adjustments", data={
        "adjustment_date": TODAY.isoformat(), "account_type": "BANK", "bank_account_id": refs["bca"], "adjustment_category": "BIAYA_BANK",
        "adjustment_type": "DECREASE", "amount": "6500", "reason": "potongan admin bulanan"})
    capital = {"transaction_date": TODAY.isoformat()}
    run.step(own, "Setor modal Rp2.000.000 ke kas", "/finance/owner-capital", data={
        **capital, "kind": "SETOR", "account_type": "CASH", "amount": "2000000", "notes": "tambahan modal belanja"})
    run.step(own, "Tarik modal Rp500.000 dari BCA", "/finance/owner-capital", data={
        **capital, "kind": "TARIK", "account_type": "BANK", "bank_account_id": refs["bca"], "amount": "500000", "notes": "keperluan pribadi"})
    run.step(adm, "ADMIN catat modal (harus ditolak)", "/finance/owner-capital", data={
        **capital, "kind": "SETOR", "account_type": "CASH", "amount": "1000", "notes": "coba"}, expect=("danger",))
    run.step(own, "Stok Masuk manual dialihkan ke Pembelian Barang", "/logistics/stock-in", data={"item_id": refs["beras"], "qty": "5"},
             expect=("info",))


# --- tahap E: kontrak berakhir ------------------------------------------------
# Sesudah penagihan, supaya angka tagihan skenario di atas tidak berubah.

def _sign_and_activate(run, client, contract_id, label):
    """Fase 9: kontrak baru Draft -> surat kontrak -> TTD basah (scan) -> aktif."""
    from app.models.contract import ContractDocument

    run.step(client, f"{label}: buat surat kontrak", f"/customer-success/contracts/{contract_id}/generate-document")
    document_id = run.q(lambda: ContractDocument.query.filter_by(contract_id=contract_id)
                        .order_by(ContractDocument.id.desc()).first().id)
    run.step(client, f"{label}: tanda tangan basah (unggah scan bermeterai)",
             f"/customer-success/contracts/{contract_id}/documents/{document_id}/sign-wet",
             data={"scan_file": (io.BytesIO(b"%PDF-1.4 surat kontrak bermeterai %%EOF"), "kontrak_ttd.pdf")},
             content_type="multipart/form-data")
    run.step(client, f"{label}: aktifkan", f"/customer-success/contracts/{contract_id}/activate")
    return document_id


def _draft_contract_id(run, client_id):
    from app.models.contract import CustomerContract

    return run.q(lambda: CustomerContract.query.filter_by(client_id=client_id, status="DRAFT")
                 .order_by(CustomerContract.id.desc()).first().id)


def stage_contracts(run):
    from app.models.contract import CustomerContract
    from app.models.master import Client, ClientPic, Mandor, User
    from app.models.system import Notification
    from app.services.credit_control_service import check_internal_order_credit, resolve_due_date

    run.stage = "E. Kontrak berakhir"
    own, adm = run.client("owner.pilot"), run.client("admin.pilot")
    branch_id = run.q(lambda: User.query.filter_by(username="owner.pilot").one().branch_id)
    sinar = run.q(lambda: Client.query.filter_by(name="PT Sinar Beton").one().id)
    asep = run.q(lambda: Mandor.query.filter_by(name="Mandor Asep").one().id)
    pic = run.q(lambda: ClientPic.query.filter_by(client_id=sinar, is_active=True).first().id)

    run.step(own, "Kontrak PT Sinar net 30 yang berakhir kemarin", "/customer-success/contracts", data={
        "client_id": sinar, "client_pic_id": pic, "title": "Katering Batching Plant 2026",
        "start_date": (TODAY - timedelta(days=180)).isoformat(), "end_date": (TODAY - timedelta(days=1)).isoformat(),
        "payment_terms": "net 30", "credit_limit": "0"})
    _sign_and_activate(run, own, _draft_contract_id(run, sinar), "Kontrak PT Sinar")
    run.check("Termin kontrak aktif dipakai (net 30)",
              run.q(lambda: resolve_due_date(TODAY, branch_id=branch_id, client_id=sinar)) == TODAY + timedelta(days=30),
              "jatuh tempo invoice = 30 hari")
    run.step(adm, "Periksa Kontrak Sekarang (sama dengan sapuan harian otomatis)", "/customer-success/contracts/check")

    def contract_state():
        row = CustomerContract.query.filter_by(client_id=sinar).order_by(CustomerContract.id.desc()).first()
        lapsed = Notification.query.filter_by(generated_key=f"contract-lapsed:{branch_id}:{sinar}").first()
        return {"id": row.id, "status": row.status, "lapsed": lapsed.status if lapsed else None}

    state = run.q(contract_state)
    run.check("Kontrak lewat tanggal otomatis Kedaluwarsa + pemberitahuan mendesak",
              state["status"] == "EXPIRED" and state["lapsed"] == "UNREAD", state)
    run.check("Termin kembali ke bawaan 7 hari setelah kontrak berakhir",
              run.q(lambda: resolve_due_date(TODAY, branch_id=branch_id, client_id=sinar)) == TODAY + timedelta(days=7),
              "jatuh tempo invoice = 7 hari")

    def order_gate(role):
        ok, message, _ = check_internal_order_credit(branch_id=branch_id, mandor_id=asep, amount=500000, actor_role=role)
        return ok, message

    admin_gate, owner_gate = run.q(lambda: order_gate("ADMIN")), run.q(lambda: order_gate("OWNER"))
    run.check("Order Mandor Asep ditahan untuk ADMIN, diteruskan untuk OWNER",
              not admin_gate[0] and owner_gate[0], f"ADMIN: {admin_gate[1]} | OWNER: {owner_gate[1]}")

    run.step(adm, "Perpanjang kontrak PT Sinar 1 tahun", f"/customer-success/contracts/{state['id']}/renew", data={
        "start_date": TODAY.isoformat(), "end_date": (TODAY + timedelta(days=365)).isoformat(),
        "payment_terms": "net 30", "credit_limit": "0", "notes": "perpanjangan gladi"})
    state = run.q(contract_state)
    admin_gate = run.q(lambda: order_gate("ADMIN"))
    run.check("Setelah diperpanjang: order ADMIN jalan lagi, pemberitahuan selesai sendiri",
              state["status"] == "ACTIVE" and state["lapsed"] == "RESOLVED" and admin_gate[0], {**state, "admin_ok": admin_gate[0]})


# --- tahap F: pemeriksaan baseline (2 hari demo) ----------------------------

def stage_baseline_checks(run):
    import csv
    import json

    from sqlalchemy import text

    from app.extensions import db
    from app.models.system import AuditLog
    from app.services.readiness_service import FAIL, run_readiness_checks
    from tools.audit_financial_invariants import collect_results_from_database

    run.stage = "F. Pemeriksaan baseline (2 hari demo)"
    own = run.client("owner.pilot")

    balances = run.q(lambda: {code: Decimal(value) for code, value in db.session.execute(text(
        "SELECT a.account_code, COALESCE(SUM(d.debit), 0) - COALESCE(SUM(d.credit), 0) FROM accounts a "
        "JOIN journal_details d ON d.account_id = a.id GROUP BY a.account_code")).fetchall()})
    wrong = {code: (str(expected), str(balances.get(code, 0))) for code, expected in EXPECTED_BALANCES.items() if balances.get(code, Decimal(0)) != expected}
    extra = {code: str(value) for code, value in balances.items() if code not in EXPECTED_BALANCES and value}
    run.check("Saldo buku besar = hitungan manual (baseline)", not wrong and not extra,
              "semua akun cocok" if not wrong and not extra else f"beda {wrong} lain {extra}")
    run.check("Debit = kredit (baseline)", sum(balances.values()) == 0, f"selisih {sum(balances.values())}")

    from app.services.subledger_check_service import subledger_lines, unjournaled_stock_movements

    lines = run.q(lambda: [(line.label, line.ok, f"{line.ledger:,.0f}/{line.subledger:,.0f}") for line in subledger_lines()])
    run.check("Buku pembantu = buku besar (baseline)", all(ok for _, ok, _ in lines),
              "; ".join(f"{label} {amounts}" for label, _, amounts in lines))
    unjournaled = run.q(lambda: len(unjournaled_stock_movements()))
    run.check("Semua pergerakan stok dijurnal (baseline)", unjournaled == 0, f"{unjournaled} tanpa jurnal")

    violations = sum(len(result.violations) for result in collect_results_from_database())
    run.check("Audit rekonsiliasi baseline (audit_financial_invariants)", violations == 0, f"{violations} pelanggaran")

    def csv_rows(url):
        rows = list(csv.reader(io.StringIO(own.get(url).get_data(as_text=True)), delimiter=";"))
        return [row for row in rows[2:] if len(row) > 4]

    health = csv_rows("/accounting/data-health/export.csv")
    risks = [row[5:8] for row in health if row[4] == "RISIKO"]
    run.check("Cek Kesehatan Data: tidak ada RISIKO", not risks, f"{len(risks)} RISIKO {risks[:3]}")
    for day in (TODAY, D1, D2):
        closing = [row[5:8] for row in csv_rows(f"/accounting/daily-closing/export.csv?date={day.isoformat()}") if row[4] == "RISIKO"]
        run.check(f"Tutup Harian {day:%d-%m-%Y}: tidak ada RISIKO", not closing, f"{len(closing)} RISIKO {closing[:3]}")
    trial = run.text(own, "/accounting/reports/trial-balance/print")
    run.check("Neraca saldo (baseline)", "Status Neraca BALANCE" in trial, "BALANCE" if "Status Neraca BALANCE" in trial else "tidak balance")
    dashboard = run.text(own, "/dashboard/owner")
    run.check("Dashboard OWNER: Dua Jalur Transaksi tampil", "Dua Jalur Transaksi" in dashboard, "tampil" if "Dua Jalur Transaksi" in dashboard else "tidak tampil")

    def reasons(event_type):
        return run.q(lambda: [json.loads(row.metadata_json or "{}").get("reason") for row in AuditLog.query.filter_by(event_type=event_type).all()])
    price_reasons = reasons("PORTION_PRICE_SET")
    run.check("Audit log: perubahan harga punya alasan", price_reasons and all(price_reasons), f"{price_reasons}")
    refund_reasons = [r for r in reasons("ADVANCE_SETTLED") if r and ("ditolak" in r.lower() or "kurang kirim" in r.lower())]
    run.check("Audit log: pengembalian uang muka punya alasan", bool(refund_reasons), f"{refund_reasons}")
    lock_reasons = reasons("SENSITIVE_OPENING_BALANCE_LOCK_PASS")
    run.check("Audit log: penguncian saldo awal punya alasan", lock_reasons and all(lock_reasons), f"{lock_reasons}")
    override_reasons = reasons("PREPAYMENT_OVERRIDE")
    run.check("Audit log: pesanan diloloskan sebelum lunas punya alasan", override_reasons and all(override_reasons), f"{override_reasons}")

    from app.models.finance import Invoice
    from app.models.master import Mandor
    from app.models.operational import DailyOrder, DailyOrderDetail

    budi_invoice = run.q(lambda: Invoice.query.filter_by(source_type="PERIOD_INVOICE", mandor_id=Mandor.query.filter_by(name="Mandor Budi").one().id).one().invoice_number)
    pt_page = run.text(run.client("portal.maju"), "/portal/pt/invoices")
    run.check("Portal PT melihat invoice PT-nya", budi_invoice in pt_page, f"{budi_invoice} {'tampil' if budi_invoice in pt_page else 'tidak tampil'}")
    ordered = run.q(lambda: [(d.lunch_qty, d.dinner_qty) for d in DailyOrderDetail.query.join(DailyOrder, DailyOrder.id == DailyOrderDetail.daily_order_id)
                             .filter(DailyOrder.order_date == D2, DailyOrderDetail.mandor_id == Mandor.query.filter_by(name="Mandor Budi").one().id).all()])
    run.check("Pesanan Portal Mandor masuk order harian", ordered == [(42, 30)], f"{ordered}")
    joko_invoice = run.q(lambda: [(item.qty, item.description) for item in Invoice.query.filter_by(
        source_type="PERIOD_INVOICE", mandor_id=Mandor.query.filter_by(name="Mandor Joko").one().id).one().items])
    run.check("Kurang kirim tidak ditagih (Joko 23 dari 25)", any(float(qty) == 23 and "Kurang kirim 2" in desc for qty, desc in joko_invoice), f"{joko_invoice}")


# --- tahap G: Pengaturan kontrak (Fase 3) -------------------------------------

def stage_phase3_contracts(run, refs):
    from app.models.contract import CustomerContract
    from app.models.master import Client, ClientPic, User

    run.stage = "G. Pengaturan kontrak (Fase 3)"
    own, adm = run.client("owner.pilot"), run.client("admin.pilot")
    maju = run.q(lambda: Client.query.filter_by(name="PT Maju Konstruksi").one().id)
    pic = run.q(lambda: ClientPic.query.filter_by(client_id=maju, is_active=True).first().id)

    contract_data = {
        "client_id": maju,
        "client_pic_id": pic,
        "title": "Kontrak Katering PT Maju Konstruksi 2026",
        "start_date": (D4 - timedelta(days=14)).isoformat(),
        "end_date": (TODAY + timedelta(days=365)).isoformat(),
        "payment_terms": "Net 7",
        "credit_limit": "20000000",
        "lunch_lock_time": "10:00",
        "dinner_lock_time": "15:00",
        "weekly_holidays": ["7"],
        "default_billing_mode": "VIA_CLIENT",
        "billing_cycle": "BIWEEKLY",
        "billing_anchor_date": (D4 - timedelta(days=14)).isoformat(),
        "due_days": "7",
        "dispute_court": "PN_PANGKALAN_BALAI",
        "tazir_amount": "100000",
        "notes": "Kontrak aktif gladi pilot Fase 3",
    }
    run.step(own, "Buat kontrak PT Maju (Draft; jam lock, 14 hari, tempo 7 hari, ta'zir 100rb, PN Pangkalan Balai)",
             "/customer-success/contracts", data=contract_data)
    draft_id = _draft_contract_id(run, maju)

    # Fase 9: aktif hanya setelah surat kontrak ditandatangani.
    run.step(own, "Aktifkan sebelum surat ditandatangani (harus ditolak)",
             f"/customer-success/contracts/{draft_id}/activate", expect=("danger", "warning"))
    document_id = _sign_and_activate(run, own, draft_id, "Kontrak PT Maju")

    contract = run.q(lambda: CustomerContract.query.filter_by(client_id=maju, status="ACTIVE").order_by(CustomerContract.id.desc()).first())
    assert contract is not None, "Kontrak PT Maju harus aktif setelah ditandatangani"
    run.check("Kontrak baru aktif hanya setelah surat ditandatangani", contract.id == draft_id,
              f"kontrak {contract.contract_number} aktif, surat #{document_id} DITANDATANGANI")

    # Tambahkan 1 libur khusus lewat update rules
    run.step(adm, f"Atur aturan kontrak: libur rutin Minggu + libur khusus {D5:%d-%m-%Y}",
             f"/customer-success/contracts/{contract.id}/rules", data={
                 "lunch_lock_time": "10:00",
                 "dinner_lock_time": "15:00",
                 "weekly_holidays": ["7"],
                 "default_billing_mode": "VIA_CLIENT",
                 "billing_cycle": "BIWEEKLY",
                 "billing_anchor_date": (D4 - timedelta(days=14)).isoformat(),
                 "due_days": "7",
                 "dispute_court": "PN_PANGKALAN_BALAI",
                 "tazir_amount": "100000",
                 "holiday_dates": [D5.isoformat()],
                 "holiday_notes": ["Libur Khusus Gladi"],
             })

    info = run.q(lambda: (lambda c: {
        "status": c.status,
        "due_days": c.due_days,
        "tazir_amount": c.tazir_amount,
        "dispute_court": c.dispute_court,
        "weekly_holidays": c.weekly_holidays,
        "holidays_count": len(c.holidays),
    })(CustomerContract.query.get(contract.id)))
    run.check("Kontrak PT Maju aktif dengan aturan lengkap",
              info["status"] == "ACTIVE" and info["due_days"] == 7 and info["tazir_amount"] == Decimal("100000")
              and info["dispute_court"] == "PN_PANGKALAN_BALAI" and info["weekly_holidays"] == "7"
              and info["holidays_count"] == 1,
              f"Status: {info['status']}, Due: {info['due_days']}, Tazir: {info['tazir_amount']}, Court: {info['dispute_court']}, Holidays: {info['holidays_count']}")
    return contract.id


# --- tahap H: Pesanan otomatis (Fase 5) ---------------------------------------

def stage_phase5_auto_orders(run, refs, contract_id):
    from datetime import datetime, time
    from app.models.master import Mandor, User
    from app.models.operational import DailyOrder, DailyOrderDetail, OrderQtyChange
    from app.services.scheduler_service import run_job_now

    run.stage = "H. Pesanan otomatis (Fase 5)"
    branch_id = run.q(lambda: User.query.filter_by(username="owner.pilot").one().branch_id)
    budi = run.client("mandor.budi")
    budi_mandor_id = run.q(lambda: Mandor.query.filter_by(name="Mandor Budi").one().id)
    tol = _location(run, "Proyek Tol Km 12")

    # 1. Jalankan auto_daily_orders untuk tanggal D2 (membuat pesanan untuk D3)
    # Kemarin (D2): Mandor Budi punya pesanan siang 42 / malam 30.
    run.q(lambda: run_job_now("auto_daily_orders", branch_id=branch_id, period_key=D2.isoformat(),
                              now=datetime.combine(D2, time(18, 0))))

    order_d3 = run.q(lambda: (lambda o: {"id": o.id, "number": o.order_number} if o else None)(
        DailyOrder.query.filter_by(branch_id=branch_id, order_date=D3).first()))
    d3_detail = run.q(lambda: (lambda d: {"id": d.id, "lunch": d.lunch_qty, "dinner": d.dinner_qty} if d else None)(
        DailyOrderDetail.query.filter_by(daily_order_id=order_d3["id"], mandor_id=budi_mandor_id).first() if order_d3 else None))
    run.check("Pesanan besok (D3) otomatis terbentuk dari hari kerja terakhir (siang 42 / malam 30)",
              d3_detail is not None and d3_detail["lunch"] == 42 and d3_detail["dinner"] == 30,
              f"Order D3: {order_d3['number'] if order_d3 else None}, Siang {d3_detail['lunch'] if d3_detail else None}, Malam {d3_detail['dinner'] if d3_detail else None}")

    # 2. Hari libur khusus (D5) dilewati
    run.q(lambda: run_job_now("auto_daily_orders", branch_id=branch_id, period_key=(D5 - timedelta(days=1)).isoformat(),
                              now=datetime.combine(D5 - timedelta(days=1), time(18, 0))))
    d5_detail = run.q(lambda: DailyOrderDetail.query.join(DailyOrder, DailyOrder.id == DailyOrderDetail.daily_order_id)
                      .filter(DailyOrder.order_date == D5, DailyOrderDetail.mandor_id == budi_mandor_id).first())
    run.check("Hari libur khusus (D5) dilewati oleh pesanan otomatis",
              d5_detail is None, "Pesanan D5 tidak dibuat (libur)")

    # 3. Porsi 0 wajib alasan
    run.step(budi, "Portal Mandor Budi ubah porsi D3 jadi 0 tanpa alasan (harus ditolak)", "/portal/orders/update-qty", data={
        "mandor_id": budi_mandor_id, "delivery_location_id": tol["id"], "meal_type": "LUNCH",
        "order_date": D3.isoformat(), "new_qty": "0"}, expect=("danger", "warning"))

    run.step(budi, "Portal Mandor Budi ubah porsi D3 jadi 0 dengan alasan 'OFF_TODAY'", "/portal/orders/update-qty", data={
        "mandor_id": budi_mandor_id, "delivery_location_id": tol["id"], "meal_type": "LUNCH",
        "order_date": D3.isoformat(), "new_qty": "0", "reason_code": "OFF_TODAY", "note": "Pekerja libur hari ini"})

    qty_zero = run.q(lambda: DailyOrderDetail.query.filter_by(daily_order_id=order_d3["id"], mandor_id=budi_mandor_id).one().lunch_qty)
    has_audit = run.q(lambda: OrderQtyChange.query.filter_by(daily_order_detail_id=d3_detail["id"], reason_code="OFF_TODAY").count() > 0)
    run.check("Porsi berhasil diubah ke 0 dengan alasan tercatat di riwayat",
              qty_zero == 0 and has_audit, f"lunch_qty: {qty_zero}, audit logged: {has_audit}")

    # Setel porsi siang 35 dan malam 0 untuk pengiriman D3
    run.step(budi, "Portal Mandor Budi set porsi D3 siang 35 / malam 0 untuk operasional", "/portal/orders/update-qty", data={
        "mandor_id": budi_mandor_id, "delivery_location_id": tol["id"], "meal_type": "LUNCH",
        "order_date": D3.isoformat(), "new_qty": "35"})
    run.step(budi, "Portal Mandor Budi set malam 0 dengan alasan", "/portal/orders/update-qty", data={
        "mandor_id": budi_mandor_id, "delivery_location_id": tol["id"], "meal_type": "DINNER",
        "order_date": D3.isoformat(), "new_qty": "0", "reason_code": "OFF_TODAY", "note": "Tidak ada lembur malam"})


# --- tahap I: Dapur -> kirim -> scan terima (D3) ------------------------------

def stage_phase5_operations(run):
    from app.models.delivery import Delivery, DeliveryDetail, DeliveryReceipt
    from app.models.operational import DailyOrder
    from app.models.production import Production, ProductionDetail

    run.stage = "I. Dapur -> kirim -> scan terima (D3)"
    adm, dapur, antar = run.client("admin.pilot"), run.client("dapur.pilot"), run.client("antar.pilot")
    order_id = run.q(lambda: DailyOrder.query.filter_by(order_date=D3).one().id)
    run.step(adm, f"Kunci order {D3:%d-%m}", f"/operational/orders/{order_id}/lock", data={})

    for production_id, kind in run.q(lambda: [(p.id, p.production_type) for p in Production.query.filter_by(production_date=D3).all()]):
        planned = run.q(lambda: int(sum(row.planned_qty for row in ProductionDetail.query.filter_by(production_id=production_id).all())))
        if planned > 0:
            run.step(dapur, f"Dapur realisasi {kind} {planned} porsi", f"/production/{production_id}/realization",
                     data={"actual_qty": planned, "status": "COMPLETED", "notes": "gladi D3"})

    run.step(antar, "Pengantar buat pengiriman LUNCH D3", f"/delivery/create-from-order/{order_id}/LUNCH", data={})
    find = lambda: Delivery.query.filter(Delivery.delivery_date == D3, Delivery.notes.like("delivery_type=LUNCH;%")).first()
    delivery_id = run.q(lambda: (lambda row: row and row.id)(find()))
    assert delivery_id, "Pengiriman LUNCH D3 harus ada"

    run.step(antar, "Pengantar berangkat LUNCH D3", f"/delivery/{delivery_id}/dispatch", data={})

    details = run.q(lambda: [(row.id, row.delivery_location.location_name, int(row.planned_qty or 0))
                             for row in DeliveryDetail.query.filter_by(delivery_id=delivery_id).all()])
    for detail_id, location, planned in details:
        if "Tol Km 12" in location:
            run.step(antar, f"Tanda terima LUNCH {location}: {planned}/{planned}", f"/delivery/details/{detail_id}/receive", data={
                "delivered_qty": planned, "receiver_name": "Pak Mandor Budi", "notes": "diterima lengkap"})
        else:
            # Mandor Joko (Gudang Cikarang) sengaja tidak dicatat tanda terima agar ditunda ke invoice berikutnya
            pass

    budi_detail_id = [d[0] for d in details if "Tol Km 12" in d[1]][0]
    run.check("Tanda terima Mandor Budi LUNCH D3 tercatat",
              run.q(lambda: DeliveryReceipt.query.filter_by(delivery_detail_id=budi_detail_id).first() is not None),
              "Receipt Mandor Budi OK")


# --- tahap J: Invoice otomatis (Fase 6) ----------------------------------------

def stage_phase6_auto_invoices(run, refs):
    from datetime import datetime, time
    from app.models.accounting import Journal
    from app.models.finance import Invoice
    from app.models.master import Mandor, User
    from app.models.system import Notification
    from app.services.scheduler_service import run_job_now

    run.stage = "J. Invoice otomatis (Fase 6)"
    branch_id = run.q(lambda: User.query.filter_by(username="owner.pilot").one().branch_id)
    budi_mandor_id = run.q(lambda: Mandor.query.filter_by(name="Mandor Budi").one().id)
    joko_mandor_id = run.q(lambda: Mandor.query.filter_by(name="Mandor Joko").one().id)

    # 1. Jalankan auto_invoice_preview pada H-1 (D3, untuk hari potong D4)
    run.q(lambda: run_job_now("auto_invoice_preview", branch_id=branch_id, period_key=D3.isoformat(),
                              now=datetime.combine(D3, time(7, 0))))
    preview_notif = run.q(lambda: (lambda n: {"title": n.title} if n else None)(
        Notification.query.filter_by(branch_id=branch_id, notification_type="AUTO_INVOICE_PREVIEW").first()))
    run.check("Pratinjau invoice otomatis (H-1) memberi tahu admin & owner",
              preview_notif is not None, f"Notifikasi: {preview_notif['title'] if preview_notif else 'None'}")

    # 2. Jalankan auto_period_invoices pada hari potong H (D4)
    run.q(lambda: run_job_now("auto_period_invoices", branch_id=branch_id, period_key=D4.isoformat(),
                              now=datetime.combine(D4, time(6, 0))))

    # Cek: hanya pengiriman yang diterima ditagih (Mandor Budi: 35 porsi @ 16.000 = Rp560.000)
    budi_auto_inv = run.q(lambda: (lambda inv: {"id": inv.id, "number": inv.invoice_number, "total": inv.total_amount} if inv else None)(
        Invoice.query.filter(
            Invoice.branch_id == branch_id,
            Invoice.mandor_id == budi_mandor_id,
            Invoice.invoice_date == D4,
            Invoice.notes.ilike("%[Invoice otomatis]%"),
        ).first()))
    run.check("Invoice otomatis Mandor Budi terbit pada hari potong D4 (hanya pengiriman diterima)",
              budi_auto_inv is not None and budi_auto_inv["total"] == Decimal("560000"),
              f"Invoice: {budi_auto_inv['number'] if budi_auto_inv else None}, Total: {budi_auto_inv['total'] if budi_auto_inv else None}")

    # Cek: pengiriman Mandor Joko yang belum diterima TIDAK ditagih sekarang (ikut periode berikutnya)
    joko_auto_inv = run.q(lambda: Invoice.query.filter(
        Invoice.branch_id == branch_id,
        Invoice.mandor_id == joko_mandor_id,
        Invoice.invoice_date == D4,
        Invoice.notes.ilike("%[Invoice otomatis]%"),
    ).first() is not None)
    run.check("Pengiriman belum diterima (Mandor Joko) dilewati, ikut periode berikutnya",
              not joko_auto_inv, "Mandor Joko belum ditagih (sesuai aturan)")

    # Cek: jurnal piutang otomatis ada
    journal = run.q(lambda: (lambda j: {"id": j.id, "number": j.journal_number} if j else None)(
        Journal.query.filter_by(reference_type="INVOICE", reference_id=budi_auto_inv["id"]).first() if budi_auto_inv else None))
    run.check("Jurnal piutang invoice otomatis dibuat",
              journal is not None, f"Journal: {journal['number'] if journal else 'None'}")

    # Cek: notifikasi pihak ditagih (portal.maju) + salinan (mandor.budi)
    portal_maju_user = run.q(lambda: User.query.filter_by(username="portal.maju").one().id)
    mandor_budi_user = run.q(lambda: User.query.filter_by(username="mandor.budi").one().id)
    notif_billed = run.q(lambda: Notification.query.filter_by(target_user_id=portal_maju_user, notification_type="INVOICE_ISSUED").first() is not None)
    notif_copy = run.q(lambda: Notification.query.filter_by(target_user_id=mandor_budi_user, notification_type="INVOICE_COPY").first() is not None)
    run.check("Notifikasi pihak ditagih (INVOICE_ISSUED) dan salinan (INVOICE_COPY) terkirim",
              notif_billed and notif_copy,
              f"Billed: {notif_billed}, Copy: {notif_copy}")

    return budi_auto_inv["id"] if budi_auto_inv else None


# --- tahap K: Bayar 3 jalur ----------------------------------------------------

def stage_phase6_payments_3ways(run, refs, invoice_id):
    from app.extensions import db
    from app.models.finance import Invoice
    from app.models.system import DigitalAttachment
    from app.models.credit import PARTY_MANDOR
    from app.services.credit_control_service import get_credit_account

    run.stage = "K. Bayar 3 jalur (manual, bukti portal, potong deposit)"
    own, adm = run.client("owner.pilot"), run.client("admin.pilot")
    maju_portal = run.client("portal.maju")

    # Setel invoice_date ke TODAY agar pembayaran hari ini memenuhi validasi tanggal sistem
    def set_invoice_today():
        inv_row = db.session.get(Invoice, invoice_id)
        if inv_row:
            inv_row.invoice_date = TODAY
            db.session.commit()
    run.q(set_invoice_today)

    inv = run.q(lambda: (lambda i: {
        "id": i.id, "number": i.invoice_number, "mandor_id": i.mandor_id, "branch_id": i.branch_id
    })(Invoice.query.get(invoice_id)))
    assert inv is not None, "Invoice harus ada untuk bayar 3 jalur"

    # (a) Bayar manual sebagian: Rp200.000 tunai
    run.step(adm, f"Bayar manual sebagian: Rp200.000 tunai ke invoice {inv['number']}",
             f"/finance/invoices/{inv['id']}/payments/create", data={
                 "idempotency_key": uuid.uuid4().hex,
                 "payment_date": TODAY.isoformat(),
                 "payment_method": "CASH",
                 "amount": "200000",
                 "notes": "Bayar manual sebagian gladi",
             })

    # (b) Bukti transfer portal -> verifikasi -> pembayaran: Rp160.000 transfer BCA
    run.step(maju_portal, f"Portal PT Maju unggah bukti transfer Rp160.000 untuk {inv['number']}",
             f"/portal/invoices/{inv['id']}/payment", data={
                 "notes": "Transfer BCA sebagian Rp160.000",
                 "proof_file": (io.BytesIO(_png()), "transfer_bca.png"),
             }, content_type="multipart/form-data")

    attachment_id = run.q(lambda: (lambda a: a.id if a else None)(DigitalAttachment.query.filter_by(
        reference_type="INVOICE", reference_id=inv["id"]
    ).order_by(DigitalAttachment.id.desc()).first()))
    assert attachment_id is not None, "Attachment bukti transfer portal harus ada"

    run.step(adm, f"Finance verifikasi bukti transfer portal #{attachment_id}",
             f"/finance/portal-payment-proofs/{attachment_id}/decide", data={
                 "decision": "VERIFIED", "notes": "Mutasi BCA cocok gladi",
             })

    run.step(adm, "Finance catat pembayaran dari bukti portal Rp160.000",
             f"/finance/portal-payment-proofs/{attachment_id}/create-payment", data={
                 "payment_date": TODAY.isoformat(),
                 "amount": "160000",
                 "payment_method": "TRANSFER",
                 "bank_account_id": refs["bca"],
                 "reference_number": f"TRF-PORTAL-{attachment_id}",
                 "notes": "Pembayaran resmi dari verifikasi portal",
                 "idempotency_key": uuid.uuid4().hex,
             })

    # (c) Potong deposit: Mandor Budi disetel ditagih langsung, terima deposit Rp300.000, potong Rp200.000
    budi_mandor_id = inv["mandor_id"]
    run.step(own, "Owner setel syarat kredit Mandor Budi ke 'Ditagih langsung'",
             f"/credit/sub-client/{budi_mandor_id}/settings", data={
                 "billing_mode": "DIRECT",
                 "credit_limit": "5000000",
                 "payment_terms_days": "7",
                 "id_number": "3201010101010001",
                 "address": "Jl. Raya Tol Km 12, Bekasi",
                 "guarantor_name": "PT Maju Konstruksi",
                 "guarantor_phone": "021-555-0101",
                 "guarantor_id_number": "0123456789",
             })

    account_id = run.q(lambda: get_credit_account(inv["branch_id"], PARTY_MANDOR, budi_mandor_id).id)
    run.step(adm, "Admin terima deposit jaminan Mandor Budi Rp300.000 tunai",
             f"/credit/accounts/{account_id}/deposit", data={
                 "amount": "300000",
                 "deposit_date": TODAY.isoformat(),
                 "payment_method": "CASH",
                 "notes": "Deposit jaminan gladi",
             })

    run.step(own, f"Owner potong deposit Rp200.000 untuk melunasi sisa invoice {inv['number']}",
             f"/credit/accounts/{account_id}/deposit/apply", data={
                 "invoice_id": inv["id"],
                 "amount": "200000",
                 "notes": "Pelunasan sisa invoice dari deposit",
             })

    inv_after = run.q(lambda: (lambda i: {
        "paid": i.paid_amount, "remaining": i.remaining_amount, "status": i.status, "total": i.total_amount
    })(Invoice.query.get(inv["id"])))
    run.check("Invoice lunas setelah 3 jalur bayar (200rb manual + 160rb portal + 200rb deposit = 560rb)",
              inv_after["paid"] == Decimal("560000") and inv_after["remaining"] == Decimal("0") and inv_after["status"] == "PAID",
              f"Total: {inv_after['total']}, Paid: {inv_after['paid']}, Remaining: {inv_after['remaining']}, Status: {inv_after['status']}")


# --- tahap L: Kontrol kredit syariah (Fase 7) ----------------------------------

def stage_phase7_sharia_credit(run, refs):
    from datetime import datetime, time
    from app.extensions import db
    from app.models.accounting import Account, Journal, JournalDetail
    from app.models.credit import (
        CHARGE_IMPOSED, CHARGE_PROPOSED, CHARGE_TAZIR,
        PARTY_CLIENT, STATUS_BLOCKED, STATUS_HOLD, CreditCharge,
    )
    from app.models.finance import Invoice, InvoiceItem
    from app.models.master import Client, User
    from app.models.system import Notification
    from app.services.accounting_service import create_invoice_journal_for_invoice
    from app.services.credit_control_service import evaluate_party, get_credit_account
    from app.services.scheduler_service import run_job_now
    from app.services.sharia_credit_service import social_fund_summary

    run.stage = "L. Kontrol kredit syariah (Fase 7)"
    own, adm = run.client("owner.pilot"), run.client("admin.pilot")
    branch_id = run.q(lambda: User.query.filter_by(username="owner.pilot").one().branch_id)
    maju = run.q(lambda: Client.query.filter_by(name="PT Maju Konstruksi").one().id)

    # 1. Buat invoice overdue untuk PT Maju + janji bayar yang meleset
    overdue_due = TODAY - timedelta(days=10)
    def make_overdue():
        inv = Invoice(
            branch_id=branch_id,
            invoice_number=f"INV-OVERDUE-{uuid.uuid4().hex[:6]}",
            invoice_date=overdue_due - timedelta(days=7),
            due_date=overdue_due,
            bill_to_type="CLIENT",
            client_id=maju,
            customer_path="KONTRAK",
            total_amount=Decimal("1000000"),
            paid_amount=0,
            remaining_amount=Decimal("1000000"),
            status="OPEN",
            source_type="PERIOD_INVOICE",
            created_by=User.query.filter_by(username="admin.pilot").one().id,
        )
        db.session.add(inv)
        db.session.flush()
        db.session.add(InvoiceItem(
            invoice_id=inv.id,
            item_type="CATERING",
            description="Catering proyek overdue gladi",
            qty=100,
            unit_price=Decimal("10000"),
            subtotal=Decimal("1000000"),
            source_type="ORDER_DETAIL",
            source_id=1,
        ))
        db.session.flush()
        create_invoice_journal_for_invoice(inv, created_by=inv.created_by, commit=False)
        db.session.commit()
        return inv.id

    overdue_inv_id = run.q(make_overdue)
    overdue_number = run.q(lambda: Invoice.query.get(overdue_inv_id).invoice_number)

    run.step(adm, f"Catat janji bayar meleset untuk invoice overdue {overdue_number}",
             f"/finance/invoices/{overdue_inv_id}/collection/create", data={
                 "follow_up_date": (TODAY - timedelta(days=5)).isoformat(),
                 "promise_date": (TODAY - timedelta(days=2)).isoformat(),
                 "channel": "WHATSAPP",
                 "collection_status": "PROMISE_TO_PAY",
                 "contact_person": "Bapak Hendra",
                 "response_note": "Janji bayar 2 hari lalu meleset gladi",
                 "notes": "Janji bayar 2 hari lalu meleset gladi",
             })

    # 2. Jalankan sapuan kredit harian
    run.step(adm, "Periksa Kredit Sekarang (sapuan harian)", "/credit/sweep", expect=("success", "warning"))

    client_account = run.q(lambda: (lambda a: {"id": a.id, "status": a.status} if a else None)(
        get_credit_account(branch_id, PARTY_CLIENT, maju)))
    run.check("Status kredit PT Maju naik (TAHAN/BLOKIR)",
              client_account is not None and client_account["status"] in (STATUS_HOLD, STATUS_BLOCKED),
              f"Status: {client_account['status'] if client_account else None}")

    portal_maju_user = run.q(lambda: User.query.filter_by(username="portal.maju").one().id)
    notif_credit = run.q(lambda: (lambda n: {"title": n.title} if n else None)(
        Notification.query.filter_by(target_user_id=portal_maju_user, notification_type="CREDIT_STATUS").first()))
    run.check("Notifikasi kenaikan status kredit (CREDIT_STATUS) sampai ke portal client",
              notif_credit is not None, f"Notif: {notif_credit['title'] if notif_credit else None}")

    proposal = run.q(lambda: (lambda p: {"id": p.id, "amount": p.amount} if p else None)(
        CreditCharge.query.filter_by(branch_id=branch_id, charge_type=CHARGE_TAZIR, status=CHARGE_PROPOSED).first()))
    run.check("Usulan ta'zir otomatis muncul dengan nominal Rp100.000 sesuai kontrak",
              proposal is not None and proposal["amount"] == Decimal("100000"),
              f"Proposal: {proposal['id'] if proposal else None}, Nominal: {proposal['amount'] if proposal else None}")

    # 3. Owner 'Kenakan' -> tagihan ta'zir terpisah, jurnal ke 2009 (bukan pendapatan)
    run.step(own, f"Owner kenakan ta'zir #{proposal['id']} (tagihan terpisah -> 2009 Dana Sosial)",
             f"/credit/charges/{proposal['id']}/decide", data={
                 "decision": "IMPOSE", "note": "Kenakan ta'zir sesuai kontrak gladi", "notes": "Kenakan ta'zir sesuai kontrak gladi",
             })

    tazir_charge = run.q(lambda: (lambda c: {
        "status": c.status, "inv_id": c.invoice_id,
        "inv_number": c.invoice.invoice_number if c.invoice else None,
        "inv_source": c.invoice.source_type if c.invoice else None
    })(CreditCharge.query.get(proposal["id"])))
    run.check("Tagihan ta'zir terpisah terbit dengan source_type=TAZIR",
              tazir_charge["status"] == CHARGE_IMPOSED and tazir_charge["inv_id"] is not None and tazir_charge["inv_source"] == CHARGE_TAZIR,
              f"Status: {tazir_charge['status']}, Inv: {tazir_charge['inv_number']}")

    lines_2009 = run.q(lambda: db.session.query(Account.account_code, JournalDetail.credit)
                       .join(Journal, Journal.id == JournalDetail.journal_id)
                       .join(Account, Account.id == JournalDetail.account_id)
                       .filter(Journal.reference_type == "INVOICE", Journal.reference_id == tazir_charge["inv_id"], Account.account_code == "2009")
                       .first())
    run.check("Jurnal tagihan ta'zir masuk ke Cr 2009 Dana Sosial (bukan pendapatan)",
              lines_2009 is not None and Decimal(str(lines_2009[1])) == Decimal("100000"),
              f"Cr 2009: {lines_2009[1] if lines_2009 else None}")

    # 4. Kelonggaran menahan status di TAHAN
    run.step(own, "Owner catat kelonggaran untuk PT Maju sampai 14 hari ke depan",
             f"/credit/accounts/{client_account['id']}/grace", data={
                 "grace_until": (TODAY + timedelta(days=14)).isoformat(),
                 "grace_reason": "Kendala likuiditas proyek sementara gladi",
             })
    evaluated = run.q(lambda: (lambda a: (lambda ev: {"status": ev.status, "approval": ev.requires_approval})(
        evaluate_party(branch_id, PARTY_CLIENT, maju, a, today=TODAY)))(
        get_credit_account(branch_id, PARTY_CLIENT, maju)))
    run.check("Kelonggaran menahan status kredit maksimal di TAHAN (bayar di muka)",
              evaluated["status"] == STATUS_HOLD and evaluated["approval"] is True,
              f"Evaluated status: {evaluated['status']}, Approval: {evaluated['approval']}")

    # 5. Catat penyaluran Dana Sosial (hanya dari dana yang sudah dibayar)
    # Coba salurkan sebelum ta'zir dibayar (harus ditolak)
    run.step(own, "Owner salurkan Dana Sosial sebelum ada dana diterima (harus ditolak)",
             "/credit/social-fund/disburse", data={
                 "disbursed_on": TODAY.isoformat(),
                 "recipient": "Panti Asuhan Al-Kautsar",
                 "purpose": "Bantuan sembako",
                 "amount": "100000",
                 "account_type": "CASH",
                 "evidence": (io.BytesIO(_png()), "bukti_tolak.png"),
             }, content_type="multipart/form-data", expect=("warning", "danger"))

    # Pelanggan bayar tagihan ta'zir Rp100.000 tunai
    run.step(adm, f"Pelanggan bayar tagihan ta'zir {tazir_charge['inv_number']} Rp100.000 tunai",
             f"/finance/invoices/{tazir_charge['inv_id']}/payments/create", data={
                 "idempotency_key": uuid.uuid4().hex,
                 "payment_date": TODAY.isoformat(),
                 "payment_method": "CASH",
                 "amount": "100000",
                 "notes": "Pelunasan tagihan ta'zir gladi",
             })

    # Owner salurkan Dana Sosial Rp100.000 tunai dengan bukti
    run.step(own, "Owner catat penyaluran Dana Sosial Rp100.000 ke Panti Asuhan Al-Kautsar",
             "/credit/social-fund/disburse", data={
                 "disbursed_on": TODAY.isoformat(),
                 "recipient": "Panti Asuhan Al-Kautsar",
                 "purpose": "Bantuan beras untuk anak yatim gladi",
                 "amount": "100000",
                 "account_type": "CASH",
                 "evidence": (io.BytesIO(_png()), "bukti_salur.png"),
             }, content_type="multipart/form-data")

    fund = run.q(lambda: social_fund_summary(branch_id))
    run.check("Ringkasan Dana Sosial: diterima Rp100.000, disalurkan Rp100.000, sisa Rp0",
              fund["collected"] == Decimal("100000") and fund["disbursed"] == Decimal("100000") and fund["available"] == Decimal("0"),
              f"Collected: {fund['collected']}, Disbursed: {fund['disbursed']}, Available: {fund['available']}")


# --- tahap M: Cek tagihan dobel ------------------------------------------------

def stage_phase6_double_billing_guard(run):
    from app.models.master import Mandor
    from app.models.operational import DailyOrder

    run.stage = "M. Cek tagihan dobel"
    adm = run.client("admin.pilot")
    order_d3 = run.q(lambda: DailyOrder.query.filter_by(order_date=D3).one().id)
    budi_mandor_id = run.q(lambda: Mandor.query.filter_by(name="Mandor Budi").one().id)

    # Coba buat invoice per pesanan untuk pesanan D3 Mandor Budi yang sudah masuk invoice otomatis
    run.step(adm, "Buat invoice per pesanan untuk pesanan yang sudah ditagih otomatis (harus ditolak)",
             f"/finance/invoices/generate-order/{order_d3}/{budi_mandor_id}",
             expect=("warning", "danger"))



# --- tahap O: SDM, kasbon, penggajian, slip/kwitansi, PPh 21 (2026-10-12) ----------

def _signature_png():
    """Goresan tanda tangan palsu yang cukup besar untuk lolos validasi."""
    import base64

    size = 48
    raw = b"".join(b"\x00" + bytes(((x * 31 + y * 17) ^ (x * y)) % 256 for x in range(size * 3)) for y in range(size))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 0)) + chunk(b"IEND", b""))
    return png, "data:image/png;base64," + base64.b64encode(png).decode()


def stage_hr_payroll(run):
    """Satu bulan SDM lewat halaman asli: aturan, karyawan, kontrak bertanda tangan, apel, izin, mangkir,
    denda, kasbon, penggajian dengan PPh 21, bayar, slip, kwitansi, setor PPh 21 -- lalu cek jurnalnya."""
    from sqlalchemy import text
    from app.extensions import db
    from app.models.finance import BankAccount
    from app.models.hr import Payroll, PayrollDetail
    from app.models.master import Employee
    from app.models.workforce import EmployeeCharge, EmploymentContract, PayrollReceipt
    from app.services.tax_service import build_tax_month

    run.stage = "O. SDM, kasbon, penggajian & PPh 21"
    own, adm = run.client("owner.pilot"), run.client("admin.pilot")
    png, signature = _signature_png()
    period_day = TODAY - timedelta(days=62)
    if period_day.month == 12:  # Desember = masa tahunan; gladi memakai masa TER biasa
        period_day = TODAY - timedelta(days=93)
    p_start = period_day.replace(day=1)
    branch_id = run.q(lambda: Employee.query.session.execute(text("SELECT id FROM branches WHERE code = 'PILOT'")).scalar())
    bca = run.q(lambda: BankAccount.query.filter_by(branch_id=branch_id, bank_name="BCA").first().id)

    def balances():
        return run.q(lambda: {code: Decimal(value) for code, value in db.session.execute(text(
            "SELECT a.account_code, COALESCE(SUM(d.debit), 0) - COALESCE(SUM(d.credit), 0) FROM accounts a "
            "JOIN journal_details d ON d.account_id = a.id GROUP BY a.account_code")).fetchall()})

    before = balances()

    run.step(own, "Owner atur aturan gaji & potongan (izin + tanpa ket. dipotong, ÷30, denda)", "/sdm/aturan", data={
        "unpaid_status": ["IZIN", "ALPA"], "hr.daily_wage_divisor": "30", "hr.fine_absent_per_day": "50000",
        "hr.fine_leave_site": "100000", "hr.fine_late_return_per_day": "50000", "hr.fine_short_notice": "200000",
        "hr.max_deduction_percent": "50", "hr.notice_days": "30", "hr.deemed_resign_days": "5", "hr.portions_per_worker": "60",
        "hr.employer_signer_name": "Owner Pilot", "hr.employer_signer_position": "Direktur", "hr.work_location": "Dapur Pilot",
    })
    for name, nik, kind, ptkp in (("Rina Juru Masak", "1602000000009001", "KARYAWAN", "K/1"),
                                  ("Tono Pengemas", "1602000000009002", "KARYAWAN", "TK/0"),
                                  ("Dodi Cadangan", "1602000000009003", "CADANGAN", "")):
        run.step(adm, f"Tambah karyawan {name}", "/hr/employees/create", data={
            "full_name": name, "nik": nik, "phone": "081200009" + nik[-3:], "employee_type": kind, "position": "Dapur",
            "address": "Desa Pilot", "join_date": p_start.isoformat(), "ptkp_status": ptkp, "salary_amount": "",
        })
    ids = run.q(lambda: {e.full_name: e.id for e in Employee.query.filter(Employee.nik.like("160200000000900%")).all()})

    for name, ctype, salary, end in (("Rina Juru Masak", "PKWT", "8000000", (p_start + timedelta(days=364)).isoformat()),
                                     ("Tono Pengemas", "PKWTT", "3000000", "")):
        run.step(adm, f"Buat kontrak {ctype} {name}", "/sdm/kontrak/baru", data={
            "employee_id": ids[name], "contract_type": ctype, "position": "Dapur", "start_date": p_start.isoformat(),
            "end_date": end, "probation_months": "0", "monthly_salary": salary,
        })
        contract_id = run.q(lambda n=name: EmploymentContract.query.filter_by(employee_id=ids[n]).order_by(EmploymentContract.id.desc()).first().id)
        run.step(adm, f"{name} tanda tangan kontrak di HP + foto KTP", f"/sdm/kontrak/{contract_id}/ttd-karyawan", data={
            "typed_name": name, "agree": "1", "signature_data": signature, "ktp_photo": (io.BytesIO(png), "ktp.png"),
        }, content_type="multipart/form-data")
        run.step(own, f"Owner tanda tangan kontrak {name}", f"/sdm/kontrak/{contract_id}/ttd-perusahaan", data={"signature_data": signature})
        if ctype == "PKWT":
            run.step(adm, "Catat pencatatan PKWT ke Disnaker", f"/sdm/kontrak/{contract_id}/disnaker",
                     data={"registered_at": TODAY.isoformat(), "reference": "DISNAKER/GLADI/001"})

    day1, day2 = TODAY - timedelta(days=2), TODAY - timedelta(days=1)
    run.step(adm, "Apel: Tono tanpa keterangan (kasus mangkir terbuka)", "/sdm/apel", data={
        "tanggal": day1.isoformat(), f"status_{ids['Rina Juru Masak']}": "HADIR", f"status_{ids['Tono Pengemas']}": "ALPA",
    })
    run.step(adm, "Apel: Tono kembali (denda diusulkan)", "/sdm/apel", data={
        "tanggal": day2.isoformat(), f"status_{ids['Rina Juru Masak']}": "HADIR", f"status_{ids['Tono Pengemas']}": "HADIR",
    })
    run.step(adm, "Izin pulang kampung Rina (dicatat admin = langsung disetujui)", "/sdm/izin/baru", data={
        "employee_id": ids["Rina Juru Masak"], "leave_type": "PULANG_KAMPUNG", "start_date": D1.isoformat(),
        "expected_return_date": D3.isoformat(), "reason": "Keluarga hajatan",
    })
    fines = run.q(lambda: [(c.id, int(c.amount)) for c in EmployeeCharge.query.filter_by(employee_id=ids["Tono Pengemas"], status="DIUSULKAN").all()])
    run.check("Mangkir 1 hari -> 2 usulan denda (50.000 + 100.000)", sorted(a for _, a in fines) == [50000, 100000], str(fines))
    for charge_id, amount in fines:
        run.step(own, f"Owner setujui denda {amount}", f"/sdm/denda/{charge_id}/setujui", data={"amount": str(amount)})

    run.step(adm, "Ajukan kasbon Tono 600.000 cicil 300.000 (ttd karyawan)", "/sdm/kasbon/baru", data={
        "employee_id": ids["Tono Pengemas"], "amount": "600000", "installment": "300000", "reason": "Biaya berobat",
        "account_type": "BANK", "bank_account_id": bca, "typed_name": "Tono Pengemas", "signature_data": signature,
    })
    advance_id = run.q(lambda: EmployeeCharge.query.filter_by(employee_id=ids["Tono Pengemas"], charge_type="KASBON").one().id)
    run.step(own, "Owner setujui & cairkan kasbon dari BCA", f"/sdm/denda/{advance_id}/setujui",
             data={"amount": "600000", "next": "/sdm/kasbon"})

    run.step(own, "Owner aktifkan PPh 21 (dipotong dari gaji, TER diverifikasi)", "/finance/tax/settings", data={
        "tax.pph21_enabled": "1", "tax.pph21_effective_from": p_start.isoformat(), "tax.pph21_borne_by": "KARYAWAN",
        "tax.pph21_ter_verified": "1", "tax.pbjt_rate": "10", "tax.pbjt_due_day": "15",
    })
    run.step(adm, f"Buat penggajian {p_start:%m-%Y}", "/hr/payrolls/generate",
             data={"period_month": p_start.month, "period_year": p_start.year})
    payroll_id = run.q(lambda: Payroll.query.filter_by(branch_id=branch_id, period_month=p_start.month, period_year=p_start.year).one().id)
    run.step(adm, "Hitung ulang potongan", f"/hr/payrolls/{payroll_id}/sync-workforce")
    lines = run.q(lambda: {d.employee.full_name: (int(d.final_salary), int(d.pph21_amount or 0), int(d.charge_deduction or 0), d.ter_category)
                           for d in PayrollDetail.query.filter_by(payroll_id=payroll_id).all()})
    run.check("Penggajian: Rina 8 jt TER B 1% = 80.000 -> 7.920.000; Tono 3 jt - denda 150.000 - cicilan kasbon 300.000 = 2.550.000; cadangan tidak ikut",
              lines == {"Rina Juru Masak": (7920000, 80000, 0, "B"), "Tono Pengemas": (2550000, 0, 450000, "A")}, str(lines))
    run.step(adm, "Kunci penggajian", f"/hr/payrolls/{payroll_id}/finalize")
    run.step(adm, "Catat hutang gaji (jurnal)", f"/hr/payrolls/{payroll_id}/post-journal")
    run.step(adm, "Bayar gaji transfer BCA", f"/hr/payrolls/{payroll_id}/pay", data={"payment_method": "TRANSFER", "bank_account_id": bca})

    detail_ids = run.q(lambda: {d.employee.full_name: d.id for d in PayrollDetail.query.filter_by(payroll_id=payroll_id).all()})
    run.step(adm, "Cetak semua slip", f"/hr/slip/penggajian/{payroll_id}", method="GET")
    slip = run.text(adm, f"/hr/slip/{detail_ids['Rina Juru Masak']}")
    run.check("Slip Rina memuat PPh 21 TER B dan gaji bersih", "PPh 21 (TER kategori B" in slip and "Rp 7.920.000" in slip, slip[:0] or "cek teks slip")
    run.step(adm, "Kirim link slip Tono lewat WhatsApp", f"/hr/slip/{detail_ids['Tono Pengemas']}/whatsapp")
    run.step(adm, "Tono tanda tangan kwitansi terima gaji di HP", f"/hr/slip/{detail_ids['Tono Pengemas']}/kwitansi/ttd",
             data={"typed_name": "Tono Pengemas", "signature_data": signature})
    run.step(adm, "Kwitansi Rina ditandai TTD kertas", f"/hr/slip/{detail_ids['Rina Juru Masak']}/kwitansi/manual", data={})
    run.check("2 kwitansi tercatat", run.q(lambda: PayrollReceipt.query.filter_by(payroll_id=payroll_id).count()) == 2, "")

    run.step(own, "Setor PPh 21 masa penggajian dari BCA", "/finance/tax/payments", data={
        "tax_type": "PPH21", "amount": "80000", "reference_number": "NTPN-GLADI-PPH21", "paid_on": TODAY.isoformat(),
        "period_year": p_start.year, "period_month": p_start.month, "account_type": "BANK", "bank_account_id": bca,
    })
    report = run.q(lambda: build_tax_month(branch_id, p_start.year, p_start.month))
    run.check("Laporan pajak masa: PPh 21 terutang 80.000, disetor 80.000, sisa 0",
              (report["pph21_due"], report["pph21_paid"], report["pph21_to_pay"]) == (Decimal("80000"), Decimal("80000"), 0),
              f"{report['pph21_due']}/{report['pph21_paid']}/{report['pph21_to_pay']}")
    statuses = run.q(lambda: sorted((c.charge_type, c.status, int(c.deducted_amount)) for c in EmployeeCharge.query.filter_by(employee_id=ids["Tono Pengemas"]).all()))
    run.check("Denda lunas terpotong; kasbon tinggal 300.000", statuses == [("DENDA", "LUNAS", 50000), ("DENDA", "LUNAS", 100000), ("KASBON", "AKTIF", 300000)], str(statuses))

    after = balances()
    delta = {code: after.get(code, Decimal(0)) - before.get(code, Decimal(0)) for code in ("1001", "1002", "1005", "2003", "2011", "4004", "5004")}
    expected = {"1001": Decimal(0), "1002": Decimal("-11150000"), "1005": Decimal("300000"), "2003": Decimal(0),
                "2011": Decimal(0), "4004": Decimal("-150000"), "5004": Decimal("11000000")}
    run.check("Jurnal SDM: BCA -11.150.000 (kasbon+gaji+PPh21), piutang karyawan +300.000, denda 150.000, beban gaji 11.000.000, hutang gaji & PPh 21 nol",
              delta == expected, "; ".join(f"{k} {v:,.0f}" for k, v in delta.items()))
    for url in ("/sdm/", "/sdm/kasbon", "/sdm/laporan", "/sdm/aturan/peraturan-perusahaan", "/finance/tax"):
        run.step(own, f"Halaman {url} terbuka", url, method="GET")


# --- tahap N: Pemeriksaan akhir integrasi (Stage 8) ---------------------------

def stage_final_checks(run, backup):
    import csv
    from decimal import Decimal
    from sqlalchemy import text
    from app.extensions import db
    from app.models.finance import Invoice, Payment, AdvanceSettlement
    from app.models.accounting import Journal
    from app.services.readiness_service import FAIL, run_readiness_checks
    from app.services.subledger_check_service import subledger_lines, unjournaled_stock_movements
    from tools.audit_financial_invariants import collect_results_from_database

    run.stage = "N. Pemeriksaan akhir integrasi"
    own = run.client("owner.pilot")

    # 1. Buku besar = buku pembantu (subledger_check_service) selisih 0
    lines = run.q(lambda: [(line.label, line.ok, f"{line.ledger:,.0f}/{line.subledger:,.0f}") for line in subledger_lines()])
    run.check("Buku besar = buku pembantu (subledger_check_service selisih 0)",
              all(ok for _, ok, _ in lines),
              "; ".join(f"{label} {amounts}" for label, _, amounts in lines))

    # 2. Tidak ada invoice tanpa jurnal (kecuali OPENING_BALANCE)
    unjournaled_invoices = run.q(lambda: [
        inv.invoice_number for inv in Invoice.query.filter(Invoice.source_type != "OPENING_BALANCE").all()
        if not Journal.query.filter_by(reference_type="INVOICE", reference_id=inv.id).first()
    ])
    run.check("Tidak ada invoice tanpa jurnal (kecuali OPENING_BALANCE)",
              len(unjournaled_invoices) == 0,
              f"{len(unjournaled_invoices)} invoice tanpa jurnal: {unjournaled_invoices[:3]}")

    # 3. Tidak ada jurnal tidak seimbang
    unbalanced_journals = run.q(lambda: db.session.execute(text(
        "SELECT journal_id, SUM(debit) - SUM(credit) FROM journal_details GROUP BY journal_id HAVING SUM(debit) != SUM(credit)"
    )).fetchall())
    run.check("Tidak ada jurnal tidak seimbang",
              len(unbalanced_journals) == 0,
              f"{len(unbalanced_journals)} jurnal tidak seimbang: {unbalanced_journals}")

    # 4. paid_amount = pembayaran + potongan DP/deposit per invoice
    mismatched_invoices = []
    invoices_to_check = run.q(lambda: [(inv.id, inv.invoice_number, Decimal(str(inv.paid_amount or 0))) for inv in Invoice.query.all()])
    for inv_id, inv_num, actual_paid in invoices_to_check:
        pmts = run.q(lambda i=inv_id: sum(Decimal(str(p.amount or 0)) for p in Payment.query.filter_by(invoice_id=i).all()))
        stls = run.q(lambda i=inv_id: sum(Decimal(str(s.amount or 0)) for s in AdvanceSettlement.query.filter(
            AdvanceSettlement.reference_id == i,
            AdvanceSettlement.settlement_type.in_(["DEPOSIT_TO_INVOICE", "CLIENT_INVOICE"])
        ).all()))
        expected_paid = pmts + stls
        if expected_paid != actual_paid:
            mismatched_invoices.append((inv_num, str(actual_paid), str(expected_paid)))
    run.check("paid_amount = pembayaran + potongan DP/deposit per invoice",
              len(mismatched_invoices) == 0,
              f"{len(mismatched_invoices)} invoice mismatch: {mismatched_invoices[:3]}")

    # 5. Debit = kredit total
    balances = run.q(lambda: {code: Decimal(value) for code, value in db.session.execute(text(
        "SELECT a.account_code, COALESCE(SUM(d.debit), 0) - COALESCE(SUM(d.credit), 0) FROM accounts a "
        "JOIN journal_details d ON d.account_id = a.id GROUP BY a.account_code")).fetchall()})
    run.check("Total Debit = Total Kredit", sum(balances.values()) == 0, f"selisih {sum(balances.values())}")

    # 6. Audit rekonsiliasi finansial
    violations = sum(len(result.violations) for result in collect_results_from_database())
    run.check("Audit rekonsiliasi (audit_financial_invariants): 0 pelanggaran", violations == 0, f"{violations} pelanggaran")

    # 7. Cek Kesehatan Data & Tutup Harian
    def csv_rows(url):
        rows = list(csv.reader(io.StringIO(own.get(url).get_data(as_text=True)), delimiter=";"))
        return [row for row in rows[2:] if len(row) > 4]

    health = csv_rows("/accounting/data-health/export.csv")
    risks = [row[5:8] for row in health if row[4] == "RISIKO"]
    run.check("Cek Kesehatan Data: 0 RISIKO", not risks, f"{len(risks)} RISIKO")
    for day in (TODAY, D1, D2, D3, D4):
        closing = [row[5:8] for row in csv_rows(f"/accounting/daily-closing/export.csv?date={day.isoformat()}") if row[4] == "RISIKO"]
        run.check(f"Tutup Harian {day:%d-%m-%Y}: 0 RISIKO", not closing, f"{len(closing)} RISIKO {closing[:3]}")

    # 8. Neraca saldo
    trial = run.text(own, "/accounting/reports/trial-balance/print")
    run.check("Neraca Saldo: BALANCE", "Status Neraca BALANCE" in trial, "BALANCE" if "Status Neraca BALANCE" in trial else "tidak balance")

    # 9. Backup penuh
    if backup:
        from app.services.backup_service import create_full_backup_package, verify_full_backup_package
        package = run.q(lambda: create_full_backup_package(created_by="GLADI"))
        verified = run.q(lambda: verify_full_backup_package(package["path"]))
        run.check("Backup penuh", verified["status"] == "PASS", f"{verified['status']} {package['name']}")

    # 10. ops-check: 0 FAIL
    results = run.q(lambda: run_readiness_checks())
    failed = [f"{row.name}: {row.message}" for row in results if row.status == FAIL]
    warned = [f"{row.name}: {row.message}" for row in results if row.status == "WARN"]
    run.check("ops-check: 0 FAIL", not failed, f"{len(results)} cek, FAIL {failed}, WARN {warned}")


def _clean_gladi_db(app):
    from sqlalchemy import text
    from app.extensions import db
    from app.services.bootstrap_service import bootstrap_company

    print("[INFO] Membersihkan database gladi ke kondisi awal bootstrap...")
    with app.app_context():
        with db.engine.connect() as conn:
            tables = [r[0] for r in conn.execute(text("""
                SELECT table_name FROM information_schema.tables 
                WHERE table_schema = 'public' 
                  AND table_type = 'BASE TABLE'
                  AND table_name NOT IN ('branches', 'accounts', 'alembic_version', 'users')
                ORDER BY table_name;
            """)).fetchall()]
            table_list = ", ".join(f'"{t}"' for t in tables)

        with db.engine.begin() as conn:
            conn.execute(text(f"TRUNCATE TABLE {table_list} CASCADE;"))
            conn.execute(text("DELETE FROM users;"))

        bootstrap_company(
            branch_code="PILOT",
            branch_name="Cabang Pilot",
            owner_username="owner.pilot",
            owner_full_name="Owner Pilot",
            owner_password=OWNER_PASSWORD,
        )
    print("[INFO] Database gladi bersih, siap gladi!")


def write_report(run, path):
    lines = [f"# Hasil gladi pilot {TODAY:%d-%m-%Y}", "",
             f"Database: `{os.environ['DATABASE_URL'].rsplit('/', 1)[-1]}`. Hari operasional: {D1:%d-%m-%Y} s/d {D4:%d-%m-%Y}.", "",
             "## Pemeriksaan", "", "| Hasil | Pemeriksaan | Rincian |", "| --- | --- | --- |"]
    lines += [f"| {'LULUS' if ok else 'GAGAL'} | {label} | {str(detail)[:300].replace('|', '/')} |" for label, ok, detail in run.checks]
    stage = None
    for name, label, ok, status, messages in run.steps:
        if name != stage:
            stage = name
            lines += ["", f"## {name}", "", "| | Langkah | Pesan sistem |", "| --- | --- | --- |"]
        text = " / ".join(message for _category, message in messages)[:240].replace("|", "/")
        lines.append(f"| {'OK' if ok else 'GAGAL'} | {label} | {text or f'HTTP {status}'} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--db", default="idha_boga_pilot")
    parser.add_argument("--output", type=Path, default=ROOT / "instance" / "gladi_pilot_hasil.md")
    parser.add_argument("--backup", action="store_true", help="Buat backup penuh (butuh pg_dump / PG_DUMP_PATH) sebelum ops-check.")
    args = parser.parse_args()
    if not re.search(r"pilot|gladi", args.db):
        raise SystemExit("Gladi hanya boleh di database yang namanya mengandung 'pilot' atau 'gladi'.")

    from dotenv import dotenv_values

    base = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    target_url = base.rsplit("/", 1)[0] + "/" + args.db
    os.environ["DATABASE_URL"] = target_url

    if "PG_DUMP_PATH" not in os.environ:
        laragon_pg_dump = Path(r"C:\laragon\bin\postgresql\postgresql-11.0-1\bin\pg_dump.exe")
        if laragon_pg_dump.exists():
            os.environ["PG_DUMP_PATH"] = str(laragon_pg_dump)

    from config import Config
    Config.SQLALCHEMY_DATABASE_URI = target_url

    from app import create_app
    from app.models.master import User

    app = create_app()
    app.config["SQLALCHEMY_DATABASE_URI"] = target_url
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    run = DryRun(app)
    if run.q(lambda: User.query.filter_by(username="admin.pilot").first()):
        _clean_gladi_db(app)

    refs = stage_setup(run)
    stage_orders(run, refs)
    stage_operations(run, D1, shortage={"Gudang Cikarang": 2, "Kantor Notaris": 1})
    stage_operations(run, D2)
    stage_billing(run, refs)
    stage_one_step(run, refs)
    stage_contracts(run)
    stage_baseline_checks(run)

    # Stage baru Fase 3-7 + audit integrasi
    contract_id = stage_phase3_contracts(run, refs)
    stage_phase5_auto_orders(run, refs, contract_id)
    stage_phase5_operations(run)
    auto_inv_id = stage_phase6_auto_invoices(run, refs)
    stage_phase6_payments_3ways(run, refs, auto_inv_id)
    stage_phase7_sharia_credit(run, refs)
    stage_phase6_double_billing_guard(run)
    stage_hr_payroll(run)
    stage_final_checks(run, args.backup)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(run, args.output)
    failed_steps = [label for _stage, label, ok, _status, _messages in run.steps if not ok]
    failed_checks = [label for label, ok, _detail in run.checks if not ok]
    print(f"\n{len(run.steps) - len(failed_steps)}/{len(run.steps)} langkah OK, "
          f"{len(run.checks) - len(failed_checks)}/{len(run.checks)} pemeriksaan lulus. Laporan: {args.output}")
    raise SystemExit(1 if failed_steps or failed_checks else 0)


if __name__ == "__main__":
    main()
