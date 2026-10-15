# Lanjutan: Admin Operasional (sesi sebelumnya macet)

Baca `PROMPT_GEMINI_ADMIN_OPERASIONAL.md` untuk aturan lengkap (semua larangan tetap berlaku). Sebagian SUDAH jadi — jangan ditulis ulang:
`layouts/ops_mobile.html`, `services/ops_navigation_service.py`, 13 template di `templates/ops/` (dashboard, orders, order_detail, drafts, order_qty_changes, menu_schedule, kitchen_recap, production, production_detail, today, receiving, delivery_detail, receive), dan perubahan route.

Kerjakan HANYA daftar ini, satu per satu, file kecil (jangan edit ulang `ops/receive.html` kecuali poin 2 di bawah):

1. Template yang dirujuk route tapi BELUM ADA (tiru versi `templates/driver/` yang sama, ganti extends ke `layouts/ops_mobile.html`, teks "pengantar" → operasional):
   - `ops/account.html` (dari `driver/account.html`, SOP = `sop.role_sop` slug operasional yang ada di `sop_routes.py`),
   - `ops/notifications.html` (dari `driver/notifications.html`),
   - `ops/sop.html` (dari `driver/sop.html`).
2. `delivery.history` dan `delivery.scan` belum memilih template ops: buat `ops/history.html` & `ops/scan.html` (dari versi driver) dan tambahkan pilihan template `ADMIN_OPERASIONAL` di route-nya, pola sama seperti `delivery.today`.
3. `ops_navigation_service.py` merujuk endpoint yang TIDAK ADA: `delivery.receive_detail` (yang benar `delivery.receive`) dan `operational.revise_order_detail_route` (cari nama endpoint revisi yang benar di `operational_routes.py`, route `/order-details/<id>/revision`). Perbaiki.
4. `tools/portal_tailwind/tailwind.config.js`: tambah `./app/templates/ops/**/*.html` dan `./app/templates/layouts/ops_mobile.html` ke `content`, lalu jalankan `tools\portal_tailwind\build.ps1`.
5. Tes (tulis saja, JANGAN jalankan):
   - `tests/test_ops_navigation.py` — satu pintu per halaman (pola `tests/test_driver_navigation.py`), semua endpoint di peta benar-benar ada di `app.url_map`, halaman ops render 200 + `ops-mobile-shell` untuk ADMIN_OPERASIONAL, `/ops` bisa dibuka OWNER & ADMIN.
   - `tests/test_admin_operasional_permissions.py` — ADMIN_OPERASIONAL DITOLAK di contoh halaman keuangan/akuntansi/master/pengaturan/warung; DIIZINKAN di halaman lingkup; tidak bisa meloloskan pesanan sebelum lunas.

Selesai → laporkan daftar file yang dibuat/diubah + perintah untuk owner:
`venv\Scripts\python.exe -m pytest -q tests/test_ops_navigation.py tests/test_admin_operasional_permissions.py tests/test_driver_navigation.py tests/test_portal_navigation.py tests/test_delivery_scan_flow.py`
