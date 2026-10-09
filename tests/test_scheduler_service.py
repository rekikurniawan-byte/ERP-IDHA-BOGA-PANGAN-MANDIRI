"""Unit & integration tests untuk mesin penjadwal otomatis (Fase 4)."""
from datetime import datetime, time, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError
from werkzeug.security import generate_password_hash

from app.extensions import db
from app.models.master import Branch, User
from app.models.system import AuditLog, ScheduledJobRun
from app.services.scheduler_service import (
    daily_at,
    due_periods,
    every_minutes,
    get_heartbeat_status,
    get_job,
    get_scheduler_warning,
    list_jobs,
    register_job,
    run_due_jobs,
    run_job_now,
    unregister_job,
)
from app.utils.clock import now_wib


def _create_branch(code_prefix="SCHED"):
    suffix = uuid4().hex[:6]
    branch = Branch(code=f"{code_prefix}-{suffix}", name=f"Cabang Penjadwal {suffix}", is_active=True)
    db.session.add(branch)
    db.session.commit()
    return branch


def _create_user(branch, role, username_prefix="u_sch"):
    suffix = uuid4().hex[:6]
    user = User(
        branch_id=branch.id,
        full_name=f"User {role} {suffix}",
        username=f"{username_prefix}_{role.lower()}_{suffix}",
        password_hash=generate_password_hash("password123"),
        role=role,
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _login_user(client, user):
    from flask import g, has_app_context

    # Request di test ini berjalan di dalam app_context yang sama, jadi Flask-Login
    # menyimpan user sebelumnya di g; buang supaya user baru benar-benar dipakai.
    if has_app_context():
        g.pop("_login_user", None)
    with client.session_transaction() as sess:
        sess["_user_id"] = str(user.id)
        sess["_fresh"] = True


def test_due_periods_daily_at_boundaries(app):
    """Tugas harian 18:00: tick jam 17:59 -> tidak jalan; 18:01 -> jalan sekali; tick kedua 18:06 -> tidak jalan lagi."""
    job_key = "test_daily_job"
    register_job(
        key=job_key,
        label="Test Harian 18:00",
        schedule=daily_at("18:00"),
        handler=lambda **kwargs: {"ok": True},
        per_branch=False,
    )
    try:
        job = get_job(job_key)
        # 1. Tick jam 17:59 WIB pada 2026-10-08 (belum jatuh tempo untuk hari ini)
        time_1759 = datetime(2026, 10, 8, 17, 59, 0)
        due_1759 = due_periods(job, now=time_1759, last_success="2026-10-07")
        assert due_1759 == []

        # 2. Tick jam 18:01 WIB pada 2026-10-08 (jatuh tempo, jalan sekali)
        time_1801 = datetime(2026, 10, 8, 18, 1, 0)
        due_1801 = due_periods(job, now=time_1801, last_success="2026-10-07")
        assert due_1801 == ["2026-10-08"]

        # 3. Tick kedua jam 18:06 WIB pada 2026-10-08 (periode 2026-10-08 sudah sukses -> tidak jalan lagi)
        time_1806 = datetime(2026, 10, 8, 18, 6, 0)
        due_1806 = due_periods(job, now=time_1806, last_success="2026-10-08")
        assert due_1806 == []
    finally:
        unregister_job(job_key)


def test_due_periods_catchup(app):
    """Catch-up: tick terakhir 3 hari lalu -> 3 periode dijalankan berurutan; lebih dari 7 hari -> hanya 7 terakhir."""
    job_key = "test_catchup_job"
    register_job(
        key=job_key,
        label="Test Catchup",
        schedule=daily_at("18:00"),
        handler=lambda **kwargs: {"ok": True},
        per_branch=False,
    )
    try:
        job = get_job(job_key)
        now_dt = datetime(2026, 10, 8, 18, 5, 0)

        # Kasus A: Terakhir sukses 3 hari lalu (2026-10-05) -> 3 periode berurutan (06, 07, 08)
        due_3_days = due_periods(job, now=now_dt, last_success="2026-10-05")
        assert due_3_days == ["2026-10-06", "2026-10-07", "2026-10-08"]

        # Kasus B: Terakhir sukses 18 hari lalu (2026-09-20) -> dibatasi hanya 7 periode terakhir
        due_many_days = due_periods(job, now=now_dt, last_success="2026-09-20")
        assert len(due_many_days) == 7
        assert due_many_days == [
            "2026-10-02",
            "2026-10-03",
            "2026-10-04",
            "2026-10-05",
            "2026-10-06",
            "2026-10-07",
            "2026-10-08",
        ]

        # Kasus C: Tugas baru dipasang (belum pernah sukses) -> hanya periode terbaru,
        # supaya pemasangan pertama tidak membuat pesanan/invoice untuk hari yang sudah lewat.
        due_none = due_periods(job, now=now_dt, last_success=None)
        assert due_none == ["2026-10-08"]
    finally:
        unregister_job(job_key)


def test_unique_constraint_prevents_duplicate_runs(app):
    """Unique constraint mencegah dobel walau dua runner berjalan bersamaan (simulasikan insert kedua)."""
    with app.app_context():
        branch = _create_branch("UQ")
        period = f"2026-10-08-{uuid4().hex[:4]}"

        # Insert pertama berhasil
        run1 = ScheduledJobRun(
            job_key="simulated_job",
            branch_id=branch.id,
            period_key=period,
            status="SUCCESS",
            started_at=now_wib(),
        )
        db.session.add(run1)
        db.session.commit()

        # Insert kedua dengan tuple yang sama harus gagal IntegrityError
        run2 = ScheduledJobRun(
            job_key="simulated_job",
            branch_id=branch.id,
            period_key=period,
            status="RUNNING",
            started_at=now_wib(),
        )
        db.session.add(run2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

        # Uji juga untuk job global (branch_id=None)
        global_period = f"2026-10-08-g-{uuid4().hex[:4]}"
        run_g1 = ScheduledJobRun(
            job_key="global_job",
            branch_id=None,
            period_key=global_period,
            status="SUCCESS",
            started_at=now_wib(),
        )
        db.session.add(run_g1)
        db.session.commit()

        run_g2 = ScheduledJobRun(
            job_key="global_job",
            branch_id=None,
            period_key=global_period,
            status="RUNNING",
            started_at=now_wib(),
        )
        db.session.add(run_g2)
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()


def test_handler_failure_rolls_back_and_retries_max_3_times(app):
    """Handler gagal -> status FAILED, pekerjaan handler di-rollback, catatan run tersimpan; tugas lain tetap jalan; dicoba ulang maks 3 kali."""
    with app.app_context():
        branch = _create_branch("FAIL")
        job_fail_key = f"failing_job_{uuid4().hex[:4]}"
        job_ok_key = f"ok_job_{uuid4().hex[:4]}"

        call_count = {"fail": 0, "ok": 0}

        def failing_handler(branch_id=None, period_key=None, now=None):
            call_count["fail"] += 1
            # Simulasi pekerjaan yang harus di-rollback:
            dummy_user = User(
                branch_id=branch.id,
                full_name="Should Not Exist",
                username=f"phantom_{uuid4().hex[:6]}",
                password_hash="fake",
                role="ADMIN",
            )
            db.session.add(dummy_user)
            db.session.flush()
            raise RuntimeError("Database connection timed out during execution")

        def ok_handler(branch_id=None, period_key=None, now=None):
            call_count["ok"] += 1
            return {"status": "ok"}

        fixed_period = "2026-10-08"
        test_now = datetime(2026, 10, 8, 18, 5)

        register_job(
            key=job_fail_key,
            label="Failing Job",
            schedule=daily_at("18:00"),
            handler=failing_handler,
            per_branch=False,
        )
        register_job(
            key=job_ok_key,
            label="OK Job",
            schedule=daily_at("18:00"),
            handler=ok_handler,
            per_branch=False,
        )

        # Seed kemarin agar hanya hari ini (2026-10-08) yang jatuh tempo
        db.session.add(ScheduledJobRun(job_key=job_fail_key, period_key="2026-10-07", status="SUCCESS", started_at=test_now - timedelta(days=1)))
        db.session.add(ScheduledJobRun(job_key=job_ok_key, period_key="2026-10-07", status="SUCCESS", started_at=test_now - timedelta(days=1)))
        db.session.commit()

        try:
            # 1. Tick Pertama: job_fail gagal, job_ok tetap jalan sukses
            only_these = [job_fail_key, job_ok_key]
            runs1 = run_due_jobs(now=test_now, job_keys=only_these)
            assert len(runs1) <= 10, "Run count per tick melebihi batas wajar"
            fail_run = ScheduledJobRun.query.filter_by(job_key=job_fail_key, period_key=fixed_period).first()
            ok_run = ScheduledJobRun.query.filter_by(job_key=job_ok_key, period_key=fixed_period).first()

            assert fail_run is not None
            assert fail_run.status == "FAILED"
            assert "RuntimeError" in (fail_run.message or "")
            assert fail_run.attempts == 1

            assert ok_run is not None
            assert ok_run.status == "SUCCESS"

            # Pastikan phantom_user di-rollback
            phantom = User.query.filter_by(full_name="Should Not Exist").first()
            assert phantom is None

            # 2. Tick Kedua: job_fail dicoba ulang (attempt 2)
            runs2 = run_due_jobs(now=test_now, job_keys=only_these)
            assert len(runs2) <= 10, "Run count per tick melebihi batas wajar"
            fail_run = ScheduledJobRun.query.filter_by(job_key=job_fail_key, period_key=fixed_period).first()
            assert fail_run.attempts == 2
            assert fail_run.status == "FAILED"

            # 3. Tick Ketiga: job_fail dicoba ulang (attempt 3)
            runs3 = run_due_jobs(now=test_now, job_keys=only_these)
            assert len(runs3) <= 10, "Run count per tick melebihi batas wajar"
            fail_run = ScheduledJobRun.query.filter_by(job_key=job_fail_key, period_key=fixed_period).first()
            assert fail_run.attempts == 3
            assert fail_run.status == "FAILED"

            # 4. Tick Keempat: percobaan sudah mencapai 3 -> LEWATI (tidak dicoba lagi otomatis)
            before_calls = call_count["fail"]
            runs4 = run_due_jobs(now=test_now, job_keys=only_these)
            assert len(runs4) <= 10, "Run count per tick melebihi batas wajar"
            assert call_count["fail"] == before_calls  # Tidak dipanggil lagi
            fail_run = ScheduledJobRun.query.filter_by(job_key=job_fail_key, period_key=fixed_period).first()
            assert fail_run.attempts == 3
            assert fail_run.status == "FAILED"

        finally:
            unregister_job(job_fail_key)
            unregister_job(job_ok_key)


def test_per_branch_execution(app):
    """`per_branch`: tiap cabang aktif dapat satu run."""
    with app.app_context():
        branch1 = _create_branch("PB1")
        branch2 = _create_branch("PB2")

        job_key = f"job_per_branch_{uuid4().hex[:4]}"
        executed_branches = []

        def per_branch_handler(branch_id=None, period_key=None, now=None):
            executed_branches.append(branch_id)
            return {"branch_id": branch_id}

        register_job(
            key=job_key,
            label="Per Branch Job",
            schedule=daily_at("18:00"),
            handler=per_branch_handler,
            per_branch=True,
        )

        # Seed kemarin agar hanya hari ini (2026-10-08) yang jatuh tempo
        db.session.add(ScheduledJobRun(job_key=job_key, branch_id=branch1.id, period_key="2026-10-07", status="SUCCESS", started_at=datetime(2026, 10, 7, 18, 5)))
        db.session.add(ScheduledJobRun(job_key=job_key, branch_id=branch2.id, period_key="2026-10-07", status="SUCCESS", started_at=datetime(2026, 10, 7, 18, 5)))
        db.session.commit()

        try:
            test_now = datetime(2026, 10, 8, 18, 5)
            # Database test berisi ribuan cabang sisa test lain; batasi ke cabang test ini.
            runs = run_due_jobs(now=test_now, job_keys=[job_key], branch_ids=[branch1.id, branch2.id])
            assert len(runs) == 2

            # Periksa apakah kedua cabang aktif dijalankan
            runs_branch1 = ScheduledJobRun.query.filter_by(job_key=job_key, branch_id=branch1.id, period_key="2026-10-08").first()
            runs_branch2 = ScheduledJobRun.query.filter_by(job_key=job_key, branch_id=branch2.id, period_key="2026-10-08").first()

            assert runs_branch1 is not None
            assert runs_branch1.status == "SUCCESS"
            assert runs_branch2 is not None
            assert runs_branch2.status == "SUCCESS"
            assert branch1.id in executed_branches
            assert branch2.id in executed_branches
        finally:
            unregister_job(job_key)


def test_run_job_now_enforces_idempotency_and_force_audit(app):
    """`run_job_now` menolak periode yang sudah SUCCESS kecuali OWNER memaksa dengan alasan (tercatat audit)."""
    with app.app_context():
        branch = _create_branch("FORCE")
        owner_user = _create_user(branch, "OWNER")
        admin_user = _create_user(branch, "ADMIN")

        job_key = f"manual_job_{uuid4().hex[:4]}"
        register_job(
            key=job_key,
            label="Manual Test Job",
            schedule=daily_at("18:00"),
            handler=lambda **kwargs: {"ok": True},
            per_branch=False,
        )

        try:
            period = "2026-10-08"

            # 1. Eksekusi pertama berhasil
            run1 = run_job_now(key=job_key, period_key=period, user=owner_user)
            assert run1.status == "SUCCESS"

            # 2. Panggilan kedua tanpa force ditolak
            with pytest.raises(ValueError, match="sudah berhasil"):
                run_job_now(key=job_key, period_key=period, user=owner_user, force=False)

            # 3. ADMIN mencoba memaksa -> ditolak PermissionError
            with pytest.raises(PermissionError, match="Hanya OWNER"):
                run_job_now(key=job_key, period_key=period, user=admin_user, force=True, force_reason="Alasan admin")

            # 4. OWNER mencoba memaksa tanpa alasan -> ditolak ValueError
            with pytest.raises(ValueError, match="Alasan wajib diisi"):
                run_job_now(key=job_key, period_key=period, user=owner_user, force=True, force_reason="")

            # 5. OWNER memaksa dengan alasan -> berhasil dan tercatat di audit log
            reason = "Koreksi data pesanan setelah komplain client"
            run_force = run_job_now(key=job_key, period_key=period, user=owner_user, force=True, force_reason=reason)
            assert run_force.status == "SUCCESS"

            # Verifikasi audit log tercatat
            audit = AuditLog.query.filter_by(module="SCHEDULER", event_type="JOB_FORCE_RUN").order_by(AuditLog.id.desc()).first()
            assert audit is not None
            assert reason in (audit.description or "")
            assert audit.user_id == owner_user.id
        finally:
            unregister_job(job_key)


def test_scheduled_jobs_page_and_heartbeat_alert(client, app):
    """Halaman Tugas Otomatis: OWNER/ADMIN bisa buka, DAPUR/PENGANTAR/portal ditolak; peringatan heartbeat muncul bila > 15 menit."""
    with app.app_context():
        branch = _create_branch("UI")
        owner = _create_user(branch, "OWNER")
        admin = _create_user(branch, "ADMIN")
        dapur = _create_user(branch, "DAPUR")
        pengantar = _create_user(branch, "PENGANTAR")

        # 1. OWNER bisa buka halaman (200 OK)
        _login_user(client, owner)
        res_owner = client.get("/settings/jobs")
        assert res_owner.status_code == 200
        assert "Tugas Otomatis" in res_owner.get_data(as_text=True)

        # 2. ADMIN bisa buka halaman (200 OK)
        _login_user(client, admin)
        res_admin = client.get("/settings/jobs")
        assert res_admin.status_code == 200

        # 3. DAPUR ditolak. role_required menolak dengan redirect ke dashboard + pesan.
        _login_user(client, dapur)
        res_dapur = client.get("/settings/jobs")
        assert res_dapur.status_code == 302
        assert "/settings/jobs" not in res_dapur.headers["Location"]

        # 4. PENGANTAR ditolak
        _login_user(client, pengantar)
        res_pengantar = client.get("/settings/jobs")
        assert res_pengantar.status_code == 302
        assert "/settings/jobs" not in res_pengantar.headers["Location"]

        # 5. Verifikasi peringatan heartbeat bila > 15 menit
        # Hapus semua run heartbeat sukses atau ubah started_at menjadi 30 menit yang lalu
        ScheduledJobRun.query.filter_by(job_key="heartbeat").delete()
        stale_heartbeat = ScheduledJobRun(
            job_key="heartbeat",
            branch_id=None,
            period_key="2026-10-08T06:00",
            status="SUCCESS",
            started_at=now_wib() - timedelta(minutes=30),
        )
        db.session.add(stale_heartbeat)
        db.session.commit()

        _login_user(client, owner)
        res_warning = client.get("/settings/jobs")
        html = res_warning.get_data(as_text=True)
        assert "Penjadwal tidak berjalan — tugas otomatis (pesanan 18.00, invoice 06.00) tidak akan jalan." in html

        # Peringatan yang sama muncul di dashboard owner
        res_dash = client.get("/dashboard/owner")
        dash_html = res_dash.get_data(as_text=True)
        assert "Penjadwal tidak berjalan — tugas otomatis (pesanan 18.00, invoice 06.00) tidak akan jalan." in dash_html


def test_cli_flask_jobs_tick(app):
    """CLI `flask jobs tick` jalan lewat `app.test_cli_runner()`."""
    with app.app_context():
        runner = app.test_cli_runner()

        # 1. Jalankan tick normal -> exit code 0.
        # Tugas per cabang (mis. pesanan otomatis) dimatikan sementara: database test
        # berisi ribuan cabang sisa test lain dan handler aslinya menyentuh data.
        paused = [job for job in list_jobs() if job.get("per_branch", True) and job.get("enabled", True)]
        for job in paused:
            job["enabled"] = False
        try:
            result = runner.invoke(args=["jobs", "tick"])
        finally:
            for job in paused:
                job["enabled"] = True
        assert result.exit_code == 0
        assert "Tick selesai" in result.output

        # 2. Uji `flask jobs list`
        result_list = runner.invoke(args=["jobs", "list"])
        assert result_list.exit_code == 0
        assert "heartbeat" in result_list.output

        # 3. Jika ada job yang FAILED, tick harus keluar dengan exit code != 0
        job_cli_fail = f"cli_fail_{uuid4().hex[:4]}"

        def error_handler(**kwargs):
            raise ValueError("Kegagalan simulasi CLI")

        register_job(
            key=job_cli_fail,
            label="CLI Failure Test",
            schedule=daily_at("18:00"),
            handler=error_handler,
            per_branch=False,
        )

        try:
            # Panggil dengan period spesifik agar due saat ini
            test_run = run_job_now(key=job_cli_fail, period_key="2026-10-08")
            assert test_run.status == "FAILED"

            # Jalankan run_due_jobs atau jobs run
            result_run = runner.invoke(args=["jobs", "run", job_cli_fail, "--period", "2026-10-09"])
            assert result_run.exit_code != 0
        finally:
            unregister_job(job_cli_fail)


def test_due_periods_interval_no_catchup(app):
    """Tugas interval (every_minutes) TIDAK boleh catch-up: hanya mengembalikan bucket sekarang bila belum sukses ([current_key]) atau []."""
    job_key = f"interval_test_{uuid4().hex[:4]}"
    register_job(
        key=job_key,
        label="Interval Test",
        schedule=every_minutes(5),
        handler=lambda **kwargs: {"ok": True},
        per_branch=False,
    )
    try:
        job = get_job(job_key)
        now_dt = datetime(2026, 10, 8, 14, 17)
        # Bucket untuk 14:17 pada interval 5 menit adalah 14:15
        expected_bucket = "2026-10-08T14:15"

        # 1. last_success is None -> hanya [expected_bucket]
        assert due_periods(job, now=now_dt, last_success=None) == [expected_bucket]

        # 2. last_success adalah 2 jam yang lalu -> TIDAK catch-up banyak periode, hanya [expected_bucket]
        two_hours_ago = "2026-10-08T12:00"
        assert due_periods(job, now=now_dt, last_success=two_hours_ago) == [expected_bucket]

        # 3. last_success sudah sama dengan expected_bucket -> []
        assert due_periods(job, now=now_dt, last_success=expected_bucket) == []
    finally:
        unregister_job(job_key)


def test_stale_running_run_is_retried():
    """RUNNING > 60 menit = proses mati di tengah jalan -> boleh diulang; yang baru tidak."""
    from app.services.scheduler_service import _is_stale_run

    now_dt = datetime(2026, 10, 8, 6, 30)
    fresh = ScheduledJobRun(status="RUNNING", started_at=now_dt - timedelta(minutes=10))
    stale = ScheduledJobRun(status="RUNNING", started_at=now_dt - timedelta(minutes=90))
    assert _is_stale_run(fresh, now_dt) is False
    assert _is_stale_run(stale, now_dt) is True
