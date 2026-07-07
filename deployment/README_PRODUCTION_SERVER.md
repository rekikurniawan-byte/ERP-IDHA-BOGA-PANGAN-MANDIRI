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
flask db upgrade
python tools/check_production_runtime_foundation.py
python tools/check_production_health_monitoring.py
```

## Endpoint monitoring

```text
/healthz   -> app alive
/readiness -> DB, migration, storage, log, disk, journal quick check
```

## Prinsip lampiran/bukti digital

Upload disimpan di folder private dan tidak boleh di-serve langsung oleh Nginx.
Akses file tetap melalui route Flask yang sudah login dan role guard.
