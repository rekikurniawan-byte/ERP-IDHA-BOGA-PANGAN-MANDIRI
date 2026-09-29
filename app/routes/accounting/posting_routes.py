"""Saldo awal satu pintu: satu halaman per cabang (Akuntansi > Saldo Awal).

Isi draf, lihat neraca saldo awalnya, lalu OWNER mengunci dengan password.
Semua aturan ada di app.services.opening_balance_service.
"""
from app.routes.accounting_routes import *  # noqa: F401,F403

OPENING_ROLES = ("OWNER", "ADMIN")


def _opening_context(opening):
    from app.models.finance import BankAccount
    from app.models.master import Client, Item, Mandor, Supplier
    from app.services import opening_balance_service as svc

    payload = svc.load_payload(opening)
    branch_id = current_user.branch_id
    banks = BankAccount.query.filter_by(branch_id=branch_id, is_active=True).order_by(BankAccount.bank_name.asc()).all()
    cashbank = {line["key"]: line for line in payload["cashbank"]}
    corrections = []
    if opening.id:
        from app.models.accounting import OpeningBalanceCorrection

        corrections = (OpeningBalanceCorrection.query.filter_by(opening_balance_id=opening.id)
                       .order_by(OpeningBalanceCorrection.id.desc()).all())
    return {
        "opening": opening,
        "locked": opening.status == svc.STATUS_LOCKED,
        "payload": payload,
        "cash_amount": cashbank.get("CASH", {}).get("amount", "0"),
        "bank_rows": [{"bank": bank, "amount": cashbank.get(f"BANK:{bank.id}", {}).get("amount", "0")} for bank in banks],
        "preview": svc.balance_preview(payload),
        "activity": svc.later_activity(opening) if opening.status == svc.STATUS_LOCKED else [],
        "corrections": corrections,
        "clients": Client.query.filter_by(is_active=True).order_by(Client.name.asc()).all(),
        "mandors": Mandor.query.filter_by(branch_id=branch_id, is_active=True).order_by(Mandor.name.asc()).all(),
        "suppliers": Supplier.query.filter_by(branch_id=branch_id, is_active=True).order_by(Supplier.supplier_name.asc()).all(),
        "stock_items": Item.query.filter_by(is_active=True, is_stock_tracked=True).order_by(Item.item_name.asc()).all(),
        "asset_categories": svc.ASSET_CATEGORY_LABELS,
        "liability_accounts": svc.LIABILITY_ACCOUNTS,
        "section_labels": svc.SECTION_LABELS,
    }


def _run(action, success_message):
    """Jalankan satu perubahan saldo awal dalam satu transaksi, lalu kembali ke halaman."""
    from app.services.opening_balance_service import OpeningBalanceError, run_opening_action

    try:
        message = run_opening_action(current_user.branch_id, current_user.id, action) or success_message
        flash(message, "success")
    except OpeningBalanceError as error:
        flash(str(error), "warning")
    except Exception as error:
        logger.exception("Gagal menyimpan saldo awal")
        flash(f"Gagal menyimpan saldo awal: {error}", "danger")
    return redirect(url_for("accounting.opening_balance"))


@accounting_bp.route("/opening-balance")
@login_required
@role_required(*OPENING_ROLES)
def opening_balance():
    from app.models.accounting import OpeningBalance
    from app.services.opening_balance_service import STATUS_DRAFT, get_opening

    opening = get_opening(current_user.branch_id) or OpeningBalance(branch_id=current_user.branch_id, status=STATUS_DRAFT)
    return render_template("accounting/opening_balance.html", data=_opening_context(opening))


@accounting_bp.route("/opening-balance/start-date", methods=["POST"])
@login_required
@role_required(*OPENING_ROLES)
def opening_balance_start_date():
    from app.services.opening_balance_service import set_start_date

    return _run(lambda opening: set_start_date(opening, request.form.get("start_date")), "Tanggal mulai tersimpan.")


@accounting_bp.route("/opening-balance/cash-bank", methods=["POST"])
@login_required
@role_required(*OPENING_ROLES)
def opening_balance_cash_bank():
    from app.models.finance import BankAccount
    from app.services.opening_balance_service import change_line

    def action(opening):
        reason = request.form.get("reason")
        change_line(opening, "cashbank", None, {"account_type": "CASH", "amount": request.form.get("cash")}, user=current_user, reason=reason)
        for bank in BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).all():
            change_line(opening, "cashbank", None, {"account_type": "BANK", "bank_account_id": bank.id,
                                                    "amount": request.form.get(f"bank_{bank.id}")}, user=current_user, reason=reason)

    return _run(action, "Saldo kas dan bank tersimpan.")


@accounting_bp.route("/opening-balance/<section>/add", methods=["POST"])
@login_required
@role_required(*OPENING_ROLES)
def opening_balance_add_line(section):
    from app.services.opening_balance_service import SECTION_LABELS, change_line

    return _run(lambda opening: change_line(opening, section, None, request.form, user=current_user, reason=request.form.get("reason")),
                f"{SECTION_LABELS.get(section, 'Baris')}: baris ditambahkan.")


@accounting_bp.route("/opening-balance/<section>/<key>/update", methods=["POST"])
@login_required
@role_required(*OPENING_ROLES)
def opening_balance_update_line(section, key):
    from app.services.opening_balance_service import SECTION_LABELS, OpeningBalanceError, change_line, load_payload

    def action(opening):
        current = next((line for line in load_payload(opening).get(section, []) if line["key"] == key), None)
        if current is None:
            raise OpeningBalanceError("Baris tidak ditemukan. Muat ulang halaman.")
        change_line(opening, section, key, {**current, **request.form.to_dict()}, user=current_user, reason=request.form.get("reason"))

    return _run(action, f"{SECTION_LABELS.get(section, 'Baris')}: baris diperbarui.")


@accounting_bp.route("/opening-balance/<section>/<key>/remove", methods=["POST"])
@login_required
@role_required(*OPENING_ROLES)
def opening_balance_remove_line(section, key):
    from app.services.opening_balance_service import SECTION_LABELS, change_line

    return _run(lambda opening: change_line(opening, section, key, None, user=current_user, reason=request.form.get("reason")),
                f"{SECTION_LABELS.get(section, 'Baris')}: baris dihapus.")


@accounting_bp.route("/opening-balance/lock", methods=["POST"])
@login_required
@role_required("OWNER")
def opening_balance_lock():
    from app.services.opening_balance_service import lock_opening
    from app.services.sensitive_action_guard_service import validate_sensitive_action_guard

    allowed, message, _ = validate_sensitive_action_guard("OPENING_BALANCE_LOCK", form=request.form)
    if not allowed:
        flash(message, "danger")
        return redirect(url_for("accounting.opening_balance"))

    def action(opening):
        journal = lock_opening(opening, user=current_user)
        return f"Saldo awal dikunci. Jurnal {journal.journal_number} dan semua buku pembantunya sudah dibuat."

    return _run(action, "Saldo awal dikunci.")


@accounting_bp.route("/opening-balance/reopen", methods=["POST"])
@login_required
@role_required("OWNER")
def opening_balance_reopen():
    from app.services.opening_balance_service import reopen_opening
    from app.services.sensitive_action_guard_service import validate_sensitive_action_guard

    allowed, message, metadata = validate_sensitive_action_guard("OPENING_BALANCE_REOPEN", form=request.form)
    if not allowed:
        flash(message, "danger")
        return redirect(url_for("accounting.opening_balance"))
    return _run(lambda opening: reopen_opening(opening, user=current_user, reason=metadata.get("reason")),
                "Saldo awal dibuka kembali. Semua catatan dan jurnalnya dihapus; draf tetap ada untuk diperbaiki.")
