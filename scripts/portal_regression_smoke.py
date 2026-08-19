"""Runtime smoke check for integrated portal and finance portal screens.

Run manually after coding batches:

    python scripts/portal_regression_smoke.py

This script uses the active local ERP database and does not mutate data.
It logs in through Flask-Login session data and requests read-only GET pages.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app import create_app
from app.models.master import User


@dataclass(frozen=True)
class SmokePersona:
    label: str
    role: str
    paths: tuple[str, ...]
    preferred_usernames: tuple[str, ...] = ()


PERSONAS = (
    SmokePersona(
        "owner-admin",
        "OWNER",
        (
            "/portal/dashboard",
            "/portal/admin/order-drafts",
            "/finance/",
            "/finance/portal-payment-proofs",
            "/finance/portal-payment-proofs?status=VERIFIED",
            "/finance/portal-payment-proofs?status=PAYMENT_CREATED",
            "/customer-success/complaints",
        ),
    ),
    SmokePersona(
        "portal-customer",
        "PORTAL_CUSTOMER",
        (
            "/portal/customer",
            "/portal/customer/order",
            "/portal/customer/orders",
            "/portal/customer/tracking",
            "/portal/customer/invoices",
            "/portal/customer/payments",
            "/portal/customer/complaints",
            "/portal/customer/returns",
            "/portal/orders/draft",
            "/portal/orders/status",
            "/portal/notifications",
            "/portal/documents",
            "/portal/approvals",
            "/portal/calendar",
        ),
        ("usercustomer1", "portal.customer.local", "agus123"),
    ),
    SmokePersona(
        "portal-mandor",
        "PORTAL_MANDOR",
        (
            "/portal/mandor",
            "/portal/mandor/order",
            "/portal/mandor/workers",
            "/portal/mandor/catering-debts",
            "/portal/mandor/canteen-debts",
            "/portal/mandor/installments",
            "/portal/mandor/invoices",
            "/portal/mandor/payments",
            "/portal/mandor/subscriptions",
            "/portal/orders/draft",
            "/portal/orders/status",
            "/portal/notifications",
            "/portal/documents",
            "/portal/approvals",
            "/portal/calendar",
        ),
        ("usermandor1", "portal.mandor.local", "mandor1"),
    ),
    SmokePersona(
        "portal-pt",
        "PORTAL_PT",
        (
            "/portal/pt",
            "/portal/pt/mandors",
            "/portal/pt/invoices",
            "/portal/pt/receivables",
            "/portal/pt/payments",
            "/portal/pt/contracts",
            "/portal/pt/subscriptions",
            "/portal/pt/order",
            "/portal/orders/draft",
            "/portal/orders/status",
            "/portal/notifications",
            "/portal/documents",
            "/portal/approvals",
            "/portal/calendar",
        ),
        ("userpt123", "portal.pt.local", "userpt12"),
    ),
)


def _login_session(client, user_id: int) -> None:
    with client.session_transaction() as session:
        session["_user_id"] = str(user_id)
        session["_fresh"] = True


def _select_smoke_user_id(app, persona: SmokePersona) -> int | None:
    with app.app_context():
        user: User | None = None
        if persona.preferred_usernames:
            user = (
                User.query.filter(
                    User.role == persona.role,
                    User.username.in_(persona.preferred_usernames),
                    User.is_active.is_(True),
                )
                .order_by(User.branch_id.asc(), User.id.asc())
                .first()
            )
        if not user:
            user = (
                User.query.filter_by(role=persona.role, is_active=True)
                .order_by(User.branch_id.asc(), User.id.asc())
                .first()
            )
        return user.id if user else None


def main() -> int:
    app = create_app()
    failures: list[str] = []
    checked = 0
    skipped = 0
    for persona in PERSONAS:
        user_id = _select_smoke_user_id(app, persona)
        if not user_id:
            skipped += len(persona.paths)
            print(f"SKIP {persona.label}: tidak ada user role {persona.role}")
            continue
        with app.test_client() as client:
            _login_session(client, user_id)
            for path in persona.paths:
                checked += 1
                response = client.get(path, follow_redirects=False)
                status = response.status_code
                location = response.headers.get("Location", "")
                print(f"{status:3} {persona.label:15} {path} {location}")
                if status >= 500:
                    failures.append(f"{persona.label} {path} menghasilkan {status}")
                if status in {301, 302, 303, 307, 308} and location.endswith(path):
                    failures.append(f"{persona.label} {path} redirect loop ke dirinya sendiri")
    print(f"CHECKED={checked} SKIPPED={skipped} FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAIL {failure}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
