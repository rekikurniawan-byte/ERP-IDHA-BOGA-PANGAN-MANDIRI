"""Pajak PT (Fase 8): pengaturan, PBJT di invoice, potongan pajak pelanggan, setoran, laporan.

Keputusan owner 2026-10-09 (RENCANA bagian 10):
- Rezim PPh dipilih di pengaturan (PP 55 final 0,5% atau tarif normal); belum
  dipilih = fitur PPh mati. PP 55 untuk PT paling lama 3 tahun pajak sejak
  tahun pertama; sesudahnya sistem memperlakukan sebagai tarif normal.
- PBJT (pajak daerah makan/minum, Kab. OKI) DITAMBAHKAN di atas harga sebagai
  baris invoice terpisah; dijurnal ke 2010 Hutang PBJT, bukan pendapatan.
- Semua pajak MATI bawaan sampai owner mengisi pengaturan.

Jurnal:
- PBJT di invoice      : Dr 1004 / Cr 2010 (lewat jurnal invoice).
- Potongan PPh final   : Dr 5014 Beban PPh Final / Cr 1004.
- Potongan PPh 23      : Dr 1009 Pajak Dibayar di Muka / Cr 1004 (kredit pajak).
- Setor PPh final      : Dr 5014 / Cr kas/bank.
- Setor PBJT           : Dr 2010 / Cr kas/bank.
- Setor PPh 25/29      : Dr 1009 / Cr kas/bank (diperhitungkan saat SPT Tahunan).
"""
from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, or_

from app.extensions import db
from app.models.finance import Invoice, InvoiceItem
from app.models.master import BranchSetting
from app.models.tax import (
    TAX_PAYMENT_PBJT,
    TAX_PAYMENT_PPH25,
    TAX_PAYMENT_PPH29,
    TAX_PAYMENT_PPH_FINAL,
    TAX_PAYMENT_TYPES,
    WITHHOLDING_PPH23,
    WITHHOLDING_PPH_FINAL,
    TaxDocument,
    TaxPayment,
    TaxWithholding,
)
from app.services.atomic_transaction_service import atomic_business_action
from app.utils.roles import effective_role

ZERO = Decimal("0")
REGIME_PP55 = "PP55"
REGIME_NORMAL = "NORMAL"
REGIME_LABELS = {REGIME_PP55: "PPh final UMKM 0,5% (PP 55)", REGIME_NORMAL: "Tarif normal (PPh 23 2% = kredit pajak)"}
PP55_RATE = Decimal("0.5")
PPH23_RATE = Decimal("2")
PP55_MAX_YEARS_PT = 3
UMKM_GROSS_LIMIT = Decimal("4800000000")
PBJT_MAX_RATE = Decimal("10")
PPH_DUE_DAY = 15  # setor PPh masa paling lambat tgl 15 bulan berikutnya

PBJT_ITEM_TYPE = "PBJT"
PBJT_BASE_ITEM_TYPES = {"CATERING", "REVISION_INCREASE"}
DELIVERY_ITEM_TYPES = {"ONGKIR"}
# Invoice yang bukan penjualan makanan: tidak kena PBJT dan tidak bisa dipotong PPh jasa.
NON_SALES_SOURCES = {"TAZIR", "TAWIDH", "OPENING_BALANCE"}
REVENUE_ACCOUNT_CODES = ("4001", "4002", "4003", "4004", "4005")

WITHHOLDING_LABELS = {WITHHOLDING_PPH_FINAL: "PPh final 0,5% (PP 55)", WITHHOLDING_PPH23: "PPh 23 (2%)"}
TAX_PAYMENT_LABELS = {
    TAX_PAYMENT_PPH_FINAL: "PPh final 0,5% (PP 55)",
    TAX_PAYMENT_PBJT: "PBJT (pajak daerah)",
    TAX_PAYMENT_PPH25: "PPh Pasal 25 (angsuran)",
    TAX_PAYMENT_PPH29: "PPh Pasal 29 (kurang bayar tahunan)",
}
TAX_PAYMENT_DEBIT = {
    TAX_PAYMENT_PPH_FINAL: "5014",
    TAX_PAYMENT_PBJT: "2010",
    TAX_PAYMENT_PPH25: "1009",
    TAX_PAYMENT_PPH29: "1009",
}
TAX_PAYMENT_REFERENCE = "TAX_PAYMENT"
TAX_WITHHOLDING_REFERENCE = "TAX_WITHHOLDING"
TAX_ATTACHMENT_MODULE = "TAX"
DOCUMENT_TYPES = {
    "SKT": "Surat Keterangan Terdaftar (NPWP)",
    "SK_PP55": "Surat Keterangan PP 55 (PPh final 0,5%)",
    "NPWPD": "NPWPD / pengukuhan PBJT (Bapenda)",
    "AKTA": "Akta pendirian & SK Kemenkumham",
    "NIB": "NIB / perizinan usaha",
    "PKP": "Surat pengukuhan PKP",
    "LAINNYA": "Dokumen lain",
}

SETTING_DEFAULTS = {
    "tax.regime": "",
    "tax.pp55_first_year": "",
    "tax.pp55_certificate_number": "",
    "tax.pp55_certificate_valid_until": "",
    "tax.kpp": "",
    "tax.registered_on": "",
    "tax.pbjt_enabled": "",
    "tax.pbjt_rate": "10",
    "tax.pbjt_region": "Kab. Ogan Komering Ilir",
    "tax.npwpd": "",
    "tax.pbjt_effective_from": "",
    "tax.pbjt_include_delivery": "",
    "tax.pbjt_due_day": "15",
    "company.directors": "",
    "company.shareholders": "",
}


class TaxError(ValueError):
    """Tindakan pajak ditolak; pesannya aman ditampilkan."""


# --- utilitas ---------------------------------------------------------------------

def _money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"))
    except InvalidOperation as error:
        raise TaxError(f"Nominal tidak valid: {value}") from error


def _round_rupiah(value: Decimal) -> Decimal:
    return Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def parse_amount(value) -> Decimal:
    text = str(value or "").replace("Rp", "").replace(" ", "").strip()
    if not text:
        return ZERO
    text = text.replace(".", "").replace(",", ".") if "," in text else text.replace(".", "")
    try:
        amount = Decimal(text)
    except InvalidOperation as error:
        raise TaxError(f"Nominal tidak valid: {value}") from error
    if amount < 0:
        raise TaxError("Nominal tidak boleh minus.")
    return amount


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as error:
        raise TaxError(f"Tanggal tidak valid: {value}") from error


def _require_role(actor, roles=("OWNER",)):
    if actor is None or effective_role(getattr(actor, "role", None)) not in roles:
        raise TaxError("Hanya OWNER yang boleh melakukan ini." if roles == ("OWNER",) else "Hanya OWNER atau ADMIN yang boleh melakukan ini.")


def _rupiah(value) -> str:
    return f"Rp{float(value or 0):,.0f}".replace(",", ".")


# --- pengaturan -------------------------------------------------------------------

def get_tax_settings(branch_id) -> dict:
    raw = dict(SETTING_DEFAULTS)
    if branch_id:
        for row in BranchSetting.query.filter(
            BranchSetting.branch_id == branch_id,
            BranchSetting.setting_key.in_(tuple(SETTING_DEFAULTS)),
        ).all():
            raw[row.setting_key] = row.setting_value or ""

    def as_date(key):
        try:
            return date.fromisoformat(raw[key]) if raw[key] else None
        except ValueError:
            return None

    def as_decimal(key, default):
        try:
            return Decimal(raw[key]) if raw[key] else default
        except InvalidOperation:
            return default

    first_year = int(raw["tax.pp55_first_year"]) if raw["tax.pp55_first_year"].isdigit() else None
    return {
        "raw": raw,
        "regime": raw["tax.regime"] if raw["tax.regime"] in REGIME_LABELS else "",
        "pp55_first_year": first_year,
        "pp55_last_year": (first_year + PP55_MAX_YEARS_PT - 1) if first_year else None,
        "pp55_certificate_number": raw["tax.pp55_certificate_number"],
        "pp55_certificate_valid_until": as_date("tax.pp55_certificate_valid_until"),
        "kpp": raw["tax.kpp"],
        "registered_on": as_date("tax.registered_on"),
        "pbjt_enabled": raw["tax.pbjt_enabled"] == "1",
        "pbjt_rate": as_decimal("tax.pbjt_rate", Decimal("10")),
        "pbjt_region": raw["tax.pbjt_region"],
        "npwpd": raw["tax.npwpd"],
        "pbjt_effective_from": as_date("tax.pbjt_effective_from"),
        "pbjt_include_delivery": raw["tax.pbjt_include_delivery"] == "1",
        "pbjt_due_day": int(raw["tax.pbjt_due_day"]) if raw["tax.pbjt_due_day"].isdigit() else 15,
        "directors": raw["company.directors"],
        "shareholders": raw["company.shareholders"],
    }


def save_tax_settings(branch_id, form, actor):
    """Simpan pengaturan pajak. Hanya OWNER. Divalidasi dulu, baru ditulis semua."""
    from app.services.audit_log_service import record_audit_log

    _require_role(actor)
    values = {key: str(form.get(key) or "").strip() for key in SETTING_DEFAULTS}
    values["tax.pbjt_enabled"] = "1" if form.get("tax.pbjt_enabled") else ""
    values["tax.pbjt_include_delivery"] = "1" if form.get("tax.pbjt_include_delivery") else ""

    if values["tax.regime"] not in ("", REGIME_PP55, REGIME_NORMAL):
        raise TaxError("Rezim PPh tidak valid.")
    if values["tax.regime"] == REGIME_PP55:
        if not values["tax.pp55_first_year"].isdigit():
            raise TaxError("Isi tahun pertama memakai PP 55 (mis. 2026, tahun PT terdaftar).")
    if values["tax.pp55_first_year"] and not values["tax.pp55_first_year"].isdigit():
        raise TaxError("Tahun pertama PP 55 harus angka tahun, mis. 2026.")
    for key in ("tax.pp55_certificate_valid_until", "tax.registered_on", "tax.pbjt_effective_from"):
        _parse_date(values[key])
    try:
        rate = Decimal(values["tax.pbjt_rate"] or "0")
    except InvalidOperation as error:
        raise TaxError("Tarif PBJT harus angka persen, mis. 10.") from error
    if rate < 0 or rate > PBJT_MAX_RATE:
        raise TaxError("Tarif PBJT antara 0 dan 10 persen (batas UU HKPD).")
    if values["tax.pbjt_enabled"]:
        if rate <= 0:
            raise TaxError("PBJT aktif wajib punya tarif lebih dari 0.")
        if not values["tax.npwpd"]:
            raise TaxError("PBJT baru boleh aktif setelah NPWPD dari Bapenda diisi.")
        if not values["tax.pbjt_effective_from"]:
            raise TaxError("Isi tanggal mulai memungut PBJT; invoice sebelum tanggal itu tidak berubah.")
    due_day = values["tax.pbjt_due_day"] or "15"
    if not due_day.isdigit() or not 1 <= int(due_day) <= 28:
        raise TaxError("Tanggal jatuh tempo setor PBJT antara 1 dan 28.")

    old = get_tax_settings(branch_id)["raw"]
    with atomic_business_action(
        module="TAX",
        action="TAX_SETTINGS_UPDATE",
        description="Pengaturan pajak diperbarui.",
        reference_type="branch_settings",
        user_id=actor.id,
        branch_id=branch_id,
        severity="HIGH",
        metadata={"keys": list(values)},
    ):
        for key, value in values.items():
            row = BranchSetting.query.filter_by(branch_id=branch_id, setting_key=key).first()
            if row is None:
                db.session.add(BranchSetting(branch_id=branch_id, setting_key=key, setting_value=value))
            else:
                row.setting_value = value
        record_audit_log(
            module="TAX",
            event_type="TAX_SETTINGS_UPDATED",
            action="UPDATE",
            table_name="branch_settings",
            record_id=branch_id,
            description="Pengaturan pajak diperbarui.",
            old_value={key: old.get(key) for key in values},
            new_value=values,
            user_id=actor.id,
            branch_id=branch_id,
            commit=False,
        )
    return get_tax_settings(branch_id)


def effective_regime(settings, on_date) -> str:
    """Rezim PPh yang berlaku pada tanggal itu: PP55, NORMAL, atau '' (belum dipilih)."""
    regime = settings["regime"]
    if regime == REGIME_PP55:
        last_year = settings["pp55_last_year"]
        if last_year and on_date.year > last_year:
            return REGIME_NORMAL
    return regime


def pp55_certificate_valid(settings, on_date) -> bool:
    valid_until = settings["pp55_certificate_valid_until"]
    return bool(settings["pp55_certificate_number"]) and (valid_until is None or on_date <= valid_until)


def pbjt_applies(settings, on_date) -> bool:
    start = settings["pbjt_effective_from"]
    return settings["pbjt_enabled"] and settings["pbjt_rate"] > 0 and start is not None and on_date >= start


# --- PBJT di invoice --------------------------------------------------------------

def pbjt_base_item_types(settings):
    types = set(PBJT_BASE_ITEM_TYPES)
    if settings["pbjt_include_delivery"]:
        types |= DELIVERY_ITEM_TYPES
    return types


def pbjt_for_lines(lines, branch_id, on_date) -> Decimal:
    """PBJT untuk baris rencana (pratinjau invoice otomatis), tanpa menulis apa pun."""
    settings = get_tax_settings(branch_id)
    if not pbjt_applies(settings, on_date):
        return ZERO
    types = pbjt_base_item_types(settings)
    base = sum((_money(line.get("subtotal")) for line in lines if str(line.get("item_type") or "").upper() in types), ZERO)
    return _round_rupiah(base * settings["pbjt_rate"] / Decimal(100))


def apply_pbjt_to_invoice(invoice) -> Decimal:
    """Tambahkan baris PBJT ke invoice penjualan yang baru dibuat, sebelum jurnalnya.

    PBJT ditambahkan DI ATAS harga (keputusan owner): total & sisa tagihan naik
    sebesar PBJT, pendapatan tetap. Dipanggil semua jalur pembuatan invoice
    penjualan; mengembalikan nominal PBJT (0 bila tidak berlaku). Tidak commit.
    """
    if str(getattr(invoice, "source_type", "") or "").upper() in NON_SALES_SOURCES:
        return ZERO
    settings = get_tax_settings(invoice.branch_id)
    if not pbjt_applies(settings, invoice.invoice_date):
        return ZERO
    items = InvoiceItem.query.filter_by(invoice_id=invoice.id).all()
    if any(str(item.item_type or "").upper() == PBJT_ITEM_TYPE for item in items):
        return ZERO
    types = pbjt_base_item_types(settings)
    base = sum((_money(item.subtotal) for item in items if str(item.item_type or "").upper() in types), ZERO)
    amount = _round_rupiah(base * settings["pbjt_rate"] / Decimal(100))
    if amount <= 0:
        return ZERO
    rate_label = f"{settings['pbjt_rate'].normalize():f}".replace(".", ",")
    db.session.add(InvoiceItem(
        invoice_id=invoice.id,
        item_type=PBJT_ITEM_TYPE,
        description=(
            f"PBJT makanan & minuman {rate_label}% x {_rupiah(base)} "
            f"({settings['pbjt_region']}, NPWPD {settings['npwpd']})"
        ),
        qty=1,
        unit_price=amount,
        subtotal=amount,
        source_type=PBJT_ITEM_TYPE,
        source_id=invoice.id,
        input_source=getattr(invoice, "input_source", None) or "REALTIME",
    ))
    invoice.total_amount = _money(invoice.total_amount) + amount
    invoice.remaining_amount = _money(invoice.remaining_amount) + amount
    db.session.flush()
    return amount


def tax_print_note(invoice):
    """Keterangan pajak di cetak invoice supaya pelanggan memotong dengan benar."""
    if str(getattr(invoice, "source_type", "") or "").upper() in NON_SALES_SOURCES:
        return None
    settings = get_tax_settings(invoice.branch_id)
    regime = effective_regime(settings, invoice.invoice_date)
    if regime == REGIME_PP55 and pp55_certificate_valid(settings, invoice.invoice_date):
        return (
            f"PPh final 0,5% (PP 55/2022) — Surat Keterangan No. {settings['pp55_certificate_number']}. "
            "Mohon pemotongan PPh final 0,5%, bukan PPh 23."
        )
    if regime == REGIME_NORMAL:
        return "Atas jasa katering dapat dipotong PPh Pasal 23 sebesar 2% dari nilai jasa (tidak termasuk PBJT)."
    return None


def contract_tax_clause(branch_id, on_date):
    """Butir pasal pajak surat kontrak (Fase 9), disusun dari pengaturan pajak yang berlaku."""
    from app.services.company_settings_service import get_company_settings

    settings = get_tax_settings(branch_id)
    npwp = get_company_settings(branch_id).get("company_npwp")
    items = []
    if npwp:
        items.append(f"PIHAK PERTAMA terdaftar sebagai Wajib Pajak Badan dengan NPWP {npwp}.")
    rate_label = f"{settings['pbjt_rate'].normalize():f}".replace(".", ",")
    if pbjt_applies(settings, on_date):
        base = "harga makanan dan minuman" + (" serta ongkos kirim" if settings["pbjt_include_delivery"] else "")
        items.append(
            f"Atas penyerahan makanan dan minuman dikenakan Pajak Barang dan Jasa Tertentu (PBJT) sebesar {rate_label}% "
            f"dari {base}, DITAMBAHKAN di atas harga yang disepakati dan dicantumkan terpisah pada invoice. PBJT disetor "
            f"PIHAK PERTAMA kepada {settings['pbjt_region']} (NPWPD {settings['npwpd']})."
        )
    else:
        items.append(
            "Atas penyerahan makanan dan minuman berlaku Pajak Barang dan Jasa Tertentu (PBJT) daerah, bukan PPN. "
            "Apabila PIHAK PERTAMA diwajibkan memungut PBJT, PBJT ditambahkan di atas harga yang disepakati, "
            "dicantumkan terpisah pada invoice, dan diberitahukan secara tertulis sebelum berlaku."
        )
    regime = effective_regime(settings, on_date)
    if regime == REGIME_PP55 and pp55_certificate_valid(settings, on_date):
        items.append(
            "PIHAK PERTAMA dikenai PPh final 0,5% (PP 55/2022) dengan Surat Keterangan No. "
            f"{settings['pp55_certificate_number']}. Apabila PIHAK KEDUA wajib memotong pajak, pemotongan yang berlaku "
            "adalah PPh final 0,5% dari nilai jasa (tidak termasuk PBJT), bukan PPh Pasal 23."
        )
    elif regime == REGIME_NORMAL:
        items.append(
            "Apabila PIHAK KEDUA wajib memotong pajak, pemotongan PPh Pasal 23 sebesar 2% dihitung dari nilai jasa "
            "(tidak termasuk PBJT)."
        )
    else:
        items.append(
            "Apabila PIHAK KEDUA wajib memotong pajak penghasilan, jenis dan tarif pemotongan mengikuti status pajak "
            "PIHAK PERTAMA yang tercantum pada setiap invoice."
        )
    items.append(
        "Potongan pajak hanya diperhitungkan sebagai pelunasan invoice apabila bukti potong yang sah diserahkan "
        "kepada PIHAK PERTAMA paling lambat tanggal 20 bulan berikutnya; potongan tanpa bukti potong dianggap "
        "belum dibayar."
    )
    return items


def invoice_pbjt_amount(invoice_id) -> Decimal:
    total = (
        db.session.query(func.coalesce(func.sum(InvoiceItem.subtotal), 0))
        .filter(InvoiceItem.invoice_id == invoice_id, InvoiceItem.item_type == PBJT_ITEM_TYPE)
        .scalar()
    )
    return _money(total)


# --- potongan pajak oleh pelanggan (pintu pelunasan ketiga) ------------------------

def _post_journal(**kwargs):
    """Jurnal dua baris; akun COA yang hilang jadi pesan yang bisa dibaca pengguna."""
    from app.services.cash_bank_service import post_cash_bank_journal

    try:
        return post_cash_bank_journal(**kwargs)
    except Exception as error:  # akun belum ada di COA
        raise TaxError(f"Jurnal pajak gagal dibuat: {error}") from error


def suggest_withholding(invoice, settings=None):
    """Jenis, dasar, dan nominal potongan yang wajar untuk invoice ini (bisa diubah admin)."""
    settings = settings or get_tax_settings(invoice.branch_id)
    regime = effective_regime(settings, invoice.invoice_date)
    if regime == REGIME_PP55 and pp55_certificate_valid(settings, invoice.invoice_date):
        kind, rate = WITHHOLDING_PPH_FINAL, PP55_RATE
    else:
        kind, rate = WITHHOLDING_PPH23, PPH23_RATE
    base = _money(invoice.total_amount) - invoice_pbjt_amount(invoice.id)
    return {
        "type": kind,
        "rate": rate,
        "base": base,
        "amount": _round_rupiah(base * rate / Decimal(100)),
        "regime": regime,
    }


def record_withholding(invoice, form, evidence_file, actor):
    """Pelanggan membayar setelah memotong PPh: catat bukti potongnya, kurangi sisa invoice."""
    from app.models.finance import InvoiceCollectionLog
    from app.services.business_logic_guard_service import resolve_invoice_status_after_payment
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment
    from app.services.manual_backfill_billing_service import sync_manual_backfill_batch_status_from_invoice
    from app.utils.clock import today_wib

    _require_role(actor, ("OWNER", "ADMIN"))
    if str(invoice.source_type or "").upper() in NON_SALES_SOURCES:
        raise TaxError("Potongan PPh jasa hanya untuk invoice penjualan katering.")
    if str(invoice.status or "").upper() in ("CANCELLED", "CANCELED", "PAID", "CLOSED"):
        raise TaxError("Invoice ini sudah lunas/ditutup.")
    kind = str(form.get("withholding_type") or "").strip().upper()
    if kind not in WITHHOLDING_LABELS:
        raise TaxError("Pilih jenis potongan: PPh final 0,5% atau PPh 23 2%.")
    amount = _money(parse_amount(form.get("amount")))
    if amount <= 0:
        raise TaxError("Nominal potongan harus lebih dari 0.")
    if amount > _money(invoice.remaining_amount):
        raise TaxError(f"Potongan melebihi sisa invoice ({_rupiah(invoice.remaining_amount)}).")
    number = str(form.get("certificate_number") or "").strip()
    if not number:
        raise TaxError("Nomor bukti potong wajib diisi (dari e-Bupot pelanggan).")
    withheld_on = _parse_date(form.get("withheld_on")) or today_wib()
    if withheld_on > today_wib():
        raise TaxError("Tanggal bukti potong tidak boleh di masa depan.")
    base = _money(parse_amount(form.get("base_amount"))) or suggest_withholding(invoice)["base"]
    rate = PP55_RATE if kind == WITHHOLDING_PPH_FINAL else PPH23_RATE
    debit_code = "5014" if kind == WITHHOLDING_PPH_FINAL else "1009"

    with atomic_business_action(
        module="TAX",
        action="TAX_WITHHOLDING_CREATE",
        description=f"Potongan {WITHHOLDING_LABELS[kind]} invoice {invoice.invoice_number}.",
        reference_type="tax_withholdings",
        user_id=actor.id,
        branch_id=invoice.branch_id,
        severity="HIGH",
        metadata={"invoice_id": invoice.id, "amount": str(amount), "type": kind},
    ):
        row = TaxWithholding(
            branch_id=invoice.branch_id,
            invoice_id=invoice.id,
            withholding_type=kind,
            withheld_on=withheld_on,
            base_amount=base,
            rate_percent=rate,
            amount=amount,
            certificate_number=number,
            notes=str(form.get("notes") or "").strip() or None,
            created_by=actor.id,
        )
        db.session.add(row)
        db.session.flush()
        journal = _post_journal(
            journal_date=withheld_on,
            reference_type=TAX_WITHHOLDING_REFERENCE,
            reference_id=row.id,
            description=f"{WITHHOLDING_LABELS[kind]} dipotong pelanggan, invoice {invoice.invoice_number}, bukti potong {number}",
            debit_code=debit_code,
            credit_code="1004",
            amount=float(amount),
            created_by=actor.id,
        )
        row.journal_id = getattr(journal, "id", None)
        if evidence_file is not None and getattr(evidence_file, "filename", None):
            try:
                attachment = stage_digital_attachment(
                    file_storage=evidence_file,
                    module=TAX_ATTACHMENT_MODULE,
                    reference_type=TAX_WITHHOLDING_REFERENCE,
                    reference_id=row.id,
                    attachment_type="BUKTI_POTONG",
                    branch_id=invoice.branch_id,
                    uploaded_by=actor.id,
                    notes=number,
                )
            except AttachmentValidationError as error:
                raise TaxError(str(error)) from error
            db.session.flush()
            row.attachment_id = attachment.id

        new_paid = _money(invoice.paid_amount) + amount
        remaining = _money(invoice.total_amount) - new_paid
        invoice.status = resolve_invoice_status_after_payment(invoice.total_amount, new_paid)
        invoice.paid_amount = new_paid
        invoice.remaining_amount = remaining if remaining > 0 else ZERO
        sync_manual_backfill_batch_status_from_invoice(invoice, updated_by=actor.id, commit=False)
        paid_off = invoice.remaining_amount <= 0
        db.session.add(InvoiceCollectionLog(
            branch_id=invoice.branch_id,
            invoice_id=invoice.id,
            follow_up_date=withheld_on,
            channel="SYSTEM",
            contact_person="SYSTEM - Potongan pajak pelanggan",
            response_note=(
                f"{WITHHOLDING_LABELS[kind]} {_rupiah(amount)} dipotong pelanggan (bukti potong {number}). "
                + ("Invoice sudah lunas." if paid_off else f"Sisa {_rupiah(invoice.remaining_amount)}.")
            ),
            promise_date=None,
            next_action="Invoice sudah lunas. Tidak perlu follow up penagihan." if paid_off else "Follow up pelunasan sisa piutang.",
            collection_status="PAID" if paid_off else "PARTIAL",
            created_by=actor.id,
        ))
        db.session.flush()
    return row


def withholdings_for_invoices(invoice_ids):
    ids = [int(value) for value in invoice_ids or [] if value]
    if not ids:
        return []
    return (
        TaxWithholding.query.filter(TaxWithholding.invoice_id.in_(ids))
        .order_by(TaxWithholding.withheld_on.desc(), TaxWithholding.id.desc())
        .all()
    )


# --- setoran pajak ----------------------------------------------------------------

def record_tax_payment(branch_id, form, evidence_file, actor):
    """Setor pajak: kas/bank keluar + jurnal sesuai jenis pajak + NTPN/bukti."""
    from app.models.finance import BankAccount, CashBankTransaction
    from app.services.cash_bank_service import (
        calculate_account_balance,
        cash_bank_coa_code,
        get_account_label,
        normalize_cash_bank_account,
    )
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment
    from app.utils.clock import today_wib

    _require_role(actor, ("OWNER", "ADMIN"))
    tax_type = str(form.get("tax_type") or "").strip().upper()
    if tax_type not in TAX_PAYMENT_TYPES:
        raise TaxError("Jenis pajak tidak valid.")
    amount = _money(parse_amount(form.get("amount")))
    if amount <= 0:
        raise TaxError("Nominal setoran harus lebih dari 0.")
    reference = str(form.get("reference_number") or "").strip()
    if not reference:
        raise TaxError("NTPN / nomor bukti setor wajib diisi.")
    paid_on = _parse_date(form.get("paid_on")) or today_wib()
    if paid_on > today_wib():
        raise TaxError("Tanggal setor tidak boleh di masa depan.")
    try:
        year, month = int(form.get("period_year")), int(form.get("period_month"))
    except (TypeError, ValueError) as error:
        raise TaxError("Masa pajak (bulan & tahun) wajib diisi.") from error
    if not 1 <= month <= 12 or year < 2000:
        raise TaxError("Masa pajak tidak valid.")
    try:
        account_type, bank_account_id, _ = normalize_cash_bank_account(
            form.get("account_type"), form.get("bank_account_id") or None, branch_id=branch_id
        )
    except Exception as error:  # pesan validasi kas/bank untuk pengguna
        raise TaxError(str(error)) from error
    balance = calculate_account_balance(branch_id, account_type, bank_account_id)
    if float(amount) > float(balance):
        raise TaxError(f"Saldo kas/bank tidak cukup. Saldo tersedia {_rupiah(balance)}.")
    label = TAX_PAYMENT_LABELS[tax_type]

    with atomic_business_action(
        module="TAX",
        action="TAX_PAYMENT_CREATE",
        description=f"Setor {label} masa {month:02d}/{year}.",
        reference_type="tax_payments",
        user_id=actor.id,
        branch_id=branch_id,
        severity="HIGH",
        metadata={"tax_type": tax_type, "amount": str(amount), "period": f"{year}-{month:02d}"},
    ):
        bank_account = db.session.get(BankAccount, bank_account_id) if bank_account_id else None
        row = TaxPayment(
            branch_id=branch_id,
            tax_type=tax_type,
            period_year=year,
            period_month=month,
            paid_on=paid_on,
            amount=amount,
            reference_number=reference,
            account_type=account_type,
            bank_account_id=bank_account_id,
            notes=str(form.get("notes") or "").strip() or None,
            created_by=actor.id,
        )
        db.session.add(row)
        db.session.flush()
        ledger = CashBankTransaction(
            branch_id=branch_id,
            transaction_date=paid_on,
            account_type=account_type,
            bank_account_id=bank_account_id,
            transaction_type="OUT",
            amount=float(amount),
            description=f"Setor {label} masa {month:02d}/{year} ({get_account_label(account_type, bank_account)}), NTPN {reference}",
            reference_type=TAX_PAYMENT_REFERENCE,
            reference_id=row.id,
            created_by=actor.id,
        )
        db.session.add(ledger)
        db.session.flush()
        row.cash_bank_transaction_id = ledger.id
        _post_journal(
            journal_date=paid_on,
            reference_type=TAX_PAYMENT_REFERENCE,
            reference_id=row.id,
            description=f"Setor {label} masa {month:02d}/{year}, NTPN {reference}",
            debit_code=TAX_PAYMENT_DEBIT[tax_type],
            credit_code=cash_bank_coa_code(account_type, bank_account_id),
            amount=float(amount),
            created_by=actor.id,
        )
        if evidence_file is not None and getattr(evidence_file, "filename", None):
            try:
                attachment = stage_digital_attachment(
                    file_storage=evidence_file,
                    module=TAX_ATTACHMENT_MODULE,
                    reference_type=TAX_PAYMENT_REFERENCE,
                    reference_id=row.id,
                    attachment_type="BUKTI_SETOR_PAJAK",
                    branch_id=branch_id,
                    uploaded_by=actor.id,
                    notes=reference,
                )
            except AttachmentValidationError as error:
                raise TaxError(str(error)) from error
            db.session.flush()
            row.attachment_id = attachment.id
    return row


# --- dokumen pajak ----------------------------------------------------------------

def save_tax_document(branch_id, form, evidence_file, actor):
    from app.services.digital_attachment_service import AttachmentValidationError, stage_digital_attachment

    _require_role(actor)
    doc_type = str(form.get("doc_type") or "").strip().upper()
    if doc_type not in DOCUMENT_TYPES:
        raise TaxError("Jenis dokumen tidak valid.")
    if evidence_file is None or not getattr(evidence_file, "filename", None):
        raise TaxError("File dokumen wajib diunggah.")
    with atomic_business_action(
        module="TAX",
        action="TAX_DOCUMENT_UPLOAD",
        description=f"Dokumen {DOCUMENT_TYPES[doc_type]} diunggah.",
        reference_type="tax_documents",
        user_id=actor.id,
        branch_id=branch_id,
        severity="MEDIUM",
    ):
        row = TaxDocument(
            branch_id=branch_id,
            doc_type=doc_type,
            doc_number=str(form.get("doc_number") or "").strip() or None,
            issued_on=_parse_date(form.get("issued_on")),
            valid_until=_parse_date(form.get("valid_until")),
            notes=str(form.get("notes") or "").strip() or None,
            created_by=actor.id,
        )
        db.session.add(row)
        db.session.flush()
        try:
            attachment = stage_digital_attachment(
                file_storage=evidence_file,
                module=TAX_ATTACHMENT_MODULE,
                reference_type="TAX_DOCUMENT",
                reference_id=row.id,
                attachment_type=doc_type,
                branch_id=branch_id,
                uploaded_by=actor.id,
                notes=row.doc_number,
            )
        except AttachmentValidationError as error:
            raise TaxError(str(error)) from error
        db.session.flush()
        row.attachment_id = attachment.id
    return row


def list_tax_documents(branch_id):
    return (
        TaxDocument.query.filter_by(branch_id=branch_id, is_active=True)
        .order_by(TaxDocument.doc_type.asc(), TaxDocument.id.desc())
        .all()
    )


def tax_attachment_or_none(attachment_id, branch_id):
    from app.models.system import DigitalAttachment

    attachment = db.session.get(DigitalAttachment, attachment_id)
    if attachment is None or attachment.is_deleted or attachment.module != TAX_ATTACHMENT_MODULE:
        return None
    if attachment.branch_id not in (None, branch_id):
        return None
    return attachment


# --- laporan ----------------------------------------------------------------------

def _month_bounds(year, month):
    return date(year, month, 1), date(year, month, monthrange(year, month)[1])


def gross_revenue(start, end) -> Decimal:
    """Peredaran bruto usaha dari buku besar (4001–4005), tanpa PBJT dan ta'zir."""
    from app.models.accounting import Account, Journal, JournalDetail

    credit, debit = (
        db.session.query(
            func.coalesce(func.sum(JournalDetail.credit), 0),
            func.coalesce(func.sum(JournalDetail.debit), 0),
        )
        .join(Account, Account.id == JournalDetail.account_id)
        .join(Journal, Journal.id == JournalDetail.journal_id)
        .filter(
            Account.account_code.in_(REVENUE_ACCOUNT_CODES),
            Journal.journal_date >= start,
            Journal.journal_date <= end,
            or_(Journal.reference_type.is_(None), Journal.reference_type != "PERIOD_CLOSING"),
        )
        .one()
    )
    return _money(Decimal(str(credit)) - Decimal(str(debit)))


def _sum(query_column, *filters):
    return _money(db.session.query(func.coalesce(func.sum(query_column), 0)).filter(*filters).scalar())


def _due(year, month, day):
    """Tanggal jatuh tempo di bulan berikutnya setelah masa pajak."""
    next_month = date(year, month, 1) + timedelta(days=32)
    return date(next_month.year, next_month.month, min(max(int(day), 1), 28))


def build_tax_month(branch_id, year, month):
    """Ringkasan pajak satu masa: PPh, PBJT, potongan pelanggan, setoran, rekonsiliasi."""
    settings = get_tax_settings(branch_id)
    start, end = _month_bounds(year, month)
    regime = effective_regime(settings, start)
    gross = gross_revenue(start, end)

    withheld_final = _sum(
        TaxWithholding.amount, TaxWithholding.branch_id == branch_id,
        TaxWithholding.withholding_type == WITHHOLDING_PPH_FINAL,
        TaxWithholding.withheld_on >= start, TaxWithholding.withheld_on <= end,
    )
    withheld_pph23 = _sum(
        TaxWithholding.amount, TaxWithholding.branch_id == branch_id,
        TaxWithholding.withholding_type == WITHHOLDING_PPH23,
        TaxWithholding.withheld_on >= start, TaxWithholding.withheld_on <= end,
    )

    def paid(tax_type):
        return _sum(
            TaxPayment.amount, TaxPayment.branch_id == branch_id, TaxPayment.tax_type == tax_type,
            TaxPayment.period_year == year, TaxPayment.period_month == month,
        )

    pph_final_due = _round_rupiah(gross * PP55_RATE / Decimal(100)) if regime == REGIME_PP55 else ZERO
    pph_final_paid = paid(TAX_PAYMENT_PPH_FINAL)
    pbjt_collected = _money(
        db.session.query(func.coalesce(func.sum(InvoiceItem.subtotal), 0))
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(
            Invoice.branch_id == branch_id,
            Invoice.invoice_date >= start, Invoice.invoice_date <= end,
            Invoice.status.notin_(("CANCELLED", "CANCELED")),
            InvoiceItem.item_type == PBJT_ITEM_TYPE,
        ).scalar()
    )
    pbjt_paid = paid(TAX_PAYMENT_PBJT)

    year_start = date(year, 1, 1)
    monthly = []
    for m in range(1, 13):
        m_start, m_end = _month_bounds(year, m)
        m_gross = gross_revenue(m_start, m_end) if m_start <= end else None
        m_pph = (
            _round_rupiah(m_gross * PP55_RATE / Decimal(100))
            if m_gross is not None and effective_regime(settings, m_start) == REGIME_PP55 else None
        )
        monthly.append({"month": m, "gross": m_gross, "pph_final": m_pph})
    ytd = sum((row["gross"] for row in monthly if row["gross"] is not None), ZERO)

    invoices = (
        Invoice.query.filter(
            Invoice.branch_id == branch_id,
            Invoice.invoice_date >= start, Invoice.invoice_date <= end,
            Invoice.status.notin_(("CANCELLED", "CANCELED")),
            or_(Invoice.source_type.is_(None), Invoice.source_type.notin_(tuple(NON_SALES_SOURCES))),
        ).order_by(Invoice.invoice_date.asc(), Invoice.id.asc()).all()
    )
    withheld_by_invoice = {}
    for row in withholdings_for_invoices([invoice.id for invoice in invoices]):
        withheld_by_invoice[row.invoice_id] = withheld_by_invoice.get(row.invoice_id, ZERO) + _money(row.amount)
    reconciliation = [
        {
            "invoice": invoice,
            "pbjt": invoice_pbjt_amount(invoice.id),
            "withheld": withheld_by_invoice.get(invoice.id, ZERO),
        }
        for invoice in invoices
    ]

    return {
        "settings": settings,
        "year": year,
        "month": month,
        "start": start,
        "end": end,
        "regime": regime,
        "regime_label": REGIME_LABELS.get(regime, "Belum dipilih"),
        "gross": gross,
        "pph_final_due": pph_final_due,
        "withheld_final": withheld_final,
        "pph_final_paid": pph_final_paid,
        "pph_final_to_pay": max(pph_final_due - withheld_final - pph_final_paid, ZERO),
        "pph_final_due_date": _due(year, month, PPH_DUE_DAY),
        "withheld_pph23": withheld_pph23,
        "pbjt_collected": pbjt_collected,
        "pbjt_paid": pbjt_paid,
        "pbjt_to_pay": max(pbjt_collected - pbjt_paid, ZERO),
        "pbjt_due_date": _due(year, month, settings["pbjt_due_day"]),
        "monthly": monthly,
        "ytd_gross": ytd,
        "ytd_limit_pct": float(ytd / UMKM_GROSS_LIMIT * 100) if ytd > 0 else 0.0,
        "year_start": year_start,
        "reconciliation": reconciliation,
        "payments": TaxPayment.query.filter_by(branch_id=branch_id, period_year=year, period_month=month)
        .order_by(TaxPayment.paid_on.desc(), TaxPayment.id.desc()).all(),
        "withholdings": TaxWithholding.query.filter(
            TaxWithholding.branch_id == branch_id,
            TaxWithholding.withheld_on >= start, TaxWithholding.withheld_on <= end,
        ).order_by(TaxWithholding.withheld_on.desc(), TaxWithholding.id.desc()).all(),
        "warnings": tax_warnings(branch_id, settings, end, ytd),
    }


def tax_warnings(branch_id, settings, on_date, ytd_gross=None):
    """Peringatan pajak yang harus dilihat owner (dipakai laporan & pengingat)."""
    warnings = []
    if not settings["regime"]:
        warnings.append("Rezim PPh belum dipilih di Pengaturan Pajak; potongan & PPh final belum dihitung.")
    regime = effective_regime(settings, on_date)
    last_year = settings["pp55_last_year"]
    if settings["regime"] == REGIME_PP55 and last_year:
        if on_date.year > last_year:
            warnings.append(f"Fasilitas PP 55 berakhir tahun {last_year}; sejak {last_year + 1} memakai tarif normal.")
        elif on_date.year == last_year and on_date.month >= 10:
            warnings.append(f"Fasilitas PP 55 berakhir 31 Desember {last_year}; siapkan pembukuan tarif normal.")
    if regime == REGIME_PP55 and not pp55_certificate_valid(settings, on_date):
        warnings.append("Surat Keterangan PP 55 belum diisi/kedaluwarsa: pelanggan akan memotong PPh 23 2%, bukan 0,5%.")
    if ytd_gross is not None and ytd_gross >= UMKM_GROSS_LIMIT * Decimal("0.9"):
        warnings.append(
            f"Omzet tahun ini {_rupiah(ytd_gross)} mendekati/lewat Rp4,8 M: cek kewajiban PKP dan kelayakan PP 55 tahun depan."
        )
    soon = on_date + timedelta(days=30)
    for doc in TaxDocument.query.filter(
        TaxDocument.branch_id == branch_id, TaxDocument.is_active.is_(True),
        TaxDocument.valid_until.isnot(None), TaxDocument.valid_until <= soon,
    ).all():
        warnings.append(f"{DOCUMENT_TYPES.get(doc.doc_type, doc.doc_type)} berlaku sampai {doc.valid_until.strftime('%d-%m-%Y')}.")
    return warnings


# --- pengingat (penjadwal 08.30) ----------------------------------------------------

def run_tax_reminders(branch_id=None, period_key=None, now=None):
    """Pengingat setor PPh final (tgl 15), PBJT, SPT Tahunan, dan peringatan pajak."""
    from app.services.notification_service import create_or_update_notification
    from app.utils.clock import today_wib

    today = (now.date() if now else today_wib())
    settings = get_tax_settings(branch_id)
    if not settings["regime"] and not settings["pbjt_enabled"]:
        return {"message": "Pajak belum diaktifkan."}
    previous = today.replace(day=1) - timedelta(days=1)
    report = build_tax_month(branch_id, previous.year, previous.month)
    sent = []

    def notify(key, title, message, priority="WARNING"):
        for role in ("OWNER", "ADMIN"):
            create_or_update_notification(
                branch_id=branch_id,
                notification_type="TAX_REMINDER",
                title=title,
                message=message,
                target_role=role,
                priority=priority,
                action_url=f"/finance/tax?year={previous.year}&month={previous.month}",
                generated_key=f"tax-{key}-{today.isoformat()}-{role}",
                commit=False,
            )
        sent.append(key)

    masa = f"{previous.month:02d}/{previous.year}"
    if report["pph_final_to_pay"] > 0 and today.day in (10, 14, 15):
        notify("pph-final", f"Setor PPh final masa {masa}",
               f"Kurang setor {_rupiah(report['pph_final_to_pay'])}, paling lambat {report['pph_final_due_date'].strftime('%d-%m-%Y')}.",
               "CRITICAL" if today.day >= 14 else "WARNING")
    pbjt_due = report["pbjt_due_date"]
    if report["pbjt_to_pay"] > 0 and today in (pbjt_due - timedelta(days=5), pbjt_due - timedelta(days=1), pbjt_due):
        notify("pbjt", f"Setor PBJT masa {masa}",
               f"PBJT dipungut belum disetor {_rupiah(report['pbjt_to_pay'])}, jatuh tempo {pbjt_due.strftime('%d-%m-%Y')} ({settings['pbjt_region']}).")
    if (today.month, today.day) in ((3, 1), (4, 1), (4, 20)):
        notify("spt-tahunan", f"SPT Tahunan PPh Badan {today.year - 1}",
               f"Batas lapor 30 April {today.year}. Bahan: laporan keuangan, peredaran bruto per bulan, bukti potong, bukti setor (menu Pajak).",
               "CRITICAL" if today.month == 4 else "WARNING")
    if today.day == 1:
        for index, message in enumerate(tax_warnings(branch_id, settings, today, report["ytd_gross"])):
            notify(f"warning-{index}", "Peringatan pajak", message)
    db.session.commit()
    return {"sent": sent}
