"""Accounting period closing routes.

Route functions moved out of app.routes.accounting_routes without changing URL rules or endpoint names.
"""
from app.routes.accounting_routes import *  # noqa: F401,F403
from app.routes.accounting_routes import _reserve_accounting_idempotency
from app.routes.accounting.journal_routes import _generate_journal_number
from app.routes.accounting_routes import _journal_total_credit, _journal_total_debit


def _accounting9b_float(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:2021")
        return 0


def _accounting9b_to_date(value):
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

    raise ValueError(f"Format tanggal warung future tidak valid: {value}")


def _accounting9b_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting9b_existing_journal(reference_types, reference_id):
    from app.models.accounting import Journal

    return Journal.query.filter(
        Journal.reference_type.in_(reference_types),
        Journal.reference_id == reference_id
    ).first()


def _build_accounting9b_warung_debt_accrual_candidates(include_protected_existing=False):
    from app.extensions import db
    from sqlalchemy import text

    where_clause = ""

    if not include_protected_existing:
        where_clause = "WHERE wd.id > :cutover_worker_debt_id"

    sql = f"""
        SELECT
            wd.id AS worker_debt_id,
            wd.branch_id,
            wd.worker_id,
            wd.sale_id,
            wd.debt_amount,
            wd.status AS debt_status,
            wd.created_at AS worker_debt_created_at,
            cs.sale_date,
            cs.sale_type,
            cs.total_amount AS sale_total_amount
        FROM worker_debts wd
        JOIN canteen_sales cs ON cs.id = wd.sale_id
        {where_clause}
        ORDER BY wd.id ASC
    """

    rows = db.session.execute(text(sql), {
        "cutover_worker_debt_id": legacy_cutover_id("worker_debt")
    }).mappings().all()

    candidates = []

    for row in rows:
        row_dict = dict(row)
        worker_debt_id = row_dict["worker_debt_id"]
        amount = _accounting9b_float(row_dict["debt_amount"])
        protected_existing = worker_debt_id <= legacy_cutover_id("worker_debt")

        existing = _accounting9b_existing_journal(
            ["WARUNG_DEBT_ACCRUAL"],
            worker_debt_id
        )

        candidates.append({
            "worker_debt": row_dict,
            "amount": amount,
            "journal_date": _accounting9b_to_date(row_dict["sale_date"]),
            "existing_journal": existing,
            "protected_existing": protected_existing,
            "can_generate": (
                existing is None
                and amount > 0
                and not protected_existing
            ),
        })

    return candidates


def _generate_accounting9b_warung_debt_accrual_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_piutang_karyawan = _accounting9b_get_account("1005")
    acc_pendapatan_warung = _accounting9b_get_account("4003")

    missing_accounts = []

    if not acc_piutang_karyawan:
        missing_accounts.append("1005 - Piutang Karyawan")

    if not acc_pendapatan_warung:
        missing_accounts.append("4003 - Pendapatan Warung")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting9b_warung_debt_accrual_candidates()

    for candidate in candidates:
        worker_debt = candidate["worker_debt"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "worker_debt": worker_debt,
                "reason": "Sudah ada jurnal WARUNG_DEBT_ACCRUAL",
            })
            continue

        if candidate["protected_existing"]:
            skipped.append({
                "worker_debt": worker_debt,
                "reason": "Data lama dilindungi cutover",
            })
            continue

        if amount <= 0:
            skipped.append({
                "worker_debt": worker_debt,
                "reason": "Nominal hutang warung tidak valid",
            })
            continue

        journal = Journal(
            journal_number=_generate_journal_number(candidate["journal_date"]),
            journal_date=candidate["journal_date"],
            reference_type="WARUNG_DEBT_ACCRUAL",
            reference_id=worker_debt["worker_debt_id"],
            description=f"Accrual hutang warung pekerja - Worker Debt #{worker_debt['worker_debt_id']}",
            created_by=created_by_id
        )

        db.session.add(journal)
        db.session.flush()

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_piutang_karyawan.id,
            debit=amount,
            credit=0
        ))

        db.session.add(JournalDetail(
            journal_id=journal.id,
            account_id=acc_pendapatan_warung.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "worker_debt": worker_debt,
            "amount": amount,
            "debit_account": acc_piutang_karyawan,
            "credit_account": acc_pendapatan_warung,
        })

    if commit:
        commit_accounting_transaction()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


def _build_accounting9b_warung_debt_payment_candidates(include_protected_existing=False):
    from app.extensions import db
    from sqlalchemy import text

    where_clause = ""

    if not include_protected_existing:
        where_clause = "WHERE dp.id > :cutover_debt_payment_id"

    sql = f"""
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
        {where_clause}
        ORDER BY dp.id ASC
    """

    rows = db.session.execute(text(sql), {
        "cutover_debt_payment_id": legacy_cutover_id("debt_payment")
    }).mappings().all()

    candidates = []

    for row in rows:
        row_dict = dict(row)
        debt_payment_id = row_dict["debt_payment_id"]
        amount = _accounting9b_float(row_dict["amount"])
        protected_existing = debt_payment_id <= legacy_cutover_id("debt_payment")

        existing = _accounting9b_existing_journal(
            [
                "WARUNG_DEBT_PAYMENT",
                "WARUNG_PAYMENT_CORRECTION",
                "DEBT_PAYMENT",
                "WORKER_DEBT_PAYMENT",
                "WARUNG_PAYMENT",
            ],
            debt_payment_id
        )

        candidates.append({
            "payment": row_dict,
            "amount": amount,
            "journal_date": _accounting9b_to_date(row_dict["payment_date"]),
            "existing_journal": existing,
            "protected_existing": protected_existing,
            "can_generate": (
                existing is None
                and amount > 0
                and not protected_existing
            ),
        })

    return candidates


def _generate_accounting9b_warung_debt_payment_journals(created_by_id, commit=True):
    from app.extensions import db
    from app.models.accounting import Journal, JournalDetail

    acc_cash = _accounting9b_get_account("1001")
    acc_piutang_karyawan = _accounting9b_get_account("1005")

    missing_accounts = []

    if not acc_cash:
        missing_accounts.append("1001 - Kas")

    if not acc_piutang_karyawan:
        missing_accounts.append("1005 - Piutang Karyawan")

    created = []
    skipped = []

    if missing_accounts:
        return {
            "created": created,
            "skipped": skipped,
            "errors": [f"Akun wajib belum ada: {', '.join(missing_accounts)}"],
        }

    candidates = _build_accounting9b_warung_debt_payment_candidates()

    for candidate in candidates:
        payment = candidate["payment"]
        amount = candidate["amount"]

        if candidate["existing_journal"]:
            skipped.append({
                "payment": payment,
                "reason": "Sudah ada jurnal payment warung",
            })
            continue

        if candidate["protected_existing"]:
            skipped.append({
                "payment": payment,
                "reason": "Data lama dilindungi cutover",
            })
            continue

        if amount <= 0:
            skipped.append({
                "payment": payment,
                "reason": "Nominal payment warung tidak valid",
            })
            continue

        journal = Journal(
            journal_number=_generate_journal_number(candidate["journal_date"]),
            journal_date=candidate["journal_date"],
            reference_type="WARUNG_DEBT_PAYMENT",
            reference_id=payment["debt_payment_id"],
            description=f"Pembayaran hutang warung pekerja - Debt Payment #{payment['debt_payment_id']}",
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
            account_id=acc_piutang_karyawan.id,
            debit=0,
            credit=amount
        ))

        created.append({
            "journal": journal,
            "payment": payment,
            "amount": amount,
            "debit_account": acc_cash,
            "credit_account": acc_piutang_karyawan,
        })

    if commit:
        commit_accounting_transaction()

    return {
        "created": created,
        "skipped": skipped,
        "errors": [],
    }


def _build_accounting9b_future_invoice_journal_amounts(invoice, include_protected_existing=False):
    protected_existing = invoice.id <= legacy_cutover_id("invoice")

    if protected_existing and not include_protected_existing:
        return {
            "protected_existing": True,
            "total_debit": _accounting9b_float(invoice.total_amount),
            "credits": {},
            "total_credit": 0,
            "catering_total": 0,
            "warung_transfer_total": 0,
            "other_total": 0,
        }

    catering_total = 0
    warung_transfer_total = 0
    other_total = 0

    for item in invoice.items:
        item_type = str(item.item_type or "").upper()
        subtotal = _accounting9b_float(item.subtotal)

        if item_type in ["CATERING", "REVISION_INCREASE"]:
            catering_total += subtotal
        elif item_type in ["WARUNG_DEBT", "WARUNG"]:
            warung_transfer_total += subtotal
        else:
            other_total += subtotal

    credits = {}

    if catering_total > 0:
        credits["4001"] = catering_total

    if warung_transfer_total > 0:
        credits["1005"] = warung_transfer_total

    if other_total > 0:
        credits["4004"] = other_total

    return {
        "protected_existing": protected_existing,
        "total_debit": _accounting9b_float(invoice.total_amount),
        "credits": credits,
        "total_credit": sum(credits.values()),
        "catering_total": catering_total,
        "warung_transfer_total": warung_transfer_total,
        "other_total": other_total,
    }



# === PRODUCTION_PERIOD_CLOSING_RETAINED_EARNINGS_ROUTES ===
@accounting_bp.route("/period-closing")
@login_required
@role_required("OWNER", "ACCOUNTING")
def period_closing():
    from datetime import date
    from app.services.period_closing_service import get_period_closing_preview

    today = date.today()
    selected_year = request.args.get("year", today.year)
    selected_month = request.args.get("month", today.month)
    preview = get_period_closing_preview(current_user.branch_id, selected_year, selected_month)
    year_options = list(range(today.year - 3, today.year + 2))
    month_options = [
        (1, "Januari"), (2, "Februari"), (3, "Maret"), (4, "April"),
        (5, "Mei"), (6, "Juni"), (7, "Juli"), (8, "Agustus"),
        (9, "September"), (10, "Oktober"), (11, "November"), (12, "Desember"),
    ]
    return render_template(
        "accounting/period_closing.html",
        preview=preview,
        year_options=year_options,
        month_options=month_options,
        post_idempotency_key=uuid4().hex,
    )


@accounting_bp.route("/period-closing/post", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def post_period_closing_route():
    from datetime import datetime
    from app.services.period_closing_service import post_period_closing

    selected_year = request.form.get("year")
    selected_month = request.form.get("month")
    closing_date_raw = (request.form.get("closing_date") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    idempotency_record, idempotency_response = _reserve_accounting_idempotency(
        "ACCOUNTING_PERIOD_CLOSING_POST",
        {
            "year": selected_year,
            "month": selected_month,
            "closing_date": closing_date_raw,
            "notes": notes,
        },
        default_endpoint="accounting.period_closing",
    )
    if idempotency_response:
        return idempotency_response

    try:
        closing_date = datetime.strptime(closing_date_raw, "%Y-%m-%d").date() if closing_date_raw else None
        closing = post_period_closing(
            branch_id=current_user.branch_id,
            year=selected_year,
            month=selected_month,
            closing_date=closing_date,
            notes=notes,
            created_by=current_user.id,
            commit=True,
        )
        mark_idempotency_completed(
            idempotency_record,
            reference_type="PERIOD_CLOSING",
            reference_id=closing.id,
            response_payload={"closing_id": closing.id, "closing_number": closing.closing_number},
            commit=True,
        )
        flash(f"Closing periode {closing.closing_number} berhasil diposting ke 3002 Laba Ditahan.", "success")
        return redirect(url_for("accounting.period_closing_detail", closing_id=closing.id))
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:2484")
        flash(str(exc), "danger")
        return redirect(url_for("accounting.period_closing", year=selected_year, month=selected_month))


@accounting_bp.route("/period-closing/<int:closing_id>")
@login_required
@role_required("OWNER", "ACCOUNTING")
def period_closing_detail(closing_id):
    from app.models.accounting import PeriodClosing

    closing = PeriodClosing.query.get_or_404(closing_id)
    if closing.branch_id != current_user.branch_id:
        return redirect(url_for("accounting.period_closing"))
    journal = closing.journal
    total_debit = _journal_total_debit(journal) if journal else 0
    total_credit = _journal_total_credit(journal) if journal else 0
    return render_template(
        "accounting/period_closing_detail.html",
        closing=closing,
        journal=journal,
        total_debit=total_debit,
        total_credit=total_credit,
        is_balanced=round(total_debit, 2) == round(total_credit, 2),
    )
