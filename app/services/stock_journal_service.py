"""Jurnal otomatis untuk setiap pergerakan stok (keputusan owner 2026-09-28, poin 8).

Dulu hanya pemakaian produksi yang dijurnal, itu pun lewat tombol
"Sinkronkan HPP Produksi". Barang rusak, selisih opname, pemakaian
operasional, dan pemenuhan permintaan dapur mengurangi stok tanpa mengurangi
Persediaan (1006) di buku besar, jadi keduanya tidak pernah bisa cocok.

Sekarang setiap pergerakan dijurnal dalam transaksi yang sama dengan
pergerakannya. Nilainya qty x harga rata-rata pembelian barang itu -- aturan
yang sama dengan tombol lama. Pembelian barang tidak dijurnal di sini; jurnal
pembeliannya sudah dibuat bersama pembeliannya (create_procurement_journal).

Tidak commit; pemanggil yang commit.
"""
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.accounting import Journal, JournalDetail

STOCK_JOURNAL_REFERENCE = "STOCK_MOVEMENT"
# Tombol lama menjurnal pemakaian produksi dengan referensi ini. Dicek juga,
# supaya pergerakan lama yang sudah dijurnal tidak dijurnal dua kali.
LEGACY_HPP_REFERENCE = "HPP_PRODUKSI"

INVENTORY_CODE = "1006"
LOSS_CODE = "5009"  # rusak, terbuang, selisih kurang saat opname
GAIN_CODE = "4004"  # selisih lebih saat opname

# Barang keluar karena dipakai: akun beban menurut tujuannya.
USAGE_ACCOUNTS = {
    "PEMAKAIAN_PRODUKSI": "5001",
    "PERMINTAAN_BARANG_DAPUR": "5001",
    "HPP_SNAPSHOT_CONSUMPTION": "5001",
    "PEMAKAIAN_OPERASIONAL": "5002",
    "PEMAKAIAN_LAINNYA": "5009",
}
# Jurnalnya dibuat di tempat lain.
JOURNALED_ELSEWHERE = {"PEMBELIAN_BARANG"}

_CENT = Decimal("0.01")


def stock_journal_rule(movement):
    """(akun debit, akun kredit, keterangan) untuk pergerakan ini, atau None kalau tidak dijurnal di sini."""
    movement_type = str(movement.movement_type or "").upper()
    reference_type = str(movement.reference_type or "").upper()
    if reference_type in JOURNALED_ELSEWHERE or movement_type == "AUDIT_OK":
        return None
    if movement_type == "OUT":
        return USAGE_ACCOUNTS.get(reference_type, LOSS_CODE), INVENTORY_CODE, "Pemakaian barang"
    if movement_type in ("DAMAGED", "WASTE"):
        return LOSS_CODE, INVENTORY_CODE, "Barang rusak/terbuang"
    if movement_type == "ADJUSTMENT_OUT":
        return LOSS_CODE, INVENTORY_CODE, "Selisih kurang stok"
    if movement_type == "ADJUSTMENT_IN":
        return INVENTORY_CODE, GAIN_CODE, "Selisih lebih stok"
    # IN selain pembelian (stok masuk tanpa uang keluar) tidak punya lawan yang
    # jelas; jalurnya sudah ditutup, dan Cek Kesehatan Data menandainya.
    return None


def item_average_cost(item_id):
    """Harga rata-rata: (nilai stok awal + nilai pembelian) / (qty stok awal + qty pembelian)."""
    from app.models.logistics import ProcurementItem, StockOpeningBalance

    bought_qty, bought_value = db.session.query(
        func.sum(ProcurementItem.qty), func.sum(ProcurementItem.subtotal)
    ).filter(ProcurementItem.item_id == item_id).one()
    opening_qty, opening_value = db.session.query(
        func.sum(StockOpeningBalance.qty), func.sum(StockOpeningBalance.qty * StockOpeningBalance.unit_cost)
    ).filter(StockOpeningBalance.item_id == item_id, StockOpeningBalance.unit_cost > 0).one()
    total_qty = Decimal(str(bought_qty or 0)) + Decimal(str(opening_qty or 0))
    total_value = Decimal(str(bought_value or 0)) + Decimal(str(opening_value or 0))
    if total_qty <= 0 or total_value <= 0:
        return Decimal("0")
    return total_value / total_qty


def stock_movement_journal(movement):
    return Journal.query.filter(
        Journal.reference_type.in_((STOCK_JOURNAL_REFERENCE, LEGACY_HPP_REFERENCE)),
        Journal.reference_id == movement.id,
    ).first()


def journal_stock_movement(movement, *, created_by):
    """Buat jurnal pergerakan stok ini. Kembalikan jurnalnya, atau None kalau
    pergerakan ini tidak dijurnal di sini atau barangnya belum punya harga
    pembelian (Cek Kesehatan Data menandai yang terakhir)."""
    from app.services.accounting_service import generate_journal_number, get_active_account_by_code

    rule = stock_journal_rule(movement)
    if rule is None:
        return None
    if movement.id is None:
        db.session.flush()
    existing = stock_movement_journal(movement)
    if existing:
        return existing

    amount = (Decimal(str(movement.qty or 0)) * item_average_cost(movement.item_id)).quantize(_CENT, ROUND_HALF_UP)
    if amount <= 0:
        return None

    debit_code, credit_code, label = rule
    debit_account = get_active_account_by_code(debit_code)
    credit_account = get_active_account_by_code(credit_code)
    missing = [code for code, account in ((debit_code, debit_account), (credit_code, credit_account)) if account is None]
    if missing:
        raise ValueError(f"Akun {', '.join(missing)} belum ada atau tidak aktif di COA.")

    item_name = getattr(getattr(movement, "item", None), "item_name", None) or f"Item #{movement.item_id}"
    journal = Journal(
        journal_number=generate_journal_number(movement.movement_date),
        journal_date=movement.movement_date,
        reference_type=STOCK_JOURNAL_REFERENCE,
        reference_id=movement.id,
        description=f"{label}: {item_name} {Decimal(str(movement.qty)):g} ({movement.reference_type}) - Stok #{movement.id}",
        created_by=created_by,
    )
    db.session.add(journal)
    db.session.flush()
    db.session.add(JournalDetail(journal_id=journal.id, account_id=debit_account.id, debit=amount, credit=0))
    db.session.add(JournalDetail(journal_id=journal.id, account_id=credit_account.id, debit=0, credit=amount))
    db.session.flush()
    return journal
