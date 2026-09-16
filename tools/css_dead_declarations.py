#!/usr/bin/env python3
"""Find and remove CSS declarations that can never win.

A declaration is dead when a LATER declaration in the built cascade has all of:

  * the same at-rule context (same @media / @supports nesting),
  * the same selector set (compared order-insensitively),
  * the same property name,
  * a priority that beats or equals it -- a later `!important` always wins; a
    later normal declaration beats an earlier normal one but NOT an earlier
    `!important`.

Same context + same selector set means both rules match exactly the same
elements on every page, so the earlier one can never apply. That is what makes
the removal safe without reasoning about specificity at all.

Two buckets are reported separately because they carry different risk:

  identical   same property, same value, same priority -- removal is a literal
              no-op even if the analysis were wrong
  overridden  same property, later value wins

Deliberately skipped: values using vendor prefixes, and progressive-enhancement
pairs (a plain value followed by one using color-mix()/clamp()/env()/gradient()),
where the earlier declaration is an intentional fallback rather than dead code.

Usage:
    python tools/css_dead_declarations.py report
    python tools/css_dead_declarations.py apply identical
    python tools/css_dead_declarations.py apply overridden
    python tools/css_dead_declarations.py tidy

`apply` only deletes declarations; run `tidy` afterwards to drop rule blocks
that are now empty and to collapse the blank lines left behind. Always rebuild
(`python tools/build_css.py`) and re-check a visual baseline afterwards --
tools/visual_baseline/computed_fingerprint.py is the sensitive one.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_SRC_DIR = ROOT / "app" / "static" / "css" / "src"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_css import SOURCE_ORDER  # noqa: E402

VENDOR_RE = re.compile(r"-(webkit|moz|ms|o)-")
PROGRESSIVE = ("color-mix(", "clamp(", "env(", "gradient(")
DECL_RE = re.compile(r"([-a-zA-Z0-9_]+)\s*:\s*([^;{}]+?)\s*(!important)?\s*;")
ANY_DECL_RE = re.compile(r"[-a-zA-Z0-9_]+\s*:\s*[^;{}]+;")
COMMENT_RE = re.compile(r"/\*.*?\*/", re.S)


def blank_comments(text: str) -> str:
    """Blank out comments while preserving every character position.

    Offsets taken from the blanked text therefore address the original text
    unchanged, which is what lets declarations be spliced out precisely.
    """
    def blank(match: re.Match) -> str:
        return "".join("\n" if ch == "\n" else " " for ch in match.group(0))

    return COMMENT_RE.sub(blank, text)


def parse_declarations(text: str, filename: str) -> list[dict]:
    """Collect every declaration with its at-rule context and byte offsets."""
    found: list[dict] = []
    at_rules: list[str] = []
    index = 0
    prelude_start = 0

    while index < len(text):
        char = text[index]
        if char == "{":
            prelude = text[prelude_start:index].strip()
            if prelude.startswith("@"):
                at_rules.append(prelude)
                index += 1
                prelude_start = index
                continue

            depth = 1
            cursor = index + 1
            while cursor < len(text) and depth:
                if text[cursor] == "{":
                    depth += 1
                elif text[cursor] == "}":
                    depth -= 1
                cursor += 1

            body_start = index + 1
            body = text[body_start:cursor - 1]
            inside_keyframes = any(rule.startswith("@keyframes") or rule.startswith("@-")
                                   for rule in at_rules)
            if not inside_keyframes:
                selectors = tuple(sorted(re.sub(r"\s+", " ", part).strip()
                                         for part in prelude.split(",") if part.strip()))
                for match in DECL_RE.finditer(body):
                    found.append({
                        "file": filename,
                        "context": " | ".join(at_rules),
                        "selectors": selectors,
                        "property": match.group(1).strip().lower(),
                        "value": match.group(2).strip(),
                        "important": bool(match.group(3)),
                        "start": body_start + match.start(),
                        "end": body_start + match.end(),
                        "line": text[:body_start + match.start()].count("\n") + 1,
                    })
            index = cursor
            prelude_start = index
            continue

        if char == "}":
            if at_rules:
                at_rules.pop()
            index += 1
            prelude_start = index
            continue

        index += 1

    return found


def classify() -> tuple[dict[str, str], list[dict], list[tuple[dict, dict]], list[tuple[dict, dict]], int]:
    sources: dict[str, str] = {}
    declarations: list[dict] = []
    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            continue
        raw = path.read_text(encoding="utf-8")
        sources[filename] = raw
        declarations.extend(parse_declarations(blank_comments(raw), filename))

    grouped: dict[tuple, list[dict]] = {}
    for declaration in declarations:
        key = (declaration["context"], declaration["selectors"], declaration["property"])
        grouped.setdefault(key, []).append(declaration)

    identical: list[tuple[dict, dict]] = []
    overridden: list[tuple[dict, dict]] = []
    skipped = 0

    for items in grouped.values():
        if len(items) < 2:
            continue
        for position, candidate in enumerate(items[:-1]):
            winner = None
            for later in items[position + 1:]:
                if later["important"] or not candidate["important"]:
                    winner = later
                    break
            if winner is None:
                continue

            old_value, new_value = candidate["value"], winner["value"]
            if VENDOR_RE.search(old_value) or VENDOR_RE.search(new_value):
                skipped += 1
                continue
            if (any(token in new_value for token in PROGRESSIVE)
                    and not any(token in old_value for token in PROGRESSIVE)):
                skipped += 1
                continue

            is_identical = old_value == new_value and candidate["important"] == winner["important"]
            (identical if is_identical else overridden).append((candidate, winner))

    return sources, declarations, identical, overridden, skipped


def remove(sources: dict[str, str], victims: list[tuple[dict, dict]]) -> tuple[int, int, int]:
    by_file: dict[str, list[dict]] = {}
    for candidate, _ in victims:
        by_file.setdefault(candidate["file"], []).append(candidate)

    removed_important = 0
    for filename, items in by_file.items():
        text = sources[filename]
        for declaration in sorted(items, key=lambda item: item["start"], reverse=True):
            text = text[:declaration["start"]] + text[declaration["end"]:]
            if declaration["important"]:
                removed_important += 1
        (CSS_SRC_DIR / filename).write_text(text, encoding="utf-8")

    return len(victims), removed_important, len(by_file)


def _empty_block_spans(text: str, blanked: str) -> list[tuple[int, int]]:
    """Spans of blocks holding no declaration, no nested block and no comment.

    Walks braces rather than pattern-matching `selector {}`: a regex splits
    multi-line selector lists like `.a,\\n.b { }` and leaves a dangling `.a,`
    that silently merges into the next rule.
    """
    spans: list[tuple[int, int]] = []
    index = 0
    prelude_start = 0
    while index < len(blanked):
        char = blanked[index]
        if char == "{":
            depth = 1
            cursor = index + 1
            while cursor < len(blanked) and depth:
                if blanked[cursor] == "{":
                    depth += 1
                elif blanked[cursor] == "}":
                    depth -= 1
                cursor += 1

            body = blanked[index + 1:cursor - 1]
            raw_body = text[index + 1:cursor - 1]
            if not ANY_DECL_RE.search(body) and "{" not in body and "/*" not in raw_body:
                spans.append((prelude_start, cursor))
            else:
                for start, end in _empty_block_spans(raw_body, body):
                    spans.append((index + 1 + start, index + 1 + end))
            index = cursor
            prelude_start = index
            continue
        if char == "}":
            index += 1
            prelude_start = index
            continue
        index += 1
    return spans


def _collapse_body_blank_lines(text: str) -> str:
    """Drop blank lines inside declaration blocks, keeping them between rules.

    Removing a declaration leaves the blank line it sat on, so a cleaned file
    ends up with ragged holes inside otherwise short rules. CSS ignores that
    whitespace, but a reader cannot tell a gap left by a deletion from one put
    there deliberately, and 02_typography.css had rules reduced to a property
    marooned between two blank lines.

    Only bodies with no nested block are touched, so @media and friends keep
    the blank lines separating the rules they contain.
    """
    blanked = blank_comments(text)
    edits: list[tuple[int, int, str]] = []
    index = 0
    while index < len(blanked):
        if blanked[index] != "{":
            index += 1
            continue
        depth = 1
        cursor = index + 1
        while cursor < len(blanked) and depth:
            if blanked[cursor] == "{":
                depth += 1
            elif blanked[cursor] == "}":
                depth -= 1
            cursor += 1
        body_start, body_end = index + 1, cursor - 1
        if "{" not in blanked[body_start:body_end]:
            body = text[body_start:body_end]
            # Match the blank lines only -- never the indentation of the line
            # that survives, or the declaration after the gap lands in column 0.
            collapsed = re.sub(r"\n(?:[ \t]*\n)+", "\n", body)
            if collapsed != body:
                edits.append((body_start, body_end, collapsed))
        index = cursor

    for start, end, replacement in reversed(edits):
        text = text[:start] + replacement + text[end:]
    return text


def tidy() -> tuple[int, int]:
    removed_blocks = 0
    rewritten = 0
    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            continue
        original = path.read_text(encoding="utf-8")
        text = original
        spans = sorted(_empty_block_spans(text, blank_comments(text)),
                       key=lambda span: span[0], reverse=True)

        kept: list[tuple[int, int]] = []
        for start, end in spans:
            if any(start >= outer_start and end <= outer_end for outer_start, outer_end in kept):
                continue
            kept.append((start, end))
        for start, end in kept:
            text = text[:start] + text[end:]
        removed_blocks += len(kept)

        text = _collapse_body_blank_lines(text)
        text = re.sub(r"(\n[ \t]*){3,}\n", "\n\n", text)
        text = re.sub(r"\n[ \t]+\n", "\n\n", text)
        if text != original:
            path.write_text(text, encoding="utf-8")
            rewritten += 1
    return removed_blocks, rewritten


def main() -> int:
    command = sys.argv[1] if len(sys.argv) > 1 else "report"

    if command == "tidy":
        blocks, files = tidy()
        print(f"removed {blocks} now-empty blocks; rewrote {files} files")
        return 0

    sources, declarations, identical, overridden, skipped = classify()
    total_important = sum(1 for item in declarations if item["important"])
    raw_important = sum(sources[name].count("!important") for name in sources)

    print(f"declarations parsed: {len(declarations)} | with !important: {total_important}")
    if total_important != raw_important:
        print(f"WARNING: parser saw {total_important} !important but the sources contain "
              f"{raw_important} -- do not apply until this matches")
        return 1
    print(f"bucket identical : {len(identical):5d} "
          f"(!important: {sum(1 for item, _ in identical if item['important'])})")
    print(f"bucket overridden: {len(overridden):5d} "
          f"(!important: {sum(1 for item, _ in overridden if item['important'])})")
    print(f"skipped as vendor-prefixed or progressive-enhancement fallbacks: {skipped}")

    if command == "apply":
        which = sys.argv[2] if len(sys.argv) > 2 else ""
        if which not in ("identical", "overridden"):
            print("usage: css_dead_declarations.py apply {identical|overridden}")
            return 2
        count, important, files = remove(sources, identical if which == "identical" else overridden)
        print()
        print(f"applied bucket {which}: removed {count} declarations "
              f"({important} with !important) across {files} files")
        print("next: python tools/css_dead_declarations.py tidy && python tools/build_css.py")
    elif command != "report":
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
