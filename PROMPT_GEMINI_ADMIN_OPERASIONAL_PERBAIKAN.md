# Perbaikan hasil review Claude: aplikasi HP Admin Operasional

Aturan & larangan di `PROMPT_GEMINI_ADMIN_OPERASIONAL.md` tetap berlaku (tanpa git berbahaya, tanpa pytest, tanpa data palsu/CDN). Kerjakan per file, file kecil. Claude SUDAH mengoreksi izin (hapus lampiran bukti = ADMIN saja, komplain ditutup untuk ADMIN_OPERASIONAL, pengingat HPP dibuang) — jangan dikembalikan.

## A. Fitur inti yang HILANG di template ops (salin form persis dari template asli: action, method, nama field, csrf, data-*, alasan wajib, data-app-confirm)
1. `ops/today.html` ← `delivery/today.html`: panel **"Pengiriman belum dibuat"** (`delivery_next_actions`) dengan form `delivery.create_from_order` + `blocking_reason` bila tidak bisa. Ini satu-satunya cara admin membuat pengiriman.
2. `ops/orders.html` ← `operational/orders.html`: form **buat produksi** `operational.generate_production`.
3. `ops/order_detail.html` ← `operational/order_detail.html`: form **ubah porsi** `operational.change_order_detail_qty` (field `meal_type`, `new_qty`, `reason`, `reason_code`) — pakai bottom-sheet `<dialog>` kecil, bukan modal Bootstrap. Tautan HPP/stok TETAP tidak ditampilkan.
4. `ops/delivery_detail.html` ← `delivery/detail.html`: form **pengganti kekurangan** `delivery.create_shortage_replacement`, form **SLA** `delivery.update_sla` (field `target_dispatch_time`, `target_arrival_time`, `late_tolerance_minutes`), tautan lihat foto bukti `delivery.view_attachment` dan foto lokasi `location_photos.view`.
5. `ops/receiving.html`: foto lokasi `location_photos.view` seperti asli.
6. `ops/menu_schedule.html` ← `operational/menu_schedule.html`: form **simpan slot menu** `operational.save_menu_schedule_slot` (field `menu_date`, `meal_type`, `menu_id`, `notes`, `week_ref`) + tombol salin minggu lalu bila ada di asli. Tautan ke `costing.menus` TIDAK ditampilkan (di luar lingkup).
7. `ops/order_qty_changes.html`: filter asli (`source`, `mandor_id`, tanggal) dalam satu form GET berkelas `app-filter`.
8. `ops/production_detail.html`: tombol buat pengiriman pakai `production_delivery_action.delivery_type` dan tampilkan `blocking_reason` seperti asli (jangan `production.production_type`).

## B. Mode HP untuk OWNER/ADMIN (sekarang rusak: dari `/ops` hanya beranda yang versi HP, tab lain kembali ke desktop)
- Di `ops_navigation_service.py` buat satu fungsi `uses_ops_ui(user)`: `True` bila role `ADMIN_OPERASIONAL`, atau role OWNER/ADMIN dan `session.get("ops_mode")`.
- Route `/ops` (`dashboard.ops_door`) untuk OWNER/ADMIN: set `session["ops_mode"] = True` lalu redirect ke beranda ops. Tambah route `/ops/exit` (POST, csrf) untuk OWNER/ADMIN: hapus flag lalu redirect ke dashboard biasa; tombolnya **hanya** di `ops/account.html` ("Kembali ke tampilan desktop", tampil bila role OWNER/ADMIN).
- Ganti SEMUA pemilihan template `current_user.role == "ADMIN_OPERASIONAL"` di route menjadi `uses_ops_ui(current_user)`; `is_ops_context` memakai fungsi yang sama. Pemilihan `driver/...` untuk PENGANTAR jangan diubah.

## C. Tes (tulis, jangan jalankan)
- `tests/test_admin_operasional_permissions.py`: ADMIN_OPERASIONAL DITOLAK pada `POST /delivery/attachments/<id>/delete` dan `/customer-success/complaints`.
- `tests/test_ops_navigation.py`: OWNER setelah membuka `/ops` mendapat `ops-mobile-shell` di `/operational/orders` dan `/delivery/today`; setelah `POST /ops/exit` kembali ke layout desktop.
- Tes kecocokan form: untuk tiap pasangan template di bagian A, semua `action`/`url_for` form di template asli (kecuali yang sengaja dikecualikan: HPP/stok, `costing.menus`, `owner_override`, `finance.*`, `settings.approvals`) ada di template ops.

Selesai → daftar file + perintah owner:
`venv\Scripts\python.exe -m pytest -q tests/test_ops_navigation.py tests/test_admin_operasional_permissions.py tests/test_driver_navigation.py tests/test_portal_navigation.py tests/test_delivery_scan_flow.py`
