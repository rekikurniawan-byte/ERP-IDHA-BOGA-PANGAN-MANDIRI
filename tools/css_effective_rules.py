#!/usr/bin/env python3
"""Report which CSS declarations actually win the cascade on real pages.

tools/css_dead_declarations.py can only judge rules that share a selector set.
Most of what is left in the numbered _lock/_fix files is overridden by a LATER
rule with a DIFFERENT selector, which needs the real cascade to settle. This
walks the rendered pages and, for every element and property, works out which
declaration wins, then reports per source file how much of it ever wins.

Read the output as a PRIORITY MAP, not a delete list. "Never wins here" is
evidence about the pages captured, not proof about the app: only ~31 of 260
templates render in this harness. Anything acted on still needs its own
before/after run of tools/visual_baseline/computed_fingerprint.py, and
ideally on pages that were not used to produce the candidate.

Specificity follows the usual (id, class, type) counting. :where() counts
zero; :is()/:not()/:has() take the highest specificity among their arguments.
Rules inside @media are only considered when that query currently matches, so
each viewport/theme is measured on its own.

Usage:
    python tools/css_effective_rules.py            # all sources, summary
    python tools/css_effective_rules.py 150 167    # only files numbered 150-167
"""
from __future__ import annotations

import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from visual_baseline.computed_fingerprint import (  # noqa: E402
    BASE_URL, PUBLIC_PAGES, THEMES, VIEWPORTS, FREEZE_CSS,
    _session_cookie, discover_pages,
)

# Returns [[sourceHref, ruleIndexInSheet, selectorText, property, winCount], ...]
ANALYSE_JS = r"""
() => {
  const SPEC = sel => {
    let a = 0, b = 0, c = 0;
    let s = sel;
    // strip and score functional pseudo-classes first
    s = s.replace(/:where\([^()]*\)/g, ' ');
    const funcs = s.match(/:(is|not|has)\(([^()]*)\)/g) || [];
    for (const f of funcs) {
      const inner = f.slice(f.indexOf('(') + 1, -1);
      let best = [0, 0, 0];
      for (const part of inner.split(',')) {
        const sub = SPEC(part.trim());
        if (sub[0] > best[0] || (sub[0] === best[0] && sub[1] > best[1]) ||
            (sub[0] === best[0] && sub[1] === best[1] && sub[2] > best[2])) best = sub;
      }
      a += best[0]; b += best[1]; c += best[2];
    }
    s = s.replace(/:(is|not|has)\([^()]*\)/g, ' ');
    a += (s.match(/#[\w-]+/g) || []).length;
    b += (s.match(/\.[\w-]+/g) || []).length;
    b += (s.match(/\[[^\]]*\]/g) || []).length;
    b += (s.match(/:[a-zA-Z-]+(?!\()/g) || []).length;
    s = s.replace(/#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[a-zA-Z-]+/g, ' ');
    c += (s.match(/\b[a-zA-Z][\w-]*\b/g) || []).length;
    return [a, b, c];
  };

  const decls = [];   // {href, ruleOrdinal, selector, prop, important, spec, order}
  let order = 0;

  // ruleOrdinal counts style rules per sheet in document order, exactly as a
  // linear scan of the file would, so Python can map it back to a source file
  // via the BEGIN/END SOURCE markers the build writes.
  const walk = (rules, href, mediaOK, counter) => {
    for (let i = 0; i < rules.length; i++) {
      const r = rules[i];
      if (r.type === CSSRule.KEYFRAMES_RULE || r.constructor.name === 'CSSKeyframesRule') continue;
      if (r.media) {
        let ok = true;
        try { ok = window.matchMedia(r.conditionText || r.media.mediaText).matches; }
        catch (e) { ok = true; }
        if (r.cssRules) walk(r.cssRules, href, mediaOK && ok, counter);
        continue;
      }
      if (r.cssRules && !r.selectorText) { walk(r.cssRules, href, mediaOK, counter); continue; }
      if (!r.selectorText) continue;
      const ordinal = counter.n++;
      const idx = order++;
      if (!mediaOK) continue;
      for (const part of r.selectorText.split(',')) {
        const sel = part.trim();
        if (!sel) continue;
        let els;
        try { els = document.querySelectorAll(sel); } catch (e) { continue; }
        if (!els.length) continue;
        const spec = SPEC(sel);
        for (let p = 0; p < r.style.length; p++) {
          const prop = r.style[p];
          decls.push({
            href, ruleOrdinal: ordinal, selector: r.selectorText, prop,
            important: r.style.getPropertyPriority(prop) === 'important',
            spec, order: idx, els
          });
        }
      }
    }
  };

  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    walk(rules, sheet.href || 'inline', true, {n: 0});
  }

  // winner per (element, property)
  const best = new Map();          // element -> prop -> decl
  for (const d of decls) {
    for (const el of d.els) {
      let byProp = best.get(el);
      if (!byProp) { byProp = new Map(); best.set(el, byProp); }
      const cur = byProp.get(d.prop);
      if (!cur) { byProp.set(d.prop, d); continue; }
      const beats =
        (d.important !== cur.important) ? d.important :
        (d.spec[0] !== cur.spec[0]) ? d.spec[0] > cur.spec[0] :
        (d.spec[1] !== cur.spec[1]) ? d.spec[1] > cur.spec[1] :
        (d.spec[2] !== cur.spec[2]) ? d.spec[2] > cur.spec[2] :
        d.order >= cur.order;
      if (beats) byProp.set(d.prop, d);
    }
  }

  const wins = new Map();
  for (const byProp of best.values()) {
    for (const d of byProp.values()) {
      const key = d.href + '|' + d.ruleOrdinal + '|' + d.prop;
      wins.set(key, (wins.get(key) || 0) + 1);
    }
  }
  const seen = new Map();
  for (const d of decls) {
    const key = d.href + '|' + d.ruleOrdinal + '|' + d.prop;
    if (!seen.has(key)) seen.set(key, [d.selector, d.prop]);
  }
  const out = [];
  for (const [key, meta] of seen) out.push([key, meta[0], meta[1], wins.get(key) || 0]);
  return out;
}
"""


def rule_ordinal_to_source() -> list[str]:
    """Map each style rule in style.css, in order, to the source file it came from.

    Counts rules exactly the way the browser enumerates them: every rule with
    a selector, including those nested in @media, and never @keyframes steps.
    """
    import re

    from css_dead_declarations import blank_comments

    text = (ROOT / "app" / "static" / "css" / "style.css").read_text(encoding="utf-8")
    blanked = blank_comments(text)
    marker = re.compile(r"BEGIN SOURCE:\s*(\S+)")

    owners: list[str] = []
    current = "(unattributed)"
    index = 0
    prelude_start = 0
    at_stack: list[str] = []

    while index < len(blanked):
        char = blanked[index]
        if char == "{":
            prelude = text[prelude_start:index]
            found = marker.findall(prelude)
            if found:
                current = found[-1]
            stripped = prelude.strip().split("*/")[-1].strip()
            if stripped.startswith("@"):
                at_stack.append(stripped)
                index += 1
                prelude_start = index
                continue
            depth = 1
            cursor = index + 1
            while cursor < len(blanked) and depth:
                if blanked[cursor] == "{":
                    depth += 1
                elif blanked[cursor] == "}":
                    depth -= 1
                cursor += 1
            if not any(rule.startswith("@keyframes") or rule.startswith("@-")
                       for rule in at_stack):
                owners.append(current)
            index = cursor
            prelude_start = cursor
            continue
        if char == "}":
            if at_stack:
                at_stack.pop()
            index += 1
            prelude_start = index
            continue
        if char == "/" and blanked[index:index + 2] == "/*":
            index += 2
            continue
        index += 1

    # comments were blanked, so re-scan markers against the original text
    return owners


def main() -> int:
    from playwright.sync_api import sync_playwright

    lo, hi = (int(sys.argv[1]), int(sys.argv[2])) if len(sys.argv) > 2 else (0, 999)
    cookie = _session_cookie()
    pages = discover_pages()
    print(f"analysing {len(pages)} discovered pages plus {len(PUBLIC_PAGES)} public ones "
          f"across {len(VIEWPORTS) * len(THEMES)} viewport/theme combinations",
          file=sys.stderr)

    declared: dict[str, tuple[str, str]] = {}
    win_totals: collections.Counter = collections.Counter()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        for viewport_name, width, height in VIEWPORTS:
            for theme in THEMES:
                for authed, page_list in ((True, pages), (False, PUBLIC_PAGES)):
                    context = browser.new_context(
                        viewport={"width": width, "height": height}, color_scheme=theme)
                    if authed:
                        context.add_cookies([{"name": "session", "value": cookie,
                                              "domain": "127.0.0.1", "path": "/"}])
                    page = context.new_page()
                    for name, path in page_list:
                        try:
                            response = page.goto(BASE_URL + path,
                                                 wait_until="networkidle", timeout=60000)
                            if response.status != 200:
                                continue
                            page.add_style_tag(content=FREEZE_CSS)
                            page.wait_for_timeout(900)
                            for key, selector, prop, wins in page.evaluate(ANALYSE_JS):
                                declared[key] = (selector, prop)
                                win_totals[key] += wins
                        except Exception as error:  # noqa: BLE001
                            print(f"error {path}: {error}", file=sys.stderr)
                    context.close()
        browser.close()

    import re

    owners = rule_ordinal_to_source()

    # A static capture never hovers, focuses, opens a dropdown or ticks a box,
    # so every rule keyed to an interaction state looks idle while being very
    # much alive. Those are counted separately instead of being reported as
    # candidates -- without this split the numbers are worse than useless.
    STATEFUL = re.compile(
        r":(hover|focus|focus-visible|focus-within|active|checked|disabled|"
        r"indeterminate|placeholder-shown|target|visited|invalid|valid|open)\b"
        r"|\[aria-(expanded|selected|current|pressed|checked)"
        r"|\[open\b|\[data-[\w-]*(open|active|expanded|collapsed|state)"
        r"|\.(show|showing|collapsing|active|is-[\w-]+|has-[\w-]+|dragging|"
        r"selected|open|expanded)\b")

    total: collections.Counter = collections.Counter()
    idle: collections.Counter = collections.Counter()
    idle_stateful: collections.Counter = collections.Counter()
    skipped_other_sheet = 0

    for key in declared:
        href, ordinal_text, _prop = key.split("|", 2)
        # the href carries the cache-busting query, so match on the path
        if "/css/style.css" not in href:
            skipped_other_sheet += 1      # vendored Bootstrap, not ours to prune
            continue
        ordinal = int(ordinal_text)
        source = owners[ordinal] if ordinal < len(owners) else "(out of range)"
        total[source] += 1
        if win_totals[key] == 0:
            if STATEFUL.search(declared[key][0]):
                idle_stateful[source] += 1
            else:
                idle[source] += 1

    ours = sum(total.values())
    idle_total = sum(idle.values())
    stateful_total = sum(idle_stateful.values())
    print(f"declarations in style.css observed here   : {ours}")
    print(f"  idle, but keyed to an interaction state : {stateful_total} "
          f"(hover/focus/open/checked -- NOT candidates)")
    print(f"  idle with an unconditional selector     : {idle_total} "
          f"({100.0 * idle_total / max(ours, 1):.0f}%)")
    print(f"declarations from other sheets, ignored   : {skipped_other_sheet} "
          f"(vendored Bootstrap)")
    print()
    print(f"{'source file':<52} {'decls':>6} {'cand':>6} {'state':>6} {'%':>5}")
    print("-" * 80)
    for source in sorted(total, key=lambda name: -idle[name]):
        name = source.rsplit("/", 1)[-1]
        number = name.split("_", 1)[0]
        if number.isdigit() and not (lo <= int(number) <= hi):
            continue
        if not idle[source]:
            continue
        share = 100.0 * idle[source] / max(total[source], 1)
        print(f"  {name:<50} {total[source]:>6} {idle[source]:>6} "
              f"{idle_stateful[source]:>6} {share:>4.0f}%")
    # Files that matched nothing at all are a coverage signal, not a delete
    # list: the harness simply never rendered a page they apply to.
    unexercised = [name for name in sorted(set(owners))
                   if name not in total and name != "(unattributed)"]
    if unexercised:
        print()
        print(f"never matched a single element here ({len(unexercised)} files) --")
        print("this measures the harness's page coverage, not dead code:")
        for name in unexercised:
            print(f"  {name.rsplit('/', 1)[-1]}")

    print()
    print("'cand' = never won, and its selector needs no interaction state.")
    print("'state' = never won only because nothing was hovered/focused/opened.")
    print("Candidates only: 31 of 260 templates render here, so a declaration")
    print("can be idle simply because its page was never visited.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
