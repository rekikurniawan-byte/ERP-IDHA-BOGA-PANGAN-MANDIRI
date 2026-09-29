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

OWNER_PASSWORD = os.environ.get("PILOT_OWNER_PASSWORD", "PilotOwner#2026")
USER_PASSWORD = "PilotUser#2026"
TODAY = date.today()
D1, D2 = TODAY + timedelta(days=1), TODAY + timedelta(days=2)

# Hitungan manual skenario di bawah (harga standar 18.000, kontrak PT Maju 16.000,
# ongkir Dekat 10.000 / Jauh 25.000 / kontrak PT Sinar 15.000 per trip).
# Kurang kirim yang tidak diganti tidak ditagih (keputusan owner 2026-09-28):
# Gudang Cikarang (Joko) kurang 2 dari 25, Kantor Notaris (Sari) kurang 1 dari 20.
EXPECTED_BALANCES = {
    "1001": Decimal("5405000"),     # 5.000.000 awal + 200.000 Joko + 205.000 Dedi D2 tunai
    "1002": Decimal("28335000"),    # 25.000.000 + 1.271.000 uang muka - 190.000 refund ditolak - 18.000 refund kurang kirim + 2.272.000 Budi
    "1004": Decimal("1596000"),     # sisa Joko 368.000 - 200.000 + Asep 1.428.000
    "1006": Decimal("3500000"),
    "1101": Decimal("30000000"),
    "2002": Decimal("-2000000"),
    "2008": Decimal("0"),
    "3001": Decimal("-61500000"),
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
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00")) + chunk(b"IEND", b""))


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
        run.step(adm, f"Lokasi {location}", "/master/locations/create", data={"mandor_id": mandor_id, "location_name": location, "is_active": "on"})
    for driver in ("Pak Ujang", "Pak Karim"):
        run.step(adm, f"Pengantar {driver}", "/master/drivers/create", data={"name": driver, "phone": "0814000000", "license_number": "SIM-A", "is_active": "on"})

    budi = run.q(lambda: Mandor.query.filter_by(name="Mandor Budi").one().id)
    portal = {"branch_id": branch_id, "is_active": "on", "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD, **guard}
    run.step(own, "Akun Portal PT tanpa memilih PT (harus ditolak)", "/settings/users/create", data={
        "full_name": "Portal PT Maju", "username": "portal.maju", "role": "PORTAL_CLIENT", **portal}, expect=("warning",))
    run.step(own, "Akun Portal PT dihubungkan ke PT Maju", "/settings/users/create", data={
        "full_name": "Portal PT Maju", "username": "portal.maju", "role": "PORTAL_CLIENT", "portal_client_id": maju, **portal})
    run.step(own, "Akun Portal Mandor dihubungkan ke Mandor Budi", "/settings/users/create", data={
        "full_name": "Mandor Budi", "username": "mandor.budi", "role": "PORTAL_SUBCLIENT", "portal_mandor_id": budi, **portal})

    anon = run.client()
    for index, (full_name, username, zone, location, address) in enumerate((
        ("Ibu Rina", "rina.cust", "Dekat (< 5 km)", "Rumah Bu Rina", "Perum Graha Asri Blok C2, Cikarang"),
        ("Pak Dedi", "dedi.cust", "Jauh (5-15 km)", "Kantor Pak Dedi", "Ruko Sentra Niaga No. 5, Cibitung"),
        ("Kantor Notaris Sari", "sari.cust", "Dekat (< 5 km)", "Kantor Notaris", "Jl. Kasuari No. 3, Cikarang"),
    )):
        run.step(anon, f"Pelanggan umum daftar sendiri: {full_name}", "/portal/register", data={
            "full_name": full_name, "phone": f"08157000{index}{index}{index}", "username": username, "branch_id": branch_id,
            "password": USER_PASSWORD, "password_confirmation": USER_PASSWORD, "location_name": location,
            "delivery_zone_id": zones[zone], "address": address, "notes": "gerbang biru"})

    run.step(own, "Akuntansi > Saldo Awal (jurnal)", "/accounting/opening-balance", data={
        "journal_date": TODAY.isoformat(), "cash": "5000000", "bank1": "25000000", "inventory": "3500000",
        "equipment": "30000000", "ap_supplier": "2000000"})
    bca = run.q(lambda: BankAccount.query.filter_by(account_number="1234567890").one().id)
    run.step(own, "Finance > Saldo Awal Kas (buku kas, angka sama)", "/finance/cash-bank-opening-balances", data={
        "account_type": "CASH", "opening_date": TODAY.isoformat(), "amount": "5000000", "notes": "sama dengan jurnal saldo awal"})
    run.step(own, "Finance > Saldo Awal Bank BCA (buku bank, angka sama)", "/finance/cash-bank-opening-balances", data={
        "account_type": "BANK", "bank_account_id": bca, "opening_date": TODAY.isoformat(), "amount": "25000000", "notes": "sama dengan jurnal saldo awal"})
    return {"bca": bca}


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
                 data={"paid_amount": str(amount), "notes": label, "proof_file": (io.BytesIO(_png()), "bukti.png")},
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


# --- tahap D: kontrak berakhir ------------------------------------------------
# Sesudah penagihan, supaya angka tagihan skenario di atas tidak berubah.

def stage_contracts(run):
    from app.models.contract import CustomerContract
    from app.models.master import Client, ClientPic, Mandor, User
    from app.models.system import Notification
    from app.services.credit_control_service import check_internal_order_credit, resolve_due_date

    run.stage = "D. Kontrak berakhir"
    own, adm = run.client("owner.pilot"), run.client("admin.pilot")
    branch_id = run.q(lambda: User.query.filter_by(username="owner.pilot").one().branch_id)
    sinar = run.q(lambda: Client.query.filter_by(name="PT Sinar Beton").one().id)
    asep = run.q(lambda: Mandor.query.filter_by(name="Mandor Asep").one().id)
    pic = run.q(lambda: ClientPic.query.filter_by(client_id=sinar, is_active=True).first().id)

    run.step(own, "Kontrak PT Sinar net 30 yang berakhir kemarin", "/customer-success/contracts", data={
        "client_id": sinar, "client_pic_id": pic, "title": "Katering Batching Plant 2026",
        "start_date": (TODAY - timedelta(days=180)).isoformat(), "end_date": (TODAY - timedelta(days=1)).isoformat(),
        "payment_terms": "net 30", "credit_limit": "0", "status": "ACTIVE"})
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


# --- tahap E: pemeriksaan -----------------------------------------------------

def stage_checks(run, backup):
    import csv
    import json

    from sqlalchemy import text

    from app.extensions import db
    from app.models.system import AuditLog
    from app.services.readiness_service import FAIL, run_readiness_checks
    from tools.audit_financial_invariants import collect_results_from_database

    run.stage = "E. Pemeriksaan"
    own = run.client("owner.pilot")

    balances = run.q(lambda: {code: Decimal(value) for code, value in db.session.execute(text(
        "SELECT a.account_code, COALESCE(SUM(d.debit), 0) - COALESCE(SUM(d.credit), 0) FROM accounts a "
        "JOIN journal_details d ON d.account_id = a.id GROUP BY a.account_code")).fetchall()})
    wrong = {code: (str(expected), str(balances.get(code, 0))) for code, expected in EXPECTED_BALANCES.items() if balances.get(code, Decimal(0)) != expected}
    extra = {code: str(value) for code, value in balances.items() if code not in EXPECTED_BALANCES and value}
    run.check("Saldo buku besar = hitungan manual", not wrong and not extra,
              "semua akun cocok" if not wrong and not extra else f"beda {wrong} lain {extra}")
    run.check("Debit = kredit", sum(balances.values()) == 0, f"selisih {sum(balances.values())}")

    violations = sum(len(result.violations) for result in collect_results_from_database())
    run.check("Audit rekonsiliasi mingguan (audit_financial_invariants)", violations == 0, f"{violations} pelanggaran")

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
    run.check("Neraca saldo", "Status Neraca BALANCE" in trial, "BALANCE" if "Status Neraca BALANCE" in trial else "tidak balance")
    dashboard = run.text(own, "/dashboard/owner")
    run.check("Dashboard OWNER: Dua Jalur Transaksi tampil", "Dua Jalur Transaksi" in dashboard, "tampil" if "Dua Jalur Transaksi" in dashboard else "tidak tampil")

    def reasons(event_type):
        return run.q(lambda: [json.loads(row.metadata_json or "{}").get("reason") for row in AuditLog.query.filter_by(event_type=event_type).all()])
    price_reasons = reasons("PORTION_PRICE_SET")
    run.check("Audit log: perubahan harga punya alasan", price_reasons and all(price_reasons), f"{price_reasons}")
    refund_reasons = [r for r in reasons("ADVANCE_SETTLED") if r and ("ditolak" in r.lower() or "kurang kirim" in r.lower())]
    run.check("Audit log: pengembalian uang muka punya alasan", bool(refund_reasons), f"{refund_reasons}")
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

    if backup:
        from app.services.backup_service import create_full_backup_package, verify_full_backup_package

        package = run.q(lambda: create_full_backup_package(created_by="GLADI"))
        verified = run.q(lambda: verify_full_backup_package(package["path"]))
        run.check("Backup penuh", verified["status"] == "PASS", f"{verified['status']} {package['name']}")
    results = run.q(lambda: run_readiness_checks())
    failed = [f"{row.name}: {row.message}" for row in results if row.status == FAIL]
    warned = [f"{row.name}: {row.message}" for row in results if row.status == "WARN"]
    run.check("ops-check: 0 FAIL", not failed, f"{len(results)} cek, FAIL {failed}, WARN {warned}")


def write_report(run, path):
    lines = [f"# Hasil gladi pilot {TODAY:%d-%m-%Y}", "",
             f"Database: `{os.environ['DATABASE_URL'].rsplit('/', 1)[-1]}`. Hari operasional: {D1:%d-%m-%Y} dan {D2:%d-%m-%Y}.", "",
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
    os.environ["DATABASE_URL"] = base.rsplit("/", 1)[0] + "/" + args.db

    from app import create_app
    from app.models.master import User

    app = create_app()
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    run = DryRun(app)
    if run.q(lambda: User.query.filter_by(username="admin.pilot").first()):
        raise SystemExit("Database ini sudah pernah dipakai gladi. Buat ulang database kosong dulu (lihat docstring).")

    refs = stage_setup(run)
    stage_orders(run, refs)
    stage_operations(run, D1, shortage={"Gudang Cikarang": 2, "Kantor Notaris": 1})
    stage_operations(run, D2)
    stage_billing(run, refs)
    stage_contracts(run)
    stage_checks(run, args.backup)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_report(run, args.output)
    failed_steps = [label for _stage, label, ok, _status, _messages in run.steps if not ok]
    failed_checks = [label for label, ok, _detail in run.checks if not ok]
    print(f"\n{len(run.steps) - len(failed_steps)}/{len(run.steps)} langkah OK, "
          f"{len(run.checks) - len(failed_checks)}/{len(run.checks)} pemeriksaan lulus. Laporan: {args.output}")
    raise SystemExit(1 if failed_steps or failed_checks else 0)


if __name__ == "__main__":
    main()
