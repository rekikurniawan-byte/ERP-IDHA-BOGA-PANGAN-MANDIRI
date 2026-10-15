$header = @"
/* ==================================================
   FILE HASIL RAKIT - JANGAN DIEDIT LANGSUNG
   Sumber: app/static/css/app/*.css
   Rakit:  python tools/build_css.py
   ================================================== */
"@

$files = @(
    "tokens.css",
    "base.css",
    "layout.css",
    "components.css",
    "pages.css",
    "portal.css",
    "public.css",
    "print.css"
)

$content = $header + "`n"
foreach ($f in $files) {
    $p = "app/static/css/app/$f"
    $raw = [System.IO.File]::ReadAllText($p, [System.Text.Encoding]::UTF8).TrimEnd() + "`n"
    $content += "`n/* --- $f --- */`n" + $raw
}

[System.IO.File]::WriteAllText("app/static/css/style.css", $content, [System.Text.Encoding]::UTF8)
Write-Output "Style.css built successfully"
