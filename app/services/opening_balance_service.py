"""Saldo awal satu pintu (keputusan owner 2026-09-28, poin 1-5).

Dulu saldo awal diisi di tiga tempat yang tidak saling tahu: jurnal saldo awal
(Akuntansi), saldo awal kas/bank (Keuangan), dan saldo awal stok (Stok). Salah
ketik atau lupa salah satunya membuat buku besar dan buku pembantu berbeda.

Sekarang satu halaman per cabang. Semua baris diisi dulu sebagai draf, lalu
"Kunci Saldo Awal" membuat semuanya sekaligus dalam satu transaksi:

- kas dan tiap rekening bank  -> buku kas/bank (IN saldo awal)
- piutang lama per nota       -> invoice saldo awal (bukan pendapatan)
- hutang supplier lama        -> hutang supplier tanpa pembelian asal
- stok per barang + harga     -> saldo awal stok (ikut harga rata-rata)
- aset lama + akumulasi       -> register aset + penyusutan saldo awal
- hutang lain                 -> hanya jurnal (tidak punya buku pembantu)
- modal pemilik (3001)        -> selisihnya, dihitung otomatis

dan satu jurnal SALDO_AWAL yang angkanya dihitung dari baris yang sama.

Sesudah dikunci: "Buka Kembali" boleh selama belum ada transaksi bertanggal
sejak tanggal mulai; sesudahnya setiap perubahan adalah koreksi beralasan yang
mengubah buku pembantu dan membuat jurnal koreksinya sekaligus.
"""
import json
import re
import uuid
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail, OpeningBalance, OpeningBalanceCorrection

STATUS_DRAFT = "DRAFT"
STATUS_LOCKED = "LOCKED"
JOURNAL_REFERENCE = "SALDO_AWAL"
CORRECTION_REFERENCE = "SALDO_AWAL_KOREKSI"
OPENING_SOURCE = "OPENING_BALANCE"
EQUITY_CODE = "3001"
MIN_REASON_LENGTH = 8

SECTIONS = ("cashbank", "receivables", "payables", "stock", "assets", "liabilities")
SECTION_LABELS = {
    "cashbank": "Kas & Bank",
    "receivables": "Piutang lama",
    "payables": "Hutang supplier lama",
    "stock": "Stok awal",
    "assets": "Aset tetap",
    "liabilities": "Hutang lain",
}
LIABILITY_ACCOUNTS = {
    "2001": "Hutang Usaha / Pembiayaan",
    "2003": "Hutang Gaji",
    "2004": "Hutang Operasional",
    "2005": "Hutang Transport",
    "2006": "Hutang Lain-lain",
}
ASSET_CATEGORY_ACCOUNTS = {
    "KITCHEN_EQUIPMENT": ("1101", "2101"),
    "OFFICE_EQUIPMENT": ("1101", "2101"),
    "OTHER": ("1101", "2101"),
    "VEHICLE": ("1102", "2102"),
    "BUILDING": ("1103", "2103"),
}
ASSET_CATEGORY_LABELS = {
    "KITCHEN_EQUIPMENT": "Peralatan dapur",
    "OFFICE_EQUIPMENT": "Peralatan kantor",
    "VEHICLE": "Kendaraan",
    "BUILDING": "Bangunan / dapur",
    "OTHER": "Lainnya",
}

_CENT = Decimal("0.01")
_ZERO = Decimal("0")


class OpeningBalanceError(Exception):
    pass


# --- angka ---------------------------------------------------------------------

def parse_amount(value, label="Nominal"):
    """Rupiah dari teks form: "1.500.000", "1500000", "1.500.000,50". Kosong = 0."""
    text = re.sub(r"[Rp\s]", "", str(value or ""), flags=re.I)
    if not text:
        return _ZERO
    if "," in text and "." in text:
        text = text.replace(".", "").replace(",", ".")
    elif "," in text:
        text = text.replace(",", ".")
    elif text.count(".") > 1 or re.fullmatch(r"\d{1,3}(\.\d{3})+", text):
        text = text.replace(".", "")
    try:
        amount = Decimal(text).quantize(_CENT, ROUND_HALF_UP)
    except InvalidOperation:
        raise OpeningBalanceError(f"{label} tidak terbaca: {value}")
    if amount < 0:
        raise OpeningBalanceError(f"{label} tidak boleh minus.")
    return amount


def parse_qty(value, label="Qty"):
    try:
        qty = Decimal(str(value or "0").strip().replace(",", "."))
    except InvalidOperation:
        raise OpeningBalanceError(f"{label} tidak terbaca: {value}")
    if qty < 0:
        raise OpeningBalanceError(f"{label} tidak boleh minus.")
    return qty


def _dec(value):
    return Decimal(str(value or 0))


def _date(value, label, required=True):
    if isinstance(value, date):
        return value
    text = str(value or "").strip()
    if not text:
        if required:
            raise OpeningBalanceError(f"{label} wajib diisi.")
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise OpeningBalanceError(f"{label} tidak valid.")


def _int(value):
    try:
        return int(value) if str(value or "").strip() else None
    except (TypeError, ValueError):
        return None


# --- draf ----------------------------------------------------------------------

def get_opening(branch_id):
    return OpeningBalance.query.filter_by(branch_id=branch_id).first()


def get_or_create_opening(branch_id, user_id):
    opening = get_opening(branch_id)
    if opening is None:
        opening = OpeningBalance(branch_id=branch_id, status=STATUS_DRAFT, payload_json=json.dumps(_empty_payload()),
                                 created_by=user_id)
        db.session.add(opening)
        db.session.flush()
    return opening


def run_opening_action(branch_id, user_id, action):
    """Satu perubahan di halaman saldo awal = satu transaksi. Commit; gagal = rollback semua."""
    try:
        result = action(get_or_create_opening(branch_id, user_id))
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


def is_locked(branch_id):
    opening = get_opening(branch_id)
    return bool(opening and opening.status == STATUS_LOCKED)


def _empty_payload():
    return {section: [] for section in SECTIONS}


def load_payload(opening):
    payload = _empty_payload()
    if opening and opening.payload_json:
        stored = json.loads(opening.payload_json)
        for section in SECTIONS:
            payload[section] = list(stored.get(section) or [])
    return payload


def _store_payload(opening, payload):
    opening.payload_json = json.dumps(payload)


def _find(payload, section, key):
    for line in payload[section]:
        if line["key"] == key:
            return line
    return None


# --- membersihkan isian --------------------------------------------------------

def clean_line(section, raw, branch_id):
    """Isian form -> baris draf yang sudah divalidasi (angka disimpan sebagai teks)."""
    from app.models.finance import BankAccount
    from app.models.master import Client, Item, Mandor, Supplier

    if section == "cashbank":
        account_type = str(raw.get("account_type") or "").upper()
        amount = parse_amount(raw.get("amount"))
        if account_type == "CASH":
            return {"key": "CASH", "account_type": "CASH", "bank_account_id": None, "amount": str(amount)}
        bank = BankAccount.query.filter_by(id=_int(raw.get("bank_account_id")), branch_id=branch_id).first()
        if bank is None:
            raise OpeningBalanceError("Rekening bank tidak ditemukan di cabang ini.")
        return {"key": f"BANK:{bank.id}", "account_type": "BANK", "bank_account_id": bank.id, "amount": str(amount)}

    if section == "receivables":
        client = Client.query.get(_int(raw.get("client_id"))) if _int(raw.get("client_id")) else None
        if client is None:
            raise OpeningBalanceError("Pilih pelanggan pemilik piutang.")
        mandor = None
        if _int(raw.get("mandor_id")):
            mandor = Mandor.query.filter_by(id=_int(raw.get("mandor_id")), client_id=client.id).first()
            if mandor is None:
                raise OpeningBalanceError("Mandor tidak termasuk pelanggan ini.")
        amount = parse_amount(raw.get("amount"), "Sisa piutang")
        if amount <= 0:
            raise OpeningBalanceError("Sisa piutang harus lebih dari 0.")
        invoice_date = _date(raw.get("invoice_date"), "Tanggal nota")
        due_date = _date(raw.get("due_date"), "Jatuh tempo", required=False) or invoice_date
        if due_date < invoice_date:
            raise OpeningBalanceError("Jatuh tempo tidak boleh sebelum tanggal nota.")
        return {
            "client_id": client.id, "client_name": client.name,
            "mandor_id": mandor.id if mandor else None, "mandor_name": mandor.name if mandor else None,
            "reference": str(raw.get("reference") or "").strip() or "tanpa nota",
            "invoice_date": invoice_date.isoformat(), "due_date": due_date.isoformat(), "amount": str(amount),
        }

    if section == "payables":
        supplier = None
        if _int(raw.get("supplier_id")):
            supplier = Supplier.query.filter_by(id=_int(raw.get("supplier_id")), branch_id=branch_id).first()
        supplier_name = (supplier.supplier_name if supplier else str(raw.get("supplier_name") or "").strip())
        if not supplier_name:
            raise OpeningBalanceError("Pilih supplier atau tulis namanya.")
        amount = parse_amount(raw.get("amount"), "Sisa hutang")
        if amount <= 0:
            raise OpeningBalanceError("Sisa hutang harus lebih dari 0.")
        bill_date = _date(raw.get("bill_date"), "Tanggal nota")
        due_date = _date(raw.get("due_date"), "Jatuh tempo", required=False) or bill_date
        if due_date < bill_date:
            raise OpeningBalanceError("Jatuh tempo tidak boleh sebelum tanggal nota.")
        return {
            "supplier_id": supplier.id if supplier else None, "supplier_name": supplier_name,
            "reference": str(raw.get("reference") or "").strip() or "tanpa nota",
            "bill_date": bill_date.isoformat(), "due_date": due_date.isoformat(), "amount": str(amount),
        }

    if section == "stock":
        item = Item.query.get(_int(raw.get("item_id"))) if _int(raw.get("item_id")) else None
        if item is None or not item.is_stock_tracked:
            raise OpeningBalanceError("Pilih barang yang dilacak stoknya.")
        qty = parse_qty(raw.get("qty"))
        unit_cost = parse_amount(raw.get("unit_cost"), "Harga satuan")
        if qty > 0 and unit_cost <= 0:
            raise OpeningBalanceError(f"Harga satuan {item.item_name} wajib diisi supaya nilai stoknya masuk buku besar.")
        return {"item_id": item.id, "item_name": item.item_name, "unit": item.unit, "qty": str(qty), "unit_cost": str(unit_cost)}

    if section == "assets":
        name = str(raw.get("name") or "").strip()
        if not name:
            raise OpeningBalanceError("Nama aset wajib diisi.")
        category = str(raw.get("category") or "OTHER").upper()
        if category not in ASSET_CATEGORY_ACCOUNTS:
            category = "OTHER"
        purchase_value = parse_amount(raw.get("purchase_value"), "Nilai beli")
        accumulated = parse_amount(raw.get("accumulated"), "Akumulasi penyusutan")
        if purchase_value <= 0:
            raise OpeningBalanceError("Nilai beli aset harus lebih dari 0.")
        if accumulated > purchase_value:
            raise OpeningBalanceError("Akumulasi penyusutan tidak boleh melebihi nilai beli.")
        return {
            "name": name, "category": category,
            "purchase_date": _date(raw.get("purchase_date"), "Tanggal beli aset").isoformat(),
            "purchase_value": str(purchase_value), "accumulated": str(accumulated),
            "useful_life_years": _int(raw.get("useful_life_years")) or 0,
        }

    if section == "liabilities":
        code = str(raw.get("account_code") or "")
        if code not in LIABILITY_ACCOUNTS:
            raise OpeningBalanceError("Pilih jenis hutang.")
        amount = parse_amount(raw.get("amount"))
        if amount <= 0:
            raise OpeningBalanceError("Nominal hutang harus lebih dari 0.")
        return {"account_code": code, "description": str(raw.get("description") or "").strip() or LIABILITY_ACCOUNTS[code],
                "amount": str(amount)}

    raise OpeningBalanceError("Bagian saldo awal tidak dikenal.")


# --- nilai dan neraca ----------------------------------------------------------

def line_effects(section, line):
    """Pengaruh satu baris ke buku besar: {kode akun: debit (+) / kredit (-)}."""
    from app.services.cash_bank_service import cash_bank_coa_code

    if section == "cashbank":
        return {cash_bank_coa_code(line["account_type"]): _dec(line["amount"])}
    if section == "receivables":
        return {"1004": _dec(line["amount"])}
    if section == "payables":
        return {"2002": -_dec(line["amount"])}
    if section == "stock":
        return {"1006": (_dec(line["qty"]) * _dec(line["unit_cost"])).quantize(_CENT, ROUND_HALF_UP)}
    if section == "assets":
        asset_code, accumulated_code = ASSET_CATEGORY_ACCOUNTS[line["category"]]
        return {asset_code: _dec(line["purchase_value"]), accumulated_code: -_dec(line["accumulated"])}
    if section == "liabilities":
        return {line["account_code"]: -_dec(line["amount"])}
    return {}


def _add_effects(total, effects, sign=1):
    for code, amount in effects.items():
        total[code] = total.get(code, _ZERO) + sign * amount
    return total


def payload_effects(payload):
    total = {}
    for section in SECTIONS:
        for line in payload[section]:
            _add_effects(total, line_effects(section, line))
    return {code: amount for code, amount in total.items() if amount != 0}


def balance_preview(payload):
    """Neraca saldo awal: baris per akun, modal otomatis, dan hal yang menahan penguncian."""
    effects = payload_effects(payload)
    equity = sum(effects.values(), _ZERO)  # harta - hutang = modal (saldo kredit 3001)
    names ={row.account_code: row.account_name for row in Account.query.filter(Account.account_code.in_(list(effects) + [EQUITY_CODE])).all()}
    rows = [
        {"code": code, "name": names.get(code, code), "debit": amount if amount > 0 else _ZERO, "credit": -amount if amount < 0 else _ZERO}
        for code, amount in sorted(effects.items())
    ]
    if equity:
        rows.append({"code": EQUITY_CODE, "name": names.get(EQUITY_CODE, "Modal Pemilik"),
                     "debit": -equity if equity < 0 else _ZERO, "credit": equity if equity > 0 else _ZERO})
    total_debit = sum((row["debit"] for row in rows), _ZERO)
    total_credit = sum((row["credit"] for row in rows), _ZERO)
    problems = []
    if not effects:
        problems.append("Belum ada saldo yang diisi.")
    if equity < 0:
        problems.append("Hutang lebih besar dari harta: modal pemilik jadi minus. Periksa lagi angkanya.")
    return {"rows": rows, "equity": equity, "total_debit": total_debit, "total_credit": total_credit, "problems": problems}


# --- jurnal --------------------------------------------------------------------

def _post_journal(*, reference_type, reference_id, journal_date, description, effects, created_by):
    """Satu jurnal dari pengaruh per akun; selisihnya ke 3001 Modal Pemilik. None kalau semuanya nol."""
    from app.services.accounting_service import generate_journal_number, get_active_account_by_code

    effects = {code: amount for code, amount in effects.items() if amount != 0}
    equity = -sum(effects.values(), _ZERO)
    if equity:
        effects[EQUITY_CODE] = effects.get(EQUITY_CODE, _ZERO) + equity
    effects = {code: amount for code, amount in effects.items() if amount != 0}
    if not effects:
        return None
    accounts = {code: get_active_account_by_code(code) for code in effects}
    missing = [code for code, account in accounts.items() if account is None]
    if missing:
        raise OpeningBalanceError(f"Akun {', '.join(sorted(missing))} belum ada atau tidak aktif di COA.")
    journal = Journal(
        journal_number=generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type=reference_type,
        reference_id=reference_id,
        description=description,
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()
    for code, amount in sorted(effects.items()):
        db.session.add(JournalDetail(journal_id=journal.id, account_id=accounts[code].id,
                                     debit=amount if amount > 0 else 0, credit=-amount if amount < 0 else 0))
    db.session.flush()
    return journal


# --- membuat, mengubah, menghapus catatan buku pembantu ------------------------

def _create_record(opening, section, line, journal, user_id):
    """Buat catatan buku pembantu untuk satu baris. Mengembalikan baris + id catatannya."""
    from app.models.accounting import FixedAsset
    from app.models.finance import CashBankOpeningBalance, CashBankTransaction, Invoice, InvoiceItem, SupplierBill
    from app.models.logistics import StockOpeningBalance
    from app.services.cash_bank_service import OPENING_BALANCE_REFERENCE_TYPE, _money, get_account_label
    from app.services.fixed_asset_purchase_service import generate_fixed_asset_code
    from app.services.logistics_transaction_service import next_daily_number
    from app.services.order_invoice_service import generate_invoice_number

    line = dict(line)
    start = opening.start_date
    branch_id = opening.branch_id

    if section == "cashbank":
        account_key = line["key"]
        if CashBankOpeningBalance.query.filter_by(branch_id=branch_id, account_key=account_key).first():
            raise OpeningBalanceError("Saldo awal kas/bank ini sudah pernah dicatat di halaman lama. Hubungi admin sistem.")
        record = CashBankOpeningBalance(branch_id=branch_id, account_type=line["account_type"], bank_account_id=line["bank_account_id"],
                                        account_key=account_key, opening_date=start, amount=_dec(line["amount"]),
                                        notes="Saldo awal satu pintu", created_by=user_id)
        db.session.add(record)
        db.session.flush()
        bank = record.bank_account if line["bank_account_id"] else None
        ledger = CashBankTransaction(branch_id=branch_id, transaction_date=start, account_type=line["account_type"],
                                     bank_account_id=line["bank_account_id"], transaction_type="IN", amount=_dec(line["amount"]),
                                     description=f"Saldo awal {get_account_label(line['account_type'], bank)} sebesar {_money(_dec(line['amount']))}",
                                     reference_type=OPENING_BALANCE_REFERENCE_TYPE, reference_id=record.id, created_by=user_id)
        db.session.add(ledger)
        db.session.flush()
        record.ledger_transaction_id = ledger.id
        line.update(record_id=record.id, ledger_id=ledger.id)

    elif section == "receivables":
        amount = _dec(line["amount"])
        invoice_date = _date(line["invoice_date"], "Tanggal nota")
        invoice = Invoice(branch_id=branch_id, invoice_number=generate_invoice_number(invoice_date), invoice_date=invoice_date,
                          due_date=_date(line["due_date"], "Jatuh tempo"), bill_to_type="MANDOR" if line["mandor_id"] else "CLIENT",
                          client_id=line["client_id"], mandor_id=line["mandor_id"], client_name_snapshot=line["client_name"],
                          total_amount=amount, paid_amount=0, remaining_amount=amount, status="DRAFT",
                          notes=f"Piutang saldo awal, nota {line['reference']}", source_type=OPENING_SOURCE, created_by=user_id)
        db.session.add(invoice)
        db.session.flush()
        db.session.add(InvoiceItem(invoice_id=invoice.id, item_type="SALDO_AWAL", description=f"Saldo awal piutang - nota {line['reference']}",
                                   qty=1, unit_price=amount, subtotal=amount, source_type=OPENING_SOURCE, source_id=opening.id))
        line.update(record_id=invoice.id)

    elif section == "payables":
        amount = _dec(line["amount"])
        bill_date = _date(line["bill_date"], "Tanggal nota")
        bill = SupplierBill(branch_id=branch_id, bill_number=next_daily_number(SupplierBill, "bill_number", "HSA", bill_date),
                            supplier_id=line["supplier_id"], procurement_id=None, bill_date=bill_date,
                            due_date=_date(line["due_date"], "Jatuh tempo"), supplier_name=line["supplier_name"],
                            total_amount=amount, paid_amount=0, remaining_amount=amount, status="OPEN",
                            notes=f"Hutang saldo awal, nota {line['reference']}", created_by=user_id)
        db.session.add(bill)
        db.session.flush()
        line.update(record_id=bill.id)

    elif section == "stock":
        if StockOpeningBalance.query.filter_by(branch_id=branch_id, item_id=line["item_id"]).first():
            raise OpeningBalanceError(f"Saldo awal stok {line['item_name']} sudah pernah dicatat di halaman lama. Hubungi admin sistem.")
        record = StockOpeningBalance(branch_id=branch_id, item_id=line["item_id"], opening_date=start, qty=_dec(line["qty"]),
                                     unit_cost=_dec(line["unit_cost"]), notes="Saldo awal satu pintu", created_by=user_id)
        db.session.add(record)
        db.session.flush()
        line.update(record_id=record.id)

    elif section == "assets":
        purchase_value, accumulated = _dec(line["purchase_value"]), _dec(line["accumulated"])
        asset = FixedAsset(branch_id=branch_id, asset_code=generate_fixed_asset_code(), asset_name=line["name"],
                           asset_category=line["category"], purchase_date=_date(line["purchase_date"], "Tanggal beli aset"),
                           purchase_value=purchase_value, useful_life_years=line["useful_life_years"] or 0, residual_value=0,
                           accumulated_depreciation=accumulated, book_value=purchase_value - accumulated, status="ACTIVE",
                           notes="Aset saldo awal")
        db.session.add(asset)
        db.session.flush()
        line.update(record_id=asset.id, entry_id=None)
        if accumulated > 0:
            line["entry_id"] = _opening_depreciation_entry(opening, asset, accumulated, journal, user_id).id

    return line


def _opening_depreciation_entry(opening, asset, accumulated, journal, user_id):
    """Akumulasi penyusutan sebelum sistem dipakai, dicatat sebagai satu entri penyusutan
    di bulan sebelum tanggal mulai. Modul penyusutan menjumlahkan entri, jadi
    penyusutan berikutnya berlanjut dari sini dan berhenti di nilai residu."""
    from app.models.accounting import FixedAssetDepreciation
    from app.services.fixed_asset_depreciation_service import generate_depreciation_number

    entry_date = opening.start_date - timedelta(days=1)
    entry = FixedAssetDepreciation(branch_id=opening.branch_id, depreciation_number=generate_depreciation_number(entry_date),
                                   fixed_asset_id=asset.id, period_year=entry_date.year, period_month=entry_date.month,
                                   depreciation_date=entry_date, amount=accumulated, accumulated_depreciation_after=accumulated,
                                   book_value_after=_dec(asset.purchase_value) - accumulated,
                                   journal_id=journal.id if journal else None, status="POSTED", created_by=user_id)
    db.session.add(entry)
    db.session.flush()
    return entry


def _update_record(opening, section, old, new, journal, user_id):
    """Koreksi angka satu baris yang sudah jadi catatan. Mengembalikan baris baru + id catatannya."""
    from app.models.accounting import FixedAsset, FixedAssetDepreciation
    from app.models.finance import CashBankOpeningBalance, CashBankTransaction, Invoice, SupplierBill
    from app.models.logistics import StockOpeningBalance
    from app.services.business_logic_guard_service import resolve_invoice_status_after_payment, resolve_supplier_bill_status_after_payment
    from app.services.stock_service import get_item_stock

    new = dict(new)
    for field in ("record_id", "ledger_id", "entry_id"):
        if field in old:
            new[field] = old[field]

    if section == "cashbank":
        record = db.session.get(CashBankOpeningBalance, old["record_id"])
        ledger = db.session.get(CashBankTransaction, old["ledger_id"])
        record.amount = ledger.amount = _dec(new["amount"])

    elif section == "receivables":
        invoice = db.session.get(Invoice, old["record_id"])
        if (new["client_id"], new["mandor_id"]) != (old["client_id"], old["mandor_id"]):
            raise OpeningBalanceError("Pelanggan piutang tidak bisa diganti. Hapus baris ini lalu tambahkan baris baru.")
        amount = _dec(new["amount"])
        paid = _dec(invoice.paid_amount)
        if amount < paid:
            raise OpeningBalanceError(f"Piutang {invoice.invoice_number} sudah dibayar {paid:,.0f}; nilainya tidak bisa di bawah itu.")
        invoice.total_amount, invoice.remaining_amount = amount, amount - paid
        invoice.invoice_date = _date(new["invoice_date"], "Tanggal nota")
        invoice.due_date = _date(new["due_date"], "Jatuh tempo")
        invoice.status = resolve_invoice_status_after_payment(amount, paid)
        for item in invoice.items:
            item.unit_price = item.subtotal = amount
            item.description = f"Saldo awal piutang - nota {new['reference']}"

    elif section == "payables":
        bill = db.session.get(SupplierBill, old["record_id"])
        amount = _dec(new["amount"])
        paid = _dec(bill.paid_amount)
        if amount < paid:
            raise OpeningBalanceError(f"Hutang {bill.bill_number} sudah dibayar {paid:,.0f}; nilainya tidak bisa di bawah itu.")
        bill.total_amount, bill.remaining_amount = amount, amount - paid
        bill.due_date = _date(new["due_date"], "Jatuh tempo")
        bill.status = resolve_supplier_bill_status_after_payment(amount, paid)

    elif section == "stock":
        record = db.session.get(StockOpeningBalance, old["record_id"])
        stock_after = _dec(get_item_stock(opening.branch_id, record.item_id)) - _dec(old["qty"]) + _dec(new["qty"])
        if stock_after < 0:
            raise OpeningBalanceError(f"Stok {old['item_name']} jadi minus ({stock_after:g}) kalau saldo awalnya diubah begitu.")
        record.qty, record.unit_cost = _dec(new["qty"]), _dec(new["unit_cost"])

    elif section == "assets":
        asset = db.session.get(FixedAsset, old["record_id"])
        if new["category"] != old["category"]:
            raise OpeningBalanceError("Kategori aset tidak bisa diganti lewat koreksi. Hapus baris ini lalu tambahkan baris baru.")
        delta_accumulated = _dec(new["accumulated"]) - _dec(old["accumulated"])
        asset.asset_name, asset.purchase_value = new["name"], _dec(new["purchase_value"])
        asset.accumulated_depreciation = _dec(asset.accumulated_depreciation) + delta_accumulated
        asset.book_value = _dec(asset.purchase_value) - _dec(asset.accumulated_depreciation)
        if asset.book_value < 0:
            raise OpeningBalanceError("Nilai buku aset jadi minus kalau nilainya diubah begitu.")
        entry = db.session.get(FixedAssetDepreciation, old["entry_id"]) if old.get("entry_id") else None
        if _dec(new["accumulated"]) > 0 and entry is None:
            new["entry_id"] = _opening_depreciation_entry(opening, asset, _dec(new["accumulated"]), journal, user_id).id
        elif entry is not None:
            entry.amount = entry.accumulated_depreciation_after = _dec(new["accumulated"])
            entry.book_value_after = _dec(asset.purchase_value) - _dec(new["accumulated"])

    return new


def _remove_record(section, line, *, correcting):
    """Hapus catatan satu baris. Saat koreksi, catatan yang sudah dipakai transaksi tidak bisa dihapus."""
    from app.models.accounting import FixedAsset, FixedAssetDepreciation, FixedAssetDepreciationConfig
    from app.models.finance import CashBankOpeningBalance, CashBankTransaction, Invoice, SupplierBill
    from app.models.logistics import StockOpeningBalance
    from app.services.stock_service import get_item_stock

    if section == "liabilities" or not line.get("record_id"):
        return

    if section == "cashbank":
        record = db.session.get(CashBankOpeningBalance, line["record_id"])
        record.ledger_transaction_id = None
        db.session.flush()
        db.session.delete(db.session.get(CashBankTransaction, line["ledger_id"]))
        db.session.delete(record)

    elif section == "receivables":
        invoice = db.session.get(Invoice, line["record_id"])
        if _dec(invoice.paid_amount) > 0 or invoice.payments:
            raise OpeningBalanceError(f"Piutang {invoice.invoice_number} sudah ada pembayarannya; tidak bisa dihapus.")
        for item in list(invoice.items):
            db.session.delete(item)
        db.session.flush()
        db.session.delete(invoice)

    elif section == "payables":
        bill = db.session.get(SupplierBill, line["record_id"])
        if _dec(bill.paid_amount) > 0:
            raise OpeningBalanceError(f"Hutang {bill.bill_number} sudah ada pembayarannya; tidak bisa dihapus.")
        db.session.delete(bill)

    elif section == "stock":
        record = db.session.get(StockOpeningBalance, line["record_id"])
        if correcting and _dec(get_item_stock(record.branch_id, record.item_id)) - _dec(line["qty"]) < 0:
            raise OpeningBalanceError(f"Stok {line['item_name']} sudah terpakai; saldo awalnya tidak bisa dihapus. Ubah qty-nya saja.")
        db.session.delete(record)

    elif section == "assets":
        asset = db.session.get(FixedAsset, line["record_id"])
        entries = FixedAssetDepreciation.query.filter_by(fixed_asset_id=asset.id).all()
        if any(entry.id != line.get("entry_id") for entry in entries):
            raise OpeningBalanceError(f"Aset {asset.asset_name} sudah disusutkan di sistem; tidak bisa dihapus.")
        for entry in entries:
            db.session.delete(entry)
        config = FixedAssetDepreciationConfig.query.filter_by(fixed_asset_id=asset.id).first()
        if config is not None:
            db.session.delete(config)
        db.session.flush()
        db.session.delete(asset)
    db.session.flush()


# --- aksi halaman ---------------------------------------------------------------

def set_start_date(opening, value):
    if opening.status == STATUS_LOCKED:
        raise OpeningBalanceError("Tanggal mulai tidak bisa diubah setelah dikunci. Buka kembali dulu.")
    opening.start_date = _date(value, "Tanggal mulai")


def change_line(opening, section, key, raw, *, user, reason=None):
    """Tambah (key None), ubah, atau hapus (raw None) satu baris.

    Draf: hanya isi draf yang berubah. Sudah dikunci: koreksi -- wajib alasan,
    hanya OWNER, catatan buku pembantu ikut berubah, dan jurnal koreksinya
    dibuat dengan selisihnya ke 3001 Modal Pemilik.
    """
    from app.utils.roles import effective_role

    if section not in SECTIONS:
        raise OpeningBalanceError("Bagian saldo awal tidak dikenal.")
    payload = load_payload(opening)
    old = _find(payload, section, key) if key else None
    if key and old is None:
        raise OpeningBalanceError("Baris saldo awal tidak ditemukan. Muat ulang halaman.")
    new = None
    if raw is not None:
        new = clean_line(section, raw, opening.branch_id)
        new["key"] = new.get("key") or (old["key"] if old else uuid.uuid4().hex[:10])
        if section == "cashbank" and old is None:
            old = _find(payload, section, new["key"])
        elif section == "stock" and any(line["item_id"] == new["item_id"] and line["key"] != new["key"] for line in payload["stock"]):
            raise OpeningBalanceError(f"{new['item_name']} sudah ada di daftar stok awal. Ubah barisnya saja.")

    if section == "cashbank" and new is not None and _dec(new["amount"]) == 0 and (opening.status == STATUS_DRAFT or old is None):
        new = None  # kas/bank nol: di draf cukup tidak ada barisnya
        if old is None:
            return
    if old is not None and new is not None and _same_line(old, new):
        return

    if opening.status == STATUS_LOCKED:
        if effective_role(getattr(user, "role", None)) != "OWNER":
            raise OpeningBalanceError("Saldo awal sudah dikunci. Koreksinya hanya bisa dilakukan OWNER.")
        reason = str(reason or "").strip()
        if len(reason) < MIN_REASON_LENGTH:
            raise OpeningBalanceError(f"Tulis alasan koreksi (minimal {MIN_REASON_LENGTH} huruf).")
        new = _correct(opening, section, old, new, user.id, reason)

    lines = [line for line in payload[section] if not (old and line["key"] == old["key"])]
    if new is not None:
        lines.append(new)
    payload[section] = lines
    _store_payload(opening, payload)
    opening.updated_by = user.id
    db.session.flush()


def _same_line(old, new):
    ignore = {"record_id", "ledger_id", "entry_id"}
    return {k: v for k, v in old.items() if k not in ignore} == {k: v for k, v in new.items() if k not in ignore}


def _correct(opening, section, old, new, user_id, reason):
    from app.services.audit_log_service import record_audit_log

    from app.models.accounting import FixedAssetDepreciation

    effects = {}
    if old:
        _add_effects(effects, line_effects(section, old), sign=-1)
    if new:
        _add_effects(effects, line_effects(section, new))

    # Buku pembantu dulu: di sinilah koreksi yang tidak boleh (sudah dibayar,
    # stok jadi minus, aset sudah disusutkan) ditolak, sebelum ada jurnal apa pun.
    if old and new:
        new = _update_record(opening, section, old, new, None, user_id)
    elif new:
        new = _create_record(opening, section, new, None, user_id)
    else:
        _remove_record(section, old, correcting=True)

    correction = OpeningBalanceCorrection(opening_balance_id=opening.id, section=section,
                                          line_key=(new or old)["key"], action="ADD" if not old else ("REMOVE" if not new else "UPDATE"),
                                          reason=reason, before_json=json.dumps(old) if old else None,
                                          after_json=json.dumps(new) if new else None, created_by=user_id)
    db.session.add(correction)
    db.session.flush()
    journal = _post_journal(reference_type=CORRECTION_REFERENCE, reference_id=correction.id, journal_date=opening.start_date,
                            description=f"Koreksi saldo awal ({SECTION_LABELS[section]}): {reason}", effects=effects, created_by=user_id)
    correction.journal_id = journal.id if journal else None
    entry = db.session.get(FixedAssetDepreciation, new["entry_id"]) if new and new.get("entry_id") else None
    if journal is not None and entry is not None and entry.journal_id is None:
        entry.journal_id = journal.id

    record_audit_log(module="ACCOUNTING", event_type="OPENING_BALANCE_CORRECTED", action="UPDATE", table_name="opening_balances",
                     record_id=opening.id, description=f"Koreksi saldo awal {SECTION_LABELS[section]}: {reason}",
                     metadata={"reason": reason, "section": section, "before": old, "after": new,
                               "journal_id": correction.journal_id}, user_id=user_id, branch_id=opening.branch_id, commit=False)
    return new


def lock_opening(opening, *, user):
    """Buat semua catatan buku pembantu + satu jurnal saldo awal. Tidak commit."""
    from app.services.audit_log_service import record_audit_log

    if opening.status == STATUS_LOCKED:
        raise OpeningBalanceError("Saldo awal sudah dikunci.")
    if opening.start_date is None:
        raise OpeningBalanceError("Isi tanggal mulai pakai sistem dulu.")
    payload = load_payload(opening)
    preview = balance_preview(payload)
    if preview["problems"]:
        raise OpeningBalanceError(" ".join(preview["problems"]))

    journal = _post_journal(reference_type=JOURNAL_REFERENCE, reference_id=opening.id, journal_date=opening.start_date,
                            description="Jurnal saldo awal", effects=payload_effects(payload), created_by=user.id)
    for section in SECTIONS:
        payload[section] = [_create_record(opening, section, line, journal, user.id) if section != "liabilities" else line
                            for line in payload[section]]
    _store_payload(opening, payload)
    opening.status = STATUS_LOCKED
    opening.journal_id = journal.id
    opening.locked_by = user.id
    opening.locked_at = datetime.utcnow()
    record_audit_log(module="ACCOUNTING", event_type="OPENING_BALANCE_LOCKED", action="CREATE", table_name="opening_balances",
                     record_id=opening.id, description=f"Saldo awal dikunci per {opening.start_date:%d-%m-%Y}, jurnal {journal.journal_number}.",
                     metadata={"start_date": opening.start_date.isoformat(), "journal_id": journal.id,
                               "equity": str(preview["equity"])}, user_id=user.id, branch_id=opening.branch_id, commit=False)
    db.session.flush()
    return journal


def later_activity(opening):
    """Transaksi cabang ini yang bertanggal sejak tanggal mulai (selain catatan saldo awal sendiri)."""
    from app.models.accounting import FixedAsset, FixedAssetDepreciation
    from app.models.finance import CashBankTransaction, Invoice, Payment, SupplierBill, SupplierPayment
    from app.models.logistics import Procurement, StockMovement

    if opening is None or opening.start_date is None:
        return []
    payload = load_payload(opening)

    def ids(section, field="record_id"):
        return [line[field] for line in payload[section] if line.get(field)]

    checks = (
        ("buku kas/bank", CashBankTransaction, CashBankTransaction.transaction_date, ids("cashbank", "ledger_id")),
        ("pergerakan stok", StockMovement, StockMovement.movement_date, []),
        ("invoice", Invoice, Invoice.invoice_date, ids("receivables")),
        ("pembayaran invoice", Payment, Payment.payment_date, []),
        ("hutang supplier", SupplierBill, SupplierBill.bill_date, ids("payables")),
        ("pembayaran supplier", SupplierPayment, SupplierPayment.payment_date, []),
        ("pembelian barang", Procurement, Procurement.procurement_date, []),
        ("aset tetap", FixedAsset, FixedAsset.purchase_date, ids("assets")),
        ("penyusutan", FixedAssetDepreciation, FixedAssetDepreciation.depreciation_date, ids("assets", "entry_id")),
    )
    found = []
    for label, model, date_column, own_ids in checks:
        query = model.query.filter(model.branch_id == opening.branch_id, date_column >= opening.start_date)
        if own_ids:
            query = query.filter(~model.id.in_(own_ids))
        count = query.count()
        if count:
            found.append(f"{count} {label}")
    return found


def reopen_opening(opening, *, user, reason):
    """Batalkan penguncian: hapus semua catatan dan jurnal saldo awal, kembali ke draf. Tidak commit."""
    from app.services.audit_log_service import record_audit_log

    if opening.status != STATUS_LOCKED:
        raise OpeningBalanceError("Saldo awal belum dikunci.")
    activity = later_activity(opening)
    if activity:
        raise OpeningBalanceError(
            "Sudah ada transaksi sejak tanggal mulai (" + ", ".join(activity) + "). "
            "Saldo awal tidak bisa dibuka kembali; perbaiki lewat koreksi."
        )
    payload = load_payload(opening)
    for section in reversed(SECTIONS):
        for line in payload[section]:
            _remove_record(section, line, correcting=False)
            for field in ("record_id", "ledger_id", "entry_id"):
                line.pop(field, None)
    corrections = OpeningBalanceCorrection.query.filter_by(opening_balance_id=opening.id).all()
    journal_ids = [opening.journal_id] + [row.journal_id for row in corrections if row.journal_id]
    for row in corrections:
        row.journal_id = None
    opening.journal_id = None
    db.session.flush()
    for journal in Journal.query.filter(Journal.id.in_([jid for jid in journal_ids if jid])).all():
        JournalDetail.query.filter_by(journal_id=journal.id).delete()
        db.session.delete(journal)
    _store_payload(opening, payload)
    opening.status = STATUS_DRAFT
    opening.locked_at = opening.locked_by = None
    record_audit_log(module="ACCOUNTING", event_type="OPENING_BALANCE_REOPENED", action="UPDATE", table_name="opening_balances",
                     record_id=opening.id, description=f"Saldo awal dibuka kembali: {reason}", metadata={"reason": reason},
                     user_id=user.id, branch_id=opening.branch_id, commit=False)
    db.session.flush()


def branches_without_opening():
    """Cabang aktif yang saldo awalnya belum dikunci (untuk ops-check dan dashboard)."""
    from app.models.master import Branch

    locked = {row.branch_id for row in OpeningBalance.query.filter_by(status=STATUS_LOCKED).all()}
    return [branch for branch in Branch.query.filter_by(is_active=True).order_by(Branch.id).all() if branch.id not in locked]
