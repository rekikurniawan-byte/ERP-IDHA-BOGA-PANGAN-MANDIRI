#!/usr/bin/env python3
"""Rewrite literal font sizes and weights as the tokens that already hold them.

Fase 5 restyles by changing a token value, which only reaches declarations
that read a token. Most do not: the sizes and weights are literals spread
across 66 source files, so changing the type scale today means editing
hundreds of values by hand -- exactly the "one design change = many files"
problem the audit set out to end.

This rewrites only the literals whose value is ALREADY identical to a token's:

    font-size: 13px   ->  font-size: var(--font-sm)     (--font-sm is 13px)
    font-weight: 700  ->  font-weight: var(--fw-bold)   (--fw-bold is 700)

so every computed value is unchanged by construction. Off-scale values
(18px, .82rem, clamp(...)) are left alone: snapping those is a design
decision, not a mechanical one, and belongs in a separate reviewed change.

Safe only while each token is defined exactly once, on :root, with no media
or theme override -- otherwise a var() could resolve to something else in
some context. The tool checks that itself and refuses to run if it is no
longer true.

Usage:
    python tools/css_tokenise_typography.py report
    python tools/css_tokenise_typography.py apply
    python tools/build_css.py

Verify with a before/after computed-style capture; the diff must be zero.
"""
from __future__ import annotations

import collections
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from css_dead_declarations import (  # noqa: E402
    CSS_SRC_DIR, SOURCE_ORDER, blank_comments, parse_declarations,
)

FONT_SIZE_TOKENS = {
    "11px": "--font-2xs", "12px": "--font-xs", "13px": "--font-sm",
    "14px": "--font-md", "16px": "--font-lg", "20px": "--font-xl",
    "24px": "--font-2xl", "32px": "--font-3xl",
}
FONT_WEIGHT_TOKENS = {
    "400": "--fw-regular", "500": "--fw-medium",
    "600": "--fw-semibold", "700": "--fw-bold",
}
TOKEN_NAME = re.compile(r"^--(?:font-(?:2xs|xs|sm|md|lg|xl|2xl|3xl)|fw-(?:regular|medium|semibold|bold))$")


def verify_tokens_are_unconditional() -> list[str]:
    """Each token must be defined once, on :root, outside any at-rule."""
    definitions: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            continue
        for declaration in parse_declarations(
                blank_comments(path.read_text(encoding="utf-8")), filename):
            if TOKEN_NAME.match(declaration["property"]):
                definitions[declaration["property"]].append(
                    (filename, ",".join(declaration["selectors"]), declaration["context"]))

    problems = []
    expected = set(FONT_SIZE_TOKENS.values()) | set(FONT_WEIGHT_TOKENS.values())
    for token in sorted(expected):
        places = definitions.get(token, [])
        if len(places) != 1:
            problems.append(f"{token}: defined {len(places)} times, expected 1")
            continue
        filename, selectors, context = places[0]
        if selectors != ":root" or context:
            problems.append(
                f"{token}: defined on {selectors!r} inside {context!r}, expected bare :root")
    return problems


def rewrite(write: bool):
    changed_files = 0
    per_property: collections.Counter = collections.Counter()
    per_value: collections.Counter = collections.Counter()

    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        edits = []
        for declaration in parse_declarations(blank_comments(text), filename):
            prop, value = declaration["property"], declaration["value"]
            if prop == "font-size":
                token = FONT_SIZE_TOKENS.get(value)
            elif prop == "font-weight":
                token = FONT_WEIGHT_TOKENS.get(value)
            else:
                continue
            if not token:
                continue
            suffix = " !important" if declaration["important"] else ""
            replacement = f"{prop}: var({token}){suffix};"
            edits.append((declaration["start"], declaration["end"], replacement))
            per_property[prop] += 1
            per_value[f"{prop}: {value}"] += 1

        if not edits:
            continue
        changed_files += 1
        if write:
            for start, end, replacement in sorted(edits, key=lambda e: e[0], reverse=True):
                text = text[:start] + replacement + text[end:]
            path.write_text(text, encoding="utf-8")

    return changed_files, per_property, per_value


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "report"
    if command not in ("report", "apply"):
        print(__doc__)
        return 2

    problems = verify_tokens_are_unconditional()
    if problems:
        print("refusing to run -- a token is no longer unconditional, so replacing")
        print("a literal with var() could change its value somewhere:")
        for problem in problems:
            print(f"  {problem}")
        return 1
    print("token check: every font token defined once on bare :root")

    changed_files, per_property, per_value = rewrite(write=(command == "apply"))
    total = sum(per_property.values())
    print()
    print(f"declarations {'rewritten' if command == 'apply' else 'to rewrite'}: {total} "
          f"across {changed_files} files")
    for prop, count in per_property.most_common():
        print(f"  {prop:<14} {count}")
    print()
    print("by value:")
    for value, count in per_value.most_common():
        print(f"  {value:<26} {count}")
    if command == "apply":
        print()
        print("next: python tools/build_css.py, then a before/after computed-style diff")
    else:
        print()
        print("dry run -- rerun with 'apply' to write")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
