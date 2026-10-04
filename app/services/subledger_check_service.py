"""Buku pembantu vs buku besar (keputusan owner 2026-09-28, poin 8).

Setiap transaksi sekarang dijurnal bersama pencatatannya, jadi setiap buku
pembantu harus sama dengan saldo akunnya di buku besar. Kalau tidak sama,
ada transaksi yang lolos tanpa jurnal, jurnal manual yang menyentuh akun
kontrol, atau data lama sebelum jurnal otomatis.

Dipakai Cek Kesehatan Data (tampilan) dan ops-check (FAIL). Hanya membaca.
Jurnal tidak punya cabang, jadi perbandingannya untuk semua cabang sekaligus.
"""
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func

from app.extensions import db
from app.models.accounting import Account, Journal, JournalDetail

TOLERANCE = Decimal("1")  # pembulatan sen per pergerakan stok
CANCELLED = ("CANCELLED", "CANCELED", "VOID")
ASSET_CODES = ("1101", "1102", "1103")
ACCUMULATED_DEPRECIATION_CODES = ("2101", "2102", "2103")


@dataclass
class SubledgerLine:
    label: str
    accounts: str
    ledger: Decimal
    subledger: Decimal
    source: str

    @property
    def difference(self):
        return self.ledger - self.subledger

    @property
    def ok(self):
        return abs(self.difference) <= TOLERANCE


def _dec(value):
    return Decimal(str(value or 0))


def gl_balance(codes, *, credit_normal=False):
    """Saldo akun (debit - kredit; kebalikannya untuk akun bersaldo kredit)."""
    debit, credit = (
        db.session.query(func.coalesce(func.sum(JournalDetail.debit), 0), func.coalesce(func.sum(JournalDetail.credit), 0))
        .join(Account, Account.id == JournalDetail.account_id)
        .filter(Account.account_code.in_(list(codes)))
        .one()
    )
    balance = _dec(debit) - _dec(credit)
    return -balance if credit_normal else balance


def _cash_bank(account_type):
    from app.models.finance import CashBankTransaction

    total_in, total_out = (
        db.session.query(
            func.coalesce(func.sum(CashBankTransaction.amount).filter(CashBankTransaction.transaction_type == "IN"), 0),
            func.coalesce(func.sum(CashBankTransaction.amount).filter(CashBankTransaction.transaction_type == "OUT"), 0),
        )
        .filter(CashBankTransaction.account_type == account_type)
        .one()
    )
    return _dec(total_in) - _dec(total_out)


def _open_remaining(model):
    total = db.session.query(func.coalesce(func.sum(model.remaining_amount), 0)).filter(
        ~func.upper(model.status).in_(CANCELLED)
    ).scalar()
    return _dec(total)


def _receivables():
    """Semua yang dijurnal ke 1004: invoice, piutang warung pembeli eksternal,
    dan piutang manual dari transaksi lapangan."""
    from app.models.canteen import CanteenExternalReceivable
    from app.models.field_transaction import ManualReceivable
    from app.models.finance import Invoice

    return _open_remaining(Invoice) + _open_remaining(CanteenExternalReceivable) + _open_remaining(ManualReceivable)


def _supplier_payables():
    """Semua yang dijurnal ke 2002: tagihan supplier dan hutang manual vendor nonformal."""
    from app.models.field_transaction import ManualPayable
    from app.models.finance import SupplierBill

    return _open_remaining(SupplierBill) + _open_remaining(ManualPayable)


def _inventory():
    """Nilai persediaan dari sumbernya: stok awal (qty x harga) + pembelian - barang keluar
    yang dijurnal + selisih lebih. Nilai barang keluar = qty x harga rata-rata saat
    dicatat, dan hanya ada di jurnalnya, jadi bagian itu dibaca dari jurnal pergerakan stok."""
    from app.models.logistics import Procurement, StockOpeningBalance
    from app.services.stock_journal_service import LEGACY_HPP_REFERENCE, STOCK_JOURNAL_REFERENCE

    opening = _dec(db.session.query(func.coalesce(func.sum(StockOpeningBalance.qty * StockOpeningBalance.unit_cost), 0)).scalar())
    purchases = _dec(db.session.query(func.coalesce(func.sum(Procurement.total_amount), 0)).scalar())
    movement_net = gl_balance_for_references(("1006",), (STOCK_JOURNAL_REFERENCE, LEGACY_HPP_REFERENCE))
    return (opening + purchases + movement_net).quantize(Decimal("0.01"))


def gl_balance_for_references(codes, reference_types):
    debit, credit = (
        db.session.query(func.coalesce(func.sum(JournalDetail.debit), 0), func.coalesce(func.sum(JournalDetail.credit), 0))
        .join(Account, Account.id == JournalDetail.account_id)
        .join(Journal, Journal.id == JournalDetail.journal_id)
        .filter(Account.account_code.in_(list(codes)), Journal.reference_type.in_(list(reference_types)))
        .one()
    )
    return _dec(debit) - _dec(credit)


def _fixed_assets(field):
    from app.models.accounting import FixedAsset

    column = getattr(FixedAsset, field)
    return _dec(db.session.query(func.coalesce(func.sum(column), 0)).scalar())


def subledger_lines():
    return [
        SubledgerLine("Kas", "1001", gl_balance(("1001",)), _cash_bank("CASH"), "Buku Kas/Bank (Kas)"),
        SubledgerLine("Bank", "1002, 1003", gl_balance(("1002", "1003")), _cash_bank("BANK"), "Buku Kas/Bank (Bank)"),
        SubledgerLine("Piutang Usaha", "1004", gl_balance(("1004",)), _receivables(), "Sisa invoice + piutang warung eksternal + piutang manual"),
        SubledgerLine("Hutang Supplier", "2002", gl_balance(("2002",), credit_normal=True), _supplier_payables(), "Sisa tagihan supplier + hutang manual vendor"),
        SubledgerLine("Persediaan", "1006", gl_balance(("1006",)), _inventory(), "Saldo awal + pembelian - barang keluar"),
        SubledgerLine("Aset Tetap", ", ".join(ASSET_CODES), gl_balance(ASSET_CODES), _fixed_assets("purchase_value"), "Register aset (nilai beli)"),
        SubledgerLine(
            "Akumulasi Penyusutan", ", ".join(ACCUMULATED_DEPRECIATION_CODES),
            gl_balance(ACCUMULATED_DEPRECIATION_CODES, credit_normal=True), _fixed_assets("accumulated_depreciation"),
            "Register aset (akumulasi penyusutan)",
        ),
    ]


def unjournaled_stock_movements():
    """Pergerakan stok yang seharusnya dijurnal tapi belum punya jurnal."""
    from app.models.logistics import StockMovement
    from app.services.stock_journal_service import stock_journal_rule, stock_movement_journal

    return [
        movement for movement in StockMovement.query.order_by(StockMovement.id.asc()).all()
        if stock_journal_rule(movement) is not None and stock_movement_journal(movement) is None
    ]
