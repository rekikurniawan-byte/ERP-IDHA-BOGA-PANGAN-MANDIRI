"""Cash and bank routes.

Route functions moved out of app.routes.finance_routes without changing URL rules or endpoint names.
"""
from app.routes.finance_routes import *  # noqa: F401,F403
from app.routes.finance.payment_routes import _parse_payment_amount


@finance_bp.route("/cash-bank-ledger")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def cash_bank_ledger():
    from datetime import datetime
    from app.models.finance import (
        CashBankAdjustment,
        CashBankOpeningBalance,
        CashBankTransaction,
        CashBankTransfer,
        Payment,
        SupplierPayment,
        BankAccount,
        TransportVehicleExpense,
    )
    from app.models.logistics import Procurement
    from app.models.accounting import FixedAssetPurchase

    selected_transaction_type = (request.args.get("transaction_type") or "ALL").strip().upper()
    selected_account_type = (request.args.get("account_type") or "ALL").strip().upper()
    selected_reference_type = (request.args.get("reference_type") or "ALL").strip().upper()
    selected_bank_account_id = (request.args.get("bank_account_id") or "ALL").strip()
    selected_reconciliation_status = (request.args.get("reconciliation_status") or "ALL").strip().upper()
    start_date_raw = (request.args.get("start_date") or "").strip()
    end_date_raw = (request.args.get("end_date") or "").strip()

    allowed_transaction_types = ["ALL", "IN", "OUT"]
    allowed_account_types = ["ALL", "CASH", "BANK"]
    allowed_reference_types = [
        "ALL",
        "PAYMENT",
        "PROCUREMENT",
        "SUPPLIER_PAYMENT",
        "OPENING_BALANCE",
        "CASH_BANK_TRANSFER",
        "CASH_BANK_ADJUSTMENT",
        "OWNER_CAPITAL",
        "FIXED_ASSET_PURCHASE",
        "TRANSPORT_VEHICLE_EXPENSE",
        "OPERATIONAL_EXPENSE",
    ]
    allowed_reconciliation_statuses = ["ALL", "RECONCILED", "UNRECONCILED"]

    if selected_transaction_type not in allowed_transaction_types:
        selected_transaction_type = "ALL"

    if selected_account_type not in allowed_account_types:
        selected_account_type = "ALL"

    if selected_reference_type not in allowed_reference_types:
        selected_reference_type = "ALL"

    if selected_reconciliation_status not in allowed_reconciliation_statuses:
        selected_reconciliation_status = "ALL"

    start_date = None
    end_date = None

    if start_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, "%Y-%m-%d").date()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3961")
            flash("Filter tanggal awal ledger kas/bank tidak valid.", "warning")
            start_date_raw = ""

    if end_date_raw:
        try:
            end_date = datetime.strptime(end_date_raw, "%Y-%m-%d").date()
        except Exception:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:3968")
            flash("Filter tanggal akhir ledger kas/bank tidak valid.", "warning")
            end_date_raw = ""

    query = CashBankTransaction.query.filter(
        CashBankTransaction.branch_id == current_user.branch_id
    )

    if selected_transaction_type != "ALL":
        query = query.filter(CashBankTransaction.transaction_type == selected_transaction_type)

    if selected_account_type != "ALL":
        query = query.filter(CashBankTransaction.account_type == selected_account_type)

    if selected_reference_type != "ALL":
        query = query.filter(CashBankTransaction.reference_type == selected_reference_type)

    if selected_reconciliation_status == "RECONCILED":
        query = query.filter(CashBankTransaction.is_reconciled.is_(True))
    elif selected_reconciliation_status == "UNRECONCILED":
        query = query.filter(CashBankTransaction.is_reconciled.is_(False))

    if selected_bank_account_id != "ALL":
        try:
            selected_bank_account_int = int(selected_bank_account_id)
            query = query.filter(CashBankTransaction.bank_account_id == selected_bank_account_int)
        except (TypeError, ValueError):
            flash("Filter rekening bank ledger kas/bank tidak valid.", "warning")
            selected_bank_account_id = "ALL"

    if start_date:
        query = query.filter(CashBankTransaction.transaction_date >= start_date)

    if end_date:
        query = query.filter(CashBankTransaction.transaction_date <= end_date)

    transactions_all_for_summary = query.order_by(
        CashBankTransaction.transaction_date.desc(),
        CashBankTransaction.id.desc()
    ).all()

    transactions = transactions_all_for_summary[:300]
    is_limited = len(transactions_all_for_summary) > len(transactions)

    summary = {
        "count": len(transactions_all_for_summary),
        "total_in": 0,
        "total_out": 0,
        "net": 0,
        "cash_in": 0,
        "cash_out": 0,
        "cash_net": 0,
        "bank_in": 0,
        "bank_out": 0,
        "bank_net": 0,
        "reconciled_count": 0,
        "unreconciled_count": 0,
    }

    bank_summary = {}

    for transaction in transactions_all_for_summary:
        amount = float(transaction.amount or 0)
        transaction_type = str(transaction.transaction_type or "").upper()
        account_type = str(transaction.account_type or "").upper()

        if transaction.is_reconciled:
            summary["reconciled_count"] += 1
        else:
            summary["unreconciled_count"] += 1

        if transaction_type == "IN":
            summary["total_in"] += amount
            if account_type == "CASH":
                summary["cash_in"] += amount
            elif account_type == "BANK":
                summary["bank_in"] += amount
        elif transaction_type == "OUT":
            summary["total_out"] += amount
            if account_type == "CASH":
                summary["cash_out"] += amount
            elif account_type == "BANK":
                summary["bank_out"] += amount

        if account_type == "BANK" and transaction.bank_account_id:
            bank_key = transaction.bank_account_id
            if bank_key not in bank_summary:
                bank_summary[bank_key] = {
                    "bank_account": transaction.bank_account,
                    "total_in": 0,
                    "total_out": 0,
                    "net": 0,
                    "count": 0,
                    "reconciled_count": 0,
                    "unreconciled_count": 0,
                }

            bank_summary[bank_key]["count"] += 1
            if transaction.is_reconciled:
                bank_summary[bank_key]["reconciled_count"] += 1
            else:
                bank_summary[bank_key]["unreconciled_count"] += 1

            if transaction_type == "IN":
                bank_summary[bank_key]["total_in"] += amount
            elif transaction_type == "OUT":
                bank_summary[bank_key]["total_out"] += amount

    summary["net"] = summary["total_in"] - summary["total_out"]
    summary["cash_net"] = summary["cash_in"] - summary["cash_out"]
    summary["bank_net"] = summary["bank_in"] - summary["bank_out"]

    for row in bank_summary.values():
        row["net"] = row["total_in"] - row["total_out"]

    reference_ids = {
        "PAYMENT": [],
        "PROCUREMENT": [],
        "SUPPLIER_PAYMENT": [],
        "OPENING_BALANCE": [],
        "CASH_BANK_TRANSFER": [],
        "CASH_BANK_ADJUSTMENT": [],
        "FIXED_ASSET_PURCHASE": [],
        "TRANSPORT_VEHICLE_EXPENSE": [],
        "OPERATIONAL_EXPENSE": [],
    }

    for transaction in transactions:
        reference_type = str(transaction.reference_type or "").upper()
        if reference_type in reference_ids and transaction.reference_id:
            reference_ids[reference_type].append(transaction.reference_id)

    payment_map = {}
    procurement_map = {}
    supplier_payment_map = {}
    opening_map = {}
    transfer_map = {}
    adjustment_map = {}
    fixed_asset_purchase_map = {}
    transport_expense_map = {}
    operational_expense_map = {}

    if reference_ids["PAYMENT"]:
        payments = Payment.query.filter(
            Payment.branch_id == current_user.branch_id,
            Payment.id.in_(reference_ids["PAYMENT"])
        ).all()
        payment_map = {payment.id: payment for payment in payments}

    if reference_ids["PROCUREMENT"]:
        procurements = Procurement.query.filter(
            Procurement.branch_id == current_user.branch_id,
            Procurement.id.in_(reference_ids["PROCUREMENT"])
        ).all()
        procurement_map = {procurement.id: procurement for procurement in procurements}

    if reference_ids["SUPPLIER_PAYMENT"]:
        supplier_payments = SupplierPayment.query.filter(
            SupplierPayment.branch_id == current_user.branch_id,
            SupplierPayment.id.in_(reference_ids["SUPPLIER_PAYMENT"])
        ).all()
        supplier_payment_map = {payment.id: payment for payment in supplier_payments}

    if reference_ids["OPENING_BALANCE"]:
        openings = CashBankOpeningBalance.query.filter(
            CashBankOpeningBalance.branch_id == current_user.branch_id,
            CashBankOpeningBalance.id.in_(reference_ids["OPENING_BALANCE"])
        ).all()
        opening_map = {opening.id: opening for opening in openings}

    if reference_ids["CASH_BANK_TRANSFER"]:
        transfers = CashBankTransfer.query.filter(
            CashBankTransfer.branch_id == current_user.branch_id,
            CashBankTransfer.id.in_(reference_ids["CASH_BANK_TRANSFER"])
        ).all()
        transfer_map = {transfer.id: transfer for transfer in transfers}

    if reference_ids["CASH_BANK_ADJUSTMENT"]:
        adjustments = CashBankAdjustment.query.filter(
            CashBankAdjustment.branch_id == current_user.branch_id,
            CashBankAdjustment.id.in_(reference_ids["CASH_BANK_ADJUSTMENT"])
        ).all()
        adjustment_map = {adjustment.id: adjustment for adjustment in adjustments}

    if reference_ids["FIXED_ASSET_PURCHASE"]:
        fixed_asset_purchases = FixedAssetPurchase.query.filter(
            FixedAssetPurchase.branch_id == current_user.branch_id,
            FixedAssetPurchase.id.in_(reference_ids["FIXED_ASSET_PURCHASE"])
        ).all()
        fixed_asset_purchase_map = {purchase.id: purchase for purchase in fixed_asset_purchases}

    if reference_ids["TRANSPORT_VEHICLE_EXPENSE"]:
        transport_expenses = TransportVehicleExpense.query.filter(
            TransportVehicleExpense.branch_id == current_user.branch_id,
            TransportVehicleExpense.id.in_(reference_ids["TRANSPORT_VEHICLE_EXPENSE"])
        ).all()
        transport_expense_map = {expense.id: expense for expense in transport_expenses}

    if reference_ids["OPERATIONAL_EXPENSE"]:
        from app.models.finance import OperationalExpense
        operational_expenses = OperationalExpense.query.filter(
            OperationalExpense.branch_id == current_user.branch_id,
            OperationalExpense.id.in_(reference_ids["OPERATIONAL_EXPENSE"])
        ).all()
        operational_expense_map = {expense.id: expense for expense in operational_expenses}

    rows = []

    for transaction in transactions:
        reference_type = str(transaction.reference_type or "").upper()
        source_label = reference_type or "-"
        source_detail = "-"
        source_url = None

        if reference_type == "PAYMENT":
            payment = payment_map.get(transaction.reference_id)
            if payment:
                source_label = payment.payment_number
                if payment.invoice:
                    source_detail = f"Invoice {payment.invoice.invoice_number}"
                    source_url = url_for("finance.invoice_detail", invoice_id=payment.invoice_id)
                else:
                    source_detail = f"Payment ID {payment.id}"

        elif reference_type == "PROCUREMENT":
            procurement = procurement_map.get(transaction.reference_id)
            if procurement:
                source_label = procurement.procurement_number
                source_detail = procurement.purchase_place or procurement.supplier_name or "Pembelian barang"
                source_url = url_for("logistics.purchase_detail", procurement_id=procurement.id)

        elif reference_type == "SUPPLIER_PAYMENT":
            supplier_payment = supplier_payment_map.get(transaction.reference_id)
            if supplier_payment:
                source_label = supplier_payment.payment_number
                if supplier_payment.supplier_bill:
                    source_detail = f"Hutang {supplier_payment.supplier_bill.bill_number} - {supplier_payment.supplier_bill.supplier_name}"
                    source_url = url_for("finance.supplier_bill_detail", bill_id=supplier_payment.supplier_bill.id)
                else:
                    source_detail = f"Supplier Payment ID {supplier_payment.id}"

        elif reference_type == "OPENING_BALANCE":
            opening = opening_map.get(transaction.reference_id)
            source_label = "Saldo Awal"
            if opening:
                source_detail = opening.notes or "Saldo awal kas/bank"
                source_url = url_for("accounting.opening_balance")

        elif reference_type == "CASH_BANK_TRANSFER":
            transfer = transfer_map.get(transaction.reference_id)
            if transfer:
                source_label = transfer.transfer_number
                source_detail = transfer.notes or "Transfer antar kas/bank"
                source_url = url_for("finance.cash_bank_transfers")

        elif reference_type == "CASH_BANK_ADJUSTMENT":
            adjustment = adjustment_map.get(transaction.reference_id)
            if adjustment:
                source_label = adjustment.adjustment_number
                source_detail = adjustment.reason or "Penyesuaian saldo"
                source_url = url_for("finance.cash_bank_adjustments")

        elif reference_type == "FIXED_ASSET_PURCHASE":
            purchase = fixed_asset_purchase_map.get(transaction.reference_id)
            if purchase:
                source_label = purchase.purchase_number
                asset_name = purchase.fixed_asset.asset_name if purchase.fixed_asset else "Aset tetap"
                source_detail = f"Pembelian aset tetap - {asset_name}"
                source_url = url_for("finance.fixed_asset_purchase_detail", purchase_id=purchase.id)

        elif reference_type == "TRANSPORT_VEHICLE_EXPENSE":
            expense = transport_expense_map.get(transaction.reference_id)
            if expense:
                source_label = expense.expense_number
                source_detail = f"Transport/BBM COA {expense.account_code}"
                source_url = url_for("finance.transport_expense_detail", expense_id=expense.id)

        elif reference_type == "OPERATIONAL_EXPENSE":
            expense = operational_expense_map.get(transaction.reference_id)
            if expense:
                source_label = expense.expense_number
                source_detail = f"Biaya operasional COA {expense.account_code}"
                source_url = url_for("finance.operational_expense_detail", expense_id=expense.id)

        rows.append({
            "transaction": transaction,
            "source_label": source_label,
            "source_detail": source_detail,
            "source_url": source_url,
        })

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(
        BankAccount.bank_name.asc(),
        BankAccount.account_name.asc(),
    ).all()

    transaction_type_options = [
        {"value": "ALL", "label": "Semua"},
        {"value": "IN", "label": "Uang Masuk"},
        {"value": "OUT", "label": "Uang Keluar"},
    ]
    account_type_options = [
        {"value": "ALL", "label": "Semua"},
        {"value": "CASH", "label": "Kas"},
        {"value": "BANK", "label": "Bank"},
    ]
    reference_type_options = [
        {"value": "ALL", "label": "Semua Sumber"},
        {"value": "OPENING_BALANCE", "label": "Saldo Awal"},
        {"value": "PAYMENT", "label": "Pembayaran Customer"},
        {"value": "PROCUREMENT", "label": "Pembelian Tunai"},
        {"value": "SUPPLIER_PAYMENT", "label": "Pembayaran Supplier"},
        {"value": "CASH_BANK_TRANSFER", "label": "Transfer Kas/Bank"},
        {"value": "CASH_BANK_ADJUSTMENT", "label": "Penyesuaian Saldo"},
        {"value": "OWNER_CAPITAL", "label": "Modal Pemilik"},
        {"value": "FIXED_ASSET_PURCHASE", "label": "Pembelian Aset Tetap"},
        {"value": "TRANSPORT_VEHICLE_EXPENSE", "label": "Transport & BBM"},
        {"value": "OPERATIONAL_EXPENSE", "label": "Biaya Operasional Catering"},
    ]
    reconciliation_status_options = [
        {"value": "ALL", "label": "Semua"},
        {"value": "RECONCILED", "label": "Sudah Rekonsiliasi"},
        {"value": "UNRECONCILED", "label": "Belum Rekonsiliasi"},
    ]

    return render_template(
        "finance/cash_bank_ledger.html",
        rows=rows,
        summary=summary,
        bank_summary=sorted(bank_summary.values(), key=lambda row: (row["bank_account"].bank_name if row["bank_account"] else "", row["bank_account"].account_name if row["bank_account"] else "")),
        active_bank_accounts=active_bank_accounts,
        selected_transaction_type=selected_transaction_type,
        selected_account_type=selected_account_type,
        selected_reference_type=selected_reference_type,
        selected_bank_account_id=selected_bank_account_id,
        selected_reconciliation_status=selected_reconciliation_status,
        start_date=start_date_raw,
        end_date=end_date_raw,
        export_cash_bank_ledger_url=url_for("finance.export_cash_bank_ledger_csv", **request.args.to_dict(flat=True)),
        transaction_type_options=transaction_type_options,
        account_type_options=account_type_options,
        reference_type_options=reference_type_options,
        reconciliation_status_options=reconciliation_status_options,
        is_limited=is_limited,
    )


@finance_bp.route("/cash-bank-ledger/<int:transaction_id>")
@role_required("OWNER", "ADMIN", "FINANCE", "ACCOUNTING")
def cash_bank_transaction_detail(transaction_id):
    from app.models.finance import CashBankTransaction
    from app.services.field_transaction_service import find_field_transaction_linked_source

    transaction = CashBankTransaction.query.get_or_404(transaction_id)
    if transaction.branch_id != current_user.branch_id:
        abort(404)

    field_transaction_link = find_field_transaction_linked_source(
        "CASH_BANK_TRANSACTION",
        transaction.id,
        branch_id=current_user.branch_id,
    )

    return render_template(
        "finance/cash_bank_transaction_detail.html",
        transaction=transaction,
        field_transaction_link=field_transaction_link,
    )


@finance_bp.route("/cash-bank-opening-balances", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def cash_bank_opening_balances():
    """Saldo awal sekarang satu pintu di Akuntansi > Saldo Awal (keputusan owner
    2026-09-28): kas, bank, stok, piutang, hutang, dan aset diisi di satu halaman
    dan dikunci bersama jurnalnya."""
    flash("Saldo awal sekarang diisi di satu tempat: Akuntansi > Saldo Awal.", "info")
    return redirect(url_for("accounting.opening_balance"))


@finance_bp.route("/cash-bank-transfers", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def cash_bank_transfers():
    from datetime import datetime
    from app.models.finance import BankAccount, CashBankTransfer
    from app.services.cash_bank_service import create_cash_bank_transfer_record

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    if request.method == "POST":
        transfer_date_raw = (request.form.get("transfer_date") or "").strip()
        from_account_type = (request.form.get("from_account_type") or "").strip().upper()
        from_bank_account_id = (request.form.get("from_bank_account_id") or "").strip() or None
        to_account_type = (request.form.get("to_account_type") or "").strip().upper()
        to_bank_account_id = (request.form.get("to_bank_account_id") or "").strip() or None
        amount_raw = (request.form.get("amount") or "").strip()
        reference_number = (request.form.get("reference_number") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            transfer_date = datetime.strptime(transfer_date_raw, "%Y-%m-%d").date()
            amount = _parse_payment_amount(amount_raw)
            transfer, out_transaction, in_transaction = create_cash_bank_transfer_record(
                transfer_date=transfer_date,
                from_account_type=from_account_type,
                from_bank_account_id=from_bank_account_id,
                to_account_type=to_account_type,
                to_bank_account_id=to_bank_account_id,
                amount=amount,
                created_by=current_user.id,
                branch_id=current_user.branch_id,
                reference_number=reference_number,
                notes=notes,
            )
            record_audit_log(
                module="CASH_BANK",
                event_type="CASH_BANK_TRANSFER_CREATED",
                action="CREATE",
                table_name="cash_bank_transfers",
                record_id=transfer.id,
                description=f"Transfer kas/bank dibuat: {transfer.transfer_number}.",
                metadata={"amount": amount, "out_transaction_id": out_transaction.id, "in_transaction_id": in_transaction.id},
            )
            flash("Transfer antar kas/bank berhasil disimpan dan ledger IN/OUT dibuat.", "success")
            return redirect(url_for("finance.cash_bank_transfers"))
        except Exception as error:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4444")
            flash(f"Gagal menyimpan transfer kas/bank: {error}", "danger")

    transfers = CashBankTransfer.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(CashBankTransfer.transfer_date.desc(), CashBankTransfer.id.desc()).all()

    return render_template(
        "finance/cash_bank_transfers.html",
        transfers=transfers,
        active_bank_accounts=active_bank_accounts,
    )


@finance_bp.route("/cash-bank-adjustments", methods=["GET", "POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def cash_bank_adjustments():
    from datetime import datetime
    from app.models.finance import BankAccount, CashBankAdjustment
    from app.services.cash_bank_service import create_cash_bank_adjustment_record

    active_bank_accounts = BankAccount.query.filter_by(
        branch_id=current_user.branch_id,
        is_active=True,
    ).order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all()

    if request.method == "POST":
        adjustment_date_raw = (request.form.get("adjustment_date") or "").strip()
        account_type = (request.form.get("account_type") or "").strip().upper()
        bank_account_id = (request.form.get("bank_account_id") or "").strip() or None
        adjustment_type = (request.form.get("adjustment_type") or "").strip().upper()
        category = (request.form.get("adjustment_category") or "").strip().upper()
        amount_raw = (request.form.get("amount") or "").strip()
        reason = (request.form.get("reason") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        try:
            adjustment_date = datetime.strptime(adjustment_date_raw, "%Y-%m-%d").date()
            amount = _parse_payment_amount(amount_raw)
            adjustment, ledger_transaction = create_cash_bank_adjustment_record(
                adjustment_date=adjustment_date,
                account_type=account_type,
                bank_account_id=bank_account_id,
                adjustment_type=adjustment_type,
                amount=amount,
                reason=reason,
                created_by=current_user.id,
                branch_id=current_user.branch_id,
                notes=notes,
                category=category,
                actor_role=current_user.role,
            )
            record_audit_log(
                module="CASH_BANK",
                event_type="CASH_BANK_ADJUSTMENT_CREATED",
                action="CREATE",
                table_name="cash_bank_adjustments",
                record_id=adjustment.id,
                description=f"Penyesuaian saldo dibuat: {adjustment.adjustment_number}.",
                metadata={"amount": amount, "adjustment_type": adjustment_type, "category": category,
                          "reason": reason, "ledger_transaction_id": ledger_transaction.id},
            )
            flash("Penyesuaian saldo tersimpan di buku kas/bank dan sudah dijurnal.", "success")
            return redirect(url_for("finance.cash_bank_adjustments"))
        except Exception as error:
            logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4504")
            flash(f"Gagal menyimpan penyesuaian saldo: {error}", "danger")

    adjustments = CashBankAdjustment.query.filter_by(
        branch_id=current_user.branch_id,
    ).order_by(CashBankAdjustment.adjustment_date.desc(), CashBankAdjustment.id.desc()).all()

    from app.services.cash_bank_service import ADJUSTMENT_CATEGORIES, SELISIH_OWNER_LIMIT

    return render_template(
        "finance/cash_bank_adjustments.html",
        adjustments=adjustments,
        active_bank_accounts=active_bank_accounts,
        adjustment_categories=ADJUSTMENT_CATEGORIES,
        selisih_owner_limit=SELISIH_OWNER_LIMIT,
    )


@finance_bp.route("/owner-capital", methods=["GET", "POST"])
@role_required("OWNER")
def owner_capital():
    """Setor / tarik modal pemilik: buku kas/bank dan jurnalnya sekali jalan."""
    from datetime import datetime
    from app.models.finance import BankAccount
    from app.services.owner_capital_service import CAPITAL_KINDS, OwnerCapitalError, list_owner_capital, record_owner_capital

    if request.method == "POST":
        try:
            transaction_date = datetime.strptime((request.form.get("transaction_date") or "").strip(), "%Y-%m-%d").date()
        except ValueError:
            transaction_date = None
        try:
            ledger = record_owner_capital(
                branch_id=current_user.branch_id,
                kind=request.form.get("kind"),
                transaction_date=transaction_date,
                account_type=(request.form.get("account_type") or "").strip().upper(),
                bank_account_id=(request.form.get("bank_account_id") or "").strip() or None,
                amount=_parse_payment_amount((request.form.get("amount") or "").strip()),
                notes=request.form.get("notes"),
                created_by=current_user.id,
                actor_role=current_user.role,
            )
            flash(f"{ledger.description} tersimpan di buku kas/bank dan sudah dijurnal.", "success")
            return redirect(url_for("finance.owner_capital"))
        except (OwnerCapitalError, ValueError) as error:
            flash(str(error), "warning")
        except Exception as error:
            logger.exception("Gagal mencatat modal pemilik")
            flash(f"Gagal mencatat modal pemilik: {error}", "danger")

    return render_template(
        "finance/owner_capital.html",
        rows=list_owner_capital(current_user.branch_id),
        kinds=CAPITAL_KINDS,
        active_bank_accounts=BankAccount.query.filter_by(branch_id=current_user.branch_id, is_active=True)
        .order_by(BankAccount.bank_name.asc(), BankAccount.account_name.asc()).all(),
    )


@finance_bp.route("/cash-bank-ledger/<int:transaction_id>/reconcile", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def reconcile_cash_bank_ledger_transaction(transaction_id):
    from app.models.finance import CashBankTransaction
    from app.services.cash_bank_service import reconcile_cash_bank_transaction_record

    transaction = CashBankTransaction.query.get_or_404(transaction_id)
    if transaction.branch_id != current_user.branch_id:
        flash("Transaksi kas/bank tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.cash_bank_ledger"))

    note = (request.form.get("reconciliation_note") or "").strip()

    try:
        reconcile_cash_bank_transaction_record(transaction, reconciled_by=current_user.id, note=note)
        record_audit_log(
            module="CASH_BANK",
            event_type="LEDGER_RECONCILED",
            action="UPDATE",
            table_name="cash_bank_transactions",
            record_id=transaction.id,
            description="Transaksi kas/bank ditandai sudah rekonsiliasi.",
            metadata={"note": note},
        )
        flash("Transaksi kas/bank berhasil ditandai sudah rekonsiliasi.", "success")
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4543")
        flash(f"Gagal rekonsiliasi transaksi kas/bank: {error}", "danger")

    return redirect(request.referrer or url_for("finance.cash_bank_ledger"))


@finance_bp.route("/cash-bank-ledger/<int:transaction_id>/unreconcile", methods=["POST"])
@role_required("OWNER", "ADMIN", "FINANCE")
def unreconcile_cash_bank_ledger_transaction(transaction_id):
    from app.models.finance import CashBankTransaction
    from app.services.cash_bank_service import unreconcile_cash_bank_transaction_record

    transaction = CashBankTransaction.query.get_or_404(transaction_id)
    if transaction.branch_id != current_user.branch_id:
        flash("Transaksi kas/bank tidak sesuai cabang user.", "danger")
        return redirect(url_for("finance.cash_bank_ledger"))

    try:
        unreconcile_cash_bank_transaction_record(transaction)
        record_audit_log(
            module="CASH_BANK",
            event_type="LEDGER_UNRECONCILED",
            action="UPDATE",
            table_name="cash_bank_transactions",
            record_id=transaction.id,
            description="Status rekonsiliasi transaksi kas/bank dibuka kembali.",
        )
        flash("Status rekonsiliasi transaksi kas/bank berhasil dibuka kembali.", "success")
    except Exception as error:
        logger.exception("Suppressed unexpected exception in app/routes/finance_routes.py:4571")
        flash(f"Gagal membuka rekonsiliasi transaksi kas/bank: {error}", "danger")

    return redirect(request.referrer or url_for("finance.cash_bank_ledger"))

