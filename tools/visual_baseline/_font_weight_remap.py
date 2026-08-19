#!/usr/bin/env python3
"""One-off Fase 1 script: collapse the font-weight scale to 400/500/600/700.

Before: 22 distinct literal font-weight values across app/static/css/src/*.css
(400..950), dominated by 800-950 (see RINCIAN_AUDIT_UI_UX_CSS_ERP_IDHA_BOGA.md
section 2.4). This rewrites every literal font-weight number in place using a
fixed bucket rule, leaving keyword values (bold/normal/inherit) untouched.

Run once, review the diff, then `python tools/build_css.py` and re-screenshot
with tools/visual_baseline/capture.py to confirm the visual delta is the
intended global de-bolding and nothing else moved.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CSS_SRC_DIR = ROOT / "app" / "static" / "css" / "src"

PATTERN = re.compile(r"(font-weight\s*:\s*)(\d{3,4})\b")


def bucket(weight: int) -> int:
    if weight <= 450:
        return 400
    if weight <= 550:
        return 500
    if weight <= 650:
        return 600
    return 700


def main() -> int:
    total_changed = 0
    per_file_changes = {}

    for css_path in sorted(CSS_SRC_DIR.glob("*.css")):
        original = css_path.read_text(encoding="utf-8")
        changes = []

        def replace(match: re.Match) -> str:
            prefix, digits = match.group(1), match.group(2)
            old_value = int(digits)
            new_value = bucket(old_value)
            if new_value != old_value:
                changes.append((old_value, new_value))
            return f"{prefix}{new_value}"

        updated = PATTERN.sub(replace, original)

        if changes:
            css_path.write_text(updated, encoding="utf-8")
            per_file_changes[css_path.name] = len(changes)
            total_changed += len(changes)

    for name, count in sorted(per_file_changes.items(), key=lambda kv: -kv[1]):
        print(f"{count:4d}  {name}")
    print(f"\nTotal font-weight declarations rewritten: {total_changed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
