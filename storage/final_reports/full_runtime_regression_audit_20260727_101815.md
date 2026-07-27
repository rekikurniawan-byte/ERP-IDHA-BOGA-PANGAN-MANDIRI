# Full Runtime Regression Audit ERP Idha Boga

Timestamp: `20260727_101815`

## A. Temuan Sebelum Perbaikan

- `finance.generate_period_invoice_preview` memakai private helper `_get_client_for_mandor_invoice` dari route lain sehingga runtime dapat `NameError` setelah split route.
- `finance.generate_period_invoice_preview` juga memakai helper qty realtime yang sebelumnya hanya hidup di route realtime.
- Audit sebelumnya belum memiliki manifest coverage runtime gabungan static/dynamic GET dan belum mencatat endpoint POST yang sengaja tidak dieksekusi otomatis.

## B. Perubahan

- Helper mandor invoice dipindahkan ke `app/services/mandor_invoice_helper_service.py` dengan nama publik.
- Route realtime dan period invoice memakai helper service, bukan private helper route lain.
- Placeholder `assert True` diganti menjadi app factory route-map regression test.
- Audit runner ini membuat laporan final dan route coverage manifest.

## C. Bukti Audit

| Area | Hasil |
| --- | ---: |
| Total Flask route/rule | 339 |
| Duplicate endpoint | 0 |
| Duplicate rule+method | 0 |
| GET route dieksekusi | 247 |
| GET route gagal | 0 |
| GET route belum dieksekusi | 2 |
| POST route diklasifikasi | 164 |
| Template total | 212 |
| Template parsed | 212 |
| `url_for` diverifikasi | 952 |
| Missing `url_for` endpoint | 0 |
| Missing template reference | 0 |
| Module route/service imported | 150 |
| Module import failure | 0 |
| Private helper unresolved tanpa wildcard | 0 |
| Wildcard import terdeteksi | 44 |
| JS suspicious boolean rendering | 0 |
| Pyflakes fatal undefined candidates | see command output; pyflakes is noisy due wildcard compatibility wrappers |

## D. Coverage Nyata

- Route GET yang benar-benar dieksekusi: 247.
- Route POST tidak dieksekusi oleh smoke umum: 164; diklasifikasi agar diuji dengan fixture spesifik/nested transaction.
- Endpoint belum dieksekusi otomatis: 166.

### GET Belum Dieksekusi

- `settings.download_backup_confirm` `/settings/backups/download-confirm/<path:filename>`: fixture path parameter belum tersedia untuk endpoint ini
- `static` `/static/<path:filename>`: static asset route; bukan halaman ERP

## E. Sisa Risiko

- POST mutasi/destruktif tidak dieksekusi oleh smoke umum karena membutuhkan fixture isolasi dan assertion bisnis per use case.
- Wildcard import masih ada sebagai compatibility wrapper pasca split; ini bukan runtime failure, tetapi tetap risiko maintainability.
- Pyflakes tersedia tetapi terlalu bising karena wrapper dan wildcard import; hasilnya dipakai sebagai sinyal, bukan gate tunggal.

## F. Putusan

UAT_READY
