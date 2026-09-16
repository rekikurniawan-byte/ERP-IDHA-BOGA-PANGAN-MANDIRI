#!/usr/bin/env python3
"""Count elements matching given selectors across every discoverable page.

A rule is inert exactly when nothing matches its selector, so for the question
"can this rule ever apply?" this is both the direct test and a much cheaper
one than tools/visual_baseline/computed_fingerprint.py: it needs one
querySelectorAll per selector instead of getComputedStyle on every element.
Use the fingerprint to prove a change is a no-op; use this to decide whether
a rule is worth changing at all.

Controls are mandatory, not decoration. Pass selectors you are confident are
live via --control; if those also come back zero the probe itself is broken,
and the tool says so instead of reporting everything as dead. This exists
because an earlier coverage gap in the fingerprint produced a confident
"no change" for five files that in fact set the portal topbar height.

Zero matches is where the thinking starts, not where it ends. A probe cannot
distinguish "no such markup exists" from "the markup exists but this data
never renders it", so every unmatched selector is triaged into three groups:
dependent on emptiness (:empty, empty-state siblings), referenced in a
template or script and therefore merely conditional, or referenced nowhere.
Only the last group is actionable.

That triage is not bookkeeping. Probing the four files the effective-rules map
scored 87-89% "idle" returned 43 unmatched selectors, of which 8 depended on
emptiness and 35 were conditional -- and zero were real candidates. Acting on
the raw list would have deleted the shared global filter bar, the zero-state
component and the empty-table styling.

Still bounded even then: coverage is the GET pages the url_map exposes that
answer 200 for the roles given, and markup built by JS only after an
interaction is never represented.

Usage:
    python tools/css_selector_liveness.py --control ".app-card" \\
        ".example-card.highlight" ".example-card.danger"

    python tools/css_selector_liveness.py --from-file selectors.txt \\
        --control ".app-card" --control ".btn"

Needs the dev server and its database running, plus the dev extras:
    pip install -r requirements-dev.txt && python -m playwright install chromium
"""
from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from visual_baseline.computed_fingerprint import (  # noqa: E402
    BASE_URL, FREEZE_CSS, THEMES, _session_cookie, discover_pages,
)

COUNT_JS = """(selectors) => {
  const out = {};
  for (const selector of selectors) {
    try { out[selector] = document.querySelectorAll(selector).length; }
    catch (error) { out[selector] = -1; }
  }
  return out;
}"""


CLASS_IN_SELECTOR = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
# Selectors that only match when something is absent: :empty, and the sibling
# combinators used to style an empty-state block that follows a table.
EMPTINESS_DEPENDENT = re.compile(r":empty\b|\+\s*\.|~\s*\.")
SOURCE_GLOBS = ("app/templates/**/*.html", "app/static/js/**/*.js", "app/**/*.py")


def triage_unmatched(selectors: list[str]):
    """Split 'matched nothing' into why, because the why decides everything.

    Measured on this codebase: of 43 selectors that matched nothing across
    1,988 page visits, 8 depended on emptiness and 35 were rendered
    conditionally. Zero were actually unreferenced. Reporting all 43 as dead
    would have invited deleting live markup.
    """
    blobs = []
    for pattern in SOURCE_GLOBS:
        for path in ROOT.glob(pattern):
            if path.is_file():
                try:
                    blobs.append(path.read_text(encoding="utf-8", errors="replace"))
                except OSError:
                    pass

    empty_dependent, referenced, candidates = [], [], []
    for selector in selectors:
        if EMPTINESS_DEPENDENT.search(selector):
            empty_dependent.append(selector)
            continue
        found = None
        for name in CLASS_IN_SELECTOR.findall(selector):
            pattern = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")
            if any(pattern.search(blob) for blob in blobs):
                found = name
                break
        if found:
            referenced.append((selector, f"'{found}' appears in source"))
        else:
            candidates.append(selector)
    return empty_dependent, referenced, candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("selectors", nargs="*", help="selectors to test")
    parser.add_argument("--from-file", help="file with one selector per line")
    parser.add_argument("--control", action="append", default=[],
                        help="selector known to be live; repeatable, required")
    parser.add_argument("--themes", default=",".join(THEMES),
                        help="comma-separated colour schemes to visit")
    parser.add_argument("--role", action="append", default=[],
                        help="authenticate as a user with this role; repeatable. "
                             "Defaults to OWNER. Whole template families are "
                             "role-gated -- the portal role dashboards own all "
                             "the .portal-home-* markup and an OWNER session "
                             "never renders any of it.")
    return parser.parse_args()


def main() -> int:
    from playwright.sync_api import sync_playwright

    args = parse_args()
    selectors = list(args.selectors)
    if args.from_file:
        selectors += [line.strip() for line in
                      Path(args.from_file).read_text(encoding="utf-8").splitlines()
                      if line.strip() and not line.startswith("#")]
    if not selectors:
        print("no selectors given", file=sys.stderr)
        return 2
    if not args.control:
        print("refusing to run without at least one --control selector; see the "
              "module docstring for why", file=sys.stderr)
        return 2

    probe = selectors + args.control
    roles = args.role or ["OWNER"]
    pages = discover_pages()
    print(f"probing {len(selectors)} selectors and {len(args.control)} controls "
          f"across {len(pages)} pages as {', '.join(roles)}", file=sys.stderr)

    hits: collections.Counter = collections.Counter()
    pages_seen: dict[str, set[str]] = collections.defaultdict(set)
    invalid: set[str] = set()
    visited = 0

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for role in roles:
            cookie = _session_cookie(role)
            for theme in args.themes.split(","):
                context = browser.new_context(viewport={"width": 1440, "height": 900},
                                              color_scheme=theme.strip())
                context.add_cookies([{"name": "session", "value": cookie,
                                      "domain": "127.0.0.1", "path": "/"}])
                page = context.new_page()
                for name, path in pages:
                    try:
                        response = page.goto(BASE_URL + path,
                                             wait_until="domcontentloaded", timeout=45000)
                        if not response or response.status != 200:
                            continue
                        page.add_style_tag(content=FREEZE_CSS)
                        page.wait_for_timeout(250)
                        visited += 1
                        for selector, count in page.evaluate(COUNT_JS, probe).items():
                            if count < 0:
                                invalid.add(selector)
                            elif count:
                                hits[selector] += count
                                pages_seen[selector].add(f"{role}:{name}")
                    except Exception as error:  # noqa: BLE001
                        print(f"error {role} {path}: {str(error)[:80]}", file=sys.stderr)
                context.close()
        browser.close()

    print()
    print(f"page visits that returned 200: {visited} "
          f"(roles: {', '.join(roles)})")
    print()
    print("controls:")
    dead_controls = []
    for selector in args.control:
        print(f"  {selector:<48} {hits[selector]:>7} matches "
              f"on {len(pages_seen[selector])} pages")
        if not hits[selector]:
            dead_controls.append(selector)
    if dead_controls:
        print()
        print("ABORT: these controls matched nothing, so the probe is not measuring")
        print("what it claims. Treat every result below as unusable.")
        for selector in dead_controls:
            print(f"  {selector}")
        return 1

    if invalid:
        print()
        print("selectors the browser rejected as invalid:")
        for selector in sorted(invalid):
            print(f"  {selector}")

    live = [s for s in selectors if hits[s]]
    unmatched = [s for s in selectors if not hits[s] and s not in invalid]
    print()
    print(f"reachable ({len(live)}):")
    for selector in live:
        where = sorted(pages_seen[selector])
        shown = ", ".join(where[:3]) + (f", +{len(where) - 3} more" if len(where) > 3 else "")
        print(f"  {selector:<48} {hits[selector]:>7} on {shown}")

    empty_dependent, referenced, candidates = triage_unmatched(unmatched)

    print()
    print(f"matched nothing, but DEPENDS ON EMPTINESS ({len(empty_dependent)}) -- "
          "alive, merely not triggered by seeded data:")
    for selector in empty_dependent:
        print(f"  {selector}")
    print()
    print(f"matched nothing, but RENDERED CONDITIONALLY ({len(referenced)}) -- "
          "the class exists in a template or script:")
    for selector, where in referenced:
        print(f"  {selector:<48} {where}")
    print()
    print(f"matched nothing and REFERENCED NOWHERE ({len(candidates)}) -- "
          "the only real candidates:")
    for selector in candidates:
        print(f"  {selector}")
    print()
    print("Only the last group is actionable. A probe cannot tell 'no such markup'")
    print("from 'the markup exists but this data never renders it' -- an :empty")
    print("rule, an empty-state sibling, or anything inside a Jinja conditional")
    print("matches nothing on a seeded database while being entirely alive.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
