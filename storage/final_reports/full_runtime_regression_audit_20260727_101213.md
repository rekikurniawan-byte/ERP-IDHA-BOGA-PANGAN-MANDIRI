# Full Runtime Regression Audit ERP Idha Boga

Timestamp: `20260727_101213`

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
| Private helper unresolved tanpa wildcard | 51 |
| Wildcard import terdeteksi | 44 |
| JS suspicious boolean rendering | 25 |
| Pyflakes fatal undefined candidates | see command output; pyflakes is noisy due wildcard compatibility wrappers |

## D. Coverage Nyata

- Route GET yang benar-benar dieksekusi: 247.
- Route POST tidak dieksekusi oleh smoke umum: 164; diklasifikasi agar diuji dengan fixture spesifik/nested transaction.
- Endpoint belum dieksekusi otomatis: 166.

### GET Belum Dieksekusi

- `settings.download_backup_confirm` `/settings/backups/download-confirm/<path:filename>`: fixture path parameter belum tersedia untuk endpoint ini
- `static` `/static/<path:filename>`: static asset route; bukan halaman ERP

### JS Boolean Rendering Review

- `app/static/js/main.js:432` `hint.innerHTML = '<i class="bi bi-arrow-left-right" aria-hidden="true"></i><span>Geser tabel untuk melihat kolom lainnya</span>';`
- `app/static/js/main.js:867` `dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul`
- `app/static/js/main.js:985` `dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul`
- `app/static/js/main.js:1136` `dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul`
- `app/static/js/main.js:1167` `hint.textContent = "Geser tabel ke samping untuk melihat detail stok, procurement, recipe, atau HPP lengkap.";`
- `app/static/js/main.js:1271` `dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul`
- `app/static/js/main.js:1425` `dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul`
- `app/static/js/main.js:1679` `dropdown.innerHTML = '<button class="btn app-btn-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown" aria-expanded="false"><i class="bi bi-three-dots"></i> Aksi lainnya</button><ul class="dropdown-menu dropdown-menu-end"></ul`
- `app/static/js/main.js:1747` `hint.innerHTML = '<div class="empty-state-icon"><i class="bi bi-inbox" aria-hidden="true"></i></div><h3>Data belum ada</h3><p>Belum ada data yang bisa ditampilkan untuk filter atau periode ini.</p>';`
- `app/static/js/main.js:1777` `button.innerHTML = '<span class="spinner-border spinner-border-sm me-1" aria-hidden="true"></span>' + loadingLabel;`
- `app/static/js/main.js:2660` `iconWrap.innerHTML = '<i class="bi ' + (context.icon || "bi-info-circle") + '" aria-hidden="true"></i>';`
- `app/static/js/main.js:3029` `empty.textContent = "Tidak ada pilihan yang cocok.";`
- `app/static/js/main.js:3088` `trigger.innerHTML = '<span class="app-atomic-field-value"></span><span class="app-atomic-field-icon" aria-hidden="true"><i class="bi bi-chevron-down"></i></span>';`
- `app/static/js/main.js:3361` `prevYear.innerHTML = '<i class="bi bi-chevron-left" aria-hidden="true"></i>';`
- `app/static/js/main.js:3376` `nextYear.innerHTML = '<i class="bi bi-chevron-right" aria-hidden="true"></i>';`
- `app/static/js/main.js:3512` `trigger.innerHTML = '<span class="app-atomic-field-value"></span><span class="app-atomic-field-icon" aria-hidden="true"><i class="bi bi-calendar3"></i></span>';`
- `app/static/js/main.js:3523` `head.innerHTML = '<button type="button" class="app-date-picker-nav" data-date-nav="prev" aria-label="Bulan sebelumnya"><i class="bi bi-chevron-left"></i></button><button type="button" class="app-date-picker-title" data-date-title aria-expan`
- `app/static/js/main.js:3954` `icon.textContent = safeTone === "success" ? "✓" : (safeTone === "danger" ? "!" : "i");`
- `app/static/js/main.js:4181` `button.innerHTML = '<i class="bi bi-upload" aria-hidden="true"></i><span>Pilih File</span>';`
- `app/static/js/main.js:4450` `host.innerHTML = '<div class="app-action-loading-pill"><span class="app-action-loading-spinner" aria-hidden="true"></span><span class="app-action-loading-text">Memproses aksi...</span></div>';`
- `app/static/js/main.js:4503` `submitter.innerHTML = '<span class="app-button-spinner" aria-hidden="true"></span><span class="app-button-loading-text">' + escapeHtml(loadingText || "Memproses...") + '</span>';`
- `app/static/js/main.js:4902` `trigger.innerHTML = '<span class="app-atomic-field-value"></span><span class="app-atomic-field-icon" aria-hidden="true"><i class="bi bi-clock"></i></span>';`
- `app/static/js/main.js:5016` `toggle.innerHTML = '<i class="bi bi-eye" aria-hidden="true"></i><span class="visually-hidden">Tampilkan password</span>';`
- `app/static/js/main.js:5024` `toggle.innerHTML = showing ? '<i class="bi bi-eye" aria-hidden="true"></i><span class="visually-hidden">Tampilkan password</span>' : '<i class="bi bi-eye-slash" aria-hidden="true"></i><span class="visually-hidden">Sembunyikan password</span`
- `app/static/js/main.js:5542` `pill.innerHTML = '<span class="app-print-export-spinner" aria-hidden="true"></span><span></span>';`

## E. Sisa Risiko

- POST mutasi/destruktif tidak dieksekusi oleh smoke umum karena membutuhkan fixture isolasi dan assertion bisnis per use case.
- Wildcard import masih ada sebagai compatibility wrapper pasca split; ini bukan runtime failure, tetapi tetap risiko maintainability.
- Pyflakes tersedia tetapi terlalu bising karena wrapper dan wildcard import; hasilnya dipakai sebagai sinyal, bukan gate tunggal.

## F. Putusan

UAT_READY
