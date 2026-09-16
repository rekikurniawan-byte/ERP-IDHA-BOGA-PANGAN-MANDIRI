#!/usr/bin/env python3
"""Capture and diff the computed style of every element on representative pages.

Why not screenshots: on this app they are not reproducible. Two captures with
no code change in between still differ, because main.js recolours .app-atomic
badges and runs scroll-reveal animations after load. A computed-style
fingerprint is both deterministic (once motion is frozen and those passes have
settled) and far more sensitive -- it catches a 1px padding change on an
element that never even scrolls into view.

The DOM is identical between runs, so elements are compared by document order.

Pages come from the app's own url_map, not a hand-written list: every GET
route that renders, with real ids filled in from the database, currently ~250
of them. Coverage is the whole point. A hand-written list goes stale silently,
and its gaps do not announce themselves -- an earlier 10-page list happened to
omit layouts/portal_mobile.html, so five files that set the portal topbar
height looked like dead code and were very nearly deleted.

Cost follows from that: ~250 pages x 2 viewports x 2 themes is roughly 45
minutes per capture, so a before/after pair is around an hour and a half.
That is the price of an answer you can act on.

Needs the dev server running against the real database, and requires the
dev extras: pip install -r requirements-dev.txt && python -m playwright install chromium

Usage:
    python tools/visual_baseline/computed_fingerprint.py capture before.json
    # ...make CSS changes, run tools/build_css.py...
    python tools/visual_baseline/computed_fingerprint.py capture after.json
    python tools/visual_baseline/computed_fingerprint.py diff before.json after.json

Always confirm the harness itself is quiet first: capture twice with no change
in between and diff those. It must report 0 differences before any result is
meaningful.
"""
from __future__ import annotations

import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

BASE_URL = "http://127.0.0.1:5000"

PROPERTIES = [
    "display", "position", "width", "height", "minHeight", "maxWidth",
    "marginTop", "marginRight", "marginBottom", "marginLeft",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
    "fontSize", "fontWeight", "lineHeight", "letterSpacing", "textAlign",
    "color", "backgroundColor", "opacity",
    "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
    "borderTopColor", "borderBottomColor", "borderTopLeftRadius",
    "boxShadow", "gap", "flexDirection", "justifyContent", "alignItems",
    "gridTemplateColumns", "overflowX", "overflowY", "zIndex", "textTransform",
    "visibility", "whiteSpace", "verticalAlign", "float", "flexGrow", "flexBasis",
]

# Pages are discovered from the app's url_map rather than listed by hand --
# see discover_pages(). A hand-written list silently goes stale as routes are
# added, and its gaps are invisible: an earlier 10-page list omitted
# layouts/portal_mobile.html entirely, which made five files that set the
# portal topbar height look like dead code.
#
# The list below is the fallback used when discovery cannot reach the
# database, and doubles as documentation of the structural families that must
# be covered whatever happens.
FALLBACK_PAGES = [
    ("items", "/master/items"),
    ("finance_transactions", "/finance/transactions"),
    ("accounting_journals", "/accounting/journals"),
    ("settings_users", "/settings/users"),
    ("settings_user_form", "/settings/users/create"),
    ("delivery_today", "/delivery/today"),
    ("canteen_index", "/canteen/"),
    ("sop_index", "/sop/"),
    ("finance_invoice_index", "/finance/invoices"),
    ("master_index", "/master/"),
    ("dashboard_root", "/"),
    ("dashboard_owner", "/dashboard/owner"),
    ("dashboard_admin", "/dashboard/admin"),
    ("revenue_explorer", "/dashboard/revenue-explorer"),
    ("customer_success", "/customer-success/"),
    ("customer_complaints", "/customer-success/complaints"),
    ("portal_dashboard", "/portal/dashboard"),
    ("portal_customers", "/portal/customers"),
    ("portal_my_dashboard", "/portal/my-dashboard"),
    ("portal_status", "/portal/status"),
    ("portal_invoices", "/portal/invoices"),
    ("settings_backups", "/settings/backups"),
    ("hr_index", "/hr/"),
    ("logistics_index", "/logistics/"),
    # layouts/portal_mobile.html -- a second shell with its own topbar
    # (.portal-web-topbar / .portal-mobile-topbar) that none of the pages
    # above render. Without one of these, every rule targeting that shell
    # looks unused to this check.
    ("portal_approvals", "/portal/approvals"),
    ("portal_notifications", "/portal/notifications"),
    ("portal_order_status", "/portal/orders/status"),
    ("portal_documents", "/portal/documents"),
    ("portal_calendar", "/portal/calendar"),
    ("portal_returns", "/portal/returns"),
    ("portal_subscriptions", "/portal/subscriptions"),
]

# Captured with no session cookie -- the auth screens have their own layout
# and their own CSS family (.auth-*), unreachable while logged in.
PUBLIC_PAGES = [
    ("auth_login", "/auth/login"),
    ("portal_login", "/portal/login"),
    ("portal_register", "/portal/register"),
]

VIEWPORTS = [("desktop", 1440, 900), ("mobile", 390, 844)]
THEMES = ["light", "dark"]

COLLECT_JS = """(props) => {
  const out = [];
  for (const el of document.querySelectorAll('*')) {
    const cs = getComputedStyle(el);
    const cls = el.className && el.className.baseVal !== undefined
      ? el.className.baseVal : String(el.className || '');
    const row = [el.tagName, cls];
    for (const p of props) row.push(cs[p]);
    out.push(row);
  }
  return out;
}"""

FREEZE_CSS = "*,*::before,*::after{animation:none !important;transition:none !important;}"


# Endpoints whose name or path contains any of these are never visited: they
# transfer a file, destroy something, or end the session. Everything else in
# this app gates its mutations behind POST and only renders on GET.
SKIP_WORDS = ("download", "delete", "remove", "logout", "attachment",
              "raw", "stream", "serve", "file")

# One real id per common route parameter, so detail and form pages are
# reachable instead of being skipped for want of an id.
PARAM_TABLES = {
    "invoice_id": "invoices", "order_id": "daily_orders", "user_id": "users",
    "client_id": "clients", "mandor_id": "mandors", "item_id": "items",
    "worker_id": "workers", "driver_id": "drivers", "production_id": "productions",
    "delivery_id": "deliveries", "payroll_id": "payrolls", "journal_id": "journals",
    "transaction_id": "field_transactions", "complaint_id": "customer_complaints",
    "contract_id": "customer_contracts", "correction_id": "customer_corrections",
    "debt_id": "worker_debts", "advance_id": "advances",
    "expense_id": "operational_expenses", "asset_id": "fixed_assets",
    "batch_id": "manual_billing_batches", "supplier_id": "suppliers",
    "branch_id": "branches", "location_id": "delivery_locations",
    "detail_id": "delivery_details", "period_id": "accounting_periods",
    "draft_id": "portal_order_drafts", "receipt_id": "delivery_receipts",
    "profile_id": "item_cost_profiles", "recipe_id": "recipes",
}


def discover_pages() -> list[tuple[str, str]]:
    """Every GET route that renders a page, with real ids filled in.

    Sorted by path so the page order is stable between runs.
    """
    import re

    from app import create_app, db
    from sqlalchemy import text as sql_text

    app = create_app()
    with app.app_context():
        ids = {}
        for parameter, table in PARAM_TABLES.items():
            try:
                row = db.session.execute(
                    sql_text(f"SELECT id FROM {table} ORDER BY id LIMIT 1")).first()
            except Exception:
                continue
            if row:
                ids[parameter] = row[0]

        found = []
        for rule in app.url_map.iter_rules():
            if "GET" not in rule.methods or rule.endpoint == "static":
                continue
            haystack = (rule.endpoint + rule.rule).lower()
            if any(word in haystack for word in SKIP_WORDS):
                continue
            path = rule.rule
            resolved = True
            for argument in rule.arguments:
                if argument not in ids:
                    resolved = False
                    break
                path = re.sub(r"<[^<>]*%s>" % re.escape(argument), str(ids[argument]), path)
            if not resolved or "<" in path:
                continue
            found.append((rule.endpoint.replace(".", "_"), path))

    return sorted(set(found), key=lambda entry: entry[1])


def _session_cookie(role: str = "OWNER") -> str:
    """Mint a Flask-Login cookie in-process for a user with the given role.

    Flask's default session is a signed cookie, not server-side state, so a
    cookie built here is valid against the separately running dev server.

    The role matters: whole template families are reachable only by the role
    they belong to. The portal role dashboards own all the .portal-home-*
    markup, and an OWNER session never renders a single element of it.
    """
    from app import create_app
    from app.models import User

    app = create_app()
    with app.app_context():
        client = app.test_client()
        user = User.query.filter_by(role=role).first()
        if user is None and role == "OWNER":
            user = User.query.first()
        if user is None:
            raise SystemExit(f"no user with role {role!r} to authenticate as")
        with client.session_transaction() as session:
            session["_user_id"] = str(user.get_id())
            session["_fresh"] = True
        return client.get_cookie("session").value


def capture(out_path: str) -> int:
    from playwright.sync_api import sync_playwright

    cookie = _session_cookie()
    pages: dict[str, list] = {}

    try:
        authed_pages = discover_pages()
        print(f"discovered {len(authed_pages)} GET pages from the url_map", file=sys.stderr)
    except Exception as error:  # noqa: BLE001
        print(f"route discovery failed ({error}); using the fallback list", file=sys.stderr)
        authed_pages = FALLBACK_PAGES

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for viewport_name, width, height in VIEWPORTS:
            for theme in THEMES:
              for authenticated, page_list in ((True, authed_pages), (False, PUBLIC_PAGES)):
                context = browser.new_context(viewport={"width": width, "height": height},
                                              color_scheme=theme)
                if authenticated:
                    context.add_cookies([{"name": "session", "value": cookie,
                                          "domain": "127.0.0.1", "path": "/"}])
                page = context.new_page()
                for name, path in page_list:
                    try:
                        response = page.goto(BASE_URL + path, wait_until="networkidle",
                                             timeout=60000)
                        if response.status != 200:
                            print(f"skip {path} ({response.status})", file=sys.stderr)
                            continue
                        page.add_style_tag(content=FREEZE_CSS)
                        page.wait_for_timeout(1500)
                        key = f"{name}|{viewport_name}|{theme}"
                        pages[key] = page.evaluate(COLLECT_JS, PROPERTIES)
                    except Exception as error:  # noqa: BLE001 - report and keep going
                        print(f"error {path}: {error}", file=sys.stderr)
                context.close()
        browser.close()

    Path(out_path).write_text(json.dumps({"properties": PROPERTIES, "pages": pages}),
                              encoding="utf-8")
    print(f"captured {len(pages)} page/viewport/theme combos, "
          f"{sum(len(rows) for rows in pages.values())} elements -> {out_path}")
    return 0


def diff(before_path: str, after_path: str) -> int:
    before = json.loads(Path(before_path).read_text(encoding="utf-8"))
    after = json.loads(Path(after_path).read_text(encoding="utf-8"))
    properties = before["properties"]
    left, right = before["pages"], after["pages"]

    if set(left) != set(right):
        print("page sets differ:", set(left) ^ set(right))

    total = 0
    per_property: collections.Counter = collections.Counter()
    examples: dict[str, list[str]] = collections.defaultdict(list)

    for key in sorted(set(left) & set(right)):
        rows_before, rows_after = left[key], right[key]
        if len(rows_before) != len(rows_after):
            print(f"{key}: element count {len(rows_before)} -> {len(rows_after)}")
            continue
        for position, (row_before, row_after) in enumerate(zip(rows_before, rows_after)):
            if row_before[0] != row_after[0]:
                print(f"{key}: element {position} changed tag")
                continue
            for offset, prop in enumerate(properties):
                old, new = row_before[offset + 2], row_after[offset + 2]
                if old != new:
                    total += 1
                    per_property[prop] += 1
                    if len(examples[prop]) < 4:
                        examples[prop].append(
                            f"{key} el#{position} <{row_before[0]} class={row_before[1][:60]!r}> "
                            f"{prop}: {old} -> {new}")

    print(f"total differing computed values: {total}")
    for prop, count in per_property.most_common():
        print(f"  {prop:<22} {count}")
        for example in examples[prop]:
            print(f"      {example}")
    return 1 if total else 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "capture":
        return capture(sys.argv[2])
    if len(sys.argv) >= 4 and sys.argv[1] == "diff":
        return diff(sys.argv[2], sys.argv[3])
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
