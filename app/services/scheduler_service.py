"""Mesin penjadwal tugas otomatis (Scheduler Service) PT Idha Boga Pangan Mandiri.

Menjalankan tugas terjadwal secara idempoten via `flask jobs tick` tanpa thread di Flask.
Dilengkapi PostgreSQL advisory lock, batasan catch-up 7 hari, dan isolasi kegagalan per tugas/cabang.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
import hashlib
import json
import logging
from typing import Any, Callable

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.master import Branch
from app.models.system import ScheduledJobRun
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.utils.clock import format_wib, now_wib, to_wib

logger = logging.getLogger(__name__)

# Registry in-memory
_JOB_REGISTRY: dict[str, dict[str, Any]] = {}


def _normalize_now(now: datetime | None = None) -> datetime:
    """Normalisasi waktu ke WIB naif: None -> now_wib(); ber-tzinfo -> to_wib(); naif -> apa adanya."""
    if now is None:
        return now_wib()
    if now.tzinfo is not None:
        return to_wib(now)
    return now


def daily_at(time_str: str) -> dict[str, Any]:
    """Helper jadwal harian pada jam WIB tertentu, mis. '18:00'."""
    try:
        parts = time_str.split(":")
        hour, minute = int(parts[0]), int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            raise ValueError
    except Exception as exc:
        raise ValueError(f"Format jam tidak valid: {time_str!r}. Gunakan format 'HH:MM', mis. '18:00'") from exc
    return {"type": "daily", "time": f"{hour:02d}:{minute:02d}"}


def every_minutes(minutes: int) -> dict[str, Any]:
    """Helper jadwal berkala setiap N menit."""
    if not isinstance(minutes, int) or minutes <= 0:
        raise ValueError("Interval menit harus berupa integer positif (> 0).")
    return {"type": "interval", "minutes": minutes}


def register_job(
    key: str,
    label: str,
    schedule: dict[str, Any],
    handler: Callable[..., Any],
    per_branch: bool = True,
    enabled: bool = True,
    description: str = "",
) -> None:
    """Daftarkan tugas ke registry penjadwal."""
    key = str(key).strip()
    if not key:
        raise ValueError("Job key tidak boleh kosong.")
    if schedule.get("type") not in ("daily", "interval"):
        raise ValueError(f"Tipe jadwal tidak didukung: {schedule.get('type')}")
    if not callable(handler):
        raise TypeError("Handler harus callable.")

    _JOB_REGISTRY[key] = {
        "key": key,
        "label": label,
        "schedule": schedule,
        "handler": handler,
        "per_branch": per_branch,
        "enabled": enabled,
        "description": description,
    }


def register_default_jobs() -> None:
    """Daftarkan tugas-tugas bawaan sistem (pesanan otomatis jam 18:00 WIB, dll)."""
    if "auto_daily_orders" not in _JOB_REGISTRY:
        from app.services.auto_order_service import run_auto_daily_orders

        register_job(
            key="auto_daily_orders",
            label="Pesanan Harian Otomatis",
            schedule=daily_at("18:00"),
            handler=run_auto_daily_orders,
            per_branch=True,
            enabled=True,
            description="Membuat pesanan harian untuk hari esok pada jam 18:00 WIB untuk client/sub client kontrak.",
        )
    if "auto_period_invoices" not in _JOB_REGISTRY:
        from app.services.auto_invoice_service import (
            run_auto_invoice_preview,
            run_auto_period_invoices,
            run_invoice_payment_reminders,
        )

        register_job(
            key="auto_period_invoices",
            label="Invoice Otomatis (Hari Potong)",
            schedule=daily_at("06:00"),
            handler=run_auto_period_invoices,
            per_branch=True,
            enabled=True,
            description="Menerbitkan invoice per sub client pada hari potong siklus kontrak, hanya dari pengiriman yang sudah diterima.",
        )
        register_job(
            key="auto_invoice_preview",
            label="Pratinjau Invoice Besok",
            schedule=daily_at("07:00"),
            handler=run_auto_invoice_preview,
            per_branch=True,
            enabled=True,
            description="Memberi tahu admin & owner invoice yang akan terbit besok jam 06.00, beserta yang bermasalah.",
        )
        register_job(
            key="invoice_payment_reminders",
            label="Pengingat Bayar Invoice",
            schedule=daily_at("08:00"),
            handler=run_invoice_payment_reminders,
            per_branch=True,
            enabled=True,
            description="Mengingatkan pihak yang ditagih pada H-3, H, dan H+7 jatuh tempo.",
        )
    if "credit_daily_sweep" not in _JOB_REGISTRY:
        from app.services.credit_account_service import run_credit_sweep_job

        register_job(
            key="credit_daily_sweep",
            label="Pemeriksaan Kredit Harian",
            schedule=daily_at("07:30"),
            handler=run_credit_sweep_job,
            per_branch=True,
            enabled=True,
            description="Menaikkan status kredit yang menunggak (Pantau/Tahan/Blokir), memberi tahu pelanggan, dan mengusulkan ta'zir ke Owner.",
        )


def unregister_job(key: str) -> None:
    """Hapus pendaftaran tugas (berguna untuk isolasi testing)."""
    _JOB_REGISTRY.pop(key, None)


def get_job(key: str) -> dict[str, Any] | None:
    """Ambil definisi tugas berdasarkan key."""
    register_default_jobs()
    return _JOB_REGISTRY.get(key)


def list_jobs() -> list[dict[str, Any]]:
    """Daftar semua tugas terdaftar."""
    register_default_jobs()
    return list(_JOB_REGISTRY.values())


def _advisory_lock_id(job_key: str, branch_id: int | None = None) -> int:
    """Konversi (job_key, branch_id) menjadi 64-bit signed integer untuk PostgreSQL advisory lock."""
    key_str = f"erp_job:{job_key}:{branch_id or 0}"
    digest = hashlib.sha256(key_str.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=True)


def _try_advisory_lock(job_key: str, branch_id: int | None = None) -> bool:
    """Coba ambil PostgreSQL advisory lock. Kembalikan True jika berhasil atau jika bukan PostgreSQL."""
    try:
        bind = db.session.get_bind()
        if bind.dialect.name != "postgresql":
            return True
        lock_id = _advisory_lock_id(job_key, branch_id)
        result = db.session.execute(
            text("SELECT pg_try_advisory_lock(:lock_id)"),
            {"lock_id": lock_id},
        ).scalar()
        return bool(result)
    except Exception:
        logger.exception("Gagal mencoba advisory lock untuk %s (cabang: %s)", job_key, branch_id)
        return True


def _release_advisory_lock(job_key: str, branch_id: int | None = None) -> None:
    """Lepas PostgreSQL advisory lock."""
    try:
        bind = db.session.get_bind()
        if bind.dialect.name != "postgresql":
            return
        lock_id = _advisory_lock_id(job_key, branch_id)
        try:
            db.session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": lock_id},
            )
        except Exception:
            db.session.rollback()
            db.session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": lock_id},
            )
    except Exception:
        logger.exception("Gagal melepas advisory lock untuk %s (cabang: %s)", job_key, branch_id)


def due_periods(job: dict[str, Any] | str, now: datetime | None = None, last_success: str | date | datetime | None = None) -> list[str]:
    """Hitung daftar periode yang jatuh tempo, maks 7 hari ke belakang (urut lama -> baru)."""
    if isinstance(job, str):
        job_def = get_job(job)
        if not job_def:
            raise ValueError(f"Job dengan key {job!r} tidak terdaftar.")
    else:
        job_def = job

    now_dt = _normalize_now(now)
    schedule = job_def["schedule"]
    sched_type = schedule.get("type")

    if sched_type == "daily":
        hour, minute = map(int, schedule["time"].split(":"))
        target_time = time(hour, minute)

        # Hari ini jatuh tempo jika sekarang >= target_time
        if now_dt.time() >= target_time:
            latest_due_date = now_dt.date()
        else:
            latest_due_date = now_dt.date() - timedelta(days=1)

        # Maksimal 7 hari ke belakang
        earliest_allowed_date = latest_due_date - timedelta(days=6)

        # Cek last_success
        last_success_date = None
        if last_success is not None:
            if isinstance(last_success, str):
                try:
                    last_success_date = datetime.strptime(last_success[:10], "%Y-%m-%d").date()
                except (ValueError, TypeError):
                    last_success_date = None
            elif isinstance(last_success, datetime):
                last_success_date = last_success.date()
            elif isinstance(last_success, date):
                last_success_date = last_success

        if last_success_date is not None:
            if last_success_date >= latest_due_date:
                return []
            start_date = max(earliest_allowed_date, last_success_date + timedelta(days=1))
        else:
            # Belum pernah sukses (tugas baru dipasang): jalankan periode terbaru saja.
            # Catch-up hanya untuk mengejar hari yang terlewat SETELAH tugas pernah
            # berjalan -- kalau tidak, pemasangan pertama akan membuat pesanan /
            # invoice untuk 7 hari yang sudah lewat.
            start_date = latest_due_date

        periods: list[str] = []
        curr = start_date
        while curr <= latest_due_date:
            periods.append(curr.isoformat())
            curr += timedelta(days=1)
        return periods

    if sched_type == "interval":
        minutes = schedule.get("minutes", 5)
        bucket_min = (now_dt.minute // minutes) * minutes
        current_bucket = now_dt.replace(minute=bucket_min, second=0, microsecond=0)
        current_key = current_bucket.strftime("%Y-%m-%dT%H:%M")

        if last_success is None:
            return [current_key]

        last_success_str = None
        if isinstance(last_success, str):
            last_success_str = last_success
        elif isinstance(last_success, datetime):
            last_success_str = last_success.strftime("%Y-%m-%dT%H:%M")

        if last_success_str and last_success_str >= current_key:
            return []

        return [current_key]

    return []


def _record_run_start(job_key: str, branch_id: int | None, period_key: str, started_at: datetime) -> ScheduledJobRun:
    """Inisialisasi atau update record run dengan status RUNNING dalam transaksi atomik."""
    existing = ScheduledJobRun.query.filter_by(
        job_key=job_key,
        branch_id=branch_id,
        period_key=period_key,
    ).first()

    if existing is None:
        run_record = ScheduledJobRun(
            job_key=job_key,
            branch_id=branch_id,
            period_key=period_key,
            status="RUNNING",
            started_at=started_at,
            attempts=1,
            message="Sedang berjalan...",
        )
        with atomic_business_action(module="SCHEDULER", action="INIT_JOB_RUN", branch_id=branch_id, audit_success=False):
            db.session.add(run_record)
        return run_record

    existing.status = "RUNNING"
    existing.started_at = started_at
    existing.finished_at = None
    existing.attempts += 1
    existing.message = f"Mencoba ulang (percobaan ke-{existing.attempts})..."
    with atomic_business_action(module="SCHEDULER", action="RETRY_JOB_RUN", branch_id=branch_id, audit_success=False):
        db.session.add(existing)
    return existing


def _record_run_success(run_record: ScheduledJobRun, finished_at: datetime, result_payload: Any) -> None:
    """Tandai run record sebagai SUCCESS dan simpan payload result."""
    result_str = None
    if result_payload is not None:
        if isinstance(result_payload, (dict, list)):
            result_str = json.dumps(result_payload, ensure_ascii=False, default=str)
        else:
            result_str = json.dumps({"result": str(result_payload)}, ensure_ascii=False)

    run_record.status = "SUCCESS"
    run_record.finished_at = finished_at
    run_record.message = "Selesai dengan sukses"
    run_record.result_json = result_str
    with atomic_business_action(module="SCHEDULER", action="FINISH_JOB_SUCCESS", branch_id=run_record.branch_id, audit_success=False):
        db.session.add(run_record)


def _record_run_failure(run_record: ScheduledJobRun, finished_at: datetime, error_message: str) -> None:
    """Tandai run record sebagai FAILED dan simpan pesan kesalahan."""
    run_record.status = "FAILED"
    run_record.finished_at = finished_at
    run_record.message = error_message
    with atomic_business_action(module="SCHEDULER", action="FINISH_JOB_FAILURE", branch_id=run_record.branch_id, audit_success=True):
        db.session.add(run_record)


def _execute_single_run(
    job: dict[str, Any],
    branch_id: int | None,
    period_key: str,
    now: datetime | None = None,
) -> ScheduledJobRun:
    """Jalankan satu tugas untuk satu periode dalam isolasi transaksi."""
    now_dt = _normalize_now(now)
    job_key = job["key"]

    try:
        run_record = _record_run_start(job_key, branch_id, period_key, now_dt)
    except IntegrityError:
        db.session.rollback()
        logger.warning("Duplicate insert dicegah constraint untuk %s cabang %s periode %s", job_key, branch_id, period_key)
        existing = ScheduledJobRun.query.filter_by(
            job_key=job_key,
            branch_id=branch_id,
            period_key=period_key,
        ).first()
        if existing:
            return existing
        raise

    # Eksekusi handler
    handler = job["handler"]
    try:
        result = handler(branch_id=branch_id, period_key=period_key, now=now_dt)
        finished_at = now_wib()
        _record_run_success(run_record, finished_at, result)
        logger.info("Tugas %s cabang %s periode %s SUKSES", job_key, branch_id, period_key)
    except Exception as exc:
        db.session.rollback()
        finished_at = now_wib()
        error_msg = f"{type(exc).__name__}: {str(exc)}"
        logger.exception("Tugas %s cabang %s periode %s GAGAL", job_key, branch_id, period_key)
        _record_run_failure(run_record, finished_at, error_msg)

    return run_record


STALE_RUNNING_MINUTES = 60


def _is_stale_run(run_record: ScheduledJobRun, now_dt: datetime) -> bool:
    """RUNNING lebih dari 60 menit dianggap prosesnya mati di tengah jalan."""
    started_at = getattr(run_record, "started_at", None)
    if started_at is None:
        return True
    return (now_dt - started_at) > timedelta(minutes=STALE_RUNNING_MINUTES)


def run_due_jobs(
    now: datetime | None = None,
    *,
    job_keys: list[str] | None = None,
    branch_ids: list[int] | None = None,
) -> list[ScheduledJobRun]:
    """Jalankan semua tugas yang jatuh tempo saat ini.

    `job_keys` / `branch_ids` membatasi tugas & cabang yang diproses (dipakai
    test dan perintah manual); tanpa itu semua tugas aktif x semua cabang aktif.
    """
    now_dt = _normalize_now(now)
    executed_runs: list[ScheduledJobRun] = []
    branch_targets: list[int] | None = None

    for job in list_jobs():
        if not job.get("enabled", True):
            continue

        job_key = job["key"]
        if job_keys is not None and job_key not in job_keys:
            continue
        if job.get("per_branch", True):
            if branch_targets is None:
                if branch_ids is not None:
                    branch_targets = list(branch_ids)
                else:
                    branch_targets = [
                        row.id for row in Branch.query.filter_by(is_active=True).order_by(Branch.id).all()
                    ]
            targets = branch_targets
        else:
            targets = [None]

        for branch_id in targets:
            if not _try_advisory_lock(job_key, branch_id):
                logger.info("Lock dipegang proses lain; tugas %s cabang %s dilewati", job_key, branch_id)
                continue

            try:
                last_success_run = (
                    ScheduledJobRun.query.filter_by(
                        job_key=job_key,
                        branch_id=branch_id,
                        status="SUCCESS",
                    )
                    .order_by(ScheduledJobRun.period_key.desc())
                    .first()
                )
                last_success = last_success_run.period_key if last_success_run else None
                due = due_periods(job, now=now_dt, last_success=last_success)[:7]

                for period_key in due:
                    existing = ScheduledJobRun.query.filter_by(
                        job_key=job_key,
                        branch_id=branch_id,
                        period_key=period_key,
                    ).first()

                    if existing is not None:
                        if existing.status == "SUCCESS":
                            continue
                        if existing.attempts >= 3:
                            logger.info(
                                "Tugas %s cabang %s periode %s sudah 3 kali percobaan; lewati.",
                                job_key,
                                branch_id,
                                period_key,
                            )
                            continue
                        if existing.status == "SKIPPED":
                            continue
                        if existing.status == "RUNNING" and not _is_stale_run(existing, now_dt):
                            continue
                        # RUNNING yang sudah basi = proses mati di tengah jalan
                        # (laptop/server mati). Pekerjaannya sudah di-rollback
                        # database, jadi aman diulang sebagai percobaan baru.

                    run = _execute_single_run(job, branch_id, period_key, now=now_dt)
                    executed_runs.append(run)

            finally:
                _release_advisory_lock(job_key, branch_id)

    return executed_runs


def run_job_now(
    key: str,
    branch_id: int | None = None,
    period_key: str | None = None,
    user: Any | None = None,
    force: bool = False,
    force_reason: str | None = None,
    now: datetime | None = None,
) -> ScheduledJobRun:
    """Jalankan satu tugas secara langsung (manual oleh OWNER/ADMIN)."""
    job = get_job(key)
    if not job:
        raise ValueError(f"Tugas dengan kunci {key!r} tidak terdaftar.")

    now_dt = _normalize_now(now)

    if period_key is None:
        sched = job["schedule"]
        if sched["type"] == "daily":
            period_key = now_dt.date().isoformat()
        else:
            minutes = sched.get("minutes", 5)
            bucket_min = (now_dt.minute // minutes) * minutes
            current_bucket = now_dt.replace(minute=bucket_min, second=0, microsecond=0)
            period_key = current_bucket.strftime("%Y-%m-%dT%H:%M")

    # Periode tidak boleh di masa depan: tugas harian (mis. pesanan otomatis)
    # akan membuat data untuk tanggal yang belum waktunya.
    if job["schedule"]["type"] == "daily":
        try:
            period_date = datetime.strptime(period_key[:10], "%Y-%m-%d").date()
        except (TypeError, ValueError) as exc:
            raise ValueError("Format periode harus YYYY-MM-DD.") from exc
        if period_date > now_dt.date():
            raise ValueError(f"Periode {period_key} belum tiba; tugas harian tidak boleh dijalankan untuk tanggal mendatang.")

    existing = ScheduledJobRun.query.filter_by(
        job_key=key,
        branch_id=branch_id,
        period_key=period_key,
    ).first()

    if existing and existing.status == "RUNNING" and not _is_stale_run(existing, now_dt):
        raise ValueError(f"Tugas '{job['label']}' periode {period_key} sedang berjalan. Tunggu sampai selesai.")

    if existing and existing.status == "SUCCESS":
        if not force:
            raise ValueError(
                f"Periode {period_key} untuk tugas '{job['label']}' sudah berhasil (SUCCESS). "
                "Hanya dapat dijalankan ulang jika dipaksa oleh OWNER dengan mencantumkan alasan."
            )
        user_role = getattr(user, "role", None) if user else None
        if user_role != "OWNER":
            raise PermissionError("Hanya OWNER yang berhak memaksa menjalankan ulang tugas yang sudah SUCCESS.")
        clean_reason = (force_reason or "").strip()
        if not clean_reason:
            raise ValueError("Alasan wajib diisi saat memaksa menjalankan ulang tugas yang sudah SUCCESS.")

        record_audit_log(
            module="SCHEDULER",
            event_type="JOB_FORCE_RUN",
            action="UPDATE",
            description=f"Memaksa menjalankan ulang {key} ({period_key}) cabang {branch_id}: {clean_reason}",
            table_name="scheduled_job_runs",
            record_id=existing.id,
            user_id=getattr(user, "id", None),
            branch_id=branch_id,
            metadata={"job_key": key, "period_key": period_key, "force_reason": clean_reason},
            commit=False,
        )

    return _execute_single_run(job, branch_id, period_key, now=now_dt)


# --- Heartbeat Job & Status Helper ---

def _heartbeat_handler(branch_id: int | None = None, period_key: str | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Handler heartbeat untuk mencatat waktu tick terakhir penjadwal."""
    now_dt = _normalize_now(now)
    return {
        "status": "ALIVE",
        "period": period_key,
        "recorded_at": now_dt.isoformat(),
        "message": f"Detak penjadwal aktif pada {now_dt.strftime('%d/%m/%Y %H.%M')}",
    }


register_job(
    key="heartbeat",
    label="Detak Penjadwal (Heartbeat)",
    schedule=every_minutes(5),
    handler=_heartbeat_handler,
    per_branch=False,
    enabled=True,
    description="Mencatat detak sistem penjadwal tiap 5 menit untuk memantau keaktifan otomatisasi.",
)


def get_heartbeat_status(now: datetime | None = None) -> dict[str, Any]:
    """Cek status kesehatan heartbeat penjadwal. Dianggap mati bila > 15 menit."""
    now_dt = _normalize_now(now)
    last_run = (
        ScheduledJobRun.query.filter_by(job_key="heartbeat", status="SUCCESS")
        .order_by(ScheduledJobRun.started_at.desc())
        .first()
    )

    if not last_run:
        return {
            "last_run": None,
            "is_alive": False,
            "diff_minutes": None,
            "warning": "Penjadwal tidak berjalan — tugas otomatis (pesanan 18.00, invoice 06.00) tidak akan jalan.",
        }

    last_dt = last_run.started_at
    diff_minutes = (now_dt - last_dt).total_seconds() / 60.0
    is_alive = diff_minutes <= 15.0

    return {
        "last_run": last_run,
        "is_alive": is_alive,
        "diff_minutes": round(diff_minutes, 1),
        "warning": None if is_alive else "Penjadwal tidak berjalan — tugas otomatis (pesanan 18.00, invoice 06.00) tidak akan jalan.",
    }


def get_scheduler_warning(now: datetime | None = None) -> str | None:
    """Ambil pesan peringatan jika penjadwal tidak aktif."""
    return get_heartbeat_status(now).get("warning")


def get_scheduled_jobs_status(now: datetime | None = None) -> list[dict[str, Any]]:
    """Daftar status tugas terjadwal untuk halaman antarmuka Pengaturan."""
    now_dt = _normalize_now(now)
    result = []

    for job in list_jobs():
        key = job["key"]
        sched = job["schedule"]

        last_success = (
            ScheduledJobRun.query.filter_by(job_key=key, status="SUCCESS")
            .order_by(ScheduledJobRun.started_at.desc())
            .first()
        )
        last_run = (
            ScheduledJobRun.query.filter_by(job_key=key)
            .order_by(ScheduledJobRun.started_at.desc())
            .first()
        )

        # Hitung estimasi jadwal berikutnya
        next_run_str = "-"
        if sched["type"] == "daily":
            hour, minute = map(int, sched["time"].split(":"))
            target_time = time(hour, minute)
            if now_dt.time() < target_time:
                next_dt = datetime.combine(now_dt.date(), target_time)
            else:
                next_dt = datetime.combine(now_dt.date() + timedelta(days=1), target_time)
            # next_dt sudah jam WIB; format_wib() akan menambah 7 jam lagi.
            next_run_str = next_dt.strftime("%d/%m/%Y %H.%M")
            sched_label = f"Harian {sched['time']} WIB"
        else:
            sched_label = f"Setiap {sched.get('minutes', 5)} menit"
            minutes = sched.get("minutes", 5)
            bucket_min = (now_dt.minute // minutes) * minutes
            next_dt = now_dt.replace(minute=bucket_min, second=0, microsecond=0) + timedelta(minutes=minutes)
            next_run_str = next_dt.strftime("%d/%m/%Y %H.%M")

        result.append({
            "key": key,
            "label": job["label"],
            "description": job.get("description", ""),
            "schedule_label": sched_label,
            "per_branch": job.get("per_branch", True),
            "enabled": job.get("enabled", True),
            "last_success": last_success,
            "last_run": last_run,
            "next_run_str": next_run_str,
        })

    return result


def list_job_runs(
    job_key: str | None = None,
    status: str | None = None,
    branch_id: int | None = None,
    limit: int = 50,
) -> list[ScheduledJobRun]:
    """Ambil riwayat eksekusi tugas terjadwal."""
    query = ScheduledJobRun.query

    if job_key:
        query = query.filter_by(job_key=job_key)
    if status:
        query = query.filter_by(status=status)
    if branch_id is not None:
        query = query.filter_by(branch_id=branch_id)

    return query.order_by(ScheduledJobRun.started_at.desc(), ScheduledJobRun.id.desc()).limit(limit).all()
