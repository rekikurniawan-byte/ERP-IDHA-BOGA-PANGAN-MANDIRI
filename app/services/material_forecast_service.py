from collections import OrderedDict
from datetime import date, timedelta

from app.utils.clock import today_wib

from app.models.operational import DailyOrder
from app.models.master import ItemCostProfile
from app.services.hpp_service import find_unit_multiplier, normalize_unit
from app.services.stock_service import get_item_stock, is_integer_unit


MEAL_CONFIG = {
    "LUNCH": {
        "label": "Siang",
        "menu_attr": "lunch_menu",
        "qty_attr": "lunch_qty",
    },
    "DINNER": {
        "label": "Sore",
        "menu_attr": "dinner_menu",
        "qty_attr": "dinner_qty",
    },
}


def _to_float(value, default=0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


def _status_payload(status, label, badge_class, message):
    return {
        "status": status,
        "status_label": label,
        "status_badge": badge_class,
        "status_message": message,
    }


def _new_item_row(item):
    return {
        "item": item,
        "item_id": item.id if item else None,
        "item_code": item.item_code if item else "-",
        "item_name": item.item_name if item else "Item tidak ditemukan",
        "item_unit": item.unit if item else "-",
        "current_stock_qty": 0,
        "required_stock_qty": 0,
        "shortage_qty": 0,
        "estimated_cost_total": 0,
        "menu_count": 0,
        "order_count": 0,
        "component_count": 0,
        "base_units": OrderedDict(),
        "details": [],
        "warnings": [],
        "blocking_errors": [],
        **_status_payload("OK", "CUKUP", "status-locked", "Stok cukup untuk kebutuhan order pada periode ini."),
    }


def _append_warning(container, message):
    if message and message not in container:
        container.append(message)


def _append_blocking(row, code, message):
    _append_warning(row["warnings"], message)
    if code not in row["blocking_errors"]:
        row["blocking_errors"].append(code)


def _safe_order_status(order):
    if getattr(order, "is_locked", False):
        return "LOCKED"
    return order.status or "DRAFT"


def _order_total_for_meal(order, meal_type):
    cfg = MEAL_CONFIG[meal_type]
    qty_attr = cfg["qty_attr"]
    return sum(_to_float(getattr(detail, qty_attr, 0)) for detail in order.details)


def _estimate_cost(branch_id, recipe_item, portion_qty):
    item = recipe_item.item
    if not item:
        return 0, "Item bahan tidak ditemukan."

    profile = ItemCostProfile.query.filter_by(
        branch_id=branch_id,
        item_id=item.id,
    ).first()

    if not profile:
        return 0, f"Profil HPP belum ada untuk {item.item_name}."

    multiplier = find_unit_multiplier(branch_id, recipe_item.unit, profile.base_unit)
    if multiplier is None:
        return 0, f"Konversi {normalize_unit(recipe_item.unit) or '-'} ke {normalize_unit(profile.base_unit) or '-'} belum ada untuk estimasi biaya {item.item_name}."

    base_qty_total = _to_float(recipe_item.qty_per_portion) * float(multiplier or 0) * portion_qty
    return base_qty_total * _to_float(profile.effective_cost_per_base_unit), ""


def _process_recipe_item(branch_id, rows_by_item, order, menu, recipe_item, meal_type, meal_label, portion_qty, order_warning_list):
    item = recipe_item.item
    if not item:
        _append_warning(order_warning_list, "Ada item resep yang sudah tidak ditemukan di master item.")
        return

    row = rows_by_item.get(item.id)
    if not row:
        row = _new_item_row(item)
        rows_by_item[item.id] = row

    row["component_count"] += 1
    row["order_count"] += 1
    row["menu_count"] += 1

    detail = {
        "order": order,
        "order_number": order.order_number,
        "order_date": order.order_date,
        "meal_type": meal_type,
        "meal_label": meal_label,
        "menu": menu,
        "menu_name": menu.menu_name if menu else "-",
        "portion_qty": portion_qty,
        "qty_per_portion": _to_float(recipe_item.qty_per_portion),
        "recipe_unit": normalize_unit(recipe_item.unit),
        "required_recipe_qty": _to_float(recipe_item.qty_per_portion) * portion_qty,
        "required_stock_qty": 0,
        "conversion_multiplier_to_stock_unit": None,
        "estimated_cost_total": 0,
        "status": "OK",
        "message": "Siap dihitung sebagai kebutuhan bahan.",
    }

    if _to_float(recipe_item.qty_per_portion) <= 0:
        detail["status"] = "INVALID_QTY"
        detail["message"] = "Qty per porsi pada resep belum valid."
        _append_blocking(row, "INVALID_QTY", f"Qty resep {item.item_name} belum valid.")
        _append_warning(order_warning_list, f"Qty resep {item.item_name} belum valid.")
        row["details"].append(detail)
        return

    if not item.is_active:
        detail["status"] = "ITEM_INACTIVE"
        detail["message"] = "Item bahan tidak aktif."
        _append_blocking(row, "ITEM_INACTIVE", f"{item.item_name} tidak aktif.")
        _append_warning(order_warning_list, f"{item.item_name} tidak aktif.")
        row["details"].append(detail)
        return

    if not item.is_stock_tracked:
        detail["status"] = "NOT_STOCK_TRACKED"
        detail["message"] = "Item tidak dilacak stoknya. Tidak bisa dihitung stok otomatis."
        _append_blocking(row, "NOT_STOCK_TRACKED", f"{item.item_name} tidak dilacak stoknya.")
        _append_warning(order_warning_list, f"{item.item_name} tidak dilacak stoknya.")
        row["details"].append(detail)
        return

    multiplier = find_unit_multiplier(branch_id, recipe_item.unit, item.unit)
    if multiplier is None:
        detail["status"] = "MISSING_CONVERSION"
        detail["message"] = f"Butuh konversi {normalize_unit(recipe_item.unit) or '-'} ke {normalize_unit(item.unit) or '-'} untuk dibandingkan dengan stok."
        _append_blocking(row, "MISSING_CONVERSION", f"Konversi {normalize_unit(recipe_item.unit) or '-'} ke {normalize_unit(item.unit) or '-'} belum ada untuk {item.item_name}.")
        _append_warning(order_warning_list, f"Konversi {normalize_unit(recipe_item.unit) or '-'} ke {normalize_unit(item.unit) or '-'} belum ada untuk {item.item_name}.")
        row["details"].append(detail)
        return

    required_stock_qty = detail["required_recipe_qty"] * float(multiplier or 0)
    detail["required_stock_qty"] = required_stock_qty
    detail["conversion_multiplier_to_stock_unit"] = multiplier
    row["required_stock_qty"] += required_stock_qty
    row["base_units"][detail["recipe_unit"] or "-"] = row["base_units"].get(detail["recipe_unit"] or "-", 0) + detail["required_recipe_qty"]

    if is_integer_unit(item.unit) and required_stock_qty > 0 and not float(required_stock_qty).is_integer():
        detail["status"] = "INVALID_INTEGER_QTY"
        detail["message"] = f"Satuan stok {item.unit} harus bulat."
        _append_blocking(row, "INVALID_INTEGER_QTY", f"Qty kebutuhan {item.item_name} harus bulat karena satuan stoknya {item.unit}.")
        _append_warning(order_warning_list, f"Qty kebutuhan {item.item_name} harus bulat karena satuan stoknya {item.unit}.")

    estimated_cost, cost_warning = _estimate_cost(branch_id, recipe_item, portion_qty)
    detail["estimated_cost_total"] = estimated_cost
    row["estimated_cost_total"] += estimated_cost
    if cost_warning:
        _append_warning(row["warnings"], cost_warning)
        _append_warning(order_warning_list, cost_warning)

    row["details"].append(detail)


def _process_meal(branch_id, rows_by_item, order, meal_type, order_row):
    cfg = MEAL_CONFIG[meal_type]
    meal_label = cfg["label"]
    portion_qty = _order_total_for_meal(order, meal_type)
    menu = getattr(order, cfg["menu_attr"], None)

    order_row[f"{meal_type.lower()}_qty"] = portion_qty
    order_row[f"{meal_type.lower()}_menu"] = menu

    if portion_qty <= 0:
        return

    if not menu:
        _append_warning(order_row["warnings"], f"Menu {meal_label.lower()} belum dipilih pada order {order.order_number}.")
        return

    recipe = menu.recipe
    if not recipe or not recipe.is_active or not recipe.items:
        _append_warning(order_row["warnings"], f"Menu {menu.menu_name} belum punya resep/BOM aktif.")
        return

    if getattr(recipe, "recipe_status", "DRAFT") != "FINAL":
        _append_warning(order_row["warnings"], f"Resep {menu.menu_name} masih DRAFT. Prediksi tetap dihitung, tapi belum final untuk dasar belanja.")

    for recipe_item in recipe.items:
        _process_recipe_item(
            branch_id=branch_id,
            rows_by_item=rows_by_item,
            order=order,
            menu=menu,
            recipe_item=recipe_item,
            meal_type=meal_type,
            meal_label=meal_label,
            portion_qty=portion_qty,
            order_warning_list=order_row["warnings"],
        )


def build_material_requirement_forecast(branch_id, date_from=None, date_to=None, status_filter="ALL"):
    """
    Prediksi kebutuhan bahan dari order + default menu + recipe/BOM.

    Read-only:
    - tidak membuat procurement,
    - tidak membuat stock movement,
    - tidak commit database,
    - tidak mengubah order/snapshot/jurnal/invoice.
    """
    today = today_wib()
    date_from = date_from or today
    date_to = date_to or (date_from + timedelta(days=6))
    if date_to < date_from:
        date_from, date_to = date_to, date_from

    status_filter = (status_filter or "ALL").upper()

    query = DailyOrder.query.filter(
        DailyOrder.branch_id == branch_id,
        DailyOrder.order_date >= date_from,
        DailyOrder.order_date <= date_to,
    )

    if status_filter == "LOCKED":
        query = query.filter(DailyOrder.is_locked == True)
    elif status_filter == "DRAFT":
        query = query.filter(DailyOrder.is_locked == False)
    elif status_filter not in ["ALL", "LOCKED", "DRAFT"]:
        query = query.filter(DailyOrder.status == status_filter)

    orders = query.order_by(DailyOrder.order_date.asc(), DailyOrder.id.asc()).all()

    rows_by_item = OrderedDict()
    order_rows = []

    for order in orders:
        order_row = {
            "order": order,
            "order_number": order.order_number,
            "order_date": order.order_date,
            "status": _safe_order_status(order),
            "lunch_qty": 0,
            "dinner_qty": 0,
            "total_qty": sum(_to_float(detail.total_qty) for detail in order.details),
            "lunch_menu": None,
            "dinner_menu": None,
            "warnings": [],
        }

        _process_meal(branch_id, rows_by_item, order, "LUNCH", order_row)
        _process_meal(branch_id, rows_by_item, order, "DINNER", order_row)
        order_rows.append(order_row)

    shortage_count = 0
    blocked_count = 0
    warning_count = 0
    ready_count = 0
    total_required_qty = 0
    total_current_stock_qty = 0
    total_shortage_qty = 0
    total_estimated_cost = 0

    item_rows = list(rows_by_item.values())
    for row in item_rows:
        item = row["item"]
        if item and item.is_stock_tracked:
            row["current_stock_qty"] = get_item_stock(branch_id, item.id)

        row["shortage_qty"] = max(_to_float(row["required_stock_qty"]) - _to_float(row["current_stock_qty"]), 0)

        total_required_qty += _to_float(row["required_stock_qty"])
        total_current_stock_qty += _to_float(row["current_stock_qty"])
        total_shortage_qty += _to_float(row["shortage_qty"])
        total_estimated_cost += _to_float(row["estimated_cost_total"])

        if row["blocking_errors"]:
            blocked_count += 1
            warning_count += 1
            row.update(_status_payload(
                "BLOCKED",
                "BUTUH CEK",
                "status-progress",
                "Data bahan/konversi belum lengkap. Prediksi belum siap dijadikan dasar belanja.",
            ))
        elif row["shortage_qty"] > 0:
            shortage_count += 1
            warning_count += 1
            row.update(_status_payload(
                "SHORTAGE",
                "KURANG",
                "status-cancelled",
                "Stok saat ini kurang dibanding kebutuhan periode ini.",
            ))
        else:
            ready_count += 1
            row.update(_status_payload(
                "OK",
                "CUKUP",
                "status-locked",
                "Stok cukup untuk kebutuhan periode ini.",
            ))

    item_rows.sort(key=lambda row: ({"BLOCKED": 0, "SHORTAGE": 1, "OK": 2}.get(row["status"], 9), row["item_name"]))

    order_warning_count = sum(1 for row in order_rows if row["warnings"])
    planned_portions = sum(_to_float(row["lunch_qty"]) + _to_float(row["dinner_qty"]) for row in order_rows)

    summary = {
        "order_count": len(order_rows),
        "locked_order_count": sum(1 for row in order_rows if row["status"] == "LOCKED"),
        "draft_order_count": sum(1 for row in order_rows if row["status"] != "LOCKED"),
        "planned_portions": planned_portions,
        "item_count": len(item_rows),
        "ready_count": ready_count,
        "warning_count": warning_count,
        "blocked_count": blocked_count,
        "shortage_count": shortage_count,
        "order_warning_count": order_warning_count,
        "total_required_qty": total_required_qty,
        "total_current_stock_qty": total_current_stock_qty,
        "total_shortage_qty": total_shortage_qty,
        "total_estimated_cost": total_estimated_cost,
    }

    overall_status = "AMAN"
    if blocked_count > 0:
        overall_status = "BUTUH CEK"
    elif shortage_count > 0 or order_warning_count > 0:
        overall_status = "WARNING"

    return {
        "date_from": date_from,
        "date_to": date_to,
        "status_filter": status_filter,
        "orders": order_rows,
        "items": item_rows,
        "summary": summary,
        "overall_status": overall_status,
    }
