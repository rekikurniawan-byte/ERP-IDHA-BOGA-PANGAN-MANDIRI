"""Accounting posting generator routes.

Route functions moved out of app.routes.accounting_routes without changing URL rules or endpoint names.
"""
from app.routes.accounting_routes import *  # noqa: F401,F403
from app.routes.accounting_routes import _redirect_after_accounting_post, _reserve_accounting_idempotency
from app.routes.accounting.journal_routes import _generate_journal_number


def _accounting3b_float(value):
    try:
        if value is None:
            return 0

        value = str(value).strip()

        if value == "":
            return 0

        value = value.replace("Rp", "").replace(" ", "")

        if "," in value and "." in value:
            value = value.replace(".", "").replace(",", ".")
        elif "," in value:
            value = value.replace(",", ".")
        else:
            value = value.replace(".", "") if value.count(".") > 1 else value

        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1254")
        return 0


def _accounting3b_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting3b_account_balance(account_code):
    from app.models.accounting import JournalDetail

    account = _accounting3b_get_account(account_code)

    if not account:
        return 0

    details = JournalDetail.query.filter_by(account_id=account.id).all()

    debit = sum(float(detail.debit or 0) for detail in details)
    credit = sum(float(detail.credit or 0) for detail in details)

    account_type = str(account.account_type or "").upper()

    if account_type in ["ASSET", "EXPENSE"]:
        return debit - credit

    return credit - debit


def _accounting3b_existing_opening_journal():
    from app.models.accounting import Journal

    return Journal.query.filter_by(
        reference_type="SALDO_AWAL"
    ).first()


def _build_accounting3b_opening_balance_data():
    pass

    asset_fields = [
        {"name": "cash", "code": "1001", "label": "Kas"},
        {"name": "bank1", "code": "1002", "label": "Bank 1"},
        {"name": "bank2", "code": "1003", "label": "Bank 2"},
        {"name": "receivable", "code": "1004", "label": "Piutang Usaha Awal"},
        {"name": "inventory", "code": "1006", "label": "Persediaan Bahan Baku"},
        {"name": "equipment", "code": "1101", "label": "Peralatan Dapur"},
        {"name": "vehicle", "code": "1102", "label": "Kendaraan Operasional"},
        {"name": "building", "code": "1103", "label": "Bangunan / Dapur"},
    ]

    liability_fields = [
        {"name": "ap_usaha", "code": "2001", "label": "Hutang Usaha Awal"},
        {"name": "ap_supplier", "code": "2002", "label": "Hutang Supplier Awal"},
    ]

    current_balances = []

    for code in ["1001", "1002", "1003", "1004", "1006", "1101", "1102", "1103", "2001", "2002", "3001"]:
        account = _accounting3b_get_account(code)

        if not account:
            continue

        current_balances.append({
            "account": account,
            "balance": _accounting3b_account_balance(code),
        })

    cash_balance = _accounting3b_account_balance("1001")
    suggested_cash = abs(cash_balance) if cash_balance < 0 else 0

    existing = _accounting3b_existing_opening_journal()

    return {
        "asset_fields": asset_fields,
        "liability_fields": liability_fields,
        "current_balances": current_balances,
        "cash_balance": cash_balance,
        "suggested_cash": suggested_cash,
        "existing_opening_journal": existing,
    }


def _generate_accounting3b_opening_balance_journal(form_data, created_by_id, commit=True):
    from datetime import datetime, date
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    existing = _accounting3b_existing_opening_journal()

    if existing:
        return {
            "journal": None,
            "details": [],
            "errors": [f"Jurnal saldo awal sudah ada: {existing.journal_number}"],
        }

    try:
        journal_date = datetime.strptime(form_data.get("journal_date"), "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1359")
        journal_date = date.today()

    asset_fields = [
        ("cash", "1001", "Kas"),
        ("bank1", "1002", "Bank 1"),
        ("bank2", "1003", "Bank 2"),
        ("receivable", "1004", "Piutang Usaha Awal"),
        ("inventory", "1006", "Persediaan Bahan Baku"),
        ("equipment", "1101", "Peralatan Dapur"),
        ("vehicle", "1102", "Kendaraan Operasional"),
        ("building", "1103", "Bangunan / Dapur"),
    ]

    liability_fields = [
        ("ap_usaha", "2001", "Hutang Usaha Awal"),
        ("ap_supplier", "2002", "Hutang Supplier Awal"),
    ]

    entries = []
    errors = []

    total_debit = 0
    total_liability_credit = 0

    for field_name, account_code, label in asset_fields:
        amount = _accounting3b_float(form_data.get(field_name))

        if amount < 0:
            errors.append(f"Nominal {label} tidak boleh minus.")
            continue

        if amount > 0:
            account = _accounting3b_get_account(account_code)

            if not account:
                errors.append(f"Akun {account_code} - {label} tidak ditemukan/aktif.")
                continue

            entries.append({
                "account": account,
                "debit": amount,
                "credit": 0,
                "label": label,
            })

            total_debit += amount

    for field_name, account_code, label in liability_fields:
        amount = _accounting3b_float(form_data.get(field_name))

        if amount < 0:
            errors.append(f"Nominal {label} tidak boleh minus.")
            continue

        if amount > 0:
            account = _accounting3b_get_account(account_code)

            if not account:
                errors.append(f"Akun {account_code} - {label} tidak ditemukan/aktif.")
                continue

            entries.append({
                "account": account,
                "debit": 0,
                "credit": amount,
                "label": label,
            })

            total_liability_credit += amount

    if total_debit <= 0:
        errors.append("Minimal isi salah satu saldo aset awal, misalnya Kas atau Bank.")

    modal_amount = total_debit - total_liability_credit

    if modal_amount < 0:
        errors.append("Total hutang awal lebih besar dari total aset awal. Modal pemilik menjadi minus, tahan dulu.")

    if modal_amount > 0:
        modal_account = _accounting3b_get_account("3001")

        if not modal_account:
            errors.append("Akun 3001 - Modal Pemilik tidak ditemukan/aktif.")
        else:
            entries.append({
                "account": modal_account,
                "debit": 0,
                "credit": modal_amount,
                "label": "Modal Pemilik",
            })

    final_debit = sum(float(entry["debit"] or 0) for entry in entries)
    final_credit = sum(float(entry["credit"] or 0) for entry in entries)

    if round(final_debit, 2) != round(final_credit, 2):
        errors.append(f"Jurnal saldo awal tidak balance. Debit {final_debit}, Credit {final_credit}.")

    if errors:
        return {
            "journal": None,
            "details": entries,
            "errors": errors,
        }

    description = "Jurnal saldo awal / modal pemilik"

    journal = Journal(
        journal_number=_generate_journal_number(journal_date),
        journal_date=journal_date,
        reference_type="SALDO_AWAL",
        reference_id=0,
        description=description,
        created_by=created_by_id
    )

    db.session.add(journal)
    db.session.flush()

    created_details = []

    for entry in entries:
        detail = JournalDetail(
            journal_id=journal.id,
            account_id=entry["account"].id,
            debit=float(entry["debit"] or 0),
            credit=float(entry["credit"] or 0)
        )

        db.session.add(detail)
        created_details.append(detail)

    if commit:
        commit_accounting_transaction()

    return {
        "journal": journal,
        "details": created_details,
        "errors": [],
    }


@accounting_bp.route("/opening-balance", methods=["GET", "POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def opening_balance():
    from flask import request, flash, redirect, url_for
    from flask_login import current_user

    if request.method == "POST":
        try:
            result = _generate_accounting3b_opening_balance_journal(
                form_data=request.form,
                created_by_id=current_user.id,
                commit=True
            )

            if result["errors"]:
                for error in result["errors"]:
                    flash(error, "danger")

                rollback_accounting_transaction()
                return redirect(url_for("accounting.opening_balance"))

            journal = result["journal"]
            record_audit_log(
                module="ACCOUNTING",
                event_type="OPENING_BALANCE_JOURNAL_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=journal.id,
                description=f"Jurnal saldo awal dibuat: {journal.journal_number}.",
                metadata={"journal_number": journal.journal_number, "journal_date": journal.journal_date},
            )
            flash(f"Jurnal saldo awal berhasil dibuat: {journal.journal_number}", "success")
            return redirect(url_for("accounting.journal_detail", journal_id=journal.id))

        except Exception as error:
            logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1536")
            rollback_accounting_transaction()
            flash(f"Gagal membuat jurnal saldo awal: {error}", "danger")
            return redirect(url_for("accounting.opening_balance"))

    data = _build_accounting3b_opening_balance_data()

    return render_template(
        "accounting/opening_balance.html",
        data=data
    )


# ACCOUNTING4B_HPP_PRODUCTION_GENERATOR
def _accounting4b_float(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1553")
        return 0


def _accounting4b_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting4b_get_item_average_cost(item_id):
    from app.extensions import db
    from sqlalchemy import text

    row = db.session.execute(text("""
        SELECT
            SUM(COALESCE(qty, 0)) AS total_qty,
            SUM(COALESCE(subtotal, 0)) AS total_value
        FROM procurement_items
        WHERE item_id = :item_id
    """), {"item_id": item_id}).mappings().first()

    total_qty = _accounting4b_float(row["total_qty"] if row else 0)
    total_value = _accounting4b_float(row["total_value"] if row else 0)

    if total_qty <= 0 or total_value <= 0:
        return {
            "total_qty": total_qty,
            "total_value": total_value,
            "avg_cost": 0,
        }

    return {
        "total_qty": total_qty,
        "total_value": total_value,
        "avg_cost": total_value / total_qty,
    }


def _build_accounting4b_hpp_candidates():
    from app.models.accounting import Journal
    from app.models.master import Item
    from app.models.logistics import StockMovement

    movements = StockMovement.query.filter_by(
        reference_type="PEMAKAIAN_PRODUKSI",
        movement_type="OUT"
    ).order_by(
        StockMovement.movement_date.asc(),
        StockMovement.id.asc()
    ).all()

    candidates = []

    for movement in movements:
        item = Item.query.get(movement.item_id)
        cost_info = _accounting4b_get_item_average_cost(movement.item_id)

        usage_qty = _accounting4b_float(movement.qty)
        avg_cost = _accounting4b_float(cost_info.get("avg_cost"))
        amount = round(usage_qty * avg_cost, 2)

        existing = Journal.query.filter_by(
            reference_type="HPP_PRODUKSI",
            reference_id=movement.id
        ).first()

        candidates.append({
            "movement": movement,
            "item": item,
            "usage_qty": usage_qty,
            "avg_cost": avg_cost,
            "amount": amount,
            "cost_info": cost_info,
            "existing_journal": existing,
            "can_generate": (
                existing is None
                and usage_qty > 0
                and avg_cost > 0
                and amount > 0
            ),
        })

    return candidates


def _generate_accounting4b_hpp_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_hpp = _accounting4b_get_account("5001")
    acc_inventory = _accounting4b_get_account("1006")

    missing_accounts = []

    if not acc_hpp:
        missing_accounts.append("5001 - Biaya Bahan Baku")

    if not acc_inventory:
        missing_accounts.append("1006 - Persediaan Bahan Baku")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting4b_hpp_candidates()

    for candidate in candidates:
        movement = candidate["movement"]
        item = candidate["item"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "movement": movement,
                "reason": "Sudah ada jurnal HPP",
            })
            continue

        if candidate["usage_qty"] <= 0:
            skipped.append({
                "movement": movement,
                "reason": "Qty pemakaian tidak valid",
            })
            continue

        if candidate["avg_cost"] <= 0:
            skipped.append({
                "movement": movement,
                "reason": "Harga rata-rata item belum tersedia",
            })
            continue

        if amount <= 0:
            skipped.append({
                "movement": movement,
                "reason": "Nominal HPP tidak valid",
            })
            continue

        item_name = item.item_name if item else f"Item #{movement.item_id}"

        journal = Journal(
            journal_number=_generate_journal_number(movement.movement_date),
            journal_date=movement.movement_date,
            reference_type="HPP_PRODUKSI",
            reference_id=movement.id,
            description=f"Jurnal HPP pemakaian produksi {item_name} - Stock Movement #{movement.id}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_hpp.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_inventory.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "movement": movement,
            "item": item,
            "amount": amount,
            "avg_cost": candidate["avg_cost"],
            "usage_qty": candidate["usage_qty"],
            "debit_account": acc_hpp,
            "credit_account": acc_inventory,
        })

    if commit:
        commit_accounting_transaction()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


@accounting_bp.route("/journals/generate-hpp-production", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_hpp_production_journals():
    from flask import flash
    from flask_login import current_user

    idempotency_record, idempotency_response = _reserve_accounting_idempotency(
        "ACCOUNTING_GENERATE_HPP_PRODUCTION_JOURNALS",
        {"action": "generate_hpp_production_journals"},
    )
    if idempotency_response:
        return idempotency_response

    try:
        result = _generate_accounting4b_hpp_journals(
            created_by_id=current_user.id,
            commit=True
        )

        if result["errors"]:
            for error in result["errors"]:
                flash(error, "danger")

            rollback_accounting_transaction()
            return _redirect_after_accounting_post()

        created_count = len(result["created"])
        skipped_count = len(result["skipped"])

        if created_count > 0:
            record_audit_log(
                module="ACCOUNTING",
                event_type="JOURNAL_BATCH_HPP_PRODUCTION_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=None,
                description=f"Batch jurnal HPP produksi dibuat: {created_count} jurnal, {skipped_count} dilewati.",
                metadata={"created_count": created_count, "skipped_count": skipped_count, "generator": "hpp_production"},
            )
            flash(f"{created_count} jurnal HPP produksi berhasil dibuat. {skipped_count} data dilewati.", "success")
        else:
            flash("Tidak ada jurnal HPP produksi baru yang dibuat. Semua data mungkin sudah dijurnal atau belum punya harga.", "info")

        mark_idempotency_completed(
            idempotency_record,
            reference_type="JOURNAL_BATCH",
            reference_id=None,
            response_payload={"created_count": created_count, "skipped_count": skipped_count},
            commit=True,
        )

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1789")
        rollback_accounting_transaction()
        flash(f"Gagal generate jurnal HPP produksi: {error}", "danger")

    return _redirect_after_accounting_post()


# ACCOUNTING7C_WARUNG_PAYMENT_CORRECTION_GENERATOR
def _accounting7c_float(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1800")
        return 0


def _accounting7c_to_date(value):
    from datetime import date, datetime

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    if isinstance(value, str):
        value = value.strip()

        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                pass

    raise ValueError(f"Format tanggal payment warung tidak valid: {value}")


def _accounting7c_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _build_accounting7c_warung_payment_correction_candidates():
    from app.extensions import db
    from app.models.accounting import Journal
    from sqlalchemy import text

    payment_rows = db.session.execute(text("""
        SELECT
            dp.id AS debt_payment_id,
            dp.worker_debt_id,
            dp.payment_date,
            dp.amount,
            dp.notes,
            wd.worker_id,
            wd.sale_id,
            wd.debt_amount,
            wd.status AS debt_status
        FROM debt_payments dp
        JOIN worker_debts wd ON wd.id = dp.worker_debt_id
        ORDER BY dp.payment_date ASC, dp.id ASC
    """)).mappings().all()

    existing_reference_types = [
        "WARUNG_PAYMENT_CORRECTION",
        "DEBT_PAYMENT",
        "WORKER_DEBT_PAYMENT",
        "WARUNG_PAYMENT",
    ]

    candidates = []

    for row in payment_rows:
        existing = Journal.query.filter(
            Journal.reference_type.in_(existing_reference_types),
            Journal.reference_id == row["debt_payment_id"]
        ).first()

        amount = _accounting7c_float(row["amount"])

        candidates.append({
            "payment": dict(row),
            "amount": amount,
            "existing_journal": existing,
            "can_generate": (
                existing is None
                and amount > 0
            ),
        })

    return candidates


def _generate_accounting7c_warung_payment_correction_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_cash = _accounting7c_get_account("1001")
    acc_warung_revenue = _accounting7c_get_account("4003")

    missing_accounts = []

    if not acc_cash:
        missing_accounts.append("1001 - Kas")

    if not acc_warung_revenue:
        missing_accounts.append("4003 - Pendapatan Warung")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting7c_warung_payment_correction_candidates()

    for candidate in candidates:
        payment = candidate["payment"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "payment": payment,
                "reason": "Sudah ada jurnal koreksi/payment warung",
            })
            continue

        if amount <= 0:
            skipped.append({
                "payment": payment,
                "reason": "Nominal payment tidak valid",
            })
            continue

        payment_date = _accounting7c_to_date(payment["payment_date"])

        journal = Journal(
            journal_number=_generate_journal_number(payment_date),
            journal_date=payment_date,
            reference_type="WARUNG_PAYMENT_CORRECTION",
            reference_id=payment["debt_payment_id"],
            description=f"Koreksi payment hutang warung pekerja - Debt Payment #{payment['debt_payment_id']}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_cash.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_warung_revenue.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "payment": payment,
            "amount": amount,
            "debit_account": acc_cash,
            "credit_account": acc_warung_revenue,
        })

    if commit:
        commit_accounting_transaction()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


@accounting_bp.route("/journals/generate-warung-payment-correction", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_warung_payment_correction_journals():
    from flask import flash
    from flask_login import current_user

    idempotency_record, idempotency_response = _reserve_accounting_idempotency(
        "ACCOUNTING_GENERATE_WARUNG_PAYMENT_CORRECTION_JOURNALS",
        {"action": "generate_warung_payment_correction_journals"},
    )
    if idempotency_response:
        return idempotency_response

    try:
        result = _generate_accounting7c_warung_payment_correction_journals(
            created_by_id=current_user.id,
            commit=True
        )

        if result["errors"]:
            for error in result["errors"]:
                flash(error, "danger")

            rollback_accounting_transaction()
            return _redirect_after_accounting_post()

        created_count = len(result["created"])
        skipped_count = len(result["skipped"])
        created_total = sum(float(row["amount"] or 0) for row in result["created"])

        if created_count > 0:
            flash(f"{created_count} jurnal koreksi payment warung berhasil dibuat senilai Rp {created_total:,.0f}. {skipped_count} data dilewati.", "success")
        else:
            flash("Tidak ada jurnal koreksi payment warung baru yang dibuat. Semua data mungkin sudah dijurnal.", "info")

        mark_idempotency_completed(
            idempotency_record,
            reference_type="JOURNAL_BATCH",
            reference_id=None,
            response_payload={"created_count": created_count, "skipped_count": skipped_count, "created_total": created_total},
            commit=True,
        )

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:2005")
        rollback_accounting_transaction()
        flash(f"Gagal generate koreksi payment warung: {error}", "danger")

    return _redirect_after_accounting_post()
