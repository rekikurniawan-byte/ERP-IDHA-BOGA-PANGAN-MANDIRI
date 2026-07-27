# Audit Deployment Readiness ERP Idha Boga

Laporan ini memvalidasi hal yang bisa dicek dari konfigurasi lokal. Validasi Nginx/firewall/Redis nyata tetap harus dilakukan di server.

## Ringkasan

| Metrik | Nilai |
| --- | --- |
| Total check | 7 |
| Critical failed | 0 |

## Detail

| Status | Check | Critical | Pesan |
| --- | --- | --- | --- |
| PASS | DATABASE_URL | ya | postgresql+psycopg://idha_boga_user:***@127.0.0.1:5432/idha_boga |
| PASS | RATELIMIT_STORAGE_URI | ya | redis://127.0.0.1:6379/1 |
| PASS | TRUSTED_HOSTS | ya | domainanda.com, www.domainanda.com |
| PASS | SESSION_COOKIE_SECURE | ya | True |
| REVIEW | PROXY_HEADERS_ENABLED | ya | Aktif: pastikan Gunicorn tidak bisa diakses langsung dan hanya di belakang satu proxy tepercaya. |
| REVIEW | BACKUP_ROOT | tidak | /var/backups/idha-boga | wajib diuji restore off-host dan retensi/enkripsi. |
| REVIEW | UPLOAD_ROOT | tidak | /var/www/idha-boga/instance/uploads | wajib ikut backup attachment. |

## Checklist Server

- Gunicorn bind ke `127.0.0.1` atau Unix socket.

- Port internal ditutup dari jaringan publik.

- `PROXY_HEADERS_ENABLED=1` hanya jika tepat satu reverse proxy tepercaya di depan aplikasi.

- `RATELIMIT_STORAGE_URI` memakai Redis/storage bersama untuk multi-worker.

- Jalankan restore drill off-host: backup, restore, migrate, login, rekonsiliasi.

