from app.utils.terms import L
FIELD_EVENT_POLICIES = {
    "CATERING_DAILY_CASH_SALE": {
        "label": "Pembayaran Catering Masuk Tunai",
        "direction": "IN",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER", "QRIS"},
        "supports_auto_post": True,
        "revenue_account_code": "4002",
    },
    "CATERING_PERIOD_RECAP_REVENUE": {
        "label": "Pembayaran Catering Periode",
        "direction": "IN",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER", "QRIS"},
        "supports_auto_post": True,
        "revenue_account_code": "4001",
    },
    "OTHER_OPERATING_INCOME": {
        "label": "Pendapatan Operasional Lain",
        "direction": "IN",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": False,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER", "QRIS"},
        "supports_auto_post": True,
        "revenue_account_code": "4004",
    },
    "MANUAL_RECEIVABLE_CREATED": {
        "label": "Piutang Manual Dibuat",
        "direction": "IN",
        "cash_flow": "NON_CASH",
        "payment_status": "UNPAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": False,
        "allowed_payment_methods": set(),
        "supports_auto_post": False,
        "receivable_account_code": "1004",
    },
    "MANUAL_RECEIVABLE_PAYMENT": {
        "label": "Pelunasan Piutang Manual",
        "direction": "IN",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "READY_TO_POST",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER", "QRIS"},
        "supports_auto_post": True,
        "receivable_account_code": "1004",
    },
    "SITE_OPERATION_EXPENSE": {
        "label": "Biaya Operasional Site",
        "direction": "OUT",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": False,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        "expense_account_code": "5008",
    },
    "KITCHEN_OPERATION_EXPENSE": {
        "label": "Biaya Operasional Dapur",
        "direction": "OUT",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": False,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        "expense_account_code": "5002",
    },
    "TRANSPORT_TRIP_EXPENSE": {
        "label": "Biaya Perjalanan/Transport",
        "direction": "OUT",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": False,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        "expense_account_code": "5003",
    },
    "FUEL_EXPENSE": {
        "label": "Biaya BBM",
        "direction": "OUT",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": False,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        # COA menggabung transport dan BBM di 5003; 5011 adalah Beban
        # Perawatan Kendaraan (keputusan owner 2026-09-25).
        "expense_account_code": "5003",
    },
    "UNFORMAL_VENDOR_PAYABLE": {
        "label": "Hutang Vendor Nonformal",
        "direction": "OUT",
        "cash_flow": "NON_CASH",
        "payment_status": "UNPAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": False,
        "allowed_payment_methods": set(),
        "supports_auto_post": False,
        "payable_account_code": "2002",
    },
    "VENDOR_PAYABLE_PAYMENT": {
        "label": "Pembayaran Hutang Vendor",
        "direction": "OUT",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "READY_TO_POST",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        "payable_account_code": "2002",
    },
    "MANDOR_OPERATIONAL_ADVANCE": {
        "label": L("Panjar Operasional {sub_client}"),
        "direction": "OUT",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        "advance_account_code": "1008",
    },
    "MANDOR_ADVANCE_SETTLEMENT": {
        "label": L("Settlement Panjar {sub_client}"),
        "direction": "OUT",
        "cash_flow": "NON_CASH",
        "payment_status": "PARTIAL",
        "default_review_status": "WAITING_CLASSIFICATION",
        "default_evidence_status": "PENDING",
        "needs_counterparty": True,
        "needs_payment_method": False,
        "allowed_payment_methods": set(),
        "supports_auto_post": False,
        "advance_account_code": "1008",
    },
    "OWNER_CASH_INJECTION": {
        "label": "Setoran Modal Owner",
        "direction": "IN",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_APPROVAL",
        "default_evidence_status": "PENDING",
        "needs_counterparty": False,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        "equity_account_code": "3001",
    },
    "OWNER_DRAWING": {
        "label": "Prive Owner",
        "direction": "OUT",
        "cash_flow": "DIRECT",
        "payment_status": "PAID",
        "default_review_status": "WAITING_APPROVAL",
        "default_evidence_status": "PENDING",
        "needs_counterparty": False,
        "needs_payment_method": True,
        "allowed_payment_methods": {"CASH", "TRANSFER"},
        "supports_auto_post": True,
        "equity_account_code": "3003",
    },
}

FIELD_TRANSACTION_UI_READY_EVENT_TYPES = {
    "CATERING_DAILY_CASH_SALE",
    "CATERING_PERIOD_RECAP_REVENUE",
    "OTHER_OPERATING_INCOME",
    "MANUAL_RECEIVABLE_CREATED",
    "SITE_OPERATION_EXPENSE",
    "KITCHEN_OPERATION_EXPENSE",
    "TRANSPORT_TRIP_EXPENSE",
    "FUEL_EXPENSE",
    "UNFORMAL_VENDOR_PAYABLE",
    "MANDOR_OPERATIONAL_ADVANCE",
    "OWNER_CASH_INJECTION",
    "OWNER_DRAWING",
}


class FieldTransactionPolicyError(Exception):
    """Raised when a field transaction policy cannot be resolved."""


def normalize_event_type(event_type):
    return str(event_type or "").strip().upper()


def get_field_transaction_event_policy(event_type):
    normalized = normalize_event_type(event_type)
    policy = FIELD_EVENT_POLICIES.get(normalized)
    if not policy:
        raise FieldTransactionPolicyError("Event bisnis transaksi lapangan belum terdaftar.")
    merged = dict(policy)
    merged["event_type"] = normalized
    merged["ui_ready"] = normalized in FIELD_TRANSACTION_UI_READY_EVENT_TYPES
    return merged


def is_field_transaction_event_ui_ready(event_type):
    return normalize_event_type(event_type) in FIELD_TRANSACTION_UI_READY_EVENT_TYPES


def ensure_field_transaction_event_ui_ready(event_type):
    normalized = normalize_event_type(event_type)
    if normalized not in FIELD_TRANSACTION_UI_READY_EVENT_TYPES:
        raise FieldTransactionPolicyError(
            "Event bisnis transaksi lapangan ini belum dibuka di UI karena alur end-to-end-nya belum tuntas."
        )
    return normalized


def list_field_transaction_event_choices(direction=None, ui_ready_only=False):
    if direction:
        direction = str(direction or "").strip().upper()
    rows = []
    for event_type, policy in FIELD_EVENT_POLICIES.items():
        if direction and policy.get("direction") != direction:
            continue
        if ui_ready_only and event_type not in FIELD_TRANSACTION_UI_READY_EVENT_TYPES:
            continue
        rows.append({
            "value": event_type,
            "label": policy.get("label", event_type),
            "direction": policy.get("direction"),
            "cash_flow": policy.get("cash_flow"),
            "supports_auto_post": bool(policy.get("supports_auto_post")),
            "ui_ready": event_type in FIELD_TRANSACTION_UI_READY_EVENT_TYPES,
        })
    rows.sort(key=lambda row: row["label"])
    return rows


def resolve_policy_defaults(event_type):
    policy = get_field_transaction_event_policy(event_type)
    return {
        "transaction_direction": policy["direction"],
        "payment_status": policy["payment_status"],
        "review_status": policy["default_review_status"],
        "evidence_status": policy["default_evidence_status"],
        "supports_auto_post": bool(policy.get("supports_auto_post")),
    }


def validate_field_transaction_event_payload(
    *,
    event_type,
    transaction_direction,
    amount,
    payment_status=None,
    payment_method=None,
    bank_account_id=None,
    counterparty_id=None,
    party_snapshot_name=None,
):
    policy = get_field_transaction_event_policy(event_type)
    direction = str(transaction_direction or "").strip().upper()
    if direction != policy["direction"]:
        raise FieldTransactionPolicyError(
            f"Event {policy['label']} hanya boleh memakai arah transaksi {policy['direction']}."
        )

    try:
        amount = float(amount or 0)
    except Exception as exc:
        raise FieldTransactionPolicyError("Nominal transaksi lapangan tidak valid.") from exc

    if amount <= 0:
        raise FieldTransactionPolicyError("Nominal transaksi lapangan harus lebih dari 0.")

    if policy.get("needs_counterparty") and not counterparty_id and not str(party_snapshot_name or "").strip():
        raise FieldTransactionPolicyError(
            f"Event {policy['label']} wajib memiliki pihak transaksi lapangan atau snapshot nama pihak."
        )

    allowed_methods = set(policy.get("allowed_payment_methods") or set())
    normalized_method = str(payment_method or "").strip().upper()
    if allowed_methods:
        if normalized_method not in allowed_methods:
            allowed_label = ", ".join(sorted(allowed_methods))
            raise FieldTransactionPolicyError(
                f"Metode pembayaran untuk {policy['label']} harus salah satu dari: {allowed_label}."
            )
        if normalized_method in {"TRANSFER", "QRIS"} and not bank_account_id:
            raise FieldTransactionPolicyError(
                f"Event {policy['label']} wajib memilih rekening bank untuk metode {normalized_method}."
            )
        if payment_status and str(payment_status or "").strip().upper() == "UNPAID":
            raise FieldTransactionPolicyError(
                f"Event {policy['label']} adalah transaksi kas langsung dan tidak boleh berstatus UNPAID."
            )
    else:
        if normalized_method:
            raise FieldTransactionPolicyError(
                f"Event {policy['label']} tidak menerima metode pembayaran langsung pada tahap ini."
            )

    return policy


def resolve_cash_bank_coa_code(*, payment_method=None, bank_account=None, fallback_bank_code="1002"):
    method = str(payment_method or "").strip().upper()
    if method == "CASH":
        return "1001"

    candidate = str(getattr(bank_account, "coa_account_code", "") or "").strip()
    if candidate:
        return candidate
    return fallback_bank_code


def resolve_event_account_map(*, event_type, payment_method=None, bank_account=None):
    policy = get_field_transaction_event_policy(event_type)
    cash_bank_code = resolve_cash_bank_coa_code(
        payment_method=payment_method,
        bank_account=bank_account,
    )

    if policy["direction"] == "IN":
        if policy.get("revenue_account_code"):
            return {
                "debit_account_code": cash_bank_code,
                "credit_account_code": policy["revenue_account_code"],
            }
        if policy.get("receivable_account_code") and policy.get("cash_flow") == "DIRECT":
            return {
                "debit_account_code": cash_bank_code,
                "credit_account_code": policy["receivable_account_code"],
            }
        if policy.get("equity_account_code"):
            return {
                "debit_account_code": cash_bank_code,
                "credit_account_code": policy["equity_account_code"],
            }

    if policy["direction"] == "OUT":
        if policy.get("expense_account_code") and policy.get("cash_flow") == "DIRECT":
            return {
                "debit_account_code": policy["expense_account_code"],
                "credit_account_code": cash_bank_code,
            }
        if policy.get("payable_account_code") and policy.get("cash_flow") == "DIRECT":
            return {
                "debit_account_code": policy["payable_account_code"],
                "credit_account_code": cash_bank_code,
            }
        if policy.get("advance_account_code") and policy.get("cash_flow") == "DIRECT":
            return {
                "debit_account_code": policy["advance_account_code"],
                "credit_account_code": cash_bank_code,
            }
        if policy.get("equity_account_code"):
            return {
                "debit_account_code": policy["equity_account_code"],
                "credit_account_code": cash_bank_code,
            }

    return {
        "debit_account_code": None,
        "credit_account_code": None,
    }
