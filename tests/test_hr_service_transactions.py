from datetime import date

from app.services import hr_service


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        self.flush_count += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 101

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


class _FakeSkillQuery:
    def __init__(self):
        self.deleted_for_employee_id = None

    def filter_by(self, **kwargs):
        self.deleted_for_employee_id = kwargs.get("employee_id")
        return self

    def delete(self):
        return 1


class _FakeEmployeeSkill:
    query = _FakeSkillQuery()

    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_create_employee_record_adds_employee_skills_salary_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(hr_service, "db", _FakeDb(session))

    employee = hr_service.create_employee_record(
        branch_id=2,
        full_name="Karyawan Satu",
        phone="08111",
        join_date=date(2026, 1, 2),
        salary_amount="3500000",
        skills_raw="Masak, Packing",
    )

    assert employee in session.added
    assert employee.id == 101
    assert employee.branch_id == 2
    assert employee.full_name == "Karyawan Satu"
    assert employee.status == "ACTIVE"
    assert session.flush_count == 1
    assert len(session.added) == 4
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_employee_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(hr_service, "db", _FakeDb(session))

    try:
        hr_service.create_employee_record(
            branch_id=2,
            full_name="Karyawan Satu",
            phone="08111",
            join_date=None,
            salary_amount="0",
            skills_raw="",
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("create_employee_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_update_employee_record_replaces_skills_and_adds_salary(monkeypatch):
    session = _FakeSession()
    fake_skill = _FakeEmployeeSkill
    fake_skill.query = _FakeSkillQuery()
    monkeypatch.setattr(hr_service, "db", _FakeDb(session))
    monkeypatch.setattr(hr_service, "EmployeeSkill", fake_skill)
    employee = hr_service.Employee(id=12, full_name="Lama", status="ACTIVE")

    updated = hr_service.update_employee_record(
        employee,
        full_name="Baru",
        phone="08222",
        join_date=date(2026, 2, 3),
        status="INACTIVE",
        salary_amount="4000000",
        salary_effective_date=date(2026, 2, 1),
        skills_raw="Gudang",
    )

    assert updated is employee
    assert employee.full_name == "Baru"
    assert employee.phone == "08222"
    assert employee.status == "INACTIVE"
    assert fake_skill.query.deleted_for_employee_id == 12
    assert any(isinstance(obj, _FakeEmployeeSkill) for obj in session.added)
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_employee_status_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(hr_service, "db", _FakeDb(session))
    employee = hr_service.Employee(status="ACTIVE")

    updated = hr_service.toggle_employee_status(employee)

    assert updated is employee
    assert employee.status == "INACTIVE"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_payroll_detail_record_recalculates_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(hr_service, "db", _FakeDb(session))
    detail = hr_service.PayrollDetail(base_salary=1000, bonus=0, deduction=0)

    updated = hr_service.update_payroll_detail_record(
        detail,
        base_salary="1500",
        bonus="250",
        deduction="100",
    )

    assert updated is detail
    assert detail.base_salary == 1500
    assert detail.bonus == 250
    assert detail.deduction == 100
    assert detail.final_salary == 1650
    assert session.commit_count == 1
    assert session.rollback_count == 0
