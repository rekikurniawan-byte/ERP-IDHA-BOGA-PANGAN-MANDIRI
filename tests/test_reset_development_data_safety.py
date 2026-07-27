import json
from pathlib import Path

import pytest

from scripts import reset_development_data as reset_tool


def test_confirmation_phrase_is_specific():
    assert reset_tool.CONFIRMATION_PHRASE == "RESET_ERP_DEVELOPMENT_DATA_CONFIRMED"
    assert len(reset_tool.CONFIRMATION_PHRASE) > 20


def test_parse_args_defaults_to_dry_run():
    args = reset_tool.parse_args([])
    assert args.execute is False
    assert args.option == "A"
    assert args.confirm_token == ""
    assert args.method == "delete"


def test_sanitize_database_url_redacts_password():
    sample_url = (
        "postgresql+psycopg://user:"
        "dummy-redaction-value"
        "@localhost:5432/idha_boga_staging"
    )
    sanitized = reset_tool.sanitize_database_url(sample_url)
    assert sanitized["driver"] == "postgresql+psycopg"
    assert sanitized["host"] == "localhost"
    assert sanitized["database"] == "idha_boga_staging"
    assert sanitized["username_present"] is True
    assert sanitized["password_redacted"] is True
    assert "dummy-redaction-value" not in json.dumps(sanitized)


def test_quote_identifier_rejects_unsafe_identifier():
    assert reset_tool.quote_identifier("valid_table_01") == '"valid_table_01"'
    with pytest.raises(ValueError):
        reset_tool.quote_identifier("users; DROP TABLE users")


def test_deletion_order_places_child_before_parent():
    tables = {"invoice_items", "invoices", "payments"}
    fk_out = {
        "invoice_items": [{"referred_table": "invoices"}],
        "payments": [{"referred_table": "invoices"}],
        "invoices": [],
    }

    ordered, cycles = reset_tool.deletion_order(tables, fk_out)

    assert cycles == []
    assert ordered.index("invoice_items") < ordered.index("invoices")
    assert ordered.index("payments") < ordered.index("invoices")


def test_build_plan_blocks_unclassified_tables():
    classification = {
        "tables": [
            {"table": "users", "option_a_action": "preserve", "option_b_action": "preserve"},
        ]
    }
    inventory = {
        "tables": ["users", "invoices"],
        "counts": {"users": 1, "invoices": 2},
        "fk_out": {"users": [], "invoices": []},
        "sequences": {"users": "public.users_id_seq", "invoices": "public.invoices_id_seq"},
    }

    plan = reset_tool.build_plan(classification, inventory, "A")

    assert plan["unknown_tables"] == ["invoices"]
    assert plan["preserve_tables"] == ["users"]
    assert plan["empty_tables"] == []


def test_build_plan_detects_preserved_rows_referencing_empty_parent():
    classification = {
        "tables": [
            {"table": "journals", "option_a_action": "empty", "option_b_action": "empty"},
            {"table": "fixed_asset_purchases", "option_a_action": "preserve", "option_b_action": "preserve"},
        ]
    }
    inventory = {
        "tables": ["journals", "fixed_asset_purchases"],
        "counts": {"journals": 1, "fixed_asset_purchases": 1},
        "fk_out": {
            "journals": [],
            "fixed_asset_purchases": [{"referred_table": "journals"}],
        },
        "fk_in": {
            "journals": [{"table": "fixed_asset_purchases", "columns": ["journal_id"]}],
            "fixed_asset_purchases": [],
        },
        "sequences": {
            "journals": "public.journals_id_seq",
            "fixed_asset_purchases": "public.fixed_asset_purchases_id_seq",
        },
    }

    plan = reset_tool.build_plan(classification, inventory, "A")

    assert plan["external_fk_blockers"] == [
        {
            "target_empty_table": "journals",
            "referencing_preserved_or_pending_table": "fixed_asset_purchases",
            "columns": ["journal_id"],
        }
    ]
