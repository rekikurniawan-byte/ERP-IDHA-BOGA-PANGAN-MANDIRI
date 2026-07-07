from collections import OrderedDict
from datetime import date, datetime

from app.extensions import db
from app.models.logistics import StockMovement
from app.models.operational import (
    OrderHppStockConsumption,
    OrderHppStockConsumptionLine,
)
from app.services.hpp_service import find_unit_multiplier, normalize_unit
from app.services.stock_service import get_item_stock, get_item_stock_for_update, is_integer_unit
from app.services.business_logic_guard_service import validate_stock_movement_guard


FOOD_COMPONENT_TYPE = "FOOD"


def _to_float(value, default=0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


def _meal_label(meal_type):
    labels = {
        "LUNCH": "Siang",
        "DINNER": "Sore",
        "CUSTOM": "Custom",
    }
    return labels.get((meal_type or "").upper(), meal_type or "-")


def _status_payload(status, label, badge_class, message):
    return {
        "status": status,
        "label": label,
        "badge_class": badge_class,
        "message": message,
    }


def _get_conversion_multiplier(branch_id, unit_from, unit_to):
    unit_from = normalize_unit(unit_from)
    unit_to = normalize_unit(unit_to)

    if not unit_from or not unit_to:
        return None

    return find_unit_multiplier(branch_id, unit_from, unit_to)


def _new_item_row(component, item):
    return {
        "item": item,
        "item_id": item.id if item else component.item_id,
        "item_code": item.item_code if item else component.item_code_snapshot,
        "item_name": item.item_name if item else component.item_name_snapshot,
        "item_unit": item.unit if item else None,
        "is_active": bool(item.is_active) if item else False,
        "is_stock_tracked": bool(item.is_stock_tracked) if item else False,
        "required_base_qty": 0,
        "required_stock_qty": 0,
        "current_stock_qty": 0,
        "shortage_qty": 0,
        "estimated_cost_total": 0,
        "base_units": OrderedDict(),
        "component_count": 0,
        "components": [],
        "warnings": [],
        "blocking_errors": [],
        "status": "OK",
        "status_label": "CUKUP",
        "status_badge": "status-locked",
        "status_message": "Stok cukup untuk kebutuhan snapshot ini.",
    }


def _add_row_warning(row, code, message, blocking=True):
    row["warnings"].append(message)
    if blocking:
        row["blocking_errors"].append(code)


def build_hpp_stock_consumption_dry_run(snapshot):
    """
    Membaca snapshot HPP dan membuat simulasi pemakaian stok bahan.

    Fungsi ini sengaja read-only:
    - tidak membuat StockMovement,
    - tidak commit database,
    - tidak mengubah snapshot/order/jurnal/invoice.
    """
    rows_by_item = OrderedDict()
    skipped_components = []
    food_component_count = 0
    estimated_food_cost_total = 0

    for line in snapshot.lines:
        for component in line.components:
            if (component.component_type or "").upper() != FOOD_COMPONENT_TYPE:
                continue

            food_component_count += 1
            estimated_food_cost_total += _to_float(component.cost_total)

            meal_type = line.meal_type or "-"
            component_detail = {
                "meal_type": meal_type,
                "meal_label": _meal_label(meal_type),
                "menu_name": line.menu_name_snapshot or "-",
                "component": component,
                "base_qty_total": _to_float(component.base_qty_total),
                "base_unit": normalize_unit(component.base_unit),
                "recipe_unit": normalize_unit(component.recipe_unit),
                "cost_total": _to_float(component.cost_total),
                "required_stock_qty": 0,
                "conversion_multiplier_to_stock_unit": None,
                "status": "PENDING",
                "message": "",
            }

            item = component.item
            if not item:
                component_detail["status"] = "MISSING_ITEM"
                component_detail["message"] = "Item bahan tidak ditemukan di master item."
                skipped_components.append(component_detail)
                continue

            row = rows_by_item.get(item.id)
            if not row:
                row = _new_item_row(component, item)
                rows_by_item[item.id] = row

            row["component_count"] += 1
            row["estimated_cost_total"] += _to_float(component.cost_total)
            row["required_base_qty"] += _to_float(component.base_qty_total)
            base_unit = normalize_unit(component.base_unit)
            row["base_units"][base_unit or "-"] = row["base_units"].get(base_unit or "-", 0) + _to_float(component.base_qty_total)

            if not item.is_active:
                component_detail["status"] = "ITEM_INACTIVE"
                component_detail["message"] = "Item tidak aktif. Dry-run tidak bisa dianggap siap commit."
                _add_row_warning(row, "ITEM_INACTIVE", f"{item.item_name} tidak aktif.")
                row["components"].append(component_detail)
                continue

            if not item.is_stock_tracked:
                component_detail["status"] = "NOT_STOCK_TRACKED"
                component_detail["message"] = "Item tidak dilacak stoknya. Tidak bisa dibuat pemakaian stok otomatis."
                _add_row_warning(row, "NOT_STOCK_TRACKED", f"{item.item_name} tidak dilacak stoknya.")
                row["components"].append(component_detail)
                continue

            if _to_float(component.base_qty_total) <= 0:
                component_detail["status"] = "INVALID_QTY"
                component_detail["message"] = "Qty kebutuhan bahan dari snapshot tidak valid."
                _add_row_warning(row, "INVALID_QTY", f"Qty kebutuhan {item.item_name} tidak valid.")
                row["components"].append(component_detail)
                continue

            unit_from = normalize_unit(component.base_unit or component.recipe_unit or item.unit)
            unit_to = normalize_unit(item.unit)
            multiplier = _get_conversion_multiplier(snapshot.branch_id, unit_from, unit_to)

            if multiplier is None:
                component_detail["status"] = "MISSING_CONVERSION"
                component_detail["message"] = f"Butuh konversi {unit_from or '-'} ke {unit_to or '-'} untuk dibandingkan dengan stok."
                _add_row_warning(
                    row,
                    "MISSING_CONVERSION",
                    f"Konversi {unit_from or '-'} ke {unit_to or '-'} belum ada untuk {item.item_name}.",
                )
                row["components"].append(component_detail)
                continue

            required_stock_qty = _to_float(component.base_qty_total) * float(multiplier or 0)
            component_detail["required_stock_qty"] = required_stock_qty
            component_detail["conversion_multiplier_to_stock_unit"] = multiplier
            component_detail["status"] = "OK"
            component_detail["message"] = "Siap dihitung sebagai kebutuhan stok."
            row["required_stock_qty"] += required_stock_qty
            row["components"].append(component_detail)

    shortage_count = 0
    blocking_count = 0
    ready_count = 0
    warning_count = 0
    total_required_stock_qty = 0
    total_current_stock_qty = 0

    for row in rows_by_item.values():
        item = row["item"]
        if item and row["is_stock_tracked"]:
            row["current_stock_qty"] = get_item_stock(snapshot.branch_id, item.id)

        if (
            item
            and row["is_stock_tracked"]
            and _to_float(row["required_stock_qty"]) > 0
            and is_integer_unit(item.unit)
            and not float(_to_float(row["required_stock_qty"])).is_integer()
        ):
            _add_row_warning(
                row,
                "INVALID_INTEGER_STOCK_QTY",
                f"Qty pemakaian {item.item_name} harus bulat karena satuan stoknya {item.unit}.",
            )

        row["shortage_qty"] = max(_to_float(row["required_stock_qty"]) - _to_float(row["current_stock_qty"]), 0)
        total_required_stock_qty += _to_float(row["required_stock_qty"])
        total_current_stock_qty += _to_float(row["current_stock_qty"])

        if row["blocking_errors"]:
            blocking_count += 1
            warning_count += 1
            row.update(_status_payload(
                "BLOCKED",
                "BUTUH CEK",
                "status-progress",
                "Ada data bahan/konversi yang belum lengkap. Jangan commit pemakaian stok sebelum diperbaiki.",
            ))
            continue

        if row["shortage_qty"] > 0:
            shortage_count += 1
            row.update(_status_payload(
                "SHORTAGE",
                "STOK KURANG",
                "status-cancelled",
                "Stok belum cukup untuk kebutuhan snapshot ini.",
            ))
            continue

        ready_count += 1
        row.update(_status_payload(
            "OK",
            "CUKUP",
            "status-locked",
            "Stok cukup untuk kebutuhan snapshot ini.",
        ))

    skipped_count = len(skipped_components)
    blocking_count += skipped_count
    warning_count += skipped_count

    rows = list(rows_by_item.values())
    is_ready_for_commit = bool(rows) and shortage_count == 0 and blocking_count == 0

    return {
        "snapshot": snapshot,
        "rows": rows,
        "skipped_components": skipped_components,
        "summary": {
            "food_component_count": food_component_count,
            "item_count": len(rows),
            "ready_count": ready_count,
            "shortage_count": shortage_count,
            "warning_count": warning_count,
            "blocking_count": blocking_count,
            "skipped_count": skipped_count,
            "estimated_food_cost_total": estimated_food_cost_total,
            "total_required_stock_qty": total_required_stock_qty,
            "total_current_stock_qty": total_current_stock_qty,
            "is_ready_for_commit": is_ready_for_commit,
        },
    }


def get_existing_stock_consumption(snapshot_id):
    return OrderHppStockConsumption.query.filter_by(snapshot_id=snapshot_id).first()


def _parse_consumption_date(value):
    if not value:
        return date.today()

    if isinstance(value, date):
        return value

    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _generate_consumption_number(branch_id, consumption_date):
    prefix = f"HPP-STK-{consumption_date.strftime('%Y%m%d')}"
    last = (
        OrderHppStockConsumption.query.filter(
            OrderHppStockConsumption.branch_id == branch_id,
            OrderHppStockConsumption.consumption_number.like(f"{prefix}-%"),
        )
        .order_by(OrderHppStockConsumption.id.desc())
        .first()
    )

    next_seq = 1
    if last and last.consumption_number:
        try:
            next_seq = int(last.consumption_number.rsplit("-", 1)[-1]) + 1
        except (TypeError, ValueError):
            next_seq = 1

    return f"{prefix}-{next_seq:04d}"


def commit_hpp_stock_consumption(snapshot, committed_by, consumption_date=None, notes=None):
    """
    Commit pemakaian stok dari snapshot HPP.

    Guard utama:
    - satu snapshot hanya boleh punya satu stock consumption,
    - wajib lolos dry-run,
    - membuat StockMovement OUT per item agregat,
    - tidak membuat jurnal/invoice/order mutation.
    """
    if not snapshot:
        return False, "Snapshot HPP tidak ditemukan.", None

    if (snapshot.status or "").upper() not in ["LOCKED", "COMMITTED"]:
        return False, "Snapshot HPP belum LOCKED, tidak bisa commit pemakaian stok.", None

    existing = get_existing_stock_consumption(snapshot.id)
    if existing:
        return False, "Snapshot HPP ini sudah pernah di-commit ke pemakaian stok. Proses diblok agar stok tidak terpotong dobel.", existing

    parsed_date = _parse_consumption_date(consumption_date)
    if not parsed_date:
        return False, "Tanggal pemakaian stok tidak valid.", None

    dry_run = build_hpp_stock_consumption_dry_run(snapshot)
    if not dry_run["summary"].get("is_ready_for_commit"):
        return False, "Dry-run belum siap commit. Periksa stok, item, dan konversi satuan terlebih dulu.", None

    try:
        consumption = OrderHppStockConsumption(
            branch_id=snapshot.branch_id,
            daily_order_id=snapshot.daily_order_id,
            snapshot_id=snapshot.id,
            consumption_number=_generate_consumption_number(snapshot.branch_id, parsed_date),
            consumption_date=parsed_date,
            status="COMMITTED",
            total_item_count=0,
            total_required_qty=0,
            total_cost=0,
            notes=notes,
            committed_by=committed_by,
            committed_at=datetime.utcnow(),
        )
        db.session.add(consumption)
        db.session.flush()

        total_item_count = 0
        total_required_qty = 0
        total_cost = 0

        for row in dry_run["rows"]:
            item = row.get("item")
            if not item:
                db.session.rollback()
                return False, "Ada item bahan yang tidak ditemukan. Commit dibatalkan.", None

            qty = _to_float(row.get("required_stock_qty"))
            if qty <= 0:
                db.session.rollback()
                return False, f"Qty pemakaian {item.item_name} tidak valid. Commit dibatalkan.", None

            if is_integer_unit(item.unit) and not float(qty).is_integer():
                db.session.rollback()
                return False, f"Qty pemakaian {item.item_name} harus bulat karena satuannya {item.unit}. Commit dibatalkan.", None

            current_stock = get_item_stock_for_update(snapshot.branch_id, item.id)
            if qty > current_stock:
                db.session.rollback()
                return False, f"Stok {item.item_name} tidak cukup. Stok saat ini {current_stock:g} {item.unit}, kebutuhan {qty:g} {item.unit}.", None

            try:
                validate_stock_movement_guard(
                    "OUT",
                    qty,
                    current_stock=current_stock,
                    item_unit=item.unit,
                    is_integer_unit=is_integer_unit(item.unit),
                )
            except Exception as error:
                db.session.rollback()
                return False, str(error), None

            movement = StockMovement(
                branch_id=snapshot.branch_id,
                item_id=item.id,
                movement_date=parsed_date,
                movement_type="OUT",
                reference_type="HPP_SNAPSHOT_CONSUMPTION",
                reference_id=consumption.id,
                qty=qty,
                notes=f"Pemakaian bahan dari snapshot HPP {snapshot.snapshot_number} untuk order {snapshot.daily_order.order_number if snapshot.daily_order else snapshot.daily_order_id}",
                created_by=committed_by,
            )
            db.session.add(movement)
            db.session.flush()

            stock_after = current_stock - qty
            line = OrderHppStockConsumptionLine(
                consumption_id=consumption.id,
                item_id=item.id,
                stock_movement_id=movement.id,
                item_code_snapshot=row.get("item_code"),
                item_name_snapshot=row.get("item_name"),
                stock_unit_snapshot=item.unit,
                required_stock_qty=qty,
                stock_before_qty=current_stock,
                stock_after_qty=stock_after,
                estimated_cost_total=_to_float(row.get("estimated_cost_total")),
                component_count=int(row.get("component_count") or 0),
                notes="; ".join(row.get("warnings") or []) or None,
            )
            db.session.add(line)

            total_item_count += 1
            total_required_qty += qty
            total_cost += _to_float(row.get("estimated_cost_total"))

        consumption.total_item_count = total_item_count
        consumption.total_required_qty = total_required_qty
        consumption.total_cost = total_cost

        db.session.commit()
        return True, "Pemakaian stok dari snapshot HPP berhasil di-commit. StockMovement OUT sudah dibuat.", consumption

    except Exception as exc:
        db.session.rollback()
        return False, f"Commit pemakaian stok gagal: {exc}", None
