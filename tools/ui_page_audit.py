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

Butuh database gladi yang sudah diisi tools/pilot_dry_run.py.
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
ACCOUNTS = {
    "owner.pilot": os.environ.get("PILOT_OWNER_PASSWORD", "PilotOwner#2026"),
    "portal.maju": "PilotUser#2026",
    "mandor.budi": "PilotUser#2026",
    "rina.cust": "PilotUser#2026",
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


def _routes(app):
    """Route GET yang bisa dibuka: tanpa parameter, atau dengan id angka (dicoba 1)."""
    rows = []
    for rule in app.url_map.iter_rules():
        if "GET" not in rule.methods or SKIP.search(rule.rule) or SKIP.search(rule.endpoint):
            continue
        args = list(rule.arguments)
        if any(rule._converters[a].__class__.__name__ != "IntegerConverter" for a in args):
            continue
        url = rule.rule
        for arg in args:
            url = url.replace(f"<int:{arg}>", "1")
        rows.append((rule.endpoint, url))
    return sorted(set(rows))


def _account_for(endpoint):
    if endpoint.startswith("portal.pt") or endpoint in ("portal.client_dashboard",):
        return "portal.maju"
    if endpoint.startswith("portal.mandor") or endpoint in ("portal.order_status", "portal.draft_order"):
        return "mandor.budi"
    if endpoint.startswith("portal.customer"):
        return "rina.cust"
    return "owner.pilot"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "instance" / "ui_audit" / "current")
    parser.add_argument("--db", default="idha_boga_pilot")
    parser.add_argument("--only", nargs="*", help="Hanya endpoint ini.")
    parser.add_argument("--viewports", nargs="*", default=list(VIEWPORTS))
    parser.add_argument("--full", action="store_true", help="Potret satu halaman penuh, bukan hanya layar pertama.")
    args = parser.parse_args()
    if not re.search(r"pilot|gladi", args.db):
        raise SystemExit("Hanya untuk database gladi.")

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
        by_account.setdefault(_account_for(endpoint), []).append((endpoint, url))

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
                    page.goto(f"{BASE}/auth/login")
                    page.fill("input[name=username]", account)
                    page.fill("input[name=password]", ACCOUNTS[account])
                    page.click("button[type=submit]")
                    page.wait_for_load_state("networkidle")
                    for endpoint, url in pages:
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
                        report.setdefault(endpoint, {})[viewport_name] = {"url": url, "status": status, "final_url": final, **result}
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
    errors = [(endpoint, vp_name, vp.get("status")) for endpoint, row in report.items() for vp_name, vp in row.items() if vp.get("status") not in (200, 302)]
    print(f"{len(report)} halaman, {pages_ok} tampil (200). Kontras rendah: {contrast} teks ({invisible} nyaris tak terlihat). "
          f"Meluber ke samping: {overflow} tampilan. Gagal dibuka: {len(errors)}")
    for row in errors[:30]:
        print("  gagal:", *row)


if __name__ == "__main__":
    main()
