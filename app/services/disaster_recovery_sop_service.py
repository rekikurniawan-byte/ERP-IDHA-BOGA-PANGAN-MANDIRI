from __future__ import annotations
import logging

from datetime import datetime
from pathlib import Path
from typing import Dict, List

from flask import current_app

from app.services.backup_service import (
    APP_VERSION as BACKUP_ENGINE_VERSION,
    calculate_sha256,
    get_backup_dir,
    get_database_path,
    get_digital_attachment_upload_dir,
)

logger = logging.getLogger(__name__)


APP_VERSION = "PRODUCTION"
DISASTER_RECOVERY_SOP_VERSION = "PRODUCTION_DISASTER_RECOVERY_SOP_V1"
BACKUP_RESTORE_SOP_VERSION = "PRODUCTION_BACKUP_RESTORE_SOP_V1"
RESTORE_DRILL_SOP_VERSION = "PRODUCTION_RESTORE_DRILL_SOP_V1"


def _safe_path(fn, fallback: str = "-") -> str:
    try:
        return str(fn())
    except Exception:
        logger.exception("Suppressed unexpected exception in app/services/disaster_recovery_sop_service.py:27")
        return fallback


def _db_snapshot() -> Dict[str, object]:
    try:
        db_path = get_database_path()
        return {
            "path": str(db_path),
            "exists": db_path.exists(),
            "size_bytes": db_path.stat().st_size if db_path.exists() else 0,
            "sha256": calculate_sha256(db_path) if db_path.exists() else "-",
        }
    except Exception as exc:
        logger.exception("Suppressed unexpected exception in app/services/disaster_recovery_sop_service.py:40")
        return {"path": "-", "exists": False, "size_bytes": 0, "sha256": "-", "error": str(exc)}


def _runtime_paths() -> Dict[str, object]:
    return {
        "project_root": str(Path(current_app.root_path).resolve().parent),
        "database": _db_snapshot(),
        "backup_dir": _safe_path(get_backup_dir),
        "upload_dir": _safe_path(get_digital_attachment_upload_dir),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "app_version": APP_VERSION,
        "backup_engine_version": BACKUP_ENGINE_VERSION,
    }


def _safety_pages() -> List[Dict[str, str]]:
    return [
        {"label": "Kesehatan Sistem", "endpoint": "settings.system_health", "icon": "bi-heart-pulse", "purpose": "cek DB, backup, upload, jurnal, disk, dan migration secara read-only"},
        {"label": "Backup & Restore", "endpoint": "settings.backups", "icon": "bi-database-down", "purpose": "buat full backup verified dan validasi restore preview"},
        {"label": "Atomic Smoke Simulation", "endpoint": "settings.atomic_smoke_simulation", "icon": "bi-shield-check", "purpose": "uji rollback atomic di copy DB tanpa menyentuh DB aktif"},
        {"label": "Atomic Transaction Map", "endpoint": "settings.atomic_transaction_map", "icon": "bi-diagram-3", "purpose": "lihat peta area commit/rollback yang masih perlu diperketat"},
        {"label": "Audit Log", "endpoint": "settings.audit_logs", "icon": "bi-activity", "purpose": "telusuri aksi critical/high, alasan, user, IP, dan target data"},
    ]


def get_disaster_recovery_sop() -> Dict[str, object]:
    """Return final disaster recovery SOP data for read-only SOP pages."""
    return {
        "schema_version": DISASTER_RECOVERY_SOP_VERSION,
        "title": "Disaster Recovery SOP Final",
        "eyebrow": "PRODUCTION / Recovery & Anti-Panic Procedure",
        "mode": "READ_ONLY_GUIDANCE",
        "runtime": _runtime_paths(),
        "safety_pages": _safety_pages(),
        "summary": [
            "SOP ini dipakai saat database error, aplikasi gagal jalan, file bukti hilang, backup perlu dipakai, atau patch besar akan dijalankan.",
            "Tidak ada tombol restore aktif di halaman SOP. Restore database aktif tetap manual-assisted dan hanya boleh setelah backup VERIFIED serta server dihentikan.",
            "Tujuan utama bukan panik cepat restore, tetapi mengamankan kondisi aktif, membaca health, memilih backup verified, preview/dry-run, lalu restore dengan jalur balik.",
        ],
        "incident_levels": [
            {"level": "LEVEL 1", "name": "Warning", "status_class": "warning", "examples": ["Belum ada backup verified", "orphan upload muncul", "disk mulai sempit", "ada transaksi belum posting"], "action": "Buka Kesehatan Sistem, buat full backup verified, dan catat warning."},
            {"level": "LEVEL 2", "name": "Data Risk", "status_class": "danger", "examples": ["missing upload reference", "journal imbalance", "foreign key warning", "backup gagal verified"], "action": "Hentikan patch lanjutan, buat salinan manual DB/uploads, cek Audit Log dan Backup Restore."},
            {"level": "LEVEL 3", "name": "Emergency", "status_class": "danger", "examples": ["database corrupt", "aplikasi tidak bisa start", "DB aktif terhapus", "restore sebelumnya salah"], "action": "Jangan input transaksi baru. Stop server, amankan sisa file, restore dari backup VERIFIED lewat SOP manual."},
        ],
        "decision_flow": [
            {"step": "1", "title": "Jangan lanjut input transaksi", "description": "Saat muncul error database, file hilang, atau angka aneh, hentikan input transaksi baru agar kerusakan tidak bertambah."},
            {"step": "2", "title": "Buka Kesehatan Sistem", "description": "Cek integrity, FK, journal balance, backup verified, missing/orphan upload, disk, dan migration."},
            {"step": "3", "title": "Cek Audit Log", "description": "Cari aksi terakhir: backup/download/restore preview, user change, payment, journal, payroll, procurement, atau delete/cancel."},
            {"step": "4", "title": "Amankan kondisi aktif", "description": "Sebelum restore, copy DB aktif dan folder uploads aktif ke folder pre-restore agar masih ada jalur balik."},
            {"step": "5", "title": "Pilih backup VERIFIED", "description": "Gunakan hanya full backup yang PASS pre-check, post-check, dan restore preview dry-run."},
            {"step": "6", "title": "Restore manual-assisted", "description": "Stop server Flask, pulihkan DB + uploads sebagai satu paket, lalu jalankan checklist pasca-restore."},
        ],
        "emergency_steps": [
            "Tutup aplikasi di browser dan jangan klik simpan transaksi lagi.",
            "Hentikan server Flask dengan CTRL+C di terminal yang menjalankan python run.py.",
            "Copy database aktif dan folder uploads aktif sebelum menimpa apa pun.",
            "Buka ZIP full backup VERIFIED di folder sementara, jangan ekstrak langsung menimpa project.",
            "Pastikan ZIP berisi database/postgres.dump dan uploads/digital_attachments/.",
            "Pulihkan DB dan uploads dari timestamp backup yang sama.",
            "Jalankan python run.py dan login OWNER.",
            "Buka Kesehatan Sistem, Backup, Lampiran Digital, Finance Invoice, Accounting Journal, Dashboard Owner, dan Audit Log.",
        ],
        "do_not_do": [
            "Jangan restore saat server Flask masih berjalan.",
            "Jangan restore DB saja jika masalahnya melibatkan bukti transfer/delivery/procurement/payroll.",
            "Jangan mencampur DB dari backup tanggal A dengan uploads dari backup tanggal B.",
            "Jangan memberi label aman ke backup yang belum VERIFIED.",
            "Jangan hapus backup lama sebelum restore drill terbaru PASS.",
            "Jangan edit langsung file PostgreSQL pakai tool eksternal tanpa copy cadangan.",
        ],
        "owner_admin_responsibility": [
            "OWNER memastikan keputusan restore hanya memakai backup VERIFIED dan alasan restore tercatat.",
            "ADMIN membantu cek akses, folder, koneksi LAN, dan bukti digital setelah restore.",
            "ACCOUNTING mengecek jurnal balance, laporan, dan posting status setelah restore.",
            "FINANCE mengecek invoice, payment, piutang, dan bukti transfer setelah restore.",
            "LOGISTICS/DELIVERY mengecek stok, procurement, delivery proof, dan file bukti lapangan.",
        ],
        "before_big_patch_checklist": [
            "Kesehatan Sistem status AMAN atau minimal tidak ada error kritis.",
            "Full backup terbaru status VERIFIED.",
            "Restore preview dry-run PASS.",
            "Atomic smoke simulation PASS.",
            "Journal imbalance = 0.",
            "Foreign key check = 0 error.",
            "Missing upload reference = 0 atau sudah dipahami sumbernya.",
            "DB hash dicatat di laporan patch.",
        ],
    }


def get_backup_restore_sop() -> Dict[str, object]:
    """Return final backup/restore/drill SOP data for read-only SOP pages."""
    return {
        "schema_version": BACKUP_RESTORE_SOP_VERSION,
        "drill_schema_version": RESTORE_DRILL_SOP_VERSION,
        "title": "Backup & Restore SOP Final",
        "eyebrow": "PRODUCTION / Full Backup Verified + Restore Drill",
        "mode": "READ_ONLY_GUIDANCE",
        "runtime": _runtime_paths(),
        "safety_pages": _safety_pages(),
        "backup_policy": [
            "Backup aman adalah full system backup: database + uploads/digital_attachments + manifest + checksums + backup_info + validation_result + restore_readme.",
            "Backup DB-only hanya partial dan tidak cukup untuk memulihkan bukti transfer/delivery/procurement/payroll.",
            "Backup baru wajib disimpan di instance/backups, bukan root backups/ dan bukan app/static.",
            "File upload sensitif tetap di instance/uploads/digital_attachments, database hanya menyimpan metadata/path/checksum.",
            "Backup tidak boleh disebut VERIFIED sebelum pre-check, post-check, dan restore preview dry-run PASS.",
        ],
        "create_full_backup_steps": [
            {"title": "1. Buka Kesehatan Sistem", "description": "Pastikan DB integrity, FK, journal balance, folder upload, disk, dan migration tidak error."},
            {"title": "2. Buka Backup & Restore", "description": "Pastikan panel pre-backup health check PASS sebelum membuat backup baru."},
            {"title": "3. Buat Full Backup", "description": "Gunakan tombol full backup DB + uploads. Isi alasan dan password re-confirm sesuai sensitive action guard."},
            {"title": "4. Tunggu status VERIFIED", "description": "Sistem menjalankan pre-check, staging, ZIP, post-check, dan restore preview dry-run."},
            {"title": "5. Download backup jika perlu", "description": "Download juga melewati guard; simpan file di media eksternal/drive yang aman."},
        ],
        "verification_contract": [
            "ZIP bisa dibuka dan testzip PASS.",
            "Required members lengkap.",
            "manifest.json, backup_info.json, validation_result.json, app_version.txt, alembic_version.txt, restore_readme.txt valid.",
            "checksums.sha256 cocok untuk database, metadata, dan uploads.",
            "DB snapshot di dalam ZIP PASS integrity_check dan foreign_key_check.",
            "Uploads hasil ekstrak cocok count/size/checksum dengan manifest.",
            "Restore preview dry-run PASS di folder sementara tanpa menyentuh DB aktif.",
        ],
        "restore_preview_steps": [
            "Upload file backup ke Validasi Restore / Preview Only.",
            "Isi alasan dan password akun aktif.",
            "Lanjutkan hanya jika status valid untuk manual restore dan restore dry-run PASS.",
            "Jika ada error checksum, missing member, FK, integrity, atau upload mismatch, jangan restore.",
        ],
        "active_restore_steps": [
            {"title": "1. Stop server", "commands": ["CTRL + C pada terminal python run.py"], "description": "PostgreSQL tidak boleh ditimpa saat aplikasi masih berjalan."},
            {"title": "2. Copy kondisi aktif", "commands": ["Copy-Item instance\\idha_boga_pangan.db instance\\backups\\PRE_RESTORE_ACTIVE_DB_YYYYMMDD_HHMMSS.db", "Copy-Item instance\\uploads\\digital_attachments instance\\backups\\PRE_RESTORE_DIGITAL_ATTACHMENTS_YYYYMMDD_HHMMSS -Recurse"], "description": "Ini jalur rollback jika restore salah."},
            {"title": "3. Ekstrak full backup", "commands": ["Expand-Archive IDHA_BOGA_FULL_BACKUP_YYYYMMDD_HHMMSS.zip -DestinationPath instance\\backups\\RESTORE_EXTRACT_YYYYMMDD_HHMMSS -Force"], "description": "Ekstrak ke folder sementara, bukan langsung menimpa app."},
            {"title": "4. Pulihkan DB + uploads", "commands": ["Copy-Item RESTORE_EXTRACT\\database\\idha_boga_pangan.db instance\\idha_boga_pangan.db -Force", "Copy-Item RESTORE_EXTRACT\\uploads\\digital_attachments\\* instance\\uploads\\digital_attachments\\ -Recurse -Force"], "description": "DB dan uploads harus dari backup yang sama."},
            {"title": "5. Jalankan aplikasi", "commands": ["python run.py"], "description": "Setelah server jalan, login OWNER dan lakukan checklist post-restore."},
        ],
        "post_restore_checks": [
            "Login OWNER berhasil.",
            "Kesehatan Sistem terbuka dan DB integrity PASS.",
            "Foreign key check 0 error.",
            "Journal imbalance 0.",
            "Backup & Restore terbuka dan backup terbaru terbaca.",
            "Lampiran Digital bisa dibuka/download.",
            "Invoice detail dan bukti payment terbaca.",
            "Delivery proof terbaca.",
            "Accounting journal dan laporan terbaca.",
            "Dashboard Owner/Admin terbuka.",
            "Audit Log mencatat proses validasi/download/aksi sensitif terkait.",
        ],
        "restore_drill": {
            "frequency": "Minimal 1 kali per minggu atau sebelum patch besar.",
            "result_status": ["PASS", "PASS_WITH_WARNING", "FAILED"],
            "steps": [
                "Ambil full backup terbaru yang statusnya VERIFIED.",
                "Restore preview/dry-run ke folder test/copy, bukan DB aktif.",
                "Cek DB integrity, FK, journal balance, upload checksum, invoice proof, delivery proof, dan dashboard.",
                "Catat hasil drill di laporan patch atau catatan owner.",
                "Jika FAILED, jangan hapus backup lama dan jangan lanjut patch besar.",
            ],
        },
        "download_storage_rules": [
            "Simpan minimal 2 salinan backup: satu di laptop/server, satu di media eksternal/cloud privat.",
            "Jangan kirim ZIP backup ke chat umum tanpa kebutuhan jelas karena berisi data bisnis dan bukti digital.",
            "Jangan rename isi file di dalam ZIP karena checksum akan gagal.",
            "Jangan edit manifest/checksums secara manual.",
        ],
    }


def get_recovery_sop_summary() -> Dict[str, object]:
    """Small summary used by Backup/Kesehatan Sistem pages."""
    return {
        "schema_version": "PRODUCTION_RECOVERY_SOP_SUMMARY_V1",
        "app_version": APP_VERSION,
        "disaster_recovery_route": "sop.disaster_recovery",
        "backup_restore_route": "sop.backup_restore",
        "minimum_safe_backup_status": "VERIFIED",
        "restore_mode": "MANUAL_ASSISTED_ONLY",
        "must_pass_before_restore": [
            "Pre-backup health check",
            "Post-backup verification",
            "Restore preview dry-run",
            "DB integrity/FK/journal balance",
            "Upload checksum/count/size check",
        ],
    }
