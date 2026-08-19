import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

from flask import render_template
from flask_login import UserMixin, login_user
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server

os.environ.update(
    APP_ENV="testing",
    SECRET_KEY="phase-2c-visual-qa-secret",
    DATABASE_URL="postgresql+psycopg://localhost/test_db",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app import create_app


OUT = Path(__file__).parent


class QAUser(UserMixin):
    id = 900001
    username = "visual.qa"
    full_name = "Visual QA Admin"
    role = "ADMIN"
    branch_id = 1


user = QAUser()
items = [
    SimpleNamespace(id=1, item_code="PORTAL-DEMO-CANTEEN-ITEM", item_name="Paket Konsumsi Harian Karyawan", category="MERCHANDISE", unit="paket", minimum_stock=1250, selling_price=20000000, is_stock_tracked=True, is_active=True),
    SimpleNamespace(id=2, item_code="RAW-MATERIAL-BERAS-PREMIUM-2026", item_name="Beras Premium Butir Panjang untuk Produksi Dapur Sentral", category="RAW_MATERIAL", unit="kilogram", minimum_stock=123456789.75, selling_price=987654321098, is_stock_tracked=True, is_active=True),
    SimpleNamespace(id=3, item_code="PACKAGING-FOOD-CONTAINER-650ML", item_name="Kotak Makan Food Grade 650 ml", category="PACKAGING", unit="karton-isi-500-pcs", minimum_stock=100, selling_price=2500000, is_stock_tracked=True, is_active=False),
    SimpleNamespace(id=4, item_code="SERVICE-DELIVERY-PALEMBANG", item_name="Jasa Pengiriman Area Palembang dan Sekitarnya", category="SERVICE", unit="pengiriman", minimum_stock=0, selling_price=125000, is_stock_tracked=False, is_active=True),
]
categories = ["RAW_MATERIAL", "PACKAGING", "MERCHANDISE", "SERVICE", "KATEGORI DENGAN LABEL SANGAT PANJANG UNTUK PENGUJIAN RESPONSIVE"]

app = create_app()
app.config.update(TESTING=True, WTF_CSRF_ENABLED=True)
app.login_manager._user_callback = lambda _user_id: user
app.template_context_processors[None] = [fn for fn in app.template_context_processors.get(None, []) if not fn.__name__.startswith("inject_")]


@app.context_processor
def qa_globals():
    return {
        "global_company_settings": SimpleNamespace(company_name="PT Idha Boga Pangan Mandiri"),
        "global_live_reminder_badge": {"total": 0},
        "global_persistent_notification_badge": {"total": 0},
    }


@app.before_request
def qa_login():
    login_user(user, force=True)


def qa_items():
    return render_template("master/items.html", items=items, q="", category="ALL", status="ALL", categories=categories)


app.view_functions["master.items"] = qa_items
server = make_server("127.0.0.1", 0, app, threaded=True)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
url = f"http://127.0.0.1:{server.server_port}/master/items"

measure = """() => {
  const r = (el) => { const x=el.getBoundingClientRect(); return {left:x.left,right:x.right,top:x.top,bottom:x.bottom,width:x.width,height:x.height}; };
  const c = (el) => getComputedStyle(el);
  const wrap=document.querySelector('.ui-table-scroll'), table=document.querySelector('.ui-data-table');
  const code=document.querySelector('tbody .ui-table-cell--sticky-code'), name=document.querySelector('tbody .ui-table-cell--sticky-name'), action=document.querySelector('tbody .ui-table-cell--sticky-actions');
  const primary=document.querySelector('.ui-page-actions .ui-button--primary'), danger=document.querySelector('.ui-row-actions-list .ui-button--danger');
  const codeText=document.querySelector('.ui-table-code'), number=document.querySelector('.ui-table-cell--number'), unit=document.querySelector('.ui-table-unit');
  const shell=document.querySelector('.app-shell'), page=document.querySelector('.ui-master-items-page');
  return {
    viewport:{width:innerWidth,height:innerHeight},
    overflow:{document:document.documentElement.scrollWidth-document.documentElement.clientWidth,shell:shell.scrollWidth-shell.clientWidth,page:page.scrollWidth-page.clientWidth,wrapper:wrap.scrollWidth-wrap.clientWidth},
    scroll:{left:wrap.scrollLeft,max:wrap.scrollWidth-wrap.clientWidth,overflowX:c(wrap).overflowX},
    table:{width:r(table).width,minWidth:c(table).minWidth,layout:c(table).tableLayout},
    sticky:{code:r(code),name:r(name),action:r(action),positions:[c(code).position,c(name).position,c(action).position],noOverlap:r(code).right<=r(name).left+1&&r(name).right<=r(action).left+1},
    content:{code:[c(codeText).whiteSpace,c(codeText).overflow,c(codeText).textOverflow,codeText.title],number:[c(number).whiteSpace,c(number).textAlign],unit:[c(unit).whiteSpace,c(unit).textOverflow]},
    buttons:{primary:[c(primary).backgroundColor,c(primary).color,r(primary).height],danger:[c(danger).backgroundColor,c(danger).color,r(danger).height]},
    csrf:[...document.querySelectorAll('.ui-row-action-form')].every(f=>!!f.querySelector('input[name=csrf_token]'))
  };
}"""

results = {"runtime": url, "cases": {}}


def assert_layout(case):
    assert case["overflow"]["document"] == case["overflow"]["shell"] == case["overflow"]["page"] == 0
    assert case["overflow"]["wrapper"] > 0 and case["scroll"]["overflowX"] == "auto"
    assert case["table"]["layout"] == "fixed" and case["sticky"]["noOverlap"]
    assert case["sticky"]["positions"] == ["sticky", "sticky", "sticky"]
    assert case["content"]["code"][:3] == ["nowrap", "hidden", "ellipsis"] and case["content"]["code"][3]
    assert case["content"]["number"] == ["nowrap", "right"] and case["content"]["unit"][0] == "nowrap"
    assert case["buttons"]["primary"][:2] == ["rgb(22, 101, 52)", "rgb(255, 255, 255)"]
    assert case["buttons"]["danger"][:2] == ["rgb(185, 28, 28)", "rgb(255, 255, 255)"]
    assert case["buttons"]["primary"][2] == 42 and case["buttons"]["danger"][2] in (0, 40) and case["csrf"], case


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)

    def open_page(width, height):
        context = browser.new_context(viewport={"width": width, "height": height})
        page = context.new_page()
        page.goto(url, wait_until="networkidle", timeout=45000)
        page.wait_for_timeout(600)
        return context, page

    context, page = open_page(1440, 1000)
    wrap = page.locator(".ui-table-scroll")
    results["cases"]["desktop_left"] = page.evaluate(measure)
    assert_layout(results["cases"]["desktop_left"])
    page.screenshot(path=str(OUT / "desktop_1440_left.png"), full_page=True)
    max_scroll = wrap.evaluate("el=>el.scrollWidth-el.clientWidth")
    for name, offset in (("desktop_middle", max_scroll / 2), ("desktop_right", max_scroll)):
        wrap.evaluate("(el,x)=>el.scrollLeft=x", offset)
        page.wait_for_timeout(200)
        results["cases"][name] = page.evaluate(measure)
        assert_layout(results["cases"][name])
        page.screenshot(path=str(OUT / ("desktop_1440_middle.png" if name.endswith("middle") else "desktop_1440_right.png")), full_page=True)
    wrap.evaluate("el=>el.scrollLeft=0")
    category_trigger = page.locator("#ui-master-items-category").locator("xpath=following-sibling::*[contains(@class, 'ui-select-enhanced')]//*[contains(@class, 'ui-select-trigger')]")
    category_trigger.click()
    page.wait_for_timeout(250)
    menu_id = category_trigger.get_attribute("aria-controls")
    menu = page.locator("#" + menu_id)
    results["cases"]["dropdown"] = {
        "visible": menu.is_visible(),
        "bounds": menu.evaluate("el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,within:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight}}"),
        "background": menu.evaluate("el=>getComputedStyle(el).backgroundColor"),
        "alignments": menu.locator(".ui-select-option").evaluate_all("els=>[...new Set(els.map(el=>getComputedStyle(el).textAlign))]"),
        "optionsNoOverlap": menu.locator(".ui-select-option").evaluate_all("els=>els.every((el,i)=>!i||els[i-1].getBoundingClientRect().bottom<=el.getBoundingClientRect().top)"),
        "labels": menu.locator(".ui-select-option-label").all_inner_texts(),
    }
    assert results["cases"]["dropdown"]["visible"] and results["cases"]["dropdown"]["bounds"]["within"]
    assert results["cases"]["dropdown"]["background"] == "rgb(255, 255, 255)"
    assert results["cases"]["dropdown"]["alignments"] == ["left"] and results["cases"]["dropdown"]["optionsNoOverlap"]
    page.screenshot(path=str(OUT / "desktop_1440_dropdown_open.png"), full_page=True)
    context.close()

    for name, width, height, filename in (
        ("tablet", 768, 900, "tablet_768.png"),
        ("zoom80_equivalent", 1800, 1000, "desktop_1440_zoom80_equivalent.png"),
    ):
        context, page = open_page(width, height)
        results["cases"][name] = page.evaluate(measure)
        assert_layout(results["cases"][name])
        page.screenshot(path=str(OUT / filename), full_page=True)
        context.close()

    context, page = open_page(390, 844)
    results["cases"]["mobile"] = page.evaluate(measure)
    assert_layout(results["cases"]["mobile"])
    page.screenshot(path=str(OUT / "mobile_390.png"), full_page=True)
    trigger = page.locator("[data-ui-action-menu-trigger]").first
    trigger.scroll_into_view_if_needed()
    trigger.click()
    page.wait_for_timeout(250)
    menu = page.locator(".ui-action-menu-popover")
    results["cases"]["mobile_actions"] = {
        "visible": menu.is_visible(),
        "bounds": menu.evaluate("el=>{const r=el.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,within:r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight}}"),
        "labels": menu.locator(".ui-button-label").all_inner_texts(),
        "danger": menu.locator(".ui-button--danger").evaluate("el=>[getComputedStyle(el).backgroundColor,getComputedStyle(el).color]"),
        "forms": menu.locator("form").evaluate_all("fs=>fs.map(f=>({method:f.method,action:f.action,csrf:!!f.querySelector('input[name=csrf_token]'),confirm:f.dataset.appConfirm||''}))"),
    }
    assert results["cases"]["mobile_actions"]["visible"] and results["cases"]["mobile_actions"]["bounds"]["within"]
    assert results["cases"]["mobile_actions"]["labels"] == ["Edit", "Nonaktif", "Hapus"]
    assert results["cases"]["mobile_actions"]["danger"] == ["rgb(185, 28, 28)", "rgb(255, 255, 255)"]
    assert all(form["method"] == "post" and form["csrf"] for form in results["cases"]["mobile_actions"]["forms"])
    page.screenshot(path=str(OUT / "mobile_390_actions_open.png"), full_page=False)
    menu.locator(".ui-button--danger").click()
    page.wait_for_timeout(250)
    dialog = page.locator(".app-atomic-dialog-root.is-visible")
    results["cases"]["delete_confirm"] = {"visible": dialog.is_visible(), "message": dialog.locator(".app-atomic-dialog-message").inner_text()}
    assert results["cases"]["delete_confirm"]["visible"] and "menghapus item" in results["cases"]["delete_confirm"]["message"]
    page.screenshot(path=str(OUT / "mobile_390_delete_confirm.png"), full_page=False)
    context.close()
    browser.close()

server.shutdown()
thread.join(timeout=5)
(OUT / "qa_results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
print(json.dumps(results, indent=2))
