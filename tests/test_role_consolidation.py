"""Blueprint V2 role consolidation: 14 roles -> 4 internal + portal.

Locks in the contract in app/utils/roles.py. FINANCE, ACCOUNTING, LOGISTICS,
HR and CUSTOMER_SUCCESS are retired and ADMIN does their work; every access
decision -- routes and templates alike -- reads through one table.
"""
from pathlib import Path

import pytest

from app.services.user_management_service import ALLOWED_ROLES
from app.utils.roles import (
    RETIRED_ROLE_SUCCESSOR,
    effective_role,
    role_in,
    role_permits,
)

ROOT = Path(__file__).resolve().parents[1]
RETIRED = ("FINANCE", "ACCOUNTING", "LOGISTICS", "HR", "CUSTOMER_SUCCESS")


@pytest.mark.parametrize("role", RETIRED)
def test_every_retired_internal_role_maps_to_admin(role):
    assert effective_role(role) == "ADMIN"
    assert effective_role(role.lower()) == "ADMIN"


@pytest.mark.parametrize("role", ["OWNER", "ADMIN", "DAPUR", "PENGANTAR",
                                  "PORTAL_CLIENT", "PORTAL_SUBCLIENT", "PORTAL_CUSTOMER"])
def test_surviving_roles_map_to_themselves(role):
    assert effective_role(role) == role


def test_retired_roles_are_not_assignable():
    for role in RETIRED:
        assert role not in ALLOWED_ROLES
    for role in ("OWNER", "ADMIN", "DAPUR", "PENGANTAR"):
        assert role in ALLOWED_ROLES


def test_an_allowlist_naming_a_retired_role_admits_admin():
    # The accounting routes are declared @role_required("ACCOUNTING").
    assert role_permits("ADMIN", ("ACCOUNTING",))
    assert role_permits("ADMIN", ("LOGISTICS", "DAPUR"))


def test_consolidation_does_not_widen_access_for_other_roles():
    assert not role_permits("DAPUR", ("ACCOUNTING",))
    assert not role_permits("PENGANTAR", ("FINANCE",))
    assert not role_permits("PORTAL_CLIENT", ("HR",))
    assert role_permits("DAPUR", ("LOGISTICS", "DAPUR"))


def test_owner_is_always_admitted_to_routes():
    assert role_permits("OWNER", ("DAPUR",))
    assert role_permits("OWNER", ())


def test_template_membership_has_no_owner_bypass():
    # role_in() mirrors `role in [...]`: every existing sidebar list keeps its
    # exact meaning apart from the retired-role mapping.
    assert not role_in("OWNER", ["ADMIN", "DAPUR"])
    assert role_in("ADMIN", ["OWNER", "ACCOUNTING"])
    assert role_in("FINANCE", ["ADMIN"])


def test_successor_table_covers_exactly_the_retired_roles():
    assert set(RETIRED_ROLE_SUCCESSOR) == set(RETIRED) | {"PORTAL_MANDOR"}
    for role in RETIRED:
        assert RETIRED_ROLE_SUCCESSOR[role] == "ADMIN"


def test_mandor_portal_role_is_renamed_to_sub_client():
    # A rename, not a merge: the sub client keeps its own scope and pages.
    # The domain entity stays Mandor and the /portal/mandor/* URLs are
    # unchanged, so only the role name moves.
    assert effective_role("PORTAL_MANDOR") == "PORTAL_SUBCLIENT"
    assert "PORTAL_SUBCLIENT" in ALLOWED_ROLES
    assert "PORTAL_MANDOR" not in ALLOWED_ROLES
    assert not role_in("PORTAL_SUBCLIENT", ["PORTAL_CLIENT"])
    assert not role_in("PORTAL_SUBCLIENT", ["PORTAL_CUSTOMER"])


def test_sidebar_has_no_parallel_role_lists():
    # The sidebar used to keep its own role lists and drifted from the
    # routes: it hid from ADMIN several finance pages ADMIN could open. It now
    # decides visibility through has_role(), the same table the routes use.
    sidebar = (ROOT / "app" / "templates" / "layouts" / "sidebar.html").read_text(encoding="utf-8")
    assert "role in [" not in sidebar
    assert "role in all_roles" not in sidebar
    assert "has_role(" in sidebar


def test_role_required_reads_through_the_consolidation_table():
    decorators = (ROOT / "app" / "utils" / "decorators.py").read_text(encoding="utf-8")
    assert "role_permits(" in decorators
    assert "current_user.role not in allowed_roles" not in decorators
