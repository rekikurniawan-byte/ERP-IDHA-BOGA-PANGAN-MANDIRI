"""Setor dan tarik modal pemilik (keputusan owner 2026-09-28, poin 8).

Dulu tidak ada tempatnya, jadi uang pribadi yang masuk ke kas usaha (atau
sebaliknya) dicatat lewat "penyesuaian saldo" tanpa jurnal. Sekarang satu
langkah: buku kas/bank dan jurnalnya tercatat bersamaan.

- Setor modal: kas/bank IN,  Dr 1001/1002 / Cr 3001 Modal Pemilik.
- Tarik modal: kas/bank OUT, Dr 3003 Prive / Cr 1001/1002.

Hanya OWNER. Baris buku kas/bank adalah catatannya sendiri (referensi
OWNER_CAPITAL ke dirinya), jurnal merujuk baris itu.
"""
from app.extensions import db
from app.models.finance import BankAccount, CashBankTransaction
from app.services.cash_bank_service import (
    _money,
    post_cash_bank_journal,
    calculate_account_balance,
    cash_bank_coa_code,
    get_account_label,
    normalize_cash_bank_account,
)
from app.utils.roles import effective_role

OWNER_CAPITAL_REFERENCE = "OWNER_CAPITAL"
CAPITAL_KINDS = {
    "SETOR": {"label": "Setor Modal", "transaction_type": "IN", "equity_code": "3001"},
    "TARIK": {"label": "Tarik Modal (Prive)", "transaction_type": "OUT", "equity_code": "3003"},
}


class OwnerCapitalError(Exception):
    pass


def record_owner_capital(*, branch_id, kind, transaction_date, account_type, bank_account_id, amount, notes, created_by, actor_role):
    """Catat setor/tarik modal: buku kas/bank + jurnal dalam satu transaksi. Commit."""
    if effective_role(actor_role) != "OWNER":
        raise OwnerCapitalError("Setor/tarik modal pemilik hanya bisa dicatat OWNER.")
    rule = CAPITAL_KINDS.get(str(kind or "").strip().upper())
    if rule is None:
        raise OwnerCapitalError("Pilih setor modal atau tarik modal.")
    if transaction_date is None:
        raise OwnerCapitalError("Tanggal wajib diisi.")
    amount = float(amount or 0)
    if amount <= 0:
        raise OwnerCapitalError("Nominal harus lebih dari 0.")
    notes = str(notes or "").strip()
    if not notes:
        raise OwnerCapitalError("Keterangan wajib diisi (mis. tambahan modal untuk beli bahan).")

    try:
        account_type, bank_account_id, _ = normalize_cash_bank_account(account_type, bank_account_id, branch_id=branch_id)
        if rule["transaction_type"] == "OUT":
            balance = calculate_account_balance(branch_id, account_type, bank_account_id)
            if amount > balance:
                raise OwnerCapitalError(f"Saldo tidak cukup. Saldo tersedia {_money(balance)}.")
        bank_account = db.session.get(BankAccount, bank_account_id) if bank_account_id else None
        account_label = get_account_label(account_type, bank_account)

        ledger = CashBankTransaction(
            branch_id=branch_id,
            transaction_date=transaction_date,
            account_type=account_type,
            bank_account_id=bank_account_id,
            transaction_type=rule["transaction_type"],
            amount=amount,
            description=f"{rule['label']} {account_label}: {notes}",
            reference_type=OWNER_CAPITAL_REFERENCE,
            created_by=created_by,
        )
        db.session.add(ledger)
        db.session.flush()
        ledger.reference_id = ledger.id

        cash_code, equity_code = cash_bank_coa_code(account_type), rule["equity_code"]
        post_cash_bank_journal(
            journal_date=transaction_date,
            reference_type=OWNER_CAPITAL_REFERENCE,
            reference_id=ledger.id,
            description=f"{rule['label']} ({account_label}): {notes}",
            debit_code=cash_code if rule["transaction_type"] == "IN" else equity_code,
            credit_code=equity_code if rule["transaction_type"] == "IN" else cash_code,
            amount=amount,
            created_by=created_by,
        )
        from app.services.audit_log_service import record_audit_log

        record_audit_log(
            module="CASH_BANK",
            event_type=f"OWNER_CAPITAL_{str(kind).upper()}",
            action="CREATE",
            table_name="cash_bank_transactions",
            record_id=ledger.id,
            description=f"{rule['label']} {_money(amount)} ke/dari {account_label}.",
            metadata={"amount": amount, "account_type": account_type, "bank_account_id": bank_account_id, "reason": notes},
            user_id=created_by,
            branch_id=branch_id,
            commit=False,
        )
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    return ledger


def list_owner_capital(branch_id):
    return (
        CashBankTransaction.query.filter_by(branch_id=branch_id, reference_type=OWNER_CAPITAL_REFERENCE)
        .order_by(CashBankTransaction.transaction_date.desc(), CashBankTransaction.id.desc())
        .all()
    )
