"""Kontrol kredit: daftar risiko, setel kredit mandor, deposit, status, hapus buku.

Route di sini tipis: semua aturan ada di credit_account_service, termasuk
pemeriksaan OWNER, supaya tidak ada jalan pintas lewat route lain. Decorator
role_required di sini hanya lapisan pertama.
"""
from datetime import date

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from app.extensions import db
from app.models.credit import PARTY_MANDOR, CreditAccount
from app.models.finance import BankAccount
from app.models.master import Mandor
from app.services.credit_account_service import (
    BILLING_MODE_LABELS,
    BILLING_MODES,
    CreditActionError,
    apply_deposit_to_invoice,
    change_credit_status,
    confirm_write_off,
    credit_account_detail,
    default_settings_for,
    list_credit_overview,
    receive_deposit,
    refund_deposit,
    run_sweep_now,
    save_credit_settings,
)
from app.services.credit_control_service import get_credit_account
from app.utils.decorators import role_required
from app.utils.roles import effective_role
from app.utils.terms import T


credit_bp = Blueprint("credit", __name__, url_prefix="/credit")


def _own_branch_or_404(record):
    if record is None or record.branch_id != current_user.branch_id:
        abort(404)
    return record


def _bank_accounts():
    return BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True).all()


def _is_owner():
    return effective_role(current_user.role) == "OWNER"


@credit_bp.route("/")
@role_required("ADMIN")
def overview():
    rows = list_credit_overview(current_user.branch_id)
    # Unit order langsung ("PT X — Langsung") tidak ditawarkan: itu client
    # sendiri, remnya limit kontrak, bukan kredit mandor.
    unconfigured = (
        Mandor.query.filter(
            Mandor.branch_id == current_user.branch_id,
            Mandor.is_active.is_(True),
            Mandor.is_direct_unit.is_(False),
        )
        .order_by(Mandor.name.asc())
        .all()
    )
    configured_ids = {row["account"].party_id for row in rows if row["account"].party_type == PARTY_MANDOR}
    return render_template(
        "credit/overview.html",
        rows=rows,
        unconfigured=[mandor for mandor in unconfigured if mandor.id not in configured_ids],
        is_owner=_is_owner(),
    )


@credit_bp.route("/sweep", methods=["POST"])
@role_required("ADMIN")
def sweep():
    try:
        result = run_sweep_now(current_user.branch_id, actor_id=current_user.id)
    except CreditActionError as error:
        flash(f"Pemeriksaan kredit gagal: {error}", "danger")
        return redirect(url_for("credit.overview"))
    if result["escalated"]:
        names = ", ".join(f"{row['name']} → {row['to']}" for row in result["escalated"])
        flash(f"{result['checked']} akun diperiksa. Status naik: {names}.", "warning")
    else:
        flash(f"{result['checked']} akun diperiksa. Tidak ada status yang naik.", "success")
    return redirect(url_for("credit.overview"))


@credit_bp.route(f"/{T.sub_client_lower}/<int:mandor_id>/settings", methods=["GET", "POST"])
@role_required("OWNER")
def mandor_settings(mandor_id):
    mandor = _own_branch_or_404(db.session.get(Mandor, mandor_id))
    account = get_credit_account(mandor.branch_id, PARTY_MANDOR, mandor.id)

    if request.method == "POST":
        try:
            account = save_credit_settings(mandor, request.form, current_user)
            flash(f"Syarat kredit {mandor.name} disimpan.", "success")
            return redirect(url_for("credit.account_detail", account_id=account.id))
        except CreditActionError as error:
            flash(str(error), "warning")

    return render_template(
        "credit/settings.html",
        mandor=mandor,
        account=account,
        defaults=default_settings_for(mandor),
        billing_modes=[(mode, BILLING_MODE_LABELS[mode]) for mode in BILLING_MODES],
        form=request.form if request.method == "POST" else None,
    )


@credit_bp.route("/accounts/<int:account_id>")
@role_required("ADMIN")
def account_detail(account_id):
    account = _own_branch_or_404(db.session.get(CreditAccount, account_id))
    return render_template(
        "credit/detail.html",
        detail=credit_account_detail(account),
        bank_accounts=_bank_accounts(),
        is_owner=_is_owner(),
        today=date.today(),
    )


def _account_action(account_id, action, success_message):
    account = _own_branch_or_404(db.session.get(CreditAccount, account_id))
    try:
        result = action(account)
        flash(success_message(result), "success")
    except CreditActionError as error:
        flash(str(error), "warning")
    return redirect(url_for("credit.account_detail", account_id=account.id))


def _mandor_of(account):
    if account.party_type != PARTY_MANDOR:
        raise CreditActionError(f"Deposit hanya untuk akun {T.sub_client_lower}.")
    return db.session.get(Mandor, account.party_id)


@credit_bp.route("/accounts/<int:account_id>/deposit", methods=["POST"])
@role_required("ADMIN")
def deposit_receive(account_id):
    return _account_action(
        account_id,
        lambda account: receive_deposit(_mandor_of(account), request.form, current_user),
        lambda advance: f"Deposit {advance.advance_number} diterima dan dijurnal.",
    )


@credit_bp.route("/accounts/<int:account_id>/deposit/apply", methods=["POST"])
@role_required("OWNER")
def deposit_apply(account_id):
    return _account_action(
        account_id,
        lambda account: apply_deposit_to_invoice(_mandor_of(account), request.form, current_user),
        lambda applied: "Deposit dipotong ke invoice dan dijurnal.",
    )


@credit_bp.route("/accounts/<int:account_id>/deposit/refund", methods=["POST"])
@role_required("OWNER")
def deposit_refund(account_id):
    return _account_action(
        account_id,
        lambda account: refund_deposit(_mandor_of(account), request.form, current_user),
        lambda amount: "Deposit dikembalikan dan dijurnal.",
    )


@credit_bp.route("/accounts/<int:account_id>/status", methods=["POST"])
@role_required("OWNER")
def status_change(account_id):
    return _account_action(
        account_id,
        lambda account: change_credit_status(account, request.form, current_user),
        lambda account: "Status kredit diubah dan dicatat.",
    )


@credit_bp.route("/accounts/<int:account_id>/write-off", methods=["POST"])
@role_required("OWNER")
def write_off(account_id):
    return _account_action(
        account_id,
        lambda account: confirm_write_off(account, request.form, current_user),
        lambda result: f"Hutang dihapus buku dan dijurnal. {T.sub_client} dinonaktifkan.",
    )
