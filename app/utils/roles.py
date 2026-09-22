"""Role consolidation for Blueprint V2.

The business runs internally on four roles: OWNER, ADMIN, DAPUR and
PENGANTAR. FINANCE, ACCOUNTING, LOGISTICS, HR and CUSTOMER_SUCCESS were roles
"disiapkan untuk" departments that do not exist -- the admin does that work.
Every feature behind them stays; only the role boundary goes. See
BLUEPRINT_V2_AUDIT_FITUR.md for the audit and the owner's decisions.

Rather than rewrite some 400 route allowlists across 38 files, a retired role
is mapped to its successor here, and every access decision reads through
this one table:

    role_required()   routes           OWNER always admitted
    has_role()        templates        plain membership, no OWNER bypass

So an allowlist that still says "ACCOUNTING" admits ADMIN, and a user row
that still says "FINANCE" is treated as ADMIN. The two cannot drift apart,
which is exactly what went wrong before: the sidebar kept its own role lists,
and hid from ADMIN several finance pages ADMIN was already allowed to open.
"""
from __future__ import annotations

from collections.abc import Iterable

OWNER = "OWNER"

# Retired role -> the role that now does its work.
RETIRED_ROLE_SUCCESSOR = {
    "FINANCE": "ADMIN",
    "ACCOUNTING": "ADMIN",
    "LOGISTICS": "ADMIN",
    "HR": "ADMIN",
    "CUSTOMER_SUCCESS": "ADMIN",
}


def effective_role(role: str | None) -> str:
    """The role a stored or listed role name stands for today."""
    value = str(role or "").strip().upper()
    return RETIRED_ROLE_SUCCESSOR.get(value, value)


def role_in(user_role: str | None, roles: Iterable[str]) -> bool:
    """Membership test that understands retired roles on both sides."""
    wanted = {effective_role(role) for role in roles}
    return effective_role(user_role) in wanted


def role_permits(user_role: str | None, allowed_roles: Iterable[str]) -> bool:
    """Route access: OWNER is always admitted, everyone else by membership."""
    if effective_role(user_role) == OWNER:
        return True
    return role_in(user_role, allowed_roles)
