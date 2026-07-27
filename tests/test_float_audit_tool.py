from pathlib import Path

from tools.audit_float_fields import classify_field, collect_float_fields, migration_stage


def test_float_audit_classifies_money_quantity_and_ratio_fields():
    assert classify_field("total_amount") == ("money", "db.Numeric(18, 2)", "P0")
    assert classify_field("gross_margin_percentage") == ("ratio", "db.Numeric(8, 4)", "P1")
    assert classify_field("total_portion") == ("quantity", "db.Numeric(18, 4)", "P1")
    assert classify_field("base_qty_total") == ("quantity", "db.Numeric(18, 4)", "P1")
    assert classify_field("selling_price_per_portion") == ("money", "db.Numeric(18, 2)", "P0")


def test_float_audit_current_model_inventory_count():
    fields = collect_float_fields(Path("app/models"))

    assert len(fields) == 0
