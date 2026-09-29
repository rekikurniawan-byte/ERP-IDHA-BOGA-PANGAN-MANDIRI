# Production Server Foundation — Idha Boga

Dokumen ini adalah template deployment, bukan perintah go-live otomatis.
Production final tetap wajib staging rehearsal, restore drill, dan checklist go-live.

## Folder server rekomendasi

```text
/opt/idha-boga/app
/opt/idha-boga/venv
/var/www/idha-boga/instance/uploads
/var/backups/idha-boga
/var/log/idha-boga
```

## Urutan deploy ringkas

```bash
sudo adduser idhaboga
sudo mkdir -p /opt/idha-boga/app /var/www/idha-boga/instance/uploads/digital_attachments /var/backups/idha-boga /var/log/idha-boga
sudo chown -R idhaboga:www-data /opt/idha-boga /var/www/idha-boga /var/backups/idha-boga /var/log/idha-boga
sudo chmod 750 /var/www/idha-boga/instance/uploads /var/backups/idha-boga /var/log/idha-boga

python -m venv /opt/idha-boga/venv
/opt/idha-boga/venv/bin/pip install -r /opt/idha-boga/app/requirements.txt

cd /opt/idha-boga/app
# Selalu sebagai user aplikasi dengan .env.production: tabel yang dibuat user
# database lain membuat aplikasi kena "permission denied".
sudo -u idhaboga env $(cat .env.production | xargs) /opt/idha-boga/venv/bin/flask --app run db upgrade
# Database baru hanya berisi tabel: isi COA acuan, cabang pertama, dan OWNER
# pertama. Aman diulang; password diminta (atau BOOTSTRAP_OWNER_PASSWORD).
sudo -u idhaboga env $(cat .env.production | xargs) /opt/idha-boga/venv/bin/flask --app run bootstrap \
    --branch-code PUSAT --branch-name "Cabang Pusat" --owner-username owner --owner-name "Nama Owner"
python tools/check_production_runtime_foundation.py
python tools/check_production_health_monitoring.py
/opt/idha-boga/venv/bin/flask --app run ops-check   # wajib 0 FAIL sebelum dibuka ke pengguna
```

## Penjadwal harian (systemd timer)

| Unit | Jam | Perintah | Guna |
|---|---|---|---|
| `idha-boga-credit-sweep` | 00:30 | `flask --app run credit-sweep` | Penyapu harian: kontrak yang lewat tanggal berakhir jadi Kedaluwarsa, pengingat kontrak H-30/H-7, lalu naikkan status akun kredit yang menunggak (tanpa menunggu ada yang login) |
| `idha-boga-backup` | 02:00 | `flask --app run backup-full` | Backup penuh database + lampiran, lalu diverifikasi |
| `idha-boga-ops-check` | 06:00 | `flask --app run ops-check` | Cek kesiapan; ada FAIL = unit gagal |

```bash
sudo cp deployment/systemd/idha-boga-*.service.example /etc/systemd/system/   # buang akhiran .example
sudo cp deployment/systemd/idha-boga-*.timer.example /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now idha-boga-credit-sweep.timer idha-boga-backup.timer idha-boga-ops-check.timer
systemctl list-timers 'idha-boga-*'
```

`backup-full` butuh `pg_dump` (paket `postgresql-client`, versi sama dengan server
PostgreSQL). Kalau tidak ada di PATH, set `PG_DUMP_PATH`. Backup tetap harus
disalin ke luar server dan diuji pulihkan berkala (lihat BACKUP_RESTORE_RECOVERY_SOP.md).

## Pemantauan harian

```bash
systemctl --failed                                  # unit gagal (backup/ops-check/sweep)
journalctl -u idha-boga-ops-check --since today     # hasil cek kesiapan hari ini
tail -n 100 /var/log/idha-boga/error.log            # error aplikasi (log berputar, lihat deployment/logrotate)
```

## Endpoint monitoring

```text
/healthz   -> app alive
/readiness -> DB, migration, storage, log, disk, journal quick check
```

## Prinsip lampiran/bukti digital

Upload disimpan di folder private dan tidak boleh di-serve langsung oleh Nginx.
Akses file tetap melalui route Flask yang sudah login dan role guard.
