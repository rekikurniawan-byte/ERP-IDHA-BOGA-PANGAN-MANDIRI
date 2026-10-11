"""Navigasi portal: satu pintu per halaman (keputusan owner 2026-10-11)."""

from collections import Counter

import pytest

from app.services.portal_navigation_service import build_portal_navigation, portal_navigation_map

ROLES = ["PORTAL_CUSTOMER", "PORTAL_SUBCLIENT", "PORTAL_CLIENT", "ADMIN"]


def _doors(nav):
    doors = [tab["endpoint"] for tab in nav["tabs"] if not tab["segments"]]
    for tab in nav["tabs"]:
        doors += [segment["endpoint"] for segment in tab["segments"]]
    doors += [link["endpoint"] for link in nav["account_links"]]
    return doors


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("worker_debt_on", [False, True])
@pytest.mark.parametrize("direct_ordering", [False, True])
def test_every_portal_page_has_exactly_one_door(app, role, worker_debt_on, direct_ordering):
    with app.app_context():
        nav = portal_navigation_map(role, worker_debt_on=worker_debt_on, direct_ordering=direct_ordering)
    duplicated = [endpoint for endpoint, count in Counter(_doors(nav)).items() if count > 1]
    assert duplicated == []
    # Satu halaman juga tidak boleh dinyalakan oleh dua pintu berbeda.
    lit = []
    for tab in nav["tabs"]:
        for segment in tab["segments"]:
            lit += segment["endpoints"]
    for link in nav["account_links"]:
        lit += link["endpoints"]
    assert [endpoint for endpoint, count in Counter(lit).items() if count > 1] == []


@pytest.mark.parametrize("role", ["PORTAL_CUSTOMER", "PORTAL_SUBCLIENT", "PORTAL_CLIENT"])
def test_payment_history_lives_under_billing_tab(app, role):
    with app.app_context():
        nav = portal_navigation_map(role, worker_debt_on=True)
    billing = next(tab for tab in nav["tabs"] if tab["key"] == "billing")
    billing_endpoints = {endpoint for segment in billing["segments"] for endpoint in segment["endpoints"]}
    payment_pages = {"portal.customer_payments", "portal.mandor_payments", "portal.pt_payments"}
    assert billing_endpoints & payment_pages
    account_endpoints = {endpoint for link in nav["account_links"] for endpoint in link["endpoints"]}
    assert not account_endpoints & payment_pages
    assert "portal.notifications" not in account_endpoints  # lonceng di header satu-satunya pintu


def test_worker_pages_hidden_when_module_off(app):
    with app.app_context():
        nav = portal_navigation_map("PORTAL_SUBCLIENT", worker_debt_on=False)
    assert "portal.mandor_workers" not in _doors(nav)
    assert "portal.mandor_canteen_debts" not in _doors(nav)


def test_active_tab_and_segments_follow_endpoint(app):
    with app.test_request_context():
        nav = build_portal_navigation("PORTAL_SUBCLIENT", "portal.invoice_payment_instruction")
    assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["billing"]
    assert [segment["label"] for segment in nav["segments"]] == ["Tagihan", "Riwayat Bayar"]
    assert not nav["account_child"]

    with app.test_request_context():
        nav = build_portal_navigation("PORTAL_CUSTOMER", "portal.addresses")
    assert [tab["key"] for tab in nav["tabs"] if tab["active"]] == ["account"]
    assert nav["account_child"]
