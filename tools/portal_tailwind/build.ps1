# Kompilasi CSS desain portal (Tailwind) menjadi file lokal. Jalankan dari mana saja:
#   powershell -ExecutionPolicy Bypass -File tools\portal_tailwind\build.ps1
# Jalankan ulang setiap kali template portal diubah (kelas baru perlu masuk CSS).
$root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Push-Location $root
try {
    npx --yes tailwindcss@3.4.17 -c tools/portal_tailwind/tailwind.config.js -i tools/portal_tailwind/input.css -o app/static/css/portal_tailwind.css --minify
} finally {
    Pop-Location
}
