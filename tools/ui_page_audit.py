#!/usr/bin/env python3
"""Potret dan periksa setiap halaman aplikasi dengan data gladi.

Menjalankan aplikasi di thread sendiri (port 5099, bukan server dev) terhadap
database gladi, login sebagai OWNER dan akun portal, lalu membuka setiap route
GET. Hanya membaca: tidak ada form yang dikirim.

Untuk setiap halaman x lebar layar (desktop 1440, HP 390):
- potret satu layar penuh ke <out>/<viewport>/<nama>.png;
- pemeriksa otomatis (lihat AUDIT_JS): teks dengan kontras < 3:1 terhadap
  latarnya, teks tak terlihat (warna = latar atau opacity 0), dan halaman yang
  meluber ke samping (scrollWidth > lebar layar).
Ringkasan ditulis ke <out>/report.json dan dicetak.

    python tools/ui_page_audit.py --out instance/ui_audit/before
    python tools/ui_page_audit.py --out instance/ui_audit/after --only dashboard.owner finance.invoices

Butuh database gladi (tools/pilot_dry_run.py) atau database demo
(tools/seed_demo_data.py, --db idha_boga_demotest). Halaman detail dibuka
dengan id nyata dari data (DETAIL_IDS), bukan id 1.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

PORT = 5099
BASE = f"http://127.0.0.1:{PORT}"
VIEWPORTS = {"desktop": {"width": 1440, "height": 900}, "mobile": {"width": 390, "height": 844}}
# Peran -> (username, password) per jenis database.
ACCOUNT_SETS = {
    "pilot": {
        "owner": ("owner.pilot", os.environ.get("PILOT_OWNER_PASSWORD", "PilotOwner#2026")),
        "pt": ("portal.maju", "PilotUser#2026"),
        "mandor": ("mandor.budi", "PilotUser#2026"),
        "customer": ("rina.cust", "PilotUser#2026"),
        "driver": ("antar.pilot", "PilotUser#2026"),
        "ops": ("ops.pilot", "PilotUser#2026"),
    },
    "demo": {
        "owner": ("owner", os.environ.get("DEMO_OWNER_PASSWORD", "DemoOwner#2026")),
        "pt": ("portal.pt.local", "IdhaBoga#2026"),
        "mandor": ("portal.mandor.local", "IdhaBoga#2026"),
        "customer": ("portal.customer.local", "IdhaBoga#2026"),
    },
}
# Halaman detail: SQL yang mengembalikan id (urut sesuai argumen route) dari
# data yang representatif. Endpoint yang tidak terdaftar mencoba id 1.
DETAIL_IDS = {
    "accounting.journal_detail": "SELECT max(id) FROM journals",
    "accounting.period_closing_detail": "SELECT max(id) FROM period_closings",
    "canteen.debt_payment": "SELECT max(id) FROM worker_debts WHERE status <> 'PAID'",
    "canteen.external_receivable_payment": "SELECT max(id) FROM canteen_external_receivables",
    "costing.edit_menu": "SELECT min(id) FROM menus",
    "costing.menu_recipe": "SELECT min(id) FROM menus",
    "costing.edit_overhead_profile": "SELECT min(id) FROM overhead_profiles",
    "costing.edit_packaging_profile": "SELECT min(id) FROM packaging_profiles",
    "credit.account_detail": "SELECT min(id) FROM credit_accounts",
    "credit.mandor_settings": "SELECT min(id) FROM mandors",
    "customer_success.complaint_detail": "SELECT max(id) FROM customer_complaints",
    "customer_success.contract_detail": "SELECT min(id) FROM customer_contracts",
    "delivery.detail": "SELECT max(delivery_id) FROM delivery_details",
    "delivery.receive": "SELECT max(id) FROM delivery_details",
    "field_transactions.detail": "SELECT max(id) FROM field_transactions",
    "field_transactions.edit": "SELECT max(id) FROM field_transactions",
    "finance.advance_detail": "SELECT max(id) FROM advance_transactions",
    "finance.cash_bank_transaction_detail": "SELECT max(id) FROM cash_bank_transactions",
    "finance.fixed_asset_depreciation_configure": "SELECT min(id) FROM fixed_assets",
    "finance.fixed_asset_installment_detail": "SELECT min(id) FROM asset_financing_contracts",
    "finance.fixed_asset_purchase_detail": "SELECT min(id) FROM fixed_asset_purchases",
    "finance.invoice_detail": "SELECT max(invoice_id) FROM payments",
    "finance.invoice_profit_detail": "SELECT max(id) FROM invoices WHERE source_type = 'PERIOD_INVOICE'",
    "finance.manual_billing_batch_detail": "SELECT max(id) FROM manual_billing_batches",
    "finance.edit_manual_billing_backfill_batch": "SELECT max(id) FROM manual_billing_batches",
    "finance.operational_expense_detail": "SELECT max(id) FROM operational_expenses",
    "finance.payment_receipt": "SELECT max(id) FROM payments",
    "finance.supplier_bill_detail": "SELECT max(id) FROM supplier_bills",
    "finance.transport_expense_detail": "SELECT max(id) FROM transport_vehicle_expenses",
    "hr.edit_employee": "SELECT min(id) FROM employees",
    "hr.payroll_detail": "SELECT max(id) FROM payrolls",
    "logistics.item_request_detail": "SELECT max(id) FROM item_requests",
    "logistics.item_card": "SELECT min(id) FROM items",
    "logistics.purchase_detail": "SELECT max(id) FROM procurements",
    "master.edit_bank_account": "SELECT min(id) FROM bank_accounts",
    "master.edit_client": "SELECT min(id) FROM clients",
    "master.edit_driver": "SELECT min(id) FROM drivers",
    "master.edit_fixed_asset": "SELECT min(id) FROM fixed_assets",
    "master.edit_item_cost_profile": "SELECT min(id) FROM items",
    "master.edit_item": "SELECT min(id) FROM items",
    "master.edit_location": "SELECT min(id) FROM delivery_locations",
    "master.edit_mandor": "SELECT min(id) FROM mandors",
    "master.edit_supplier": "SELECT min(id) FROM suppliers",
    "master.edit_worker": "SELECT min(id) FROM workers",
    "operational.create_revision": "SELECT max(id) FROM daily_order_details",
    "operational.order_detail": "SELECT max(daily_order_id) FROM order_hpp_snapshots",
    "operational.add_order_detail": "SELECT max(id) FROM daily_orders WHERE status = 'DRAFT'",
    "operational.update_order_hpp_defaults_route": "SELECT max(id) FROM daily_orders WHERE status = 'DRAFT'",
    "operational.order_hpp_snapshot_detail": "SELECT daily_order_id, id FROM order_hpp_snapshots ORDER BY id DESC LIMIT 1",
    "operational.order_hpp_snapshot_stock_dry_run": "SELECT daily_order_id, id FROM order_hpp_snapshots ORDER BY id DESC LIMIT 1",
    "operational.create_order_hpp_snapshot_route": "SELECT max(id) FROM daily_orders WHERE status = 'LOCKED'",
    "portal.invoice_payment_instruction": "SELECT max(id) FROM invoices WHERE customer_path = 'KONTRAK'",
    "production.detail": "SELECT max(id) FROM productions",
    "settings.audit_log_detail": "SELECT max(id) FROM audit_logs",
    "settings.digital_attachment_detail": "SELECT max(id) FROM digital_attachments",
    "settings.edit_user_page": "SELECT min(id) FROM users WHERE role <> 'OWNER'",
}
# Route yang tidak dibuka: unduhan, keluar, aksi GET yang mengubah sesuatu, API.
SKIP = re.compile(r"(export|download|logout|print|\.csv|\.json|/api/|static|toggle|delete|generate|confirm|lock|reset|restore|backup/create|/view$|preview$|healthz?)", re.I)

AUDIT_JS = r"""
() => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
    const p = m[1].split(',').map(s => parseFloat(s)); return {r:p[0], g:p[1], b:p[2], a: p.length > 3 ? p[3] : 1}; };
  const lum = (c) => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
  const bgOf = (el) => { let e = el; while (e && e.nodeType === 1) { const s = getComputedStyle(e);
      if (s.backgroundImage && s.backgroundImage !== 'none') return null;
      const c = parse(s.backgroundColor); if (c && c.a > 0.9) return c; e = e.parentElement; } return {r:255,g:255,b:255,a:1}; };
  const issues = [];
  const seen = new Set();
  for (const el of document.querySelectorAll('body *')) {
    if (!el.offsetParent && getComputedStyle(el).position !== 'fixed') continue;
    const text = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent.trim()).join(' ').trim();
    if (!text) continue;
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) continue;
    const fg = parse(s.color); const bg = bgOf(el);
    if (!fg || !bg) continue;
    let opacity = 1; let e = el; while (e && e.nodeType === 1) { opacity *= parseFloat(getComputedStyle(e).opacity); e = e.parentElement; }
    const a = fg.a * opacity;
    const blend = {r: fg.r * a + bg.r * (1 - a), g: fg.g * a + bg.g * (1 - a), b: fg.b * a + bg.b * (1 - a)};
    const l1 = lum(blend), l2 = lum(bg);
    const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
    const large = parseFloat(s.fontSize) >= 18 || (parseFloat(s.fontSize) >= 14 && parseInt(s.fontWeight) >= 700);
    const limit = large ? 3 : 4.5;
    if (ratio < limit) {
      const key = el.tagName + '.' + (el.className || '') + ':' + text.slice(0, 30);
      if (seen.has(key)) continue; seen.add(key);
      issues.push({kind: ratio < 1.5 ? 'invisible' : 'contrast', ratio: Math.round(ratio * 100) / 100,
                   el: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string' ? '.' + el.className.trim().split(/\s+/).slice(0, 3).join('.') : ''),
                   text: text.slice(0, 60)});
    }
  }
  const overflow = document.documentElement.scrollWidth - window.innerWidth;
  // Elemen terdalam yang menjorok keluar layar, di luar wadah bergulir.
  const culprits = [];
  if (overflow > 2) {
    const clipped = (el) => { for (let p = el.parentElement; p; p = p.parentElement) {
      if (['auto', 'scroll', 'hidden', 'clip'].includes(getComputedStyle(p).overflowX)) return true; } return false; };
    const sticksOut = (el) => el.getBoundingClientRect().right > window.innerWidth + 1;
    for (const el of document.querySelectorAll('body *')) {
      if (!sticksOut(el) || clipped(el) || Array.from(el.children).some(sticksOut)) continue;
      const cls = typeof el.className === 'string' ? el.className.trim().split(/\s+/).slice(0, 3).join('.') : '';
      culprits.push(el.tagName.toLowerCase() + (cls ? '.' + cls : '') + ' +' + Math.round(el.getBoundingClientRect().right - window.innerWidth) + 'px');
      if (culprits.length >= 5) break;
    }
  }
  return {issues: issues.slice(0, 40), issue_count: issues.length, overflow_px: overflow > 2 ? overflow : 0, overflow_culprits: culprits,
          title: (document.querySelector('h1') || {}).innerText || document.title};
}
"""


def _detail_ids(app, endpoint):
    from sqlalchemy import text

    from app.extensions import db

    sql = DETAIL_IDS.get(endpoint)
    if not sql:
        return None
    with app.app_context():
        try:
            row = db.session.execute(text(sql)).first()
        except Exception:
            db.session.rollback()
            return None
    return [str(value) for value in row] if row and all(value is not None for value in row) else None


def _routes(app):
    """Route GET yang bisa dibuka: tanpa parameter, atau dengan id angka dari data."""
    rows = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or SKIP.search(rule.rule) or SKIP.search(rule.endpoint):
            continue
        args = list(rule.arguments)
        if any(rule._converters[a].__class__.__name__ != "IntegerConverter" for a in args):
            continue
        url = rule.rule
        ids = _detail_ids(app, rule.endpoint) if args else None
        for index, arg in enumerate(re.findall(r"<int:(\w+)>", rule.rule)):
            url = url.replace(f"<int:{arg}>", ids[index] if ids and index < len(ids) else "1")
        rows.append((rule.endpoint, url))
    return sorted(set(rows))


def _account_for(endpoint):
    if endpoint.startswith("portal.pt") or endpoint in ("portal.client_dashboard", "portal.invoice_payment_instruction"):
        return "pt"
    if endpoint.startswith("portal.mandor") or endpoint in ("portal.order_status", "portal.draft_order"):
        return "mandor"
    if endpoint.startswith("portal.customer"):
        return "customer"
    return "owner"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "instance" / "ui_audit" / "current")
    parser.add_argument("--db", default="idha_boga_pilot")
    parser.add_argument("--only", nargs="*", help="Hanya endpoint ini.")
    parser.add_argument("--viewports", nargs="*", default=list(VIEWPORTS))
    parser.add_argument("--full", action="store_true", help="Potret satu halaman penuh, bukan hanya layar pertama.")
    parser.add_argument("--account", help="Paksa semua halaman dibuka akun ini (mis. driver), bukan pilihan otomatis.")
    args = parser.parse_args()
    if not re.search(r"pilot|gladi|demo", args.db):
        raise SystemExit("Hanya untuk database gladi/demo.")
    accounts = ACCOUNT_SETS["demo" if "demo" in args.db else "pilot"]

    from dotenv import dotenv_values

    base = os.environ.get("DATABASE_URL") or dotenv_values(ROOT / ".env").get("DATABASE_URL")
    os.environ["DATABASE_URL"] = base.rsplit("/", 1)[0] + "/" + args.db

    from playwright.sync_api import sync_playwright
    from werkzeug.serving import make_server

    from app import create_app

    app = create_app()
    app.config.update(WTF_CSRF_ENABLED=False, RATELIMIT_ENABLED=False)
    server = make_server("127.0.0.1", PORT, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    routes = [row for row in _routes(app) if not args.only or row[0] in args.only]
    by_account = {}
    for endpoint, url in routes:
        by_account.setdefault(args.account or _account_for(endpoint), []).append((endpoint, url))

    report = {}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for viewport_name in args.viewports:
                out_dir = args.out / viewport_name
                out_dir.mkdir(parents=True, exist_ok=True)
                for account, pages in by_account.items():
                    context = browser.new_context(viewport=VIEWPORTS[viewport_name], reduced_motion="reduce")
                    page = context.new_page()
                    js_errors = []
                    page.on("pageerror", lambda error: js_errors.append(str(error)[:200]))
                    page.goto(f"{BASE}/auth/login")
                    page.fill("input[name=username]", accounts[account][0])
                    page.fill("input[name=password]", accounts[account][1])
                    page.click("button[type=submit]")
                    page.wait_for_load_state("networkidle")
                    for endpoint, url in pages:
                        js_errors.clear()
                        try:
                            response = page.goto(f"{BASE}{url}")
                            page.wait_for_load_state("networkidle")
                            page.wait_for_timeout(150)
                            status = response.status if response else 0
                            final = page.url.replace(BASE, "")
                            result = page.evaluate(AUDIT_JS) if status == 200 else {"issues": [], "issue_count": 0, "overflow_px": 0}
                            page.screenshot(path=str(out_dir / f"{endpoint}.png"), full_page=args.full)
                        except Exception as error:  # halaman yang gagal dibuka tetap dilaporkan
                            status, final, result = 0, "", {"error": str(error)[:200], "issues": [], "issue_count": 0, "overflow_px": 0}
                        report.setdefault(endpoint, {})[viewport_name] = {"url": url, "status": status, "final_url": final,
                                                                          "js_errors": list(js_errors), **result}
                    context.close()
                    time.sleep(1)
        finally:
            browser.close()
            server.shutdown()

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    pages_ok = sum(1 for row in report.values() for vp in row.values() if vp.get("status") == 200)
    contrast = sum(vp.get("issue_count", 0) for row in report.values() for vp in row.values())
    invisible = sum(1 for row in report.values() for vp in row.values() for issue in vp.get("issues", []) if issue["kind"] == "invisible")
    overflow = sum(1 for row in report.values() for vp in row.values() if vp.get("overflow_px"))
    js_broken = sorted({endpoint for endpoint, row in report.items() for vp in row.values() if vp.get("js_errors")})
    errors = [(endpoint, vp_name, vp.get("status")) for endpoint, row in report.items() for vp_name, vp in row.items() if vp.get("status") not in (200, 302)]
    print(f"{len(report)} halaman, {pages_ok} tampil (200). Kontras rendah: {contrast} teks ({invisible} nyaris tak terlihat). "
          f"Meluber ke samping: {overflow} tampilan. Gagal dibuka: {len(errors)}. Error JavaScript: {len(js_broken)} halaman")
    for endpoint in js_broken:
        print("  error JS:", endpoint, next(vp["js_errors"][0] for vp in report[endpoint].values() if vp.get("js_errors")))
    for row in errors[:30]:
        print("  gagal:", *row)


if __name__ == "__main__":
    main()
