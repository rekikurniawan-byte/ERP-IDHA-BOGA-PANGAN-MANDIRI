#!/usr/bin/env python3
"""Screenshot the CSS component-gallery fixture as a visual-regression net.

Why: the real app needs PostgreSQL + an authenticated session to render any
page, which isn't always available while iterating on CSS. This captures the
static fixture in tools/visual_baseline/fixtures/component_gallery.html --
real markup, real compiled app/static/css/style.css -- across both themes and
two viewport widths.

Usage:
    python tools/visual_baseline/capture.py --out baseline   # first run, before changes
    python tools/visual_baseline/capture.py --out current    # after a CSS change
    python tools/visual_baseline/compare.py                  # diff baseline vs current

Run `python tools/build_css.py` first so style.css reflects the latest source.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tools" / "visual_baseline" / "fixtures" / "component_gallery.html"

THEMES = ["light-mono", "dark-mono"]
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}


def capture(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fixture_url = FIXTURE.as_uri()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for theme in THEMES:
                for viewport_name, viewport in VIEWPORTS.items():
                    page = browser.new_page(viewport=viewport)
                    page.goto(f"{fixture_url}?theme={theme}")
                    page.wait_for_load_state("networkidle")
                    shot_path = out_dir / f"{theme}_{viewport_name}.png"
                    page.screenshot(path=str(shot_path), full_page=True)
                    page.close()
                    print(f"captured {shot_path.relative_to(ROOT)}")
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default="baseline",
        help="Subfolder under tools/visual_baseline/ to write screenshots into (default: baseline)",
    )
    args = parser.parse_args()

    if not FIXTURE.exists():
        print(f"Fixture not found: {FIXTURE}")
        return 1

    out_dir = ROOT / "tools" / "visual_baseline" / args.out
    capture(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
