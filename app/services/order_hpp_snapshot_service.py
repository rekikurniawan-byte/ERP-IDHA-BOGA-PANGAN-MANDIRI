from datetime import datetime

from app.extensions import db
from app.models.master import Menu, PackagingProfile, OverheadProfile
from app.models.operational import (
    OrderHppSnapshot,
    OrderHppSnapshotLine,
    OrderHppSnapshotComponent,
    OrderHppSnapshotAllocation,
)
from app.services.hpp_service import calculate_menu_hpp
from app.utils.terms import T


MEAL_LABELS = {
    "LUNCH": "Siang",
    "DINNER": "Sore",
}


def _to_float(value, default=0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return float(default)


def generate_snapshot_number(daily_order):
    now = datetime.utcnow()
    return f"HPP-{daily_order.id:06d}-{now.strftime('%Y%m%d%H%M%S%f')[:20]}"


def get_order_meal_summary(daily_order):
    lunch_qty = 0
    dinner_qty = 0
    lunch_revenue = 0
    dinner_revenue = 0

    for detail in daily_order.details:
        detail_lunch_qty = _to_float(detail.lunch_qty)
        detail_dinner_qty = _to_float(detail.dinner_qty)
        price_per_portion = _to_float(detail.price_per_portion)

        lunch_qty += detail_lunch_qty
        dinner_qty += detail_dinner_qty
        lunch_revenue += detail_lunch_qty * price_per_portion
        dinner_revenue += detail_dinner_qty * price_per_portion

    return {
        "LUNCH": {
            "label": MEAL_LABELS["LUNCH"],
            "portion_qty": lunch_qty,
            "revenue_total": lunch_revenue,
            "selling_price_per_portion": lunch_revenue / lunch_qty if lunch_qty > 0 else 0,
        },
        "DINNER": {
            "label": MEAL_LABELS["DINNER"],
            "portion_qty": dinner_qty,
            "revenue_total": dinner_revenue,
            "selling_price_per_portion": dinner_revenue / dinner_qty if dinner_qty > 0 else 0,
        },
    }


def get_active_hpp_master_data(branch_id):
    menus = Menu.query.filter_by(
        branch_id=branch_id,
        is_active=True,
    ).order_by(Menu.menu_name.asc()).all()

    packaging_profiles = PackagingProfile.query.filter_by(
        branch_id=branch_id,
        is_active=True,
    ).order_by(PackagingProfile.profile_name.asc()).all()

    overhead_profiles = OverheadProfile.query.filter_by(
        branch_id=branch_id,
        is_active=True,
    ).order_by(OverheadProfile.profile_name.asc()).all()

    return menus, packaging_profiles, overhead_profiles


def _get_optional_profile(model, profile_id, branch_id):
    if not profile_id:
        return None

    profile = model.query.get(int(profile_id))
    if not profile or profile.branch_id != branch_id or not profile.is_active:
        return None

    return profile


def _get_required_menu(menu_id, branch_id):
    if not menu_id:
        return None

    menu = Menu.query.get(int(menu_id))
    if not menu or menu.branch_id != branch_id or not menu.is_active:
        return None

    return menu


def _add_food_components(snapshot_line, calculation):
    for line in calculation.get("lines", []):
        item = line.get("item")
        profile = line.get("profile")

        component = OrderHppSnapshotComponent(
            snapshot_line=snapshot_line,
            component_type="FOOD",
            item_id=item.id if item else None,
            item_code_snapshot=item.item_code if item else None,
            item_name_snapshot=item.item_name if item else "Item tidak ditemukan",
            qty_per_portion=_to_float(line.get("qty_per_portion")),
            recipe_unit=line.get("recipe_unit"),
            base_unit=line.get("base_unit"),
            conversion_multiplier=line.get("conversion_multiplier"),
            base_qty_per_portion=_to_float(line.get("base_qty_per_portion")),
            base_qty_total=_to_float(line.get("base_qty_total")),
            cost_per_base_unit_snapshot=_to_float(line.get("cost_per_base_unit")),
            cost_per_portion=_to_float(line.get("cost_per_portion")),
            cost_total=_to_float(line.get("cost_total")),
            source_profile_id=profile.id if profile else None,
            notes=line.get("message") or line.get("status") or "",
        )
        db.session.add(component)


def _add_packaging_component(snapshot_line, calculation):
    packaging_profile = calculation.get("packaging_profile")
    if not packaging_profile:
        return

    component = OrderHppSnapshotComponent(
        snapshot_line=snapshot_line,
        component_type="PACKAGING",
        item_id=None,
        item_code_snapshot=None,
        item_name_snapshot=packaging_profile.profile_name,
        qty_per_portion=1,
        recipe_unit="PORSI",
        base_unit="PORSI",
        conversion_multiplier=1,
        base_qty_per_portion=1,
        base_qty_total=_to_float(calculation.get("portion_qty")),
        cost_per_base_unit_snapshot=_to_float(packaging_profile.cost_per_portion),
        cost_per_portion=_to_float(calculation.get("packaging_cost_per_portion")),
        cost_total=_to_float(calculation.get("packaging_cost_total")),
        source_profile_id=packaging_profile.id,
        notes="Snapshot biaya kemasan per porsi.",
    )
    db.session.add(component)


def _add_overhead_components(snapshot_line, calculation):
    overhead_profile = calculation.get("overhead_profile")
    if not overhead_profile:
        return

    portion_qty = _to_float(calculation.get("portion_qty"))
    overhead_parts = [
        ("Gas", overhead_profile.gas_cost_per_portion),
        ("Listrik", overhead_profile.electricity_cost_per_portion),
        ("Air", overhead_profile.water_cost_per_portion),
        ("Tenaga Kerja", overhead_profile.labor_cost_per_portion),
        ("Bumbu Umum", overhead_profile.spices_cost_per_portion),
        ("Overhead Lain", overhead_profile.other_cost_per_portion),
    ]

    for name, cost_per_portion in overhead_parts:
        cost_per_portion = _to_float(cost_per_portion)
        if cost_per_portion <= 0:
            continue

        component = OrderHppSnapshotComponent(
            snapshot_line=snapshot_line,
            component_type="OVERHEAD",
            item_id=None,
            item_code_snapshot=None,
            item_name_snapshot=name,
            qty_per_portion=1,
            recipe_unit="PORSI",
            base_unit="PORSI",
            conversion_multiplier=1,
            base_qty_per_portion=1,
            base_qty_total=portion_qty,
            cost_per_base_unit_snapshot=cost_per_portion,
            cost_per_portion=cost_per_portion,
            cost_total=cost_per_portion * portion_qty,
            source_profile_id=overhead_profile.id,
            notes="Snapshot overhead flat per porsi.",
        )
        db.session.add(component)

    percentage_cost_total = _to_float(calculation.get("overhead_percentage_cost_total"))
    if percentage_cost_total > 0:
        component = OrderHppSnapshotComponent(
            snapshot_line=snapshot_line,
            component_type="OVERHEAD",
            item_id=None,
            item_code_snapshot=None,
            item_name_snapshot="Overhead Persentase",
            qty_per_portion=1,
            recipe_unit="PORSI",
            base_unit="PORSI",
            conversion_multiplier=1,
            base_qty_per_portion=1,
            base_qty_total=portion_qty,
            cost_per_base_unit_snapshot=(percentage_cost_total / portion_qty if portion_qty > 0 else 0),
            cost_per_portion=(percentage_cost_total / portion_qty if portion_qty > 0 else 0),
            cost_total=percentage_cost_total,
            source_profile_id=overhead_profile.id,
            notes=f"{_to_float(overhead_profile.overhead_percentage)}% dari food cost + kemasan.",
        )
        db.session.add(component)


def _detail_meal_qty(detail, meal_type):
    if meal_type == "LUNCH":
        return _to_float(getattr(detail, "lunch_qty", 0))

    if meal_type == "DINNER":
        return _to_float(getattr(detail, "dinner_qty", 0))

    return 0


def _safe_name(record, *attrs):
    if not record:
        return None

    for attr in attrs:
        value = getattr(record, attr, None)
        if value:
            return str(value)

    return f"ID {getattr(record, 'id', '-')}"


def _create_snapshot_allocations(snapshot, daily_order):
    """
    Alokasi HPP snapshot ke detail order/mandor/lokasi.

    Prinsip aman:
    - allocation dibuat saat snapshot dibuat, jadi angka invoice/profit masa depan membaca angka beku,
    - biaya dialokasikan proporsional berdasarkan porsi per meal_type,
    - tidak mengubah invoice, order, stok, atau jurnal.
    """
    for line in snapshot.lines:
        line_portion_qty = _to_float(line.portion_qty)
        if line_portion_qty <= 0:
            continue

        for detail in daily_order.details:
            detail_portion_qty = _detail_meal_qty(detail, line.meal_type)
            if detail_portion_qty <= 0:
                continue

            allocation_ratio = detail_portion_qty / line_portion_qty
            selling_price = _to_float(getattr(detail, "price_per_portion", 0))
            revenue_total = detail_portion_qty * selling_price
            food_cost_total = _to_float(line.food_cost_total) * allocation_ratio
            packaging_cost_total = _to_float(line.packaging_cost_total) * allocation_ratio
            overhead_cost_total = _to_float(line.overhead_cost_total) * allocation_ratio
            hpp_total = _to_float(line.hpp_total) * allocation_ratio
            gross_margin_amount = revenue_total - hpp_total
            gross_margin_percentage = (
                (gross_margin_amount / revenue_total) * 100
                if revenue_total > 0 else 0
            )

            allocation = OrderHppSnapshotAllocation(
                snapshot_id=snapshot.id,
                snapshot_line_id=line.id,
                daily_order_detail_id=detail.id,
                mandor_id=detail.mandor_id,
                delivery_location_id=detail.delivery_location_id,
                source_type="ORDER_DETAIL",
                source_id=detail.id,
                meal_type=line.meal_type,
                allocation_method="PORTION_RATIO",
                allocation_ratio=allocation_ratio,
                mandor_name_snapshot=_safe_name(getattr(detail, "mandor", None), "name", "mandor_name", "full_name"),
                delivery_location_name_snapshot=_safe_name(getattr(detail, "delivery_location", None), "location_name", "name"),
                portion_qty=detail_portion_qty,
                selling_price_per_portion=selling_price,
                revenue_total=revenue_total,
                food_cost_allocated_total=food_cost_total,
                packaging_cost_allocated_total=packaging_cost_total,
                overhead_cost_allocated_total=overhead_cost_total,
                hpp_allocated_total=hpp_total,
                hpp_per_portion_snapshot=_to_float(line.hpp_per_portion),
                gross_margin_amount=gross_margin_amount,
                gross_margin_percentage=gross_margin_percentage,
                notes=f"Alokasi HPP snapshot per detail order/{T.sub_client_lower} untuk dasar profit invoice/report. Tidak mengubah invoice.",
            )
            db.session.add(allocation)


def _create_snapshot_line(snapshot, meal_type, menu, meal_data, packaging_profile, overhead_profile, calculation):
    warnings = calculation.get("warnings") or []
    snapshot_line = OrderHppSnapshotLine(
        snapshot=snapshot,
        meal_type=meal_type,
        menu_id=menu.id if menu else None,
        menu_code_snapshot=menu.menu_code if menu else None,
        menu_name_snapshot=menu.menu_name if menu else None,
        recipe_id=calculation.get("recipe").id if calculation.get("recipe") else None,
        recipe_name_snapshot=calculation.get("recipe").recipe_name if calculation.get("recipe") else None,
        packaging_profile_id=packaging_profile.id if packaging_profile else None,
        packaging_name_snapshot=packaging_profile.profile_name if packaging_profile else None,
        overhead_profile_id=overhead_profile.id if overhead_profile else None,
        overhead_name_snapshot=overhead_profile.profile_name if overhead_profile else None,
        portion_qty=_to_float(meal_data["portion_qty"]),
        selling_price_per_portion=_to_float(meal_data["selling_price_per_portion"]),
        food_cost_total=_to_float(calculation.get("food_cost_total")),
        packaging_cost_total=_to_float(calculation.get("packaging_cost_total")),
        overhead_cost_total=_to_float(calculation.get("overhead_cost_total")),
        hpp_total=_to_float(calculation.get("hpp_total")),
        hpp_per_portion=_to_float(calculation.get("hpp_per_portion")),
        revenue_total=_to_float(calculation.get("revenue_total")),
        gross_margin_amount=_to_float(calculation.get("gross_margin_amount")),
        gross_margin_percentage=_to_float(calculation.get("gross_margin_percentage")),
        calculation_status="COMPLETE" if calculation.get("is_complete") else "WARNING",
        warning_text="; ".join(warnings),
    )
    db.session.add(snapshot_line)
    db.session.flush()

    _add_food_components(snapshot_line, calculation)
    _add_packaging_component(snapshot_line, calculation)
    _add_overhead_components(snapshot_line, calculation)

    return snapshot_line


def create_order_hpp_snapshot(daily_order, form_data, created_by):
    if not daily_order.is_locked:
        return False, "Snapshot HPP hanya boleh dibuat dari order yang sudah LOCKED.", None

    branch_id = daily_order.branch_id
    target_margin_percentage = _to_float(form_data.get("target_margin_percentage"), 30)
    notes = form_data.get("notes") or ""

    packaging_profile = _get_optional_profile(
        PackagingProfile,
        form_data.get("packaging_profile_id"),
        branch_id,
    )
    overhead_profile = _get_optional_profile(
        OverheadProfile,
        form_data.get("overhead_profile_id"),
        branch_id,
    )

    meal_summary = get_order_meal_summary(daily_order)
    requested_lines = []

    for meal_type in ["LUNCH", "DINNER"]:
        meal_data = meal_summary[meal_type]
        if meal_data["portion_qty"] <= 0:
            continue

        menu = _get_required_menu(form_data.get(f"{meal_type.lower()}_menu_id"), branch_id)
        if not menu:
            return False, f"Menu {meal_data['label']} wajib dipilih untuk order yang punya porsi {meal_data['label'].lower()}.", None

        requested_lines.append((meal_type, menu, meal_data))

    if not requested_lines:
        return False, "Order tidak punya porsi siang atau sore untuk dibuat snapshot HPP.", None

    calculated_lines = []
    incomplete_messages = []

    for meal_type, menu, meal_data in requested_lines:
        calculation = calculate_menu_hpp(
            menu=menu,
            portion_qty=meal_data["portion_qty"],
            selling_price_per_portion=meal_data["selling_price_per_portion"],
            target_margin_percentage=target_margin_percentage,
            packaging_profile=packaging_profile,
            overhead_profile=overhead_profile,
        )
        calculated_lines.append((meal_type, menu, meal_data, calculation))

        if not calculation.get("is_complete"):
            meal_label = meal_data.get("label") or meal_type
            warnings = "; ".join(calculation.get("warnings") or ["Data HPP belum lengkap."])
            incomplete_messages.append(f"{meal_label}: {warnings}")

    if incomplete_messages:
        return False, "Snapshot belum disimpan karena data HPP belum lengkap. " + " | ".join(incomplete_messages), None

    snapshot = OrderHppSnapshot(
        branch_id=branch_id,
        daily_order_id=daily_order.id,
        snapshot_number=generate_snapshot_number(daily_order),
        snapshot_date=datetime.utcnow(),
        status="LOCKED",
        target_margin_percentage=target_margin_percentage,
        notes=notes,
        created_by=created_by,
    )
    db.session.add(snapshot)
    db.session.flush()

    for meal_type, menu, meal_data, calculation in calculated_lines:
        _create_snapshot_line(
            snapshot=snapshot,
            meal_type=meal_type,
            menu=menu,
            meal_data=meal_data,
            packaging_profile=packaging_profile,
            overhead_profile=overhead_profile,
            calculation=calculation,
        )

    db.session.flush()

    total_portion = sum(_to_float(line.portion_qty) for line in snapshot.lines)
    snapshot.total_portion = total_portion
    snapshot.food_cost_total = sum(_to_float(line.food_cost_total) for line in snapshot.lines)
    snapshot.packaging_cost_total = sum(_to_float(line.packaging_cost_total) for line in snapshot.lines)
    snapshot.overhead_cost_total = sum(_to_float(line.overhead_cost_total) for line in snapshot.lines)
    snapshot.hpp_total = sum(_to_float(line.hpp_total) for line in snapshot.lines)
    snapshot.hpp_per_portion = snapshot.hpp_total / total_portion if total_portion > 0 else 0
    snapshot.revenue_total = sum(_to_float(line.revenue_total) for line in snapshot.lines)
    snapshot.gross_margin_amount = snapshot.revenue_total - snapshot.hpp_total
    snapshot.gross_margin_percentage = (
        (snapshot.gross_margin_amount / snapshot.revenue_total) * 100
        if snapshot.revenue_total > 0 else 0
    )

    _create_snapshot_allocations(snapshot, daily_order)

    db.session.commit()
    return True, f"Snapshot HPP order berhasil disimpan. Stok, jurnal, invoice tidak berubah. Alokasi HPP per detail order/{T.sub_client_lower} ikut dibekukan.", snapshot
