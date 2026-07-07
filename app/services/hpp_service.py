from app.models.master import ItemCostProfile, UnitConversion


def normalize_unit(value):
    return (value or "").strip().upper()


def find_unit_multiplier(branch_id, unit_from, unit_to):
    unit_from = normalize_unit(unit_from)
    unit_to = normalize_unit(unit_to)

    if not unit_from or not unit_to:
        return None

    if unit_from == unit_to:
        return 1

    direct = UnitConversion.query.filter(
        UnitConversion.branch_id == branch_id,
        UnitConversion.is_active == True,
        UnitConversion.unit_from == unit_from,
        UnitConversion.unit_to == unit_to,
    ).first()
    if direct:
        return float(direct.multiplier or 0) if float(direct.multiplier or 0) > 0 else None

    reverse = UnitConversion.query.filter(
        UnitConversion.branch_id == branch_id,
        UnitConversion.is_active == True,
        UnitConversion.unit_from == unit_to,
        UnitConversion.unit_to == unit_from,
    ).first()
    if reverse and float(reverse.multiplier or 0) > 0:
        return 1 / float(reverse.multiplier or 0)

    return None


def calculate_menu_hpp(
    menu,
    portion_qty,
    selling_price_per_portion=None,
    target_margin_percentage=30,
    packaging_profile=None,
    overhead_profile=None,
):
    portion_qty = float(portion_qty or 0)
    target_margin_percentage = float(target_margin_percentage or 0)

    result = {
        "menu": menu,
        "recipe": None,
        "packaging_profile": packaging_profile,
        "overhead_profile": overhead_profile,
        "portion_qty": portion_qty,
        "selling_price_per_portion": float(selling_price_per_portion or 0),
        "target_margin_percentage": target_margin_percentage,
        "food_cost_total": 0,
        "food_cost_per_portion": 0,
        "packaging_cost_per_portion": 0,
        "packaging_cost_total": 0,
        "overhead_flat_cost_per_portion": 0,
        "overhead_flat_cost_total": 0,
        "overhead_percentage": 0,
        "overhead_percentage_base_total": 0,
        "overhead_percentage_cost_total": 0,
        "overhead_percentage_cost_per_portion": 0,
        "overhead_cost_total": 0,
        "overhead_cost_per_portion": 0,
        "hpp_total": 0,
        "hpp_per_portion": 0,
        "recommended_selling_price": 0,
        "revenue_total": 0,
        "gross_margin_amount": 0,
        "gross_margin_percentage": 0,
        "is_complete": True,
        "warnings": [],
        "lines": [],
    }

    if not menu:
        result["is_complete"] = False
        result["warnings"].append("Menu belum dipilih.")
        return result

    recipe = menu.recipe
    result["recipe"] = recipe

    if portion_qty <= 0:
        result["is_complete"] = False
        result["warnings"].append("Jumlah porsi wajib lebih dari 0.")
        return result

    if selling_price_per_portion is None:
        result["selling_price_per_portion"] = float(menu.default_selling_price or 0)

    if not recipe or not recipe.items:
        result["is_complete"] = False
        result["warnings"].append("Menu belum punya resep/BOM.")
        return result

    if getattr(recipe, "recipe_status", "DRAFT") != "FINAL":
        result["warnings"].append("Resep masih DRAFT. Hasil HPP boleh dicek, tapi sebaiknya finalkan resep sebelum dijadikan dasar operasional.")

    total_cost = 0

    for recipe_item in recipe.items:
        item = recipe_item.item
        profile = ItemCostProfile.query.filter_by(
            item_id=recipe_item.item_id,
            branch_id=menu.branch_id,
        ).first()

        line = {
            "recipe_item": recipe_item,
            "item": item,
            "profile": profile,
            "qty_per_portion": float(recipe_item.qty_per_portion or 0),
            "recipe_unit": normalize_unit(recipe_item.unit),
            "base_unit": profile.base_unit if profile else "",
            "conversion_multiplier": None,
            "base_qty_per_portion": 0,
            "base_qty_total": 0,
            "cost_per_base_unit": profile.effective_cost_per_base_unit if profile else 0,
            "cost_per_portion": 0,
            "cost_total": 0,
            "status": "OK",
            "message": "",
        }

        if line["qty_per_portion"] <= 0:
            line["status"] = "INVALID_QTY"
            line["message"] = "Qty resep wajib lebih dari 0."
            result["is_complete"] = False
            result["warnings"].append(f"Qty resep {item.item_name if item else 'item'} belum valid.")
            result["lines"].append(line)
            continue

        if not profile:
            line["status"] = "MISSING_PROFILE"
            line["message"] = "Profil HPP item belum dibuat."
            result["is_complete"] = False
            result["warnings"].append(f"Profil HPP belum ada untuk {item.item_name if item else 'item'}.")
            result["lines"].append(line)
            continue

        if float(profile.effective_cost_per_base_unit or 0) <= 0:
            line["status"] = "ZERO_COST"
            line["message"] = "Biaya efektif item masih 0."
            result["is_complete"] = False
            result["warnings"].append(f"Biaya efektif masih 0 untuk {item.item_name if item else 'item'}.")

        multiplier = find_unit_multiplier(menu.branch_id, line["recipe_unit"], profile.base_unit)
        if multiplier is None:
            line["status"] = "MISSING_CONVERSION"
            line["message"] = f"Butuh konversi {line['recipe_unit']} ke {profile.base_unit}."
            result["is_complete"] = False
            result["warnings"].append(f"Konversi {line['recipe_unit']} ke {profile.base_unit} belum ada untuk {item.item_name if item else 'item'}.")
            result["lines"].append(line)
            continue

        line["conversion_multiplier"] = multiplier
        line["base_qty_per_portion"] = line["qty_per_portion"] * multiplier
        line["base_qty_total"] = line["base_qty_per_portion"] * portion_qty
        line["cost_per_portion"] = line["base_qty_per_portion"] * float(profile.effective_cost_per_base_unit or 0)
        line["cost_total"] = line["cost_per_portion"] * portion_qty
        total_cost += line["cost_total"]
        result["lines"].append(line)

    result["food_cost_total"] = total_cost
    result["food_cost_per_portion"] = total_cost / portion_qty if portion_qty > 0 else 0

    if packaging_profile:
        result["packaging_cost_per_portion"] = float(packaging_profile.cost_per_portion or 0)
        result["packaging_cost_total"] = result["packaging_cost_per_portion"] * portion_qty

    if overhead_profile:
        result["overhead_flat_cost_per_portion"] = float(overhead_profile.flat_cost_per_portion or 0)
        result["overhead_flat_cost_total"] = result["overhead_flat_cost_per_portion"] * portion_qty
        result["overhead_percentage"] = float(overhead_profile.overhead_percentage or 0)
        result["overhead_percentage_base_total"] = result["food_cost_total"] + result["packaging_cost_total"]
        result["overhead_percentage_cost_total"] = (
            result["overhead_percentage_base_total"] * result["overhead_percentage"] / 100
        )
        result["overhead_percentage_cost_per_portion"] = (
            result["overhead_percentage_cost_total"] / portion_qty if portion_qty > 0 else 0
        )
        result["overhead_cost_total"] = (
            result["overhead_flat_cost_total"] + result["overhead_percentage_cost_total"]
        )
        result["overhead_cost_per_portion"] = (
            result["overhead_cost_total"] / portion_qty if portion_qty > 0 else 0
        )

    result["hpp_total"] = (
        result["food_cost_total"]
        + result["packaging_cost_total"]
        + result["overhead_cost_total"]
    )
    result["hpp_per_portion"] = result["hpp_total"] / portion_qty if portion_qty > 0 else 0

    if target_margin_percentage < 100:
        denominator = 1 - (target_margin_percentage / 100)
        result["recommended_selling_price"] = result["hpp_per_portion"] / denominator if denominator > 0 else 0

    result["revenue_total"] = portion_qty * result["selling_price_per_portion"]
    result["gross_margin_amount"] = result["revenue_total"] - result["hpp_total"]
    result["gross_margin_percentage"] = (
        (result["gross_margin_amount"] / result["revenue_total"]) * 100
        if result["revenue_total"] > 0 else 0
    )

    return result
