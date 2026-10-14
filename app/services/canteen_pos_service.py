"""Kasir cepat warung (keputusan owner 2026-10-13).

Satu layar untuk jam ramai (pagi, sore, malam pulang lembur): pilih orang,
ketuk barang, ketuk TUNAI / QRIS / HUTANG. Harga selalu diambil dari master
barang di server, bukan dari browser. Penyimpanan tetap lewat
`canteen_service.create_canteen_sale` supaya jurnal, buku kas, dan hutang
pekerja tidak punya jalur kedua.

Batas hutang per pekerja = peringatan saja (owner memilih "peringatan saja"),
dihitung dari hutang warung yang belum masuk invoice mandor.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from sqlalchemy import func

from app.extensions import db
from app.models.canteen import CanteenSale, CanteenSaleItem, DebtPayment, WorkerDebt
from app.models.finance import Invoice, InvoiceItem
from app.models.master import Item, Mandor, Worker
from app.utils.clock import format_wib, today_wib

QUICK_ITEM_PRICES = {
    "Kopi Sachet": 5000,
    "Mie Instan": 8000,
    "Snack": 3000,
    "Air Mineral": 4000,
    "Rokok": 25000,
}

POPULAR_DAYS = 30
CHECKOUT_METHODS = ("CASH", "QRIS", "DEBT")


class CanteenPosError(ValueError):
    """Penolakan kasir yang pesannya aman ditampilkan ke kasir."""


def money(value) -> Decimal:
    try:
        return Decimal(str(value or 0)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def worker_debt_limit(branch_id: int) -> Decimal:
    """Batas hutang warung per pekerja dari Pengaturan Perusahaan. 0 = tanpa batas."""
    from app.services.company_settings_service import get_company_settings

    raw = str(get_company_settings(branch_id).get("warung.worker_debt_limit") or "0").strip()
    return money(raw) if raw.isdigit() else Decimal("0.00")


def item_price(item: Item) -> Decimal:
    price = money(getattr(item, "selling_price", 0))
    if price <= 0:
        price = money(QUICK_ITEM_PRICES.get(item.item_name, 0))
    return price


def _merchandise_items():
    return (
        Item.query.filter(Item.is_active.is_(True), func.upper(Item.category) == "MERCHANDISE")
        .order_by(Item.item_name.asc())
        .all()
    )


def pos_items(branch_id: int) -> list[dict]:
    """Barang warung, yang paling laku 30 hari terakhir di atas."""
    since = today_wib() - timedelta(days=POPULAR_DAYS)
    sold = dict(
        db.session.query(CanteenSaleItem.item_id, func.coalesce(func.sum(CanteenSaleItem.qty), 0))
        .join(CanteenSale, CanteenSale.id == CanteenSaleItem.sale_id)
        .filter(CanteenSale.branch_id == branch_id, CanteenSale.sale_date >= since)
        .group_by(CanteenSaleItem.item_id)
        .all()
    )
    rows = []
    for item in _merchandise_items():
        price = item_price(item)
        if price <= 0:
            continue
        rows.append({
            "id": item.id,
            "name": item.item_name,
            "unit": item.unit,
            "price": int(price),
            "sold": int(sold.get(item.id) or 0),
        })
    rows.sort(key=lambda row: (-row["sold"], row["name"].lower()))
    return rows


def _invoiced_debt_ids(debt_ids) -> set[int]:
    if not debt_ids:
        return set()
    rows = (
        db.session.query(InvoiceItem.source_id)
        .join(Invoice, Invoice.id == InvoiceItem.invoice_id)
        .filter(
            InvoiceItem.source_type == "WORKER_DEBT",
            InvoiceItem.source_id.in_(list(debt_ids)),
            Invoice.status != "CANCELLED",
        )
        .all()
    )
    return {int(row[0]) for row in rows}


def _open_debts(branch_id: int, worker_id: int | None = None):
    query = WorkerDebt.query.filter(WorkerDebt.branch_id == branch_id, WorkerDebt.status != "PAID")
    if worker_id:
        query = query.filter(WorkerDebt.worker_id == int(worker_id))
    return query.order_by(WorkerDebt.id.asc()).all()


def _paid_by_debt(debt_ids) -> dict[int, Decimal]:
    if not debt_ids:
        return {}
    rows = (
        db.session.query(DebtPayment.worker_debt_id, func.coalesce(func.sum(DebtPayment.amount), 0))
        .filter(DebtPayment.worker_debt_id.in_(list(debt_ids)))
        .group_by(DebtPayment.worker_debt_id)
        .all()
    )
    return {int(debt_id): money(total) for debt_id, total in rows}


def worker_balances(branch_id: int, worker_id: int | None = None) -> dict[int, dict]:
    """Per pekerja: hutang warung (belum ditagih ke mandor) dan yang sudah masuk invoice mandor."""
    debts = _open_debts(branch_id, worker_id)
    ids = [debt.id for debt in debts]
    paid = _paid_by_debt(ids)
    invoiced = _invoiced_debt_ids(ids)
    result: dict[int, dict] = defaultdict(lambda: {"warung": Decimal("0.00"), "invoiced": Decimal("0.00")})
    for debt in debts:
        remaining = money(debt.debt_amount) - paid.get(debt.id, Decimal("0.00"))
        if remaining <= 0:
            continue
        bucket = "invoiced" if debt.id in invoiced else "warung"
        result[debt.worker_id][bucket] += remaining
    return dict(result)


def pos_workers(branch_id: int) -> list[dict]:
    """Pekerja aktif cabang ini: yang sering belanja 30 hari terakhir di atas."""
    since = today_wib() - timedelta(days=POPULAR_DAYS)
    workers = (
        Worker.query.join(Mandor, Mandor.id == Worker.mandor_id)
        .filter(Mandor.branch_id == branch_id, func.upper(Worker.status).in_(["ACTIVE", "AKTIF"]))
        .order_by(Worker.full_name.asc())
        .all()
    )
    visits = dict(
        db.session.query(WorkerDebt.worker_id, func.count(WorkerDebt.id))
        .join(CanteenSale, CanteenSale.id == WorkerDebt.sale_id)
        .filter(WorkerDebt.branch_id == branch_id, CanteenSale.sale_date >= since)
        .group_by(WorkerDebt.worker_id)
        .all()
    )
    balances = worker_balances(branch_id)
    rows = []
    for worker in workers:
        balance = balances.get(worker.id, {})
        rows.append({
            "id": worker.id,
            "name": worker.full_name,
            "code": worker.worker_code or "",
            "group": worker.mandor.name if worker.mandor else "",
            "debt": int(balance.get("warung", 0)),
            "invoiced": int(balance.get("invoiced", 0)),
            "visits": int(visits.get(worker.id) or 0),
        })
    rows.sort(key=lambda row: (-row["visits"], row["name"].lower()))
    return rows


def _worker_in_branch(branch_id: int, worker_id) -> Worker:
    try:
        worker_id = int(worker_id)
    except (TypeError, ValueError):
        raise CanteenPosError("Pekerja belum dipilih.")
    worker = (
        Worker.query.join(Mandor, Mandor.id == Worker.mandor_id)
        .filter(Worker.id == worker_id, Mandor.branch_id == branch_id)
        .first()
    )
    if not worker:
        raise CanteenPosError("Pekerja tidak ditemukan di cabang ini.")
    return worker


def build_item_rows(cart) -> tuple[list[dict], Decimal]:
    """Keranjang dari browser → baris barang dengan harga master. Barang lain (custom) boleh berharga sendiri."""
    from app.services.canteen_service import get_or_create_custom_item

    if not isinstance(cart, list) or not cart:
        raise CanteenPosError("Keranjang masih kosong.")
    rows: list[dict] = []
    total = Decimal("0.00")
    for line in cart:
        if not isinstance(line, dict):
            raise CanteenPosError("Data keranjang tidak valid.")
        try:
            qty = int(line.get("qty") or 0)
        except (TypeError, ValueError):
            raise CanteenPosError("Jumlah barang harus angka bulat.")
        if qty <= 0 or qty > 999:
            raise CanteenPosError("Jumlah barang harus 1 sampai 999.")
        if line.get("custom"):
            name = str(line.get("name") or "").strip()
            price = money(line.get("price"))
            if not name or price <= 0:
                raise CanteenPosError("Barang lain wajib punya nama dan harga lebih dari 0.")
            # Cari sendiri dulu: jalur "barang sudah ada" di get_or_create_custom_item ikut commit.
            item = Item.query.filter(
                func.upper(Item.category) == "MERCHANDISE",
                func.lower(Item.item_name) == name[:150].lower(),
            ).first() or get_or_create_custom_item(name[:150], price)
            if not item:
                raise CanteenPosError("Barang lain gagal disimpan.")
        else:
            item = Item.query.get(int(line.get("item_id") or 0))
            if not item or not item.is_active or str(item.category or "").upper() != "MERCHANDISE":
                raise CanteenPosError("Ada barang yang sudah tidak dijual. Muat ulang halaman kasir.")
            price = item_price(item)
            if price <= 0:
                raise CanteenPosError(f"Harga {item.item_name} belum diisi di master barang.")
        rows.append({"item_id": item.id, "qty": qty, "price": float(price)})
        total += price * qty
    return rows, total


def checkout(*, branch_id: int, user_id: int, method: str, cart, worker_id=None, buyer_name=None,
             cash_received=None, bank_account_id=None) -> dict:
    """Simpan satu transaksi kasir. Tidak commit (dipanggil di dalam atomic_business_action)."""
    from app.services.canteen_service import create_canteen_sale

    method = str(method or "").upper()
    if method not in CHECKOUT_METHODS:
        raise CanteenPosError("Pilih TUNAI, QRIS, atau HUTANG.")
    item_rows, total = build_item_rows(cart)

    worker = None
    buyer_type = "GENERAL_BUYER"
    buyer_name = str(buyer_name or "").strip() or None
    if worker_id:
        worker = _worker_in_branch(branch_id, worker_id)
        buyer_type = "REGISTERED_WORKER"
        buyer_name = None
    if method == "DEBT" and not worker and not buyer_name:
        raise CanteenPosError("Hutang wajib memilih pekerja (atau isi nama pembeli luar).")

    change = None
    if method == "CASH" and cash_received not in (None, ""):
        received = money(cash_received)
        if received < total:
            raise CanteenPosError("Uang diterima kurang dari total belanja.")
        change = received - total

    if method == "QRIS" and not bank_account_id:
        from app.models.finance import BankAccount

        bank = BankAccount.query.filter_by(branch_id=branch_id, is_active=True).order_by(BankAccount.id.asc()).first()
        if not bank:
            raise CanteenPosError("Belum ada rekening bank aktif untuk QRIS. Minta Owner/Admin menambahkannya.")
        bank_account_id = bank.id

    over_limit = False
    debt_after = None
    if method == "DEBT" and worker:
        before = worker_balances(branch_id, worker.id).get(worker.id, {}).get("warung", Decimal("0.00"))
        debt_after = before + total
        limit = worker_debt_limit(branch_id)
        over_limit = bool(limit > 0 and debt_after > limit)

    ok, message, sale = create_canteen_sale(
        branch_id=branch_id,
        sale_date=today_wib(),
        payment_method=method,
        buyer_type=buyer_type,
        worker_id=worker.id if worker else None,
        buyer_name=buyer_name,
        cash_bank_account_id=bank_account_id,
        item_rows=item_rows,
        notes="Kasir cepat" + (" (lewat batas hutang)" if over_limit else ""),
        created_by=user_id,
    )
    if not ok:
        raise CanteenPosError(message)

    who = worker.full_name if worker else (buyer_name or "Pembeli umum")
    label = {"CASH": "tunai", "QRIS": "QRIS", "DEBT": "hutang"}[method]
    return {
        "sale_id": sale.id,
        "total": int(total),
        "change": int(change) if change is not None else None,
        "who": who,
        "method": method,
        "debt_after": int(debt_after) if debt_after is not None else None,
        "over_limit": over_limit,
        "message": f"Tersimpan: {who}, {label} Rp {int(total):,}".replace(",", "."),
    }


def recent_sales(branch_id: int, limit: int = 8) -> list[dict]:
    sales = (
        CanteenSale.query.filter(CanteenSale.branch_id == branch_id, CanteenSale.sale_date == today_wib())
        .order_by(CanteenSale.id.desc())
        .limit(limit)
        .all()
    )
    rows = []
    for sale in sales:
        who = "Pembeli umum"
        if sale.worker_debt and sale.worker_debt.worker:
            who = sale.worker_debt.worker.full_name
        elif sale.buyer_name:
            who = sale.buyer_name
        rows.append({
            "id": sale.id,
            "who": who,
            "method": sale.payment_method,
            "total": int(money(sale.total_amount)),
            "time": format_wib(sale.created_at, "%H.%M") if getattr(sale, "created_at", None) else "",
        })
    return rows


def pay_worker_debts(*, branch_id: int, user_id: int, worker_id, amount, method: str, bank_account_id=None) -> dict:
    """Cicil/lunasi hutang warung satu pekerja; dialokasikan ke hutang terlama dulu.

    Hutang yang sudah masuk invoice mandor dilewati (ditagih lewat invoice).
    Tidak commit (dipanggil di dalam atomic_business_action).
    """
    from app.services.canteen_service import pay_worker_debt

    worker = _worker_in_branch(branch_id, worker_id)
    method = str(method or "").upper()
    if method not in ("CASH", "QRIS"):
        raise CanteenPosError("Pilih TUNAI atau QRIS.")
    amount = money(amount)
    if amount <= 0:
        raise CanteenPosError("Jumlah bayar harus lebih dari 0.")
    if amount != amount.to_integral_value():
        raise CanteenPosError("Jumlah bayar harus rupiah bulat.")
    if method == "QRIS" and not bank_account_id:
        from app.models.finance import BankAccount

        bank = BankAccount.query.filter_by(branch_id=branch_id, is_active=True).order_by(BankAccount.id.asc()).first()
        if not bank:
            raise CanteenPosError("Belum ada rekening bank aktif untuk QRIS.")
        bank_account_id = bank.id

    debts = _open_debts(branch_id, worker.id)
    ids = [debt.id for debt in debts]
    paid = _paid_by_debt(ids)
    invoiced = _invoiced_debt_ids(ids)
    payable = []
    for debt in debts:
        remaining = money(debt.debt_amount) - paid.get(debt.id, Decimal("0.00"))
        if remaining > 0 and debt.id not in invoiced:
            payable.append((debt, remaining))
    total_payable = sum((remaining for _, remaining in payable), Decimal("0.00"))
    if total_payable <= 0:
        raise CanteenPosError(f"{worker.full_name} tidak punya hutang warung yang bisa dibayar di sini.")
    if amount > total_payable:
        raise CanteenPosError(f"Melebihi sisa hutang warung (Rp {int(total_payable):,}).".replace(",", "."))

    left = amount
    for debt, remaining in payable:
        if left <= 0:
            break
        portion = min(left, remaining)
        ok, message = pay_worker_debt(
            debt,
            today_wib(),
            float(portion),
            "Bayar hutang di kasir warung",
            user_id,
            payment_method=method,
            cash_bank_account_id=bank_account_id,
        )
        if not ok:
            raise CanteenPosError(message)
        left -= portion

    remaining_after = total_payable - amount
    return {
        "worker": worker.full_name,
        "paid": int(amount),
        "remaining": int(remaining_after),
        "message": f"Diterima Rp {int(amount):,} dari {worker.full_name}. Sisa hutang Rp {int(remaining_after):,}".replace(",", "."),
    }
