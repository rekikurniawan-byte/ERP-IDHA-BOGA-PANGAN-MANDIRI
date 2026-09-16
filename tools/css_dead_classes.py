#!/usr/bin/env python3
"""Find and remove CSS rules that require a class no element ever carries.

If nothing ever puts a class on an element, every selector part requiring it
is unreachable. The hard part is proving "nothing ever puts it there", so this
gathers three independent kinds of evidence and only calls a class dead when
all three come up empty:

  referenced   the name appears as a bare token in app/templates, app JS, the
               vendored Bootstrap JS (which adds .show/.collapsing itself), or
               Python
  assembled    the name could be built at runtime from a prefix sitting
               immediately before an interpolation -- `link-card-{{ loop.index }}`,
               `` `donut-metric-${key}` ``, `"stat-" + tone`
  in the DOM   the class is on a real element in a computed-style fingerprint
               capture (proves runtime attachment for the pages captured)

The `assembled` and DOM checks are not optional niceties. Running with only a
textual search flags 509 classes; the other two rescue 105 of them, including
three that a hand-written audit had listed as dead
(dashboard-command-link-card-3/4, dashboard-donut-metric-success).

Removal keeps live selectors: a rule goes only when every part of its selector
list is dead, otherwise just the dead parts are trimmed. Commas inside
:is()/:where()/:not()/:has() are not list separators, so splitting is
paren-depth aware, and any part using one of those functional pseudo-classes
is left alone entirely -- a dead class inside :where() is one branch of an OR,
not a requirement.

Usage:
    python tools/visual_baseline/computed_fingerprint.py capture before.json
    python tools/css_dead_classes.py report before.json
    python tools/css_dead_classes.py apply  before.json
    python tools/css_dead_declarations.py tidy && python tools/build_css.py
    python tools/visual_baseline/computed_fingerprint.py capture after.json
    python tools/visual_baseline/computed_fingerprint.py diff before.json after.json

That last diff must report 0. Pass every fingerprint file you have -- more
captured pages means more classes proven live rather than assumed dead.
"""
from __future__ import annotations

import collections
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from css_dead_declarations import CSS_SRC_DIR, SOURCE_ORDER, blank_comments  # noqa: E402

CLASS_IN_SELECTOR = re.compile(r"\.(-?[_a-zA-Z][\w-]*)")
TOKEN = re.compile(r"[A-Za-z_][\w-]*")
ASSEMBLED_PREFIX = re.compile(r"([A-Za-z][\w-]*-)(?=\{\{|\{%|\$\{|\s*[\"']\s*[+~]|\s*[+~])")
FUNCTIONAL_PSEUDO = re.compile(r":[a-z-]+\(")

# Places a class name can legitimately come from: markup, the scripts that
# attach classes at runtime, vendored Bootstrap's own JS, services that emit a
# class name into a template, and tests that assert on rendered markup.
#
# tools/ is deliberately NOT scanned. Nothing under it renders anything -- it
# only talks *about* selectors -- so including it lets a class name mentioned
# in a docstring immunise itself from detection. That is not hypothetical:
# `.summary-card` has 56 rules and appears in zero templates, and went
# undetected purely because an example in css_selector_liveness.py named it.
SCAN_GLOBS = [
    "app/templates/**/*.html",
    "app/static/js/**/*.js",
    "app/static/vendor/**/*.js",
    "app/**/*.py",
    "tests/**/*.py",
]


def css_class_usage() -> collections.Counter:
    counter: collections.Counter = collections.Counter()
    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            continue
        text = blank_comments(path.read_text(encoding="utf-8"))
        for prelude in re.findall(r"(?:^|[}\n])\s*([^{}@][^{}]*?)\{", text):
            for name in CLASS_IN_SELECTOR.findall(prelude):
                counter[name] += 1
    return counter


def source_evidence() -> tuple[set[str], set[str]]:
    tokens: set[str] = set()
    prefixes: set[str] = set()
    for pattern in SCAN_GLOBS:
        for path in ROOT.glob(pattern):
            if not path.is_file():
                continue
            try:
                blob = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            tokens.update(TOKEN.findall(blob))
            prefixes.update(ASSEMBLED_PREFIX.findall(blob))
    return tokens, prefixes


def dom_classes(fingerprints: list[str]) -> set[str]:
    seen: set[str] = set()
    for path in fingerprints:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        for rows in data["pages"].values():
            for row in rows:
                seen.update(str(row[1]).split())
    return seen


def classify(fingerprints: list[str]):
    css_classes = css_class_usage()
    tokens, prefixes = source_evidence()
    in_dom = dom_classes(fingerprints)

    dead: list[str] = []
    kept: collections.Counter = collections.Counter()
    rescued_by_dom: list[str] = []
    rescued_by_prefix: list[tuple[str, str]] = []

    for name in css_classes:
        if name in tokens:
            kept["referenced"] += 1
            continue
        if name in in_dom:
            kept["in the DOM"] += 1
            rescued_by_dom.append(name)
            continue
        prefix = next((p for p in prefixes if name.startswith(p) and len(name) > len(p)), None)
        if prefix:
            kept["runtime-assembled"] += 1
            rescued_by_prefix.append((name, prefix))
            continue
        dead.append(name)

    return css_classes, sorted(dead), kept, sorted(rescued_by_dom), sorted(rescued_by_prefix)


def split_selector_list(prelude: str) -> list[str]:
    """Split on commas that are not inside parentheses."""
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in prelude:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return parts


def _selector_start(text: str, prelude_start: int, brace: int) -> int:
    """Skip whitespace and any comment sitting before the selector."""
    chunk = text[prelude_start:brace]
    last_comment = chunk.rfind("*/")
    offset = last_comment + 2 if last_comment != -1 else 0
    while offset < len(chunk) and chunk[offset] in " \t\r\n":
        offset += 1
    return prelude_start + offset


def scan_rules(text: str) -> list[tuple[int, int, int]]:
    blanked = blank_comments(text)
    rules: list[tuple[int, int, int]] = []
    index = 0
    prelude_start = 0
    at_rules: list[bool] = []
    while index < len(blanked):
        char = blanked[index]
        if char == "{":
            if text[prelude_start:index].strip().startswith("@"):
                at_rules.append(True)
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
            rules.append((_selector_start(text, prelude_start, index), index, cursor))
            index = cursor
            prelude_start = cursor
            continue
        if char == "}":
            if at_rules:
                at_rules.pop()
            index += 1
            prelude_start = index
            continue
        index += 1
    return rules


def rewrite(dead: set[str], write: bool):
    whole = trimmed = left_alone = 0
    per_file: collections.Counter = collections.Counter()
    plan: list[tuple[str, str, str]] = []

    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        edits = []
        for selector_start, brace, end in scan_rules(text):
            prelude = text[selector_start:brace]
            parts = [part for part in split_selector_list(prelude) if part.strip()]
            if not parts:
                continue
            dead_parts, live_parts = [], []
            for part in parts:
                if FUNCTIONAL_PSEUDO.search(part):
                    left_alone += 1
                    live_parts.append(part.strip())
                    continue
                if any(cls in dead for cls in CLASS_IN_SELECTOR.findall(part)):
                    dead_parts.append(part.strip())
                else:
                    live_parts.append(part.strip())
            if not dead_parts:
                continue
            if live_parts:
                edits.append(("trim", selector_start, brace, ",\n".join(live_parts) + " "))
                trimmed += 1
                plan.append((filename, "TRIM", prelude.strip().replace("\n", " ")[:160]))
            else:
                edits.append(("whole", selector_start, end, None))
                whole += 1
                plan.append((filename, "WHOLE", prelude.strip().replace("\n", " ")[:160]))
            per_file[filename] += 1

        if write and edits:
            for kind, start, stop, replacement in sorted(edits, key=lambda e: e[1], reverse=True):
                text = text[:start] + (replacement if kind == "trim" else "") + text[stop:]
            path.write_text(text, encoding="utf-8")

    return whole, trimmed, left_alone, per_file, plan


def main() -> int:
    if len(sys.argv) < 3 or sys.argv[1] not in ("report", "apply"):
        print(__doc__)
        return 2
    command, fingerprints = sys.argv[1], sys.argv[2:]

    css_classes, dead, kept, rescued_dom, rescued_prefix = classify(fingerprints)

    print(f"distinct classes in CSS selectors: {len(css_classes)}")
    for reason, count in kept.most_common():
        print(f"  kept, {reason + ':':<20} {count}")
    print(f"  DEAD:                      {len(dead)}")
    print()
    if rescued_dom:
        print(f"rescued by the DOM ({len(rescued_dom)}): "
              + ", ".join(rescued_dom[:12]) + (" ..." if len(rescued_dom) > 12 else ""))
    if rescued_prefix:
        print(f"rescued by a runtime prefix ({len(rescued_prefix)}): "
              + ", ".join(name for name, _ in rescued_prefix[:12])
              + (" ..." if len(rescued_prefix) > 12 else ""))
    print()

    whole, trimmed, left_alone, per_file, plan = rewrite(set(dead), write=(command == "apply"))
    print(f"whole rules {'dropped' if command == 'apply' else 'to drop'}   : {whole}")
    print(f"selector lists {'trimmed' if command == 'apply' else 'to trim'}: {trimmed}")
    print(f"parts left alone for using a functional pseudo-class: {left_alone}")
    print()
    print("by file:")
    for filename, count in per_file.most_common(15):
        print(f"  {filename:<58} {count}")

    if command == "apply":
        print()
        print("applied. next: python tools/css_dead_declarations.py tidy "
              "&& python tools/build_css.py, then re-capture and diff the fingerprint")
    else:
        print()
        print("dry run -- rerun with 'apply' to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
