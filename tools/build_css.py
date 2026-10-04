#!/usr/bin/env python3
"""Rakit app/static/css/style.css dari app/static/css/app/*.css.

Jangan edit style.css langsung. Edit sumbernya, lalu jalankan:

    python tools/build_css.py

Sejak 2026-09-29 (keputusan owner): 94 file tambalan lama diganti satu set
kecil -- token, dasar, layout, komponen, halaman, cetak. Pagar di sini
menjaga agar tidak kembali jadi tumpukan tambalan:
- hanya file di SOURCE_ORDER; file lain di folder sumber = gagal;
- nama file "fix/lock/override/polish/..." = gagal;
- tidak ada mode gelap: selektor [data-theme] = gagal;
- !important dibatasi IMPORTANT_BUDGET (turunkan saja, jangan dinaikkan);
- warna ditulis sebagai token di tokens.css; hex di file lain dibatasi
  HEX_OUTSIDE_TOKENS_BUDGET.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_SRC_DIR = ROOT / "app" / "static" / "css" / "app"
CSS_OUTPUT = ROOT / "app" / "static" / "css" / "style.css"

SOURCE_ORDER = [
    "tokens.css",
    "base.css",
    "layout.css",
    "components.css",
    "pages.css",
    "portal.css",
    "public.css",
    "print.css",
]
FORBIDDEN_FILENAME_WORDS = ("final", "lock", "fix", "override", "repair", "cleanup", "polish", "patch", "hotfix")
# Hanya untuk menimpa utilitas Bootstrap yang memakai !important dan aturan
# cetak/gerak-dikurangi. Ratchet turun saja.
IMPORTANT_BUDGET = 12
# Warna literal di luar tokens.css (mis. rgba bayangan, putih di atas oranye).
HEX_OUTSIDE_TOKENS_BUDGET = 40

HEADER = """/* ==================================================
   FILE HASIL RAKIT - JANGAN DIEDIT LANGSUNG
   Sumber: app/static/css/app/*.css
   Rakit:  python tools/build_css.py
   ================================================== */
"""


def _strip_comments(css):
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def _brace_balance(css):
    cleaned = _strip_comments(css)
    balance = 0
    for char in cleaned:
        if char == "{":
            balance += 1
        elif char == "}":
            balance -= 1
            if balance < 0:
                return False
    return balance == 0


def filename_has_forbidden_word(filename):
    stem = Path(filename).stem.lower()
    return re.search(r"(?:^|[^a-z])(" + "|".join(FORBIDDEN_FILENAME_WORDS) + r")(?:[^a-z]|$)", stem) is not None


def load_sources():
    errors = []
    loaded = []
    for filename in SOURCE_ORDER:
        path = CSS_SRC_DIR / filename
        if not path.exists():
            errors.append(f"Sumber CSS hilang: {path.relative_to(ROOT)}")
            continue
        loaded.append((filename, path.read_text(encoding="utf-8").rstrip() + "\n"))
    extra = sorted(p.name for p in CSS_SRC_DIR.glob("*.css") if p.name not in SOURCE_ORDER)
    if extra:
        errors.append("File CSS di luar SOURCE_ORDER: " + ", ".join(extra))
    return loaded, errors


def check_sources(loaded):
    """Kembalikan (laporan, daftar kesalahan) untuk pagar arsitektur."""
    errors = []
    forbidden = [name for name, _ in loaded if filename_has_forbidden_word(name)]
    if forbidden:
        errors.append("Nama file tambalan dilarang: " + ", ".join(forbidden))

    important = [(name, len(re.findall(r"!important", _strip_comments(text)))) for name, text in loaded]
    important_total = sum(count for _, count in important)
    if important_total > IMPORTANT_BUDGET:
        errors.append(f"!important {important_total} melebihi batas {IMPORTANT_BUDGET}: {important}")

    themed = [name for name, text in loaded if re.search(r"\[data-theme", _strip_comments(text))]
    if themed:
        errors.append("Mode gelap sudah dihapus; selektor [data-theme] ditemukan di: " + ", ".join(themed))

    hex_outside = sum(
        len(re.findall(r"#[0-9a-fA-F]{3,8}\b", _strip_comments(text))) for name, text in loaded if name != "tokens.css"
    )
    if hex_outside > HEX_OUTSIDE_TOKENS_BUDGET:
        errors.append(f"Warna hex di luar tokens.css {hex_outside} melebihi batas {HEX_OUTSIDE_TOKENS_BUDGET}.")

    report = {
        "important_total": important_total,
        "important_by_source": dict(important),
        "hex_outside_tokens": hex_outside,
    }
    return report, errors


def build():
    loaded, errors = load_sources()
    report, check_errors = check_sources(loaded)
    errors.extend(check_errors)
    output = HEADER + "".join(f"\n/* --- {name} --- */\n{text}" for name, text in loaded)
    if not _brace_balance(output):
        errors.append("Kurung kurawal CSS tidak seimbang.")
    if errors:
        for error in errors:
            print(f"GAGAL: {error}", file=sys.stderr)
        return 1

    CSS_OUTPUT.write_text(output, encoding="utf-8")
    lines = output.count("\n")
    print(f"CSS dirakit: {CSS_OUTPUT.relative_to(ROOT)} ({len(output.encode('utf-8')):,} byte, {lines:,} baris, "
          f"{len(loaded)} sumber, !important {report['important_total']}/{IMPORTANT_BUDGET}, "
          f"hex di luar token {report['hex_outside_tokens']}/{HEX_OUTSIDE_TOKENS_BUDGET})")
    print("sha256:", hashlib.sha256(output.encode("utf-8")).hexdigest()[:16])
    print(json.dumps(report["important_by_source"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(build())
