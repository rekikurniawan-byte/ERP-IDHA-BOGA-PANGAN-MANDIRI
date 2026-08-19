#!/usr/bin/env python3
"""Pixel-diff tools/visual_baseline/baseline/*.png against .../current/*.png.

Usage:
    python tools/visual_baseline/capture.py --out current
    python tools/visual_baseline/compare.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[2]
BASELINE_DIR = ROOT / "tools" / "visual_baseline" / "baseline"
CURRENT_DIR = ROOT / "tools" / "visual_baseline" / "current"
DIFF_DIR = ROOT / "tools" / "visual_baseline" / "diff"


def compare() -> int:
    if not BASELINE_DIR.exists():
        print("No baseline captured yet. Run: python tools/visual_baseline/capture.py --out baseline")
        return 1
    if not CURRENT_DIR.exists():
        print("No current capture yet. Run: python tools/visual_baseline/capture.py --out current")
        return 1

    DIFF_DIR.mkdir(parents=True, exist_ok=True)
    changed = 0

    for baseline_path in sorted(BASELINE_DIR.glob("*.png")):
        current_path = CURRENT_DIR / baseline_path.name
        if not current_path.exists():
            print(f"MISSING in current: {baseline_path.name}")
            changed += 1
            continue

        base_img = Image.open(baseline_path).convert("RGB")
        current_img = Image.open(current_path).convert("RGB")

        if base_img.size != current_img.size:
            print(f"SIZE CHANGED: {baseline_path.name} {base_img.size} -> {current_img.size}")
            changed += 1
            continue

        diff = ImageChops.difference(base_img, current_img)
        bbox = diff.getbbox()
        if bbox is None:
            print(f"same:    {baseline_path.name}")
            continue

        diff_pixels = sum(1 for pixel in diff.getdata() if pixel != (0, 0, 0))
        total_pixels = base_img.size[0] * base_img.size[1]
        pct = 100 * diff_pixels / total_pixels
        print(f"CHANGED: {baseline_path.name} ({pct:.2f}% of pixels differ, bbox={bbox})")
        diff.save(DIFF_DIR / baseline_path.name)
        changed += 1

    print()
    print(f"{changed} file(s) changed. Diff images (if any) saved to {DIFF_DIR.relative_to(ROOT)}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(compare())
