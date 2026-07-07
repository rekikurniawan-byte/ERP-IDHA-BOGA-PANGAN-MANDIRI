# Backup/Restore/Recovery Hosting SOP

**Project:** PT Idha Boga Pangan Mandiri  
**Database:** PostgreSQL (WAJIB, SQLite DILARANG)  
**Backup Tool:** pg_dump / pg_restore  
**Hosting:** LAN server atau VPS/cloud

---

## 1. Lokasi Folder

| Folder | Path Default | Fungsi |
|--------|-------------|--------|
| Backup | `instance/backups/` | .dump dan .zip backup files |
| Staging | `instance/backups/_staging/` | Temporary file sebelum finalize |
| Restore Preview | `instance/backups/_restore_preview/` | Preview file sebelum restore |
| Logs | `instance/backups/_logs/` | Audit log backup/restore |
| Uploads | `instance/uploads/digital_attachments/` | Bukti digital (foto, PDF) |

---

## 2. Backup Harian (Otomatis)

### Windows Task Scheduler

```powershell
# File: scripts/daily_backup.ps1
$env:Path += ";C:\laragon\bin\postgresql\postgresql-11.0-1\bin"
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$backupDir = "C:\idha-boga-backups"
$dbUrl = "postgresql://idha_boga_user:PASSWORD@localhost:5432/idha_boga_production"

New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
$dumpFile = "$backupDir\daily_$timestamp.dump"

pg_dump --format=custom --no-owner --no-privileges --file=$dumpFile --dbname=$dbUrl
certutil -hashfile $dumpFile SHA256 > "$dumpFile.sha256.txt"

# Hapus backup > 30 hari
Get-ChildItem $backupDir -Filter "daily_*.dump" |
    Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
    Remove-Item -Force

Write-Host "OK: $dumpFile"
```

### Linux Cron (VPS/Cloud)

```bash
# /etc/cron.d/idha-boga-backup
0 2 * * * root /opt/idha-boga/scripts/daily_backup.sh
```

---

## 3. Backup Sebelum Update Sistem

**WAJIB sebelum:**
- Update source code / git pull
- Flask db upgrade (migration)
- Perubahan config production
- Install/update package

```powershell
$env:Path += ";C:\laragon\bin\postgresql\postgresql-11.0-1\bin"
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
pg_dump --format=custom --file="PRE_UPDATE_$stamp.dump" --dbname="postgresql://..."
certutil -hashfile "PRE_UPDATE_$stamp.dump" SHA256
```

---

## 4. Restore Dry-Run Berkala (Bulanan)

**Tujuan:** Pastikan backup terakhir bisa di-restore.

### Via Python (App)

```python
from app.services.backup_service import restore_dry_run, restore_dry_run_to_shadow

# Quick check (tidak modify DB)
result = restore_dry_run("instance/backups/latest.dump")
print(result["status"])  # PASS or FAIL

# Full shadow restore (buat DB test, restore, verifikasi, drop)
result = restore_dry_run_to_shadow("instance/backups/latest.dump")
print(result["status"])  # PASS or FAIL
```

### Via Command Line

```powershell
$env:Path += ";C:\laragon\bin\postgresql\postgresql-11.0-1\bin"

# Quick TOC check
pg_restore --list latest.dump

# Full shadow test
createdb idha_boga_restore_test
pg_restore --no-owner --no-privileges --single-transaction --exit-on-error --dbname="postgresql://...@localhost/idha_boga_restore_test" latest.dump
# Verify: python run.py dengan DATABASE_URL ke restore_test
dropdb idha_boga_restore_test
```

---

## 5. Emergency Recovery

### Skenario: Database Production Corrupt/Hilang

```powershell
# 1. STOP app
Stop-Service idha-boga  # atau Ctrl+C pada terminal

# 2. Drop database rusak (HATI-HATI)
$env:Path += ";C:\laragon\bin\postgresql\postgresql-11.0-1\bin"
dropdb idha_boga_production

# 3. Buat ulang
createdb idha_boga_production

# 4. Restore dari backup terakhir
pg_restore --no-owner --no-privileges --single-transaction --exit-on-error --dbname="postgresql://...@localhost/idha_boga_production" latest_backup.dump

# 5. Verifikasi
python -m flask db current
python run.py
# Login OWNER, cek dashboard

# 6. Restore uploads (jika pakai full backup ZIP)
# Extract uploads/ dari ZIP ke instance/uploads/digital_attachments/
```

---

## 6. Retensi Backup

| Tipe | Retensi | Storage |
|------|---------|---------|
| Harian | 30 hari | Server lokal |
| Mingguan | 12 minggu | USB/NAS external |
| Pre-update | 7 hari minimum | Server lokal |
| Go-live baseline | Permanent | Offline + cloud |
| Full package (ZIP) | 90 hari | External storage |

---

## 7. Verifikasi Checksum

Setiap backup punya file `.sha256.txt` di sampingnya.

```powershell
# Verifikasi manual
certutil -hashfile backup.dump SHA256
# Bandingkan dengan isi backup.dump.sha256.txt
```

---

## 8. Uploaded Files / Bukti Digital

Bukti digital (foto nota, struk, bukti transfer) ada di `instance/uploads/digital_attachments/`.

**Strategi backup:**
- Full backup ZIP (`create_full_backup_package`) otomatis include semua uploads
- Untuk backup terpisah: copy folder `instance/uploads/` ke external storage
- Retensi: sama dengan retensi database

---

## 9. Checklist Bulanan

- [ ] Backup harian berjalan (cek folder/log)
- [ ] Restore dry-run PASS (jalankan `restore_dry_run`)
- [ ] SHA256 match (verifikasi 1 file random)
- [ ] Disk space cukup (min 10GB free)
- [ ] Backup offsite sudah di-copy (USB/NAS)
- [ ] Uploads folder di-backup terpisah jika perlu
- [ ] Akses OWNER backup page berfungsi

---

## 10. Yang DILARANG

- ❌ Backup dengan `copy instance/*.db` (SQLite sudah tidak ada)
- ❌ Restore tanpa backup sebelumnya
- ❌ Restore ke production tanpa dry-run dulu
- ❌ Simpan backup di folder `app/static/` atau source code
- ❌ Role selain OWNER mengakses backup/restore
- ❌ Deploy update tanpa backup dulu
