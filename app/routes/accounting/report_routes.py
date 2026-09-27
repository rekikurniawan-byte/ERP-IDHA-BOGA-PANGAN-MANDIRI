"""Accounting report and COA mapping routes.

Route functions moved out of app.routes.accounting_routes without changing URL rules or endpoint names.
"""
from app.routes.accounting_routes import *  # noqa: F401,F403
from app.utils.terms import T


def _accounting1b_parse_date(value, default_value):
    from datetime import datetime

    if not value:
        return default_value

    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:462")
        return default_value


def _accounting1b_money_value(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:469")
        return 0


def _accounting1b_trial_balance_side(account_type, debit, credit):
    account_type = str(account_type or "").upper()

    debit = _accounting1b_money_value(debit)
    credit = _accounting1b_money_value(credit)

    if account_type in ["ASSET", "EXPENSE", "COGS", "COST", "HPP"]:
        balance = debit - credit
        if balance >= 0:
            return balance, 0
        return 0, abs(balance)

    balance = credit - debit
    if balance >= 0:
        return 0, balance
    return abs(balance), 0


def _build_accounting1b_reports_data(start_date=None, end_date=None):
    from datetime import date
    from app.models.accounting import Account, Journal, JournalDetail

    today = date.today()

    if not start_date:
        start_date = date(today.year, today.month, 1)

    if not end_date:
        end_date = today

    accounts = Account.query.filter_by(is_active=True).order_by(Account.account_code.asc()).all()

    journals = Journal.query.filter(
        Journal.journal_date >= start_date,
        Journal.journal_date <= end_date
    ).order_by(
        Journal.journal_date.asc(),
        Journal.id.asc()
    ).all()

    journal_ids = [journal.id for journal in journals]

    details = []

    if journal_ids:
        details = JournalDetail.query.join(
            Journal, JournalDetail.journal_id == Journal.id
        ).join(
            Account, JournalDetail.account_id == Account.id
        ).filter(
            Journal.id.in_(journal_ids)
        ).order_by(
            Journal.journal_date.asc(),
            Journal.id.asc(),
            JournalDetail.id.asc()
        ).all()

    account_map = {}

    for account in accounts:
        account_map[account.id] = {
            "account": account,
            "details": [],
            "period_debit": 0,
            "period_credit": 0,
            "trial_debit": 0,
            "trial_credit": 0,
        }

    for detail in details:
        if detail.account_id not in account_map:
            continue

        debit = _accounting1b_money_value(detail.debit)
        credit = _accounting1b_money_value(detail.credit)

        account_map[detail.account_id]["details"].append(detail)
        account_map[detail.account_id]["period_debit"] += debit
        account_map[detail.account_id]["period_credit"] += credit

    ledger_rows = []
    trial_rows = []

    total_period_debit = 0
    total_period_credit = 0
    total_trial_debit = 0
    total_trial_credit = 0

    revenue_total = 0
    expense_total = 0

    for account_id, row in account_map.items():
        account = row["account"]
        period_debit = row["period_debit"]
        period_credit = row["period_credit"]

        trial_debit, trial_credit = _accounting1b_trial_balance_side(
            account.account_type,
            period_debit,
            period_credit
        )

        row["trial_debit"] = trial_debit
        row["trial_credit"] = trial_credit

        if period_debit > 0 or period_credit > 0 or row["details"]:
            ledger_rows.append(row)

        if period_debit > 0 or period_credit > 0 or trial_debit > 0 or trial_credit > 0:
            trial_rows.append(row)

        total_period_debit += period_debit
        total_period_credit += period_credit
        total_trial_debit += trial_debit
        total_trial_credit += trial_credit

        account_type = str(account.account_type or "").upper()

        if account_type == "REVENUE":
            revenue_total += max(period_credit - period_debit, 0)

        if account_type in ["EXPENSE", "COGS", "COST", "HPP"]:
            expense_total += max(period_debit - period_credit, 0)

    net_income = revenue_total - expense_total

    return {
        "start_date": start_date,
        "end_date": end_date,
        "journals": journals,
        "ledger_rows": ledger_rows,
        "trial_rows": trial_rows,
        "journal_count": len(journals),
        "detail_count": len(details),
        "total_period_debit": total_period_debit,
        "total_period_credit": total_period_credit,
        "total_trial_debit": total_trial_debit,
        "total_trial_credit": total_trial_credit,
        "is_period_balanced": round(total_period_debit, 2) == round(total_period_credit, 2),
        "is_trial_balanced": round(total_trial_debit, 2) == round(total_trial_credit, 2),
        "revenue_total": revenue_total,
        "expense_total": expense_total,
        "net_income": net_income,
    }


@accounting_bp.route("/reports")
@login_required
@role_required("OWNER", "ACCOUNTING")
def reports():
    from datetime import date
    from flask import request

    today = date.today()
    default_start = date(today.year, today.month, 1)
    date_filter = resolve_date_filter(request.args, default_preset="this_month")
    start_date = date_filter.start_date or default_start
    end_date = date_filter.end_date or today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    filter_bar = build_filter_bar_context(
        state=date_filter,
        action_url=url_for("accounting.reports"),
        reset_url=url_for("accounting.reports"),
        title="Filter Laporan Akuntansi",
        description="Custom tanggal untuk neraca saldo, buku besar, laba rugi, dan detail jurnal.",
    )

    return render_template(
        "accounting/reports.html",
        data=data,
        filter_bar=filter_bar,
    )


@accounting_bp.route("/reports/trial-balance/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_trial_balance_csv():
    from datetime import date
    from app.services.accounting_export_service import build_trial_balance_export_response

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    return build_trial_balance_export_response(data)


@accounting_bp.route("/reports/general-ledger/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_general_ledger_csv():
    from datetime import date
    from app.services.accounting_export_service import build_general_ledger_export_response

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    return build_general_ledger_export_response(data)


@accounting_bp.route("/reports/income-summary/export.csv")
@login_required
@role_required("OWNER", "ACCOUNTING")
def export_income_summary_csv():
    from datetime import date
    from app.services.accounting_export_service import build_income_summary_export_response

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    return build_income_summary_export_response(data)


@accounting_bp.route("/reports/trial-balance/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_trial_balance():
    from datetime import date
    from app.services.accounting_print_service import build_trial_balance_print_context

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    context = build_trial_balance_print_context(current_user.branch_id, data)
    return render_template("accounting/print_trial_balance.html", **context)


@accounting_bp.route("/reports/general-ledger/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_general_ledger():
    from datetime import date
    from app.services.accounting_print_service import build_general_ledger_print_context

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    context = build_general_ledger_print_context(current_user.branch_id, data)
    return render_template("accounting/print_general_ledger.html", **context)


@accounting_bp.route("/reports/income-summary/print")
@login_required
@role_required("OWNER", "ACCOUNTING")
def print_income_summary():
    from datetime import date
    from app.services.accounting_print_service import build_income_summary_print_context

    today = date.today()
    default_start = date(today.year, today.month, 1)
    start_date = _accounting1b_parse_date(request.args.get("start_date"), default_start)
    end_date = _accounting1b_parse_date(request.args.get("end_date"), today)
    if start_date > end_date:
        start_date = default_start
        end_date = today

    data = _build_accounting1b_reports_data(start_date=start_date, end_date=end_date)
    context = build_income_summary_print_context(current_user.branch_id, data)
    return render_template("accounting/print_income_summary.html", **context)


# ACCOUNTING2B_COA_MAPPING_ROUTE
def _accounting2b_money_value(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:769")
        return 0


def _accounting2b_find_source_account_refs():
    import re
    from pathlib import Path
    from collections import defaultdict

    code_refs = defaultdict(list)

    patterns = [
        r'_get_active_account_by_code\(["\'](\d+)["\']\)',
        r'get_active_account_by_code\(["\'](\d+)["\']\)',
        r'account_code\s*=\s*["\'](\d+)["\']',
        r'filter_by\(account_code\s*=\s*["\'](\d+)["\']',
    ]

    for file in Path("app").rglob("*.py"):
        file_name = str(file).lower()

        if "backup" in file_name or "__pycache__" in file_name:
            continue

        text_file = file.read_text(encoding="utf-8", errors="ignore")
        lines = text_file.splitlines()

        for idx, line in enumerate(lines, start=1):
            for pattern in patterns:
                matches = re.findall(pattern, line)

                for code in matches:
                    code_refs[code].append({
                        "file": str(file),
                        "line_number": idx,
                        "line": line.strip(),
                    })

    return dict(code_refs)


def _build_accounting2b_coa_mapping_data():
    from collections import defaultdict
    from sqlalchemy import text
    from app.extensions import db
    from app.models.accounting import Account

    accounts = Account.query.order_by(Account.account_code.asc()).all()

    account_lookup = {
        account.account_code: account
        for account in accounts
    }

    usage_rows = db.session.execute(text("""
        SELECT
            a.id AS account_id,
            a.account_code,
            a.account_name,
            a.account_type,
            a.is_active,
            COUNT(jd.id) AS detail_count,
            SUM(COALESCE(jd.debit, 0)) AS debit_total,
            SUM(COALESCE(jd.credit, 0)) AS credit_total
        FROM accounts a
        LEFT JOIN journal_details jd ON jd.account_id = a.id
        GROUP BY a.id, a.account_code, a.account_name, a.account_type, a.is_active
        ORDER BY a.account_code ASC
    """)).mappings().all()

    usage_by_code = {}

    for row in usage_rows:
        usage_by_code[row["account_code"]] = {
            "detail_count": int(row["detail_count"] or 0),
            "debit_total": _accounting2b_money_value(row["debit_total"]),
            "credit_total": _accounting2b_money_value(row["credit_total"]),
            "is_used": int(row["detail_count"] or 0) > 0,
        }

    mapping_plan = [
        {
            "stage": "SUDAH BERJALAN",
            "module": "Finance",
            "event": "Invoice catering kontrak/harian + warung + ongkir",
            "debit_codes": ["1004"],
            "credit_codes": ["4001", "4002", "4003", "4004", "4005"],
            "note": "PRODUCTION: pelanggan jalur Kontrak masuk 4001, jalur Umum masuk 4002 (invoice tanpa jalur: periode 4001, harian 4002), ongkos kirim masuk 4005. Piutang bertambah, pendapatan diakui.",
            "risk": "LOCKED",
        },
        {
            "stage": "SUDAH BERJALAN",
            "module": "Finance",
            "event": "Pembayaran invoice",
            "debit_codes": ["1001", "1002"],
            "credit_codes": ["1004"],
            "note": "Sudah berjalan. CASH masuk Kas, transfer idealnya masuk Bank 1.",
            "risk": "LOCKED",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Logistik",
            "event": "Pembelian barang tunai",
            "debit_codes": ["1006"],
            "credit_codes": ["1001", "1002"],
            "note": "Persediaan bahan baku bertambah, kas/bank berkurang.",
            "risk": "AMAN JIKA NOMINAL PEMBELIAN VALID",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Logistik",
            "event": "Pembelian barang kredit",
            "debit_codes": ["1006"],
            "credit_codes": ["2002"],
            "note": "Persediaan bertambah, hutang supplier bertambah.",
            "risk": "AMAN JIKA STATUS CREDIT SUDAH JELAS",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Produksi",
            "event": "Pemakaian bahan untuk produksi",
            "debit_codes": ["5001"],
            "credit_codes": ["1006"],
            "note": "Biaya bahan baku bertambah, persediaan bahan baku berkurang.",
            "risk": "BUTUH NILAI HARGA POKOK BARANG",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Logistik",
            "event": "Barang rusak / selisih stok keluar",
            "debit_codes": ["5002"],
            "credit_codes": ["1006"],
            "note": "Biaya operasional dapur bertambah, persediaan berkurang.",
            "risk": "BUTUH NILAI HARGA POKOK BARANG",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Warung",
            "event": f"Hutang {T.worker_lower} warung",
            "debit_codes": ["1005"],
            "credit_codes": ["4003"],
            "note": "Piutang karyawan bertambah, pendapatan warung diakui.",
            "risk": "AMAN JIKA HUTANG PEKERJA DIANGGAP PIUTANG KARYAWAN",
        },
        {
            "stage": "TAHAP BERIKUTNYA",
            "module": "Warung",
            "event": f"Pembayaran hutang {T.worker_lower}",
            "debit_codes": ["1001"],
            "credit_codes": ["1005"],
            "note": "Kas bertambah, piutang karyawan berkurang.",
            "risk": "AMAN JIKA PAYMENT DEBT SUDAH FINAL",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "SDM",
            "event": "Pengakuan gaji karyawan",
            "debit_codes": ["5004"],
            "credit_codes": ["2003"],
            "note": "Gaji karyawan menjadi beban, hutang gaji bertambah.",
            "risk": "BUTUH MODUL GAJI",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "SDM",
            "event": "Pembayaran gaji",
            "debit_codes": ["2003"],
            "credit_codes": ["1001", "1002"],
            "note": "Hutang gaji berkurang, kas/bank berkurang.",
            "risk": "BUTUH MODUL GAJI",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Aset",
            "event": "Pembelian aset tetap",
            "debit_codes": ["1101", "1102", "1103"],
            "credit_codes": ["1001", "1002", "2001"],
            "note": "Aset tetap bertambah, kas/bank/hutang usaha berubah sesuai cara bayar.",
            "risk": "BUTUH MODUL ASET",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Aset",
            "event": "Penyusutan aset tetap",
            "debit_codes": ["5012"],
            "credit_codes": ["2101", "2102", "2103"],
            "note": "Beban penyusutan bertambah, akumulasi penyusutan bertambah.",
            "risk": "BUTUH MODUL ASET DAN UMUR MANFAAT",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Pajak",
            "event": "Pengakuan pajak",
            "debit_codes": ["5009"],
            "credit_codes": ["2004", "2005", "2006"],
            "note": "Beban pajak bertambah, hutang pajak bertambah.",
            "risk": "BUTUH ATURAN PAJAK BISNIS",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Owner",
            "event": "Setoran modal pemilik",
            "debit_codes": ["1001", "1002"],
            "credit_codes": ["3001"],
            "note": "Kas/bank bertambah, modal pemilik bertambah.",
            "risk": "JURNAL MANUAL OWNER",
        },
        {
            "stage": "BELUM AKTIF",
            "module": "Owner",
            "event": "Prive pemilik",
            "debit_codes": ["3003"],
            "credit_codes": ["1001", "1002"],
            "note": "Prive bertambah, kas/bank berkurang.",
            "risk": "JURNAL MANUAL OWNER",
        },
    ]

    def account_info(code):
        account = account_lookup.get(code)

        if not account:
            return {
                "code": code,
                "name": "AKUN BELUM ADA",
                "type": "-",
                "exists": False,
            }

        return {
            "code": account.account_code,
            "name": account.account_name,
            "type": account.account_type,
            "exists": True,
        }

    enriched_mapping = []

    proposed_by_account = defaultdict(list)

    for item in mapping_plan:
        debit_accounts = [account_info(code) for code in item["debit_codes"]]
        credit_accounts = [account_info(code) for code in item["credit_codes"]]

        for code in item["debit_codes"]:
            proposed_by_account[code].append(f"Debit: {item['event']}")

        for code in item["credit_codes"]:
            proposed_by_account[code].append(f"Credit: {item['event']}")

        enriched = dict(item)
        enriched["debit_accounts"] = debit_accounts
        enriched["credit_accounts"] = credit_accounts
        enriched["missing_accounts"] = [
            account for account in debit_accounts + credit_accounts
            if not account["exists"]
        ]

        enriched_mapping.append(enriched)

    accounts_by_type = defaultdict(list)

    for account in accounts:
        usage = usage_by_code.get(account.account_code, {
            "detail_count": 0,
            "debit_total": 0,
            "credit_total": 0,
            "is_used": False,
        })

        accounts_by_type[str(account.account_type or "UNKNOWN").upper()].append({
            "account": account,
            "usage": usage,
            "proposed": proposed_by_account.get(account.account_code, []),
        })

    used_count = sum(
        1 for row in usage_by_code.values()
        if row["is_used"]
    )

    unused_count = len(accounts) - used_count

    source_refs = _accounting2b_find_source_account_refs()

    source_code_accounts = []

    for code, refs in sorted(source_refs.items()):
        source_code_accounts.append({
            "code": code,
            "account": account_info(code),
            "refs": refs,
        })

    missing_accounts = []

    for item in enriched_mapping:
        for account in item["missing_accounts"]:
            missing_accounts.append({
                "event": item["event"],
                "code": account["code"],
            })

    return {
        "accounts": accounts,
        "accounts_by_type": dict(accounts_by_type),
        "usage_by_code": usage_by_code,
        "mapping_plan": enriched_mapping,
        "source_code_accounts": source_code_accounts,
        "missing_accounts": missing_accounts,
        "summary": {
            "total_accounts": len(accounts),
            "used_accounts": used_count,
            "unused_accounts": unused_count,
            "mapping_events": len(enriched_mapping),
            "source_code_account_count": len(source_code_accounts),
            "missing_account_count": len(missing_accounts),
        }
    }


@accounting_bp.route("/coa-mapping")
@login_required
@role_required("OWNER", "ACCOUNTING")
def coa_mapping():
    data = _build_accounting2b_coa_mapping_data()

    return render_template(
        "accounting/coa_mapping.html",
        data=data
    )


# ACCOUNTING2E_PROCUREMENT_JOURNAL_GENERATOR
def _accounting2e_float(value):
    try:
        return float(value or 0)
    except Exception:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1106")
        return 0


def _accounting2e_get_account(account_code):
    from app.models.accounting import Account

    return Account.query.filter_by(
        account_code=account_code,
        is_active=True
    ).first()


def _accounting2e_procurement_amount(procurement):
    amount = _accounting2e_float(getattr(procurement, "total_amount", 0))

    if amount > 0:
        return amount

    total = 0

    for item in getattr(procurement, "items", []) or []:
        total += _accounting2e_float(getattr(item, "subtotal", 0))

    return total


def _accounting2e_purchase_credit_account(procurement):
    purchase_type = str(getattr(procurement, "purchase_type", "") or "").upper()

    if purchase_type == "CASH":
        return _accounting2e_get_account("1001"), "Kas"

    if purchase_type == "CREDIT":
        return _accounting2e_get_account("2002"), "Hutang Supplier"

    if purchase_type in ["TRANSFER", "BANK"]:
        return _accounting2e_get_account("1002"), "Bank 1"

    return None, "UNKNOWN"


def _build_accounting2e_procurement_candidates():
    from app.models.logistics import Procurement
    from app.models.accounting import Journal

    procurements = Procurement.query.order_by(
        Procurement.procurement_date.asc(),
        Procurement.id.asc()
    ).all()

    candidates = []

    for procurement in procurements:
        existing = Journal.query.filter_by(
            reference_type="PROCUREMENT",
            reference_id=procurement.id
        ).first()

        amount = _accounting2e_procurement_amount(procurement)
        credit_account, credit_label = _accounting2e_purchase_credit_account(procurement)

        candidates.append({
            "procurement": procurement,
            "amount": amount,
            "purchase_type": str(procurement.purchase_type or "").upper(),
            "credit_account": credit_account,
            "credit_label": credit_label,
            "existing_journal": existing,
            "can_generate": (
                existing is None
                and amount > 0
                and credit_account is not None
            ),
        })

    return candidates


def _generate_accounting2e_procurement_journals(created_by_id, commit=True):
    from app.services.accounting_service import generate_procurement_journals_batch

    return generate_procurement_journals_batch(created_by_id=created_by_id, commit=commit)


@accounting_bp.route("/journals/generate-procurement", methods=["POST"])
@login_required
@role_required("OWNER", "ACCOUNTING")
def generate_procurement_journals():
    from flask import flash, redirect, url_for
    from flask_login import current_user

    idempotency_record, idempotency_response = _reserve_accounting_idempotency(
        "ACCOUNTING_GENERATE_PROCUREMENT_JOURNALS",
        {"action": "generate_procurement_journals"},
    )
    if idempotency_response:
        return idempotency_response

    try:
        result = _generate_accounting2e_procurement_journals(
            created_by_id=current_user.id,
            commit=True
        )

        if result["errors"]:
            for error in result["errors"]:
                flash(error, "danger")

            return _redirect_after_accounting_post()

        created_count = len(result["created"])
        skipped_count = len(result["skipped"])

        if created_count > 0:
            record_audit_log(
                module="ACCOUNTING",
                event_type="JOURNAL_BATCH_PROCUREMENT_CREATED",
                action="CREATE",
                table_name="journals",
                record_id=None,
                description=f"Batch jurnal pembelian dibuat: {created_count} jurnal, {skipped_count} dilewati.",
                metadata={"created_count": created_count, "skipped_count": skipped_count, "generator": "procurement"},
            )
            flash(f"{created_count} jurnal pembelian berhasil dibuat. {skipped_count} data dilewati.", "success")
        else:
            flash("Tidak ada jurnal pembelian baru yang dibuat. Semua data mungkin sudah dijurnal.", "info")

        mark_idempotency_completed(
            idempotency_record,
            reference_type="JOURNAL_BATCH",
            reference_id=None,
            response_payload={"created_count": created_count, "skipped_count": skipped_count},
            commit=True,
        )

    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/accounting_routes.py:1227")
        flash(f"Gagal generate jurnal pembelian: {error}", "danger")

    return _redirect_after_accounting_post()
