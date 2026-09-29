"""Satu langkah: setiap transaksi dijurnal bersama pencatatannya.

Keputusan owner 2026-09-28 (poin 8-9) yang dikunci di sini:
- pembelian barang dijurnal saat disimpan (kas, bank, atau hutang supplier);
  bayar hutang supplier tidak lagi menunggu "sinkronkan pembelian";
- setiap barang keluar/rusak/selisih opname dijurnal dengan harga rata-rata
  pembelian; barang masuk hanya lewat Pembelian Barang;
- pindah kas <-> bank dan penyesuaian kas/bank dijurnal; penyesuaian wajib
  punya jenis; selisih di atas Rp100.000 hanya OWNER;
- setor/tarik modal pemilik: 3001 / 3003, hanya OWNER;
- aset baru tidak lagi dibuat dari Data Master;
- buku pembantu tetap sama dengan buku besar setelah semua itu.
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

TODAY = date.today()


@pytest.fixture
def ctx(app, monkeypatch):
    """Tanpa commit ke test_db: semua di-flush lalu di-rollback."""
    app.config["WTF_CSRF_ENABLED"] = False
    with app.app_context():
        from app.extensions import db

        monkeypatch.setattr(db.session, "commit", db.session.flush)
        try:
            yield db
        finally:
            db.session.rollback()


def _setup(db):
    from app.models.finance import BankAccount
    from app.models.master import Branch, Item, User
    from app.services.bootstrap_service import ensure_chart_of_accounts

    ensure_chart_of_accounts()
    branch = Branch(code=f"OSJ-{uuid4().hex[:8]}", name="Cabang Uji Jurnal", is_active=True)
    db.session.add(branch)
    db.session.flush()
    users = {
        role: User(branch_id=branch.id, full_name=f"{role} Uji", username=f"osj-{role.lower()}-{uuid4().hex[:8]}",
                   password_hash="x", role=role, is_active=True)
        for role in ("OWNER", "ADMIN")
    }
    item = Item(item_code=f"OSJ-{uuid4().hex[:8]}", item_name="Beras Uji", category="BAHAN", unit="kg",
                is_stock_tracked=True, is_active=True)
    bank = BankAccount(branch_id=branch.id, account_name="PT Uji", bank_name="BCA", account_number=uuid4().hex[:12], is_active=True)
    db.session.add_all([*users.values(), item, bank])
    db.session.flush()
    return SimpleNamespace(branch=branch, item=item, bank=bank, **{role.lower(): user for role, user in users.items()})


def _lines(reference_type, reference_id):
    from app.models.accounting import Account, Journal, JournalDetail

    journal = Journal.query.filter_by(reference_type=reference_type, reference_id=reference_id).one()
    return {
        Account.query.get(row.account_id).account_code: (Decimal(str(row.debit)), Decimal(str(row.credit)))
        for row in JournalDetail.query.filter_by(journal_id=journal.id).all()
    }


def _login(app, user):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_user_id"] = str(user.id)
        session["_fresh"] = True
    return client


def _purchase(app, s, *, purchase_type="CASH", account="CASH", qty=10, price=12000):
    from app.models.logistics import Procurement

    data = {
        "procurement_date": TODAY.isoformat(), "purchase_type": purchase_type, "purchase_place": "Pasar Uji",
        "payment_account_type": account, "item_id[]": [str(s.item.id)], "qty[]": [str(qty)], "unit_price[]": [str(price)],
    }
    if account == "BANK":
        data["bank_account_id"] = str(s.bank.id)
    if purchase_type == "CREDIT":
        data["supplier_bill_due_date"] = TODAY.isoformat()
    _login(app, s.owner).post("/logistics/purchases/create", data=data)
    return Procurement.query.filter_by(branch_id=s.branch.id).order_by(Procurement.id.desc()).first()


def _cash_balance(s, account_type="CASH"):
    from app.services.cash_bank_service import calculate_account_balance

    return Decimal(str(calculate_account_balance(s.branch.id, account_type, s.bank.id if account_type == "BANK" else None)))


def _owner_capital(s, kind, amount, account_type="CASH", role="OWNER"):
    from app.services.owner_capital_service import record_owner_capital

    return record_owner_capital(
        branch_id=s.branch.id, kind=kind, transaction_date=TODAY, account_type=account_type,
        bank_account_id=s.bank.id if account_type == "BANK" else None, amount=amount,
        notes="modal uji", created_by=s.owner.id, actor_role=role,
    )


# --- pembelian ------------------------------------------------------------

def test_pembelian_dijurnal_saat_disimpan_sesuai_cara_bayar(app, ctx):
    s = _setup(ctx)
    _owner_capital(s, "SETOR", 1000000)
    _owner_capital(s, "SETOR", 1000000, account_type="BANK")

    cash = _purchase(app, s, qty=10, price=12000)
    bank = _purchase(app, s, account="BANK", qty=5, price=12000)
    credit = _purchase(app, s, purchase_type="CREDIT", qty=5, price=12000)

    assert _lines("PROCUREMENT", cash.id) == {"1006": (Decimal("120000"), 0), "1001": (0, Decimal("120000"))}
    assert _lines("PROCUREMENT", bank.id) == {"1006": (Decimal("60000"), 0), "1002": (0, Decimal("60000"))}
    assert _lines("PROCUREMENT", credit.id) == {"1006": (Decimal("60000"), 0), "2002": (0, Decimal("60000"))}


def test_bayar_hutang_supplier_tidak_menunggu_sinkron(app, ctx):
    from app.models.finance import SupplierBill, SupplierPayment

    s = _setup(ctx)
    _owner_capital(s, "SETOR", 500000)
    credit = _purchase(app, s, purchase_type="CREDIT", qty=5, price=12000)
    bill = SupplierBill.query.filter_by(procurement_id=credit.id).one()

    _login(app, s.owner).post(f"/finance/supplier-bills/{bill.id}/payments/create", data={
        "idempotency_key": uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": "CASH", "amount": "60000",
    })

    payment = SupplierPayment.query.filter_by(supplier_bill_id=bill.id).one()
    assert Decimal(str(bill.remaining_amount)) == 0
    assert _lines("SUPPLIER_PAYMENT", payment.id) == {"2002": (Decimal("60000"), 0), "1001": (0, Decimal("60000"))}


def test_stok_masuk_manual_dialihkan_ke_pembelian(app, ctx):
    s = _setup(ctx)

    response = _login(app, s.owner).post("/logistics/stock-in", data={"item_id": s.item.id, "qty": 3})

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/logistics/purchases/create")


# --- stok -----------------------------------------------------------------

def test_barang_keluar_rusak_dan_selisih_dijurnal_dengan_harga_rata_rata(app, ctx):
    from app.models.logistics import StockMovement
    from app.services.stock_service import create_stock_movement

    s = _setup(ctx)
    _owner_capital(s, "SETOR", 1000000)
    _purchase(app, s, qty=10, price=12000)
    _purchase(app, s, qty=10, price=14000)  # rata-rata 13.000

    def move(movement_type, reference_type, qty):
        ok, message, movement = create_stock_movement(
            branch_id=s.branch.id, item_id=s.item.id, movement_date=TODAY, movement_type=movement_type,
            reference_type=reference_type, qty=qty, notes="uji", created_by=s.owner.id,
        )
        assert ok, message
        return movement

    production = move("OUT", "PEMAKAIAN_PRODUKSI", 4)
    operational = move("OUT", "PEMAKAIAN_OPERASIONAL", 1)
    damaged = move("DAMAGED", "BARANG_RUSAK", 2)
    surplus = move("ADJUSTMENT_IN", "PENYESUAIAN_STOK", 1)

    assert _lines("STOCK_MOVEMENT", production.id) == {"5001": (Decimal("52000"), 0), "1006": (0, Decimal("52000"))}
    assert _lines("STOCK_MOVEMENT", operational.id) == {"5002": (Decimal("13000"), 0), "1006": (0, Decimal("13000"))}
    assert _lines("STOCK_MOVEMENT", damaged.id) == {"5009": (Decimal("26000"), 0), "1006": (0, Decimal("26000"))}
    assert _lines("STOCK_MOVEMENT", surplus.id) == {"1006": (Decimal("13000"), 0), "4004": (0, Decimal("13000"))}
    assert StockMovement.query.filter_by(branch_id=s.branch.id).count() == 6


def test_barang_tanpa_harga_beli_tidak_dijurnal_dan_ditandai(ctx):
    from app.models.logistics import StockMovement
    from app.services.stock_journal_service import journal_stock_movement
    from app.services.subledger_check_service import unjournaled_stock_movements

    s = _setup(ctx)
    movement = StockMovement(branch_id=s.branch.id, item_id=s.item.id, movement_date=TODAY, movement_type="ADJUSTMENT_IN",
                             reference_type="AUDIT_STOK", qty=5, notes="uji", created_by=s.owner.id)
    ctx.session.add(movement)
    ctx.session.flush()

    assert journal_stock_movement(movement, created_by=s.owner.id) is None
    assert movement in unjournaled_stock_movements()


def test_opname_tersimpan_dan_dijurnal(app, ctx):
    from app.models.logistics import StockMovement

    s = _setup(ctx)
    _owner_capital(s, "SETOR", 500000)
    _purchase(app, s, qty=10, price=12000)

    _login(app, s.owner).post("/logistics/audit/create", data={
        "item_id": s.item.id, "audit_date": TODAY.isoformat(), "physical_stock": "8", "reason": "hitung fisik",
    })

    movement = StockMovement.query.filter_by(branch_id=s.branch.id, reference_type="AUDIT_STOK").one()
    assert movement.movement_type == "ADJUSTMENT_OUT"
    assert _lines("STOCK_MOVEMENT", movement.id) == {"5009": (Decimal("24000"), 0), "1006": (0, Decimal("24000"))}


# --- kas dan bank ---------------------------------------------------------

def test_pindah_kas_ke_bank_dijurnal(ctx):
    from app.services.cash_bank_service import create_cash_bank_transfer_record

    s = _setup(ctx)
    _owner_capital(s, "SETOR", 300000)

    transfer, _, _ = create_cash_bank_transfer_record(
        transfer_date=TODAY, from_account_type="CASH", from_bank_account_id=None, to_account_type="BANK",
        to_bank_account_id=s.bank.id, amount=200000, created_by=s.owner.id, branch_id=s.branch.id,
    )

    assert _lines("CASH_BANK_TRANSFER", transfer.id) == {"1002": (Decimal("200000"), 0), "1001": (0, Decimal("200000"))}
    assert _cash_balance(s, "CASH") == Decimal("100000")


@pytest.mark.parametrize("category, direction, account_type, counter, cash_side", [
    ("SELISIH", "INCREASE", "CASH", "4004", "debit"),
    ("SELISIH", "DECREASE", "CASH", "5009", "credit"),
    ("BIAYA_BANK", "DECREASE", "BANK", "5008", "credit"),
    ("BUNGA_BANK", "INCREASE", "BANK", "4004", "debit"),
])
def test_penyesuaian_kas_bank_dijurnal_menurut_jenisnya(ctx, category, direction, account_type, counter, cash_side):
    from app.services.cash_bank_service import create_cash_bank_adjustment_record

    s = _setup(ctx)
    _owner_capital(s, "SETOR", 100000, account_type=account_type)

    adjustment, _ = create_cash_bank_adjustment_record(
        adjustment_date=TODAY, account_type=account_type, bank_account_id=s.bank.id if account_type == "BANK" else None,
        adjustment_type=direction, amount=5000, reason="uji", created_by=s.admin.id, branch_id=s.branch.id,
        category=category, actor_role="ADMIN",
    )

    cash_code = "1001" if account_type == "CASH" else "1002"
    amount = Decimal("5000")
    expected = (
        {cash_code: (amount, 0), counter: (0, amount)} if cash_side == "debit" else {counter: (amount, 0), cash_code: (0, amount)}
    )
    assert _lines("CASH_BANK_ADJUSTMENT", adjustment.id) == expected
    assert adjustment.adjustment_category == category


def _adjust(s, **kwargs):
    from app.services.cash_bank_service import create_cash_bank_adjustment_record

    base = dict(adjustment_date=TODAY, account_type="CASH", bank_account_id=None, adjustment_type="DECREASE",
                amount=150000, reason="uji", created_by=s.admin.id, branch_id=s.branch.id)
    return create_cash_bank_adjustment_record(**{**base, **kwargs})


@pytest.mark.parametrize("category, role, message", [
    (None, "ADMIN", "jenis penyesuaian"),
    ("SELISIH", "ADMIN", "hanya bisa dicatat OWNER"),
    ("BIAYA_BANK", "OWNER", "hanya untuk rekening bank"),
])
def test_penyesuaian_ditolak(ctx, category, role, message):
    s = _setup(ctx)
    _owner_capital(s, "SETOR", 1000000)

    with pytest.raises(Exception, match=message):
        _adjust(s, category=category, actor_role=role)


def test_selisih_besar_boleh_dicatat_owner(ctx):
    s = _setup(ctx)
    _owner_capital(s, "SETOR", 1000000)

    adjustment, _ = _adjust(s, category="SELISIH", actor_role="OWNER")

    assert adjustment.amount == 150000


def test_modal_pemilik_setor_dan_tarik(ctx):
    from app.services.owner_capital_service import OwnerCapitalError

    s = _setup(ctx)

    deposit = _owner_capital(s, "SETOR", 250000)
    withdrawal = _owner_capital(s, "TARIK", 50000)

    assert _lines("OWNER_CAPITAL", deposit.id) == {"1001": (Decimal("250000"), 0), "3001": (0, Decimal("250000"))}
    assert _lines("OWNER_CAPITAL", withdrawal.id) == {"3003": (Decimal("50000"), 0), "1001": (0, Decimal("50000"))}
    assert _cash_balance(s) == Decimal("200000")
    with pytest.raises(OwnerCapitalError, match="Saldo tidak cukup"):
        _owner_capital(s, "TARIK", 999999)


def test_modal_pemilik_hanya_owner(ctx):
    from app.services.owner_capital_service import OwnerCapitalError

    s = _setup(ctx)

    with pytest.raises(OwnerCapitalError, match="hanya bisa dicatat OWNER"):
        _owner_capital(s, "SETOR", 1000, role="ADMIN")


# --- aset -----------------------------------------------------------------

def test_aset_baru_tidak_dibuat_dari_data_master(app, ctx):
    from app.models.accounting import FixedAsset

    s = _setup(ctx)
    before = FixedAsset.query.filter_by(branch_id=s.branch.id).count()

    response = _login(app, s.owner).post("/master/fixed-assets/create", data={
        "asset_name": "Kompor", "asset_category": "KITCHEN_EQUIPMENT", "purchase_date": TODAY.isoformat(), "purchase_value": "5000000",
    })

    assert response.status_code == 302
    assert "/finance/fixed-asset-purchases/create" in response.headers["Location"]
    assert FixedAsset.query.filter_by(branch_id=s.branch.id).count() == before


# --- buku pembantu --------------------------------------------------------

def test_buku_pembantu_tetap_sama_dengan_buku_besar(app, ctx):
    """Selisih buku besar - buku pembantu tidak berubah oleh transaksi-transaksi di atas."""
    from app.models.finance import SupplierBill
    from app.services.cash_bank_service import create_cash_bank_adjustment_record, create_cash_bank_transfer_record
    from app.services.stock_service import create_stock_movement
    from app.services.subledger_check_service import subledger_lines

    def gaps():
        return {line.label: line.difference for line in subledger_lines()}

    before = gaps()
    s = _setup(ctx)
    _owner_capital(s, "SETOR", 2000000)
    _owner_capital(s, "SETOR", 500000, account_type="BANK")
    _purchase(app, s, qty=10, price=12000)
    _purchase(app, s, account="BANK", qty=10, price=14000)
    credit = _purchase(app, s, purchase_type="CREDIT", qty=4, price=13000)
    bill = SupplierBill.query.filter_by(procurement_id=credit.id).one()
    _login(app, s.owner).post(f"/finance/supplier-bills/{bill.id}/payments/create", data={
        "idempotency_key": uuid4().hex, "payment_date": TODAY.isoformat(), "payment_method": "CASH", "amount": "20000",
    })
    for movement_type, reference_type, qty in (("OUT", "PEMAKAIAN_PRODUKSI", 7), ("DAMAGED", "BARANG_RUSAK", 1), ("ADJUSTMENT_IN", "PENYESUAIAN_STOK", 2)):
        ok, message, _ = create_stock_movement(branch_id=s.branch.id, item_id=s.item.id, movement_date=TODAY, movement_type=movement_type,
                                               reference_type=reference_type, qty=qty, notes="uji", created_by=s.owner.id)
        assert ok, message
    create_cash_bank_transfer_record(transfer_date=TODAY, from_account_type="CASH", from_bank_account_id=None, to_account_type="BANK",
                                     to_bank_account_id=s.bank.id, amount=100000, created_by=s.owner.id, branch_id=s.branch.id)
    create_cash_bank_adjustment_record(adjustment_date=TODAY, account_type="CASH", bank_account_id=None, adjustment_type="DECREASE",
                                       amount=2500, reason="uji", created_by=s.admin.id, branch_id=s.branch.id, category="SELISIH", actor_role="ADMIN")
    _owner_capital(s, "TARIK", 100000)

    assert gaps() == before
