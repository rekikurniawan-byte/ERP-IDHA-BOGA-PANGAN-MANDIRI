"""Read-only dashboard analytics service for Owner/Admin.

PRODUCTION keeps this module strictly read-only. PRODUCTION strengthens the
Revenue vs Spending bar payload, PRODUCTION strengthens the Operational
Efficiency donut payload, and PRODUCTION adds the Revenue Explorer foundation
without creating dummy data, committing database changes, generating invoices,
mutating delivery status, or posting journals.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy import text

from app.extensions import db


CANCELLED_STATUSES = ("CANCELLED", "CANCELED")
BASE_SPENDING_EXCLUDED_REFERENCES = (
    "OPENING_BALANCE",
    "CASH_BANK_TRANSFER",
    "CASH_BANK_TRANSFER_OUT",
    "CASH_BANK_TRANSFER_IN",
    "TRANSFER",
)
ASSET_SPENDING_REFERENCES = (
    "FIXED_ASSET_PURCHASE",
    "FIXED_ASSET",
    "ASSET_PURCHASE",
)


MONTH_SHORT_LABELS = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
MONTH_FULL_LABELS = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober", "November", "Desember"]


def _today() -> date:
    return date.today()


def _safe_year(year: Optional[Any]) -> int:
    try:
        parsed_year = int(year)
        if 2000 <= parsed_year <= 2100:
            return parsed_year
    except (TypeError, ValueError):
        pass

    return _today().year


def _safe_month(month: Optional[Any]) -> int:
    try:
        parsed_month = int(month)
        if 1 <= parsed_month <= 12:
            return parsed_month
    except (TypeError, ValueError):
        pass

    return _today().month


def _as_float(value: Optional[Any]) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _as_int(value: Optional[Any]) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _year_range(year: int) -> Tuple[str, str]:
    return f"{year:04d}-01-01", f"{year + 1:04d}-01-01"


def _month_range(year: int, month: int) -> Tuple[str, str]:
    next_year = year + 1 if month == 12 else year
    next_month = 1 if month == 12 else month + 1
    return f"{year:04d}-{month:02d}-01", f"{next_year:04d}-{next_month:02d}-01"


def _normalize_date(value: Optional[Any]) -> Optional[str]:
    if value is None:
        return None

    if isinstance(value, date):
        return value.isoformat()

    value = str(value).strip()
    if len(value) >= 10:
        return value[:10]

    return None


def _rollback_after_read_error() -> None:
    try:
        db.session.rollback()
    except Exception:
        pass




def _dialect_name() -> str:
    try:
        bind = db.session.get_bind()
        return str(getattr(bind.dialect, "name", "") or "").lower()
    except Exception:
        return ""


def _is_postgres() -> bool:
    return _dialect_name() in {"postgresql", "postgres"}


def _date_bucket_sql(date_column: str, group_by: str) -> str:
    """Return dialect-safe date bucket SQL for dashboard analytics."""
    if _is_postgres():
        if group_by == "daily":
            return f"to_char({date_column}, 'YYYY-MM-DD')"
        if group_by == "weekly":
            return f"to_char({date_column}, 'IYYY-\"W\"IW')"
        if group_by == "yearly":
            return f"to_char({date_column}, 'YYYY')"
        return f"to_char({date_column}, 'YYYY-MM')"

    if group_by == "daily":
        return f"strftime('%Y-%m-%d', {date_column})"
    if group_by == "weekly":
        return f"strftime('%Y-W%W', {date_column})"
    if group_by == "yearly":
        return f"strftime('%Y', {date_column})"
    return f"strftime('%Y-%m', {date_column})"


def _year_sql(date_column: str) -> str:
    if _is_postgres():
        return f"CAST(EXTRACT(YEAR FROM {date_column}) AS INTEGER)"
    return f"CAST(strftime('%Y', {date_column}) AS INTEGER)"

def _execute_rows(sql: str, params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Execute a read-only SQL statement and return mapping rows.

    The function intentionally does not call commit/flush. Query failures are
    isolated so dashboards can render safe empty states on incomplete legacy DBs.
    PostgreSQL marks the whole transaction as failed after one SQL error, so the
    session is explicitly rolled back before returning the empty fallback.
    """
    try:
        return [dict(row) for row in db.session.execute(text(sql), params or {}).mappings().all()]
    except Exception:
        _rollback_after_read_error()
        return []


def _execute_scalar(sql: str, params: Optional[Dict[str, Any]] = None, default: Any = 0) -> Any:
    try:
        value = db.session.execute(text(sql), params or {}).scalar()
        return default if value is None else value
    except Exception:
        _rollback_after_read_error()
        return default


def _branch_where(alias: str, branch_id: Optional[int]) -> str:
    if branch_id is None:
        return ""
    return f" AND {alias}.branch_id = :branch_id"


def _branch_params(branch_id: Optional[int]) -> Dict[str, Any]:
    return {"branch_id": branch_id} if branch_id is not None else {}


def _monthly_base(year: int) -> List[Dict[str, Any]]:
    return [
        {
            "month": index,
            "month_key": f"{year:04d}-{index:02d}",
            "label": MONTH_SHORT_LABELS[index - 1],
            "revenue": 0.0,
            "spending": 0.0,
            "net": 0.0,
        }
        for index in range(1, 13)
    ]


def _fill_month_values(monthly: List[Dict[str, Any]], rows: Iterable[Dict[str, Any]], field_name: str) -> None:
    by_month = {row["month_key"]: row for row in monthly}

    for row in rows:
        month_key = str(row.get("month_key") or "").strip()
        if month_key not in by_month:
            continue

        by_month[month_key][field_name] = _as_float(row.get("total_amount"))

    for row in monthly:
        row["net"] = row["revenue"] - row["spending"]


def _spending_exclusions(include_asset_purchase: bool) -> Tuple[str, ...]:
    exclusions = list(BASE_SPENDING_EXCLUDED_REFERENCES)
    if not include_asset_purchase:
        exclusions.extend(ASSET_SPENDING_REFERENCES)
    return tuple(dict.fromkeys(exclusions))





REVENUE_PERIOD_PRESETS = ("today", "week", "month", "year", "all", "custom")
REVENUE_GROUP_BY_OPTIONS = ("daily", "weekly", "monthly", "yearly")
REVENUE_SOURCE_OPTIONS = (
    ("all", "Semua sumber"),
    ("invoice", "Invoice catering"),
    ("payment", "Kas masuk invoice"),
    ("canteen", "Warung"),
    ("receivable", "Piutang"),
)


def _safe_date(value: Optional[Any]) -> Optional[date]:
    if not value:
        return None
    if isinstance(value, date):
        return value
    text_value = str(value).strip()
    try:
        return datetime.strptime(text_value[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _date_to_sql(value: date) -> str:
    return value.isoformat()


def _safe_period_preset(value: Optional[Any]) -> str:
    normalized = str(value or "month").strip().lower()
    if normalized in REVENUE_PERIOD_PRESETS:
        return normalized
    return "month"


def _safe_group_by(value: Optional[Any], start_date: date, end_date: date, preset: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in REVENUE_GROUP_BY_OPTIONS:
        return normalized

    day_count = max((end_date - start_date).days + 1, 1)
    if preset in {"today", "week"} or day_count <= 45:
        return "daily"
    if preset == "month" or day_count <= 180:
        return "weekly"
    if day_count <= 1100:
        return "monthly"
    return "yearly"


def _safe_revenue_source(value: Optional[Any]) -> str:
    normalized = str(value or "all").strip().lower()
    allowed = {key for key, _label in REVENUE_SOURCE_OPTIONS}
    if normalized in allowed:
        return normalized
    return "all"


def _safe_optional_int(value: Optional[Any]) -> Optional[int]:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _resolve_revenue_period(
    preset: Optional[Any] = None,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    branch_id: Optional[int] = None,
) -> Dict[str, Any]:
    today = _today()
    normalized_preset = _safe_period_preset(preset)

    if normalized_preset == "today":
        start = today
        end = today
    elif normalized_preset == "week":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif normalized_preset == "month":
        start = date(today.year, today.month, 1)
        end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    elif normalized_preset == "year":
        start = date(today.year, 1, 1)
        end = date(today.year, 12, 31)
    elif normalized_preset == "all":
        min_candidates = []
        params = _branch_params(branch_id)
        for sql in (
            f"SELECT MIN(invoice_date) FROM invoices inv WHERE inv.invoice_date IS NOT NULL {_branch_where('inv', branch_id)}",
            f"SELECT MIN(payment_date) FROM payments pay WHERE pay.payment_date IS NOT NULL {_branch_where('pay', branch_id)}",
            f"SELECT MIN(sale_date) FROM canteen_sales cs WHERE cs.sale_date IS NOT NULL {_branch_where('cs', branch_id)}",
        ):
            raw_value = _execute_scalar(sql, params, default=None)
            parsed = _safe_date(raw_value)
            if parsed:
                min_candidates.append(parsed)
        start = min(min_candidates) if min_candidates else date(today.year, 1, 1)
        end = today
    else:
        start = _safe_date(start_date) or date(today.year, today.month, 1)
        end = _safe_date(end_date) or today
        if end < start:
            start, end = end, start

    return {
        "preset": normalized_preset,
        "start_date": start,
        "end_date": end,
        "start_date_sql": _date_to_sql(start),
        "end_date_sql": _date_to_sql(end),
        "end_exclusive_sql": _date_to_sql(end + timedelta(days=1)),
        "label": _format_date_range_label(start, end),
    }


def _format_date_range_label(start: date, end: date) -> str:
    if start == end:
        return start.strftime("%d-%m-%Y")
    if start.year == end.year and start.month == end.month:
        return f"{start.day:02d}–{end.day:02d} {MONTH_FULL_LABELS[start.month - 1]} {start.year}"
    if start.year == end.year:
        return f"{start.day:02d} {MONTH_FULL_LABELS[start.month - 1]} – {end.day:02d} {MONTH_FULL_LABELS[end.month - 1]} {start.year}"
    return f"{start.strftime('%d-%m-%Y')} – {end.strftime('%d-%m-%Y')}"


def _bucket_sql(date_column: str, group_by: str) -> str:
    return _date_bucket_sql(date_column, group_by)


def _bucket_label(bucket_key: str, group_by: str) -> str:
    key = str(bucket_key or "")
    try:
        if group_by == "daily":
            parsed = datetime.strptime(key, "%Y-%m-%d").date()
            return f"{parsed.day:02d} {MONTH_SHORT_LABELS[parsed.month - 1]}"
        if group_by == "weekly":
            return key.replace("-W", " Minggu ")
        if group_by == "yearly":
            return key
        parsed_year = int(key[:4])
        parsed_month = int(key[5:7])
        return f"{MONTH_SHORT_LABELS[parsed_month - 1]} {parsed_year}"
    except (TypeError, ValueError, IndexError):
        return key or "-"


def _bucket_sequence(start: date, end: date, group_by: str) -> List[Dict[str, Any]]:
    buckets: List[Dict[str, Any]] = []
    if group_by == "daily":
        current = start
        while current <= end:
            key = current.isoformat()
            buckets.append({"key": key, "label": _bucket_label(key, group_by)})
            current += timedelta(days=1)
        return buckets

    if group_by == "weekly":
        current = start - timedelta(days=start.weekday())
        seen = set()
        while current <= end:
            key = current.strftime("%Y-W%W")
            if key not in seen:
                buckets.append({"key": key, "label": _bucket_label(key, group_by)})
                seen.add(key)
            current += timedelta(days=7)
        return buckets

    if group_by == "yearly":
        for year_value in range(start.year, end.year + 1):
            key = str(year_value)
            buckets.append({"key": key, "label": _bucket_label(key, group_by)})
        return buckets

    current = date(start.year, start.month, 1)
    end_month = date(end.year, end.month, 1)
    while current <= end_month:
        key = f"{current.year:04d}-{current.month:02d}"
        buckets.append({"key": key, "label": _bucket_label(key, group_by)})
        next_year = current.year + 1 if current.month == 12 else current.year
        next_month = 1 if current.month == 12 else current.month + 1
        current = date(next_year, next_month, 1)
    return buckets


def _merge_amount_rows(
    bucket_map: Dict[str, Dict[str, Any]],
    rows: Iterable[Dict[str, Any]],
    field_name: str,
) -> None:
    for row in rows:
        key = str(row.get("bucket_key") or "").strip()
        if not key:
            continue
        if key not in bucket_map:
            bucket_map[key] = {"key": key, "label": key}
        bucket_map[key][field_name] = _as_float(bucket_map[key].get(field_name)) + _as_float(row.get("amount"))


def _where_branch(alias: str, forced_branch_id: Optional[int]) -> str:
    return _branch_where(alias, forced_branch_id)


def _where_optional_client_mandor(alias: str, client_id: Optional[int], mandor_id: Optional[int]) -> str:
    clauses = []
    if client_id:
        clauses.append(f" AND {alias}.client_id = :client_id")
    if mandor_id:
        clauses.append(f" AND {alias}.mandor_id = :mandor_id")
    return "".join(clauses)


def _query_options(table: str, value_field: str, label_field: str, where_sql: str = "", params: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows = _execute_rows(
        f"""
        SELECT {value_field} AS value, {label_field} AS label
        FROM {table}
        WHERE 1=1 {where_sql}
        ORDER BY {label_field} ASC
        """,
        params or {},
    )
    return [{"value": row.get("value"), "label": row.get("label")} for row in rows if row.get("value")]


def _source_total_for_filter(row: Dict[str, Any], source: str) -> float:
    if source == "invoice":
        return _as_float(row.get("invoice_accrual"))
    if source == "payment":
        return _as_float(row.get("invoice_payment"))
    if source == "canteen":
        return _as_float(row.get("canteen_paid")) + _as_float(row.get("canteen_debt_sale")) + _as_float(row.get("canteen_debt_payment"))
    if source == "receivable":
        return _as_float(row.get("receivable_created"))
    return _as_float(row.get("invoice_accrual")) + _as_float(row.get("canteen_paid")) + _as_float(row.get("canteen_debt_sale"))


def get_revenue_explorer_data(
    branch_id: Optional[int] = None,
    role: str = "OWNER",
    period_preset: Optional[Any] = None,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
    group_by: Optional[Any] = None,
    source: Optional[Any] = None,
    client_id: Optional[Any] = None,
    mandor_id: Optional[Any] = None,
    selected_branch_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Return read-only revenue explorer data for Owner/Admin dashboards.

    PRODUCTION separates accrual invoice value, real cash-in, direct canteen sales,
    and receivables so empty chart areas become useful analytics. It never
    mutates invoices, payments, canteen sales, ledgers, or journals.
    """
    user_role = str(role or "OWNER").upper()
    requested_branch_id = _safe_optional_int(selected_branch_id)
    forced_branch_id = branch_id
    if user_role == "OWNER" and requested_branch_id:
        forced_branch_id = requested_branch_id

    period = _resolve_revenue_period(period_preset, start_date, end_date, forced_branch_id)
    selected_group_by = _safe_group_by(group_by, period["start_date"], period["end_date"], period["preset"])
    selected_source = _safe_revenue_source(source)
    selected_client_id = _safe_optional_int(client_id)
    selected_mandor_id = _safe_optional_int(mandor_id)

    params: Dict[str, Any] = {
        "start_date": period["start_date_sql"],
        "end_exclusive": period["end_exclusive_sql"],
        **_branch_params(forced_branch_id),
    }
    if selected_client_id:
        params["client_id"] = selected_client_id
    if selected_mandor_id:
        params["mandor_id"] = selected_mandor_id

    bucket_expr_invoice = _bucket_sql("inv.invoice_date", selected_group_by)
    bucket_expr_payment = _bucket_sql("pay.payment_date", selected_group_by)
    bucket_expr_canteen = _bucket_sql("cs.sale_date", selected_group_by)
    bucket_expr_debt_payment = _bucket_sql("dp.payment_date", selected_group_by)
    bucket_expr_ext_payment = _bucket_sql("cerp.payment_date", selected_group_by)

    invoice_filter = _where_optional_client_mandor("inv", selected_client_id, selected_mandor_id)
    invoice_rows = _execute_rows(
        f"""
        SELECT {bucket_expr_invoice} AS bucket_key, SUM(COALESCE(inv.total_amount, 0)) AS amount
        FROM invoices inv
        WHERE inv.invoice_date >= :start_date
          AND inv.invoice_date < :end_exclusive
          AND COALESCE(UPPER(inv.status), '') NOT IN ('CANCELLED', 'CANCELED')
          {_where_branch('inv', forced_branch_id)}
          {invoice_filter}
        GROUP BY {bucket_expr_invoice}
        ORDER BY bucket_key ASC
        """,
        params,
    )
    invoice_payment_rows = _execute_rows(
        f"""
        SELECT {bucket_expr_payment} AS bucket_key, SUM(COALESCE(pay.amount, 0)) AS amount
        FROM payments pay
        JOIN invoices inv ON inv.id = pay.invoice_id
        WHERE pay.payment_date >= :start_date
          AND pay.payment_date < :end_exclusive
          AND COALESCE(UPPER(inv.status), '') NOT IN ('CANCELLED', 'CANCELED')
          {_where_branch('pay', forced_branch_id)}
          {invoice_filter}
        GROUP BY {bucket_expr_payment}
        ORDER BY bucket_key ASC
        """,
        params,
    )

    canteen_paid_rows = _execute_rows(
        f"""
        SELECT {bucket_expr_canteen} AS bucket_key, SUM(COALESCE(cs.total_amount, 0)) AS amount
        FROM canteen_sales cs
        WHERE cs.sale_date >= :start_date
          AND cs.sale_date < :end_exclusive
          AND UPPER(COALESCE(cs.sale_type, '')) = 'CASH'
          AND UPPER(COALESCE(cs.payment_method, 'CASH')) IN ('CASH', 'QRIS', 'TRANSFER')
          {_where_branch('cs', forced_branch_id)}
        GROUP BY {bucket_expr_canteen}
        ORDER BY bucket_key ASC
        """,
        params,
    ) if not (selected_client_id or selected_mandor_id) else []

    canteen_debt_rows = _execute_rows(
        f"""
        SELECT {bucket_expr_canteen} AS bucket_key, SUM(COALESCE(cs.total_amount, 0)) AS amount
        FROM canteen_sales cs
        WHERE cs.sale_date >= :start_date
          AND cs.sale_date < :end_exclusive
          AND UPPER(COALESCE(cs.sale_type, '')) = 'DEBT'
          {_where_branch('cs', forced_branch_id)}
        GROUP BY {bucket_expr_canteen}
        ORDER BY bucket_key ASC
        """,
        params,
    ) if not (selected_client_id or selected_mandor_id) else []

    worker_debt_payment_rows = _execute_rows(
        f"""
        SELECT {bucket_expr_debt_payment} AS bucket_key, SUM(COALESCE(dp.amount, 0)) AS amount
        FROM debt_payments dp
        JOIN worker_debts wd ON wd.id = dp.worker_debt_id
        WHERE dp.payment_date >= :start_date
          AND dp.payment_date < :end_exclusive
          {_where_branch('wd', forced_branch_id)}
        GROUP BY {bucket_expr_debt_payment}
        ORDER BY bucket_key ASC
        """,
        params,
    ) if not (selected_client_id or selected_mandor_id) else []

    external_receivable_payment_rows = _execute_rows(
        f"""
        SELECT {bucket_expr_ext_payment} AS bucket_key, SUM(COALESCE(cerp.amount, 0)) AS amount
        FROM canteen_external_receivable_payments cerp
        JOIN canteen_external_receivables cer ON cer.id = cerp.receivable_id
        WHERE cerp.payment_date >= :start_date
          AND cerp.payment_date < :end_exclusive
          {_where_branch('cer', forced_branch_id)}
        GROUP BY {bucket_expr_ext_payment}
        ORDER BY bucket_key ASC
        """,
        params,
    ) if not (selected_client_id or selected_mandor_id) else []

    buckets = _bucket_sequence(period["start_date"], period["end_date"], selected_group_by)
    bucket_map: Dict[str, Dict[str, Any]] = {
        item["key"]: {
            "key": item["key"],
            "label": item["label"],
            "invoice_accrual": 0.0,
            "invoice_payment": 0.0,
            "canteen_paid": 0.0,
            "canteen_debt_sale": 0.0,
            "canteen_debt_payment": 0.0,
            "cash_in": 0.0,
            "selected_total": 0.0,
            "receivable_created": 0.0,
        }
        for item in buckets
    }
    _merge_amount_rows(bucket_map, invoice_rows, "invoice_accrual")
    _merge_amount_rows(bucket_map, invoice_payment_rows, "invoice_payment")
    _merge_amount_rows(bucket_map, canteen_paid_rows, "canteen_paid")
    _merge_amount_rows(bucket_map, canteen_debt_rows, "canteen_debt_sale")
    _merge_amount_rows(bucket_map, worker_debt_payment_rows, "canteen_debt_payment")
    _merge_amount_rows(bucket_map, external_receivable_payment_rows, "canteen_debt_payment")

    trend_rows = []
    for key in sorted(bucket_map.keys()):
        row = bucket_map[key]
        row["label"] = _bucket_label(key, selected_group_by)
        row["cash_in"] = _as_float(row.get("invoice_payment")) + _as_float(row.get("canteen_paid")) + _as_float(row.get("canteen_debt_payment"))
        row["receivable_created"] = _as_float(row.get("invoice_accrual")) + _as_float(row.get("canteen_debt_sale"))
        row["selected_total"] = _source_total_for_filter(row, selected_source)
        row["has_value"] = any(_as_float(row.get(field)) > 0 for field in ("invoice_accrual", "invoice_payment", "canteen_paid", "canteen_debt_sale", "canteen_debt_payment"))
        trend_rows.append(row)

    # Prevent huge dashboard charts from turning into blank wide areas on very long ranges.
    if len(trend_rows) > 48:
        trend_rows = [row for row in trend_rows if row["has_value"]]

    total_invoice_accrual = sum(_as_float(row.get("invoice_accrual")) for row in trend_rows)
    total_invoice_payment = sum(_as_float(row.get("invoice_payment")) for row in trend_rows)
    total_canteen_paid = sum(_as_float(row.get("canteen_paid")) for row in trend_rows)
    total_canteen_debt_sale = sum(_as_float(row.get("canteen_debt_sale")) for row in trend_rows)
    total_canteen_debt_payment = sum(_as_float(row.get("canteen_debt_payment")) for row in trend_rows)
    total_cash_in = total_invoice_payment + total_canteen_paid + total_canteen_debt_payment
    selected_total = sum(_as_float(row.get("selected_total")) for row in trend_rows)

    receivable_params = dict(params)
    invoice_outstanding = _as_float(_execute_scalar(
        f"""
        SELECT SUM(COALESCE(inv.remaining_amount, 0))
        FROM invoices inv
        WHERE COALESCE(UPPER(inv.status), '') NOT IN ('CANCELLED', 'CANCELED', 'PAID')
          AND COALESCE(inv.remaining_amount, 0) > 0
          AND inv.invoice_date >= :start_date
          AND inv.invoice_date < :end_exclusive
          {_where_branch('inv', forced_branch_id)}
          {invoice_filter}
        """,
        receivable_params,
        default=0,
    ))
    worker_debt_outstanding = 0.0
    external_outstanding = 0.0
    if not (selected_client_id or selected_mandor_id):
        worker_debt_outstanding = _as_float(_execute_scalar(
            f"""
            SELECT SUM(COALESCE(wd.debt_amount, 0) - COALESCE(paid.total_paid, 0))
            FROM worker_debts wd
            JOIN canteen_sales cs ON cs.id = wd.sale_id
            LEFT JOIN (
                SELECT worker_debt_id, SUM(COALESCE(amount, 0)) AS total_paid
                FROM debt_payments
                GROUP BY worker_debt_id
            ) paid ON paid.worker_debt_id = wd.id
            WHERE cs.sale_date >= :start_date
              AND cs.sale_date < :end_exclusive
              AND UPPER(COALESCE(wd.status, '')) != 'PAID'
              {_where_branch('wd', forced_branch_id)}
            """,
            params,
            default=0,
        ))
        external_outstanding = _as_float(_execute_scalar(
            f"""
            SELECT SUM(COALESCE(cer.remaining_amount, 0))
            FROM canteen_external_receivables cer
            JOIN canteen_sales cs ON cs.id = cer.sale_id
            WHERE cs.sale_date >= :start_date
              AND cs.sale_date < :end_exclusive
              AND COALESCE(cer.remaining_amount, 0) > 0
              {_where_branch('cer', forced_branch_id)}
            """,
            params,
            default=0,
        ))
    total_outstanding = max(invoice_outstanding, 0.0) + max(worker_debt_outstanding, 0.0) + max(external_outstanding, 0.0)

    mix_segments = [
        {"key": "invoice", "label": "Invoice Catering", "amount": total_invoice_accrual, "endpoint": "finance.invoices", "description": "Omzet akrual dari invoice aktif."},
        {"key": "canteen_paid", "label": "Warung Lunas", "amount": total_canteen_paid, "endpoint": "canteen.index", "description": "Penjualan warung cash/QRIS/transfer."},
        {"key": "canteen_debt", "label": "Warung Hutang", "amount": total_canteen_debt_sale, "endpoint": "canteen.debts", "description": "Penjualan warung hutang pekerja/eksternal."},
    ]
    mix_total = sum(_as_float(segment.get("amount")) for segment in mix_segments)
    for segment in mix_segments:
        segment["percent"] = round((_as_float(segment.get("amount")) / mix_total) * 100, 2) if mix_total > 0 else 0.0
        segment["percent_label"] = _percent_label(segment["percent"])

    max_value = max([0.0, *[_as_float(row.get("selected_total")) for row in trend_rows], *[_as_float(row.get("cash_in")) for row in trend_rows], *[_as_float(row.get("invoice_accrual")) for row in trend_rows]])
    for row in trend_rows:
        row["selected_percent"] = round((_as_float(row.get("selected_total")) / max_value) * 100, 2) if max_value > 0 else 0.0
        row["cash_in_percent"] = round((_as_float(row.get("cash_in")) / max_value) * 100, 2) if max_value > 0 else 0.0
        row["invoice_percent"] = round((_as_float(row.get("invoice_accrual")) / max_value) * 100, 2) if max_value > 0 else 0.0

    top_period = max(trend_rows, key=lambda item: _as_float(item.get("selected_total"))) if trend_rows else {"label": "-", "selected_total": 0}
    source_label_map = dict(REVENUE_SOURCE_OPTIONS)

    branch_options = []
    if user_role == "OWNER":
        branch_options = _query_options("branches", "id", "name", " AND is_active IS TRUE")
    client_options = _query_options("clients", "id", "name", " AND is_active IS TRUE")
    mandor_where = " AND is_active IS TRUE"
    mandor_params = {}
    if forced_branch_id:
        mandor_where += " AND branch_id = :branch_id"
        mandor_params["branch_id"] = forced_branch_id
    if selected_client_id:
        mandor_where += " AND client_id = :client_id"
        mandor_params["client_id"] = selected_client_id
    mandor_options = _query_options("mandors", "id", "name", mandor_where, mandor_params)

    return {
        "key": "revenue_explorer",
        "title": "Omzet & Revenue Explorer",
        "subtitle": "Pisahkan omzet akrual, kas masuk, warung lunas, dan piutang agar angka owner tidak bercampur.",
        "period": period,
        "filters": {
            "period_preset": period["preset"],
            "start_date": period["start_date_sql"],
            "end_date": period["end_date_sql"],
            "group_by": selected_group_by,
            "source": selected_source,
            "source_label": source_label_map.get(selected_source, "Semua sumber"),
            "client_id": selected_client_id,
            "mandor_id": selected_mandor_id,
            "branch_id": forced_branch_id if user_role == "OWNER" else branch_id,
            "requested_branch_id": requested_branch_id,
        },
        "options": {
            "period_presets": [
                {"value": "today", "label": "Hari ini"},
                {"value": "week", "label": "Minggu ini"},
                {"value": "month", "label": "Bulan ini"},
                {"value": "year", "label": "Tahun ini"},
                {"value": "all", "label": "Semua"},
                {"value": "custom", "label": "Custom tanggal"},
            ],
            "group_by": [
                {"value": "daily", "label": "Harian"},
                {"value": "weekly", "label": "Mingguan"},
                {"value": "monthly", "label": "Bulanan"},
                {"value": "yearly", "label": "Tahunan"},
            ],
            "sources": [{"value": key, "label": label} for key, label in REVENUE_SOURCE_OPTIONS],
            "branches": branch_options,
            "clients": client_options,
            "mandors": mandor_options,
        },
        "stat_cards": [
            {"key": "omzet", "label": "Omzet Akrual", "amount": total_invoice_accrual, "icon": "bi-receipt", "tone": "blue", "caption": "Invoice aktif, bukan pembayaran."},
            {"key": "cash_in", "label": "Kas Masuk", "amount": total_cash_in, "icon": "bi-cash-coin", "tone": "green", "caption": "Payment invoice + warung diterima."},
            {"key": "canteen_paid", "label": "Warung Lunas", "amount": total_canteen_paid, "icon": "bi-shop", "tone": "purple", "caption": "Cash/QRIS/transfer langsung."},
            {"key": "outstanding", "label": "Outstanding", "amount": total_outstanding, "icon": "bi-hourglass-split", "tone": "orange", "caption": "Invoice + piutang warung belum lunas."},
        ],
        "totals": {
            "invoice_accrual": total_invoice_accrual,
            "invoice_payment": total_invoice_payment,
            "canteen_paid": total_canteen_paid,
            "canteen_debt_sale": total_canteen_debt_sale,
            "canteen_debt_payment": total_canteen_debt_payment,
            "cash_in": total_cash_in,
            "selected_total": selected_total,
            "outstanding": total_outstanding,
            "invoice_outstanding": invoice_outstanding,
            "worker_debt_outstanding": worker_debt_outstanding,
            "external_outstanding": external_outstanding,
        },
        "trend_rows": trend_rows,
        "mix_segments": mix_segments,
        "mix_total": mix_total,
        "top_period": top_period,
        "max_value": max_value,
        "is_empty": max_value <= 0 and mix_total <= 0 and total_outstanding <= 0,
        "empty_title": "Belum ada data omzet/revenue pada filter ini",
        "empty_message": "Ubah filter periode atau mulai dari invoice, payment, dan transaksi warung. Tidak ada data dummy yang dibuat.",
        "drilldown": {
            "invoice_endpoint": "finance.invoices",
            "payment_endpoint": "finance.payment_history",
            "canteen_endpoint": "canteen.index",
            "receivable_endpoint": "finance.receivables",
            "external_debt_endpoint": "canteen.debts",
        },
        "notes": [
            "Omzet akrual membaca invoice aktif berdasarkan tanggal invoice.",
            "Kas masuk membaca pembayaran invoice, penjualan warung lunas, dan pembayaran hutang warung.",
            "Warung debt adalah omzet warung yang belum tentu langsung jadi kas.",
            "Filter client/mandor hanya berlaku untuk invoice dan payment catering; warung tidak punya relasi client/mandor.",
        ],
        "data_contract": {
            "invoice_accrual": "invoices.total_amount where status not cancelled grouped by invoice_date",
            "cash_in": "payments.amount + canteen paid sales + canteen debt payments",
            "canteen_paid": "canteen_sales.sale_type=CASH and payment_method in CASH/QRIS/TRANSFER",
            "receivable": "remaining invoice + remaining worker/external canteen debt",
            "read_only": True,
            "no_migration": True,
        },
    }


def get_analytics_month_options() -> List[Dict[str, Any]]:
    """Return stable month options for Owner/Admin analytics filters."""
    return [
        {"value": index, "label": MONTH_FULL_LABELS[index - 1], "short_label": MONTH_SHORT_LABELS[index - 1]}
        for index in range(1, 13)
    ]


def _period_label_from_date(value: str) -> str:
    try:
        parsed_year = int(value[:4])
        parsed_month = int(value[5:7])
        if 1 <= parsed_month <= 12:
            return f"{MONTH_FULL_LABELS[parsed_month - 1]} {parsed_year}"
    except (TypeError, ValueError):
        pass
    today = _today()
    return f"{MONTH_FULL_LABELS[today.month - 1]} {today.year}"


def _percent_label(value: float) -> str:
    return f"{round(float(value or 0), 1)}%"



def get_revenue_spending_year_options(branch_id: Optional[int] = None) -> List[int]:
    """Return safe year options for the dashboard Revenue vs Spending filter.

    The query is read-only and defensive. It combines invoice years and
    cash/bank ledger years, then guarantees the current year exists so the chart
    filter never renders an empty select on a clean production database.
    """
    current_year = _today().year
    params = _branch_params(branch_id)

    invoice_year_expr = _year_sql("inv.invoice_date")
    spending_year_expr = _year_sql("cb.transaction_date")

    invoice_rows = _execute_rows(
        f"""
        SELECT DISTINCT {invoice_year_expr} AS year_value
        FROM invoices inv
        WHERE inv.invoice_date IS NOT NULL
          {_branch_where('inv', branch_id)}
        """,
        params,
    )
    spending_rows = _execute_rows(
        f"""
        SELECT DISTINCT {spending_year_expr} AS year_value
        FROM cash_bank_transactions cb
        WHERE cb.transaction_date IS NOT NULL
          {_branch_where('cb', branch_id)}
        """,
        params,
    )

    years = {current_year}
    for row in [*invoice_rows, *spending_rows]:
        year_value = _safe_year(row.get("year_value"))
        if 2000 <= year_value <= 2100:
            years.add(year_value)

    return sorted(years, reverse=True)


def _month_peak(monthly: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
    if not monthly:
        return {"label": "-", key: 0.0}
    return max(monthly, key=lambda row: _as_float(row.get(key)))


def get_revenue_spending_chart_data(
    branch_id: Optional[int] = None,
    year: Optional[Any] = None,
    include_asset_purchase: bool = False,
) -> Dict[str, Any]:
    """Return normalized monthly Revenue vs Spending payload.

    Revenue follows PRODUCTION contract: active invoice value by invoice_date.
    Spending follows PRODUCTION contract: cash/bank OUT operational spending by
    transaction_date, excluding opening balance, transfers, and asset purchases
    by default.
    """
    selected_year = _safe_year(year)
    start_date, end_date = _year_range(selected_year)
    params = {
        "start_date": start_date,
        "end_date": end_date,
        **_branch_params(branch_id),
    }

    invoice_month_expr = _date_bucket_sql("inv.invoice_date", "monthly")
    spending_month_expr = _date_bucket_sql("cb.transaction_date", "monthly")

    revenue_rows = _execute_rows(
        f"""
        SELECT
            {invoice_month_expr} AS month_key,
            SUM(COALESCE(inv.total_amount, 0)) AS total_amount
        FROM invoices inv
        WHERE inv.invoice_date >= :start_date
          AND inv.invoice_date < :end_date
          AND COALESCE(UPPER(inv.status), '') NOT IN ('CANCELLED', 'CANCELED')
          {_branch_where('inv', branch_id)}
        GROUP BY {invoice_month_expr}
        ORDER BY month_key ASC
        """,
        params,
    )

    excluded_references = _spending_exclusions(include_asset_purchase)
    excluded_sql = ", ".join(f"'{value}'" for value in excluded_references)

    spending_rows = _execute_rows(
        f"""
        SELECT
            {spending_month_expr} AS month_key,
            SUM(COALESCE(cb.amount, 0)) AS total_amount
        FROM cash_bank_transactions cb
        WHERE cb.transaction_date >= :start_date
          AND cb.transaction_date < :end_date
          AND UPPER(COALESCE(cb.transaction_type, '')) = 'OUT'
          AND (
              cb.reference_type IS NULL
              OR UPPER(cb.reference_type) NOT IN ({excluded_sql})
          )
          {_branch_where('cb', branch_id)}
        GROUP BY {spending_month_expr}
        ORDER BY month_key ASC
        """,
        params,
    )

    monthly = _monthly_base(selected_year)
    _fill_month_values(monthly, revenue_rows, "revenue")
    _fill_month_values(monthly, spending_rows, "spending")

    labels = [row["label"] for row in monthly]
    revenue_values = [row["revenue"] for row in monthly]
    spending_values = [row["spending"] for row in monthly]
    net_values = [row["net"] for row in monthly]

    total_revenue = sum(revenue_values)
    total_spending = sum(spending_values)
    net_total = total_revenue - total_spending
    max_value = max([0.0, *revenue_values, *spending_values])

    for row in monthly:
        revenue = _as_float(row.get("revenue"))
        spending = _as_float(row.get("spending"))
        row["revenue_percent"] = round((revenue / max_value) * 100, 2) if max_value > 0 else 0.0
        row["spending_percent"] = round((spending / max_value) * 100, 2) if max_value > 0 else 0.0
        row["net_tone"] = "positive" if row["net"] >= 0 else "negative"
        row["has_value"] = revenue > 0 or spending > 0

    best_revenue_month = _month_peak(monthly, "revenue")
    highest_spending_month = _month_peak(monthly, "spending")
    spending_ratio = round((total_spending / total_revenue) * 100, 2) if total_revenue > 0 else 0.0
    axis_steps = [
        round(max_value, 2),
        round(max_value * 0.75, 2),
        round(max_value * 0.5, 2),
        round(max_value * 0.25, 2),
        0.0,
    ]

    return {
        "key": "revenue_vs_spending",
        "chart_type": "bar",
        "title": "Revenue vs Spending",
        "subtitle": "Revenue Invoice Aktif dibanding Operational Spending.",
        "period": "monthly",
        "year": selected_year,
        "branch_id": branch_id,
        "include_asset_purchase": bool(include_asset_purchase),
        "available_years": get_revenue_spending_year_options(branch_id),
        "labels": labels,
        "months": monthly,
        "series": [
            {
                "key": "revenue",
                "label": "Revenue Invoice Aktif",
                "values": revenue_values,
                "total": total_revenue,
            },
            {
                "key": "spending",
                "label": "Operational Spending",
                "values": spending_values,
                "total": total_spending,
            },
        ],
        "totals": {
            "revenue": total_revenue,
            "spending": total_spending,
            "net": net_total,
        },
        "net_values": net_values,
        "max_value": max_value,
        "axis_steps": axis_steps,
        "spending_ratio": spending_ratio,
        "best_revenue_month": best_revenue_month,
        "highest_spending_month": highest_spending_month,
        "net_tone": "positive" if net_total >= 0 else "negative",
        "is_empty": max_value <= 0,
        "empty_title": "Belum ada data revenue/spending",
        "empty_message": "Chart akan terisi otomatis setelah invoice aktif dan transaksi kas/bank OUT tercatat.",
        "drilldown": {
            "revenue_endpoint": "finance.invoices",
            "spending_endpoint": "finance.cash_bank_ledger",
        },
        "chart_ui": {
            "version": "PRODUCTION",
            "filter_param_year": "analytics_year",
            "filter_param_assets": "include_asset_purchase",
            "bar_mode": "grouped_monthly",
            "read_only": True,
        },
        "data_contract": {
            "revenue_source": "invoices.total_amount grouped by invoices.invoice_date",
            "spending_source": "cash_bank_transactions.amount where transaction_type=OUT",
            "spending_excludes": list(excluded_references),
            "status_excludes": list(CANCELLED_STATUSES),
            "read_only": True,
        },
    }


def _parse_datetime(value: Optional[Any]) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    text_value = str(value).strip()
    if not text_value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text_value[:26], fmt)
        except ValueError:
            continue
    return None


def _classify_efficiency_row(row: Dict[str, Any], today_iso: str) -> str:
    delivery_status = str(row.get("delivery_status") or "").upper()
    delivery_date = _normalize_date(row.get("delivery_date"))
    has_receipt = bool(row.get("receipt_id"))
    planned_qty = _as_int(row.get("planned_qty"))
    delivered_qty = _as_int(row.get("delivered_qty"))
    shortage_qty = _as_int(row.get("shortage_qty"))
    target_arrival = _parse_datetime(row.get("target_arrival_time"))
    receive_time = _parse_datetime(row.get("receive_time"))
    tolerance_minutes = _as_int(row.get("late_tolerance_minutes") or 15)

    if shortage_qty > 0 or (has_receipt and delivered_qty < planned_qty):
        return "issue_shortage"

    if has_receipt:
        if target_arrival and receive_time:
            late_limit = target_arrival + timedelta(minutes=tolerance_minutes)
            return "late" if receive_time > late_limit else "on_time"
        return "on_time"

    if delivery_status == "DELIVERED":
        return "issue_shortage"

    if target_arrival:
        late_limit = target_arrival + timedelta(minutes=tolerance_minutes)
        if datetime.utcnow() > late_limit:
            return "late"

    if delivery_date and delivery_date < today_iso and delivery_status not in {"DELIVERED", "CANCELLED", "CANCELED"}:
        return "late"

    return "issue_shortage"


def get_operational_efficiency_chart_data(
    branch_id: Optional[int] = None,
    start_date: Optional[Any] = None,
    end_date: Optional[Any] = None,
) -> Dict[str, Any]:
    """Return Operational Efficiency donut data for deliveries.

    PRODUCTION upgrades the chart to hour-level SLA accuracy when target arrival
    and tolerance columns are available. It still falls back safely for legacy
    rows that have only delivery_date and receive_time.
    """
    today = _today()
    normalized_start = _normalize_date(start_date)
    normalized_end = _normalize_date(end_date)

    if not normalized_start or not normalized_end:
        normalized_start, normalized_end = _month_range(today.year, today.month)

    params = {
        "start_date": normalized_start,
        "end_date": normalized_end,
        **_branch_params(branch_id),
    }

    rows = _execute_rows(
        f"""
        SELECT
            d.id AS delivery_id,
            d.delivery_date AS delivery_date,
            d.status AS delivery_status,
            d.target_arrival_time AS target_arrival_time,
            d.late_tolerance_minutes AS late_tolerance_minutes,
            dd.id AS delivery_detail_id,
            COALESCE(dd.planned_qty, 0) AS planned_qty,
            COALESCE(dd.delivered_qty, 0) AS delivered_qty,
            COALESCE(dd.shortage_qty, 0) AS shortage_qty,
            dr.id AS receipt_id,
            dr.receive_time AS receive_time
        FROM delivery_details dd
        JOIN deliveries d ON d.id = dd.delivery_id
        LEFT JOIN delivery_receipts dr ON dr.delivery_detail_id = dd.id
        WHERE d.delivery_date >= :start_date
          AND d.delivery_date < :end_date
          AND COALESCE(UPPER(d.status), '') NOT IN ('CANCELLED', 'CANCELED')
          {_branch_where('d', branch_id)}
        ORDER BY d.delivery_date ASC, d.id ASC, dd.id ASC
        """,
        params,
    )

    counts = {
        "on_time": 0,
        "late": 0,
        "issue_shortage": 0,
    }
    planned_total = 0
    delivered_total = 0
    shortage_total = 0

    today_iso = today.isoformat()
    for row in rows:
        category = _classify_efficiency_row(row, today_iso)
        counts[category] += 1
        planned_total += _as_int(row.get("planned_qty"))
        delivered_total += _as_int(row.get("delivered_qty"))
        shortage_total += _as_int(row.get("shortage_qty"))

    total = sum(counts.values())

    def _percent(value: int) -> float:
        if total <= 0:
            return 0.0
        return round((value / total) * 100, 2)

    ok_rate = _percent(counts["on_time"])
    late_rate = _percent(counts["late"])
    issue_rate = _percent(counts["issue_shortage"])
    late_stop = round(ok_rate + late_rate, 2)
    fulfillment_rate = round((delivered_total / planned_total) * 100, 2) if planned_total > 0 else 0.0
    shortage_rate = round((shortage_total / planned_total) * 100, 2) if planned_total > 0 else 0.0

    segment_specs = [
        (
            "on_time",
            "On Time / OK",
            "OK",
            "success",
            counts["on_time"],
            ok_rate,
            "Bukti terima aman dan jumlah terkirim sesuai rencana.",
        ),
        (
            "late",
            "Late",
            "Late",
            "warning",
            counts["late"],
            late_rate,
            "Delivery melewati target jam tiba + toleransi SLA atau belum diterima setelah batas SLA.",
        ),
        (
            "issue_shortage",
            "Issue / Shortage",
            "Issue",
            "danger",
            counts["issue_shortage"],
            issue_rate,
            "Ada shortage, mismatch jumlah, atau bukti terima belum lengkap.",
        ),
    ]

    segments = [
        {
            "key": key,
            "label": label,
            "short_label": short_label,
            "tone": tone,
            "count": count,
            "percent": percent,
            "percent_label": _percent_label(percent),
            "count_label": f"{count} data",
            "description": description,
            "endpoint": "delivery.history",
            "filter": key,
        }
        for key, label, short_label, tone, count, percent, description in segment_specs
    ]

    dominant_segment = max(segments, key=lambda item: _as_float(item.get("percent"))) if segments else None
    period_label = _period_label_from_date(normalized_start)

    return {
        "key": "operational_efficiency",
        "chart_type": "donut",
        "title": "Operational Efficiency",
        "subtitle": "Kesehatan pengiriman berdasarkan target jam tiba, bukti terima, toleransi SLA, dan shortage.",
        "period": {
            "start_date": normalized_start,
            "end_date": normalized_end,
            "label": period_label,
        },
        "period_label": period_label,
        "branch_id": branch_id,
        "segments": segments,
        "counts": counts,
        "total": total,
        "ok_rate": ok_rate,
        "late_rate": late_rate,
        "issue_rate": issue_rate,
        "fulfillment_rate": fulfillment_rate,
        "shortage_rate": shortage_rate,
        "dominant_segment": dominant_segment,
        "totals": {
            "delivery_details": total,
            "planned_qty": planned_total,
            "delivered_qty": delivered_total,
            "shortage_qty": shortage_total,
        },
        "donut_style": {
            "on_time_percent": ok_rate,
            "late_percent": late_rate,
            "issue_percent": issue_rate,
            "late_stop_percent": late_stop,
        },
        "is_empty": total <= 0,
        "empty_title": "Belum ada data pengiriman",
        "empty_message": "Chart akan terisi setelah delivery detail dan bukti terima mulai tercatat.",
        "chart_ui": {
            "version": "PRODUCTION",
            "filter_param_month": "analytics_month",
            "donut_mode": "three_segment_operational_health",
            "read_only": True,
        },
        "data_contract": {
            "source": "deliveries + delivery_details + delivery_receipts",
            "status_excludes": list(CANCELLED_STATUSES),
            "accuracy_note": "PRODUCTION membaca on-time/late dari target_arrival_time + late_tolerance_minutes; fallback tanggal hanya untuk data legacy yang belum lengkap.",
            "read_only": True,
        },
    }


def get_owner_admin_analytics_data(
    branch_id: Optional[int] = None,
    role: str = "OWNER",
    period: str = "monthly",
    year: Optional[Any] = None,
    month: Optional[Any] = None,
    include_asset_purchase: bool = False,
    revenue_period: Optional[Any] = None,
    revenue_start_date: Optional[Any] = None,
    revenue_end_date: Optional[Any] = None,
    revenue_group_by: Optional[Any] = None,
    revenue_source: Optional[Any] = None,
    revenue_client_id: Optional[Any] = None,
    revenue_mandor_id: Optional[Any] = None,
    revenue_branch_id: Optional[Any] = None,
) -> Dict[str, Any]:
    """Combined Owner/Admin analytics payload for dashboard chart UI.

    OWNER calls this with branch_id=None. ADMIN calls this with the user's
    current branch_id. The service only prepares read-only data.
    """
    selected_year = _safe_year(year)
    selected_month = _safe_month(month)
    efficiency_start, efficiency_end = _month_range(selected_year, selected_month)

    revenue_spending = get_revenue_spending_chart_data(
        branch_id=branch_id,
        year=selected_year,
        include_asset_purchase=include_asset_purchase,
    )
    operational_efficiency = get_operational_efficiency_chart_data(
        branch_id=branch_id,
        start_date=efficiency_start,
        end_date=efficiency_end,
    )
    revenue_explorer = get_revenue_explorer_data(
        branch_id=branch_id,
        role=role,
        period_preset=revenue_period,
        start_date=revenue_start_date,
        end_date=revenue_end_date,
        group_by=revenue_group_by,
        source=revenue_source,
        client_id=revenue_client_id,
        mandor_id=revenue_mandor_id,
        selected_branch_id=revenue_branch_id,
    )

    source_counts = {
        "invoices": _as_int(_execute_scalar("SELECT COUNT(*) FROM invoices", default=0)),
        "cash_bank_transactions": _as_int(_execute_scalar("SELECT COUNT(*) FROM cash_bank_transactions", default=0)),
        "deliveries": _as_int(_execute_scalar("SELECT COUNT(*) FROM deliveries", default=0)),
        "delivery_details": _as_int(_execute_scalar("SELECT COUNT(*) FROM delivery_details", default=0)),
        "delivery_receipts": _as_int(_execute_scalar("SELECT COUNT(*) FROM delivery_receipts", default=0)),
    }

    role_scope = "OWNER_ALL_BRANCH" if branch_id is None else "ADMIN_BRANCH"
    placement_key = "owner_after_finance_operational_kpi" if branch_id is None else "admin_after_today_priority_strip"

    return {
        "key": "owner_admin_analytics",
        "role_scope": role_scope,
        "role_access": {
            "allowed_roles": ["OWNER", "ADMIN"],
            "owner_scope": "all branches",
            "admin_scope": "current branch only",
            "read_only": True,
        },
        "placement": {
            "key": placement_key,
            "owner": "Setelah KPI operasional utama dan sebelum section monitoring/detail panjang.",
            "admin": "Setelah Ringkasan Hari Ini + Priority Strip dan sebelum Akses Cepat Utama.",
        },
        "branch_id": branch_id,
        "period": str(period or "monthly"),
        "year": selected_year,
        "month": selected_month,
        "month_label": f"{MONTH_FULL_LABELS[selected_month - 1]} {selected_year}",
        "available_months": get_analytics_month_options(),
        "include_asset_purchase": bool(include_asset_purchase),
        "revenue_explorer": revenue_explorer,
        "revenue_spending": revenue_spending,
        "operational_efficiency": operational_efficiency,
        "source_counts": source_counts,
        "is_empty": revenue_explorer["is_empty"] and revenue_spending["is_empty"] and operational_efficiency["is_empty"],
        "read_only": True,
        "empty_message": "Belum ada transaksi utama. Analytics siap tampil sebagai empty state tanpa dummy data.",
    }
