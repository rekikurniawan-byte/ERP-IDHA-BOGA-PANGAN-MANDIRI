from types import SimpleNamespace

from app.services import costing_transaction_service


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.deleted = []
        self.commit_count = 0
        self.rollback_count = 0
        self.flush_count = 0
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted.append(obj)

    def flush(self):
        self.flush_count += 1
        for obj in self.added:
            if getattr(obj, "id", None) is None:
                obj.id = 77

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


class _FakeRecipeVersionQuery:
    def __init__(self, existing=None):
        self.existing = existing

    def filter_by(self, **kwargs):
        return self

    def first(self):
        return self.existing


class _FakeRecipeVersion:
    query = _FakeRecipeVersionQuery()


def test_create_menu_record_adds_menu_default_recipe_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))

    menu = costing_transaction_service.create_menu_record(
        branch_id=2,
        menu_code="MNU-0001",
        menu_name="Nasi Box",
        menu_type="CATERING",
        default_selling_price=25000,
        notes="Catatan",
        is_active=True,
        updated_by=9,
    )

    assert menu in session.added
    assert menu.id == 77
    assert menu.menu_code == "MNU-0001"
    assert menu.menu_name == "Nasi Box"
    assert session.flush_count == 1
    assert len(session.added) == 2
    recipe = session.added[1]
    assert recipe.menu_id == 77
    assert recipe.recipe_name == "Resep Nasi Box"
    assert recipe.recipe_status == "DRAFT"
    assert recipe.updated_by == 9
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_menu_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))

    try:
        costing_transaction_service.create_menu_record(
            branch_id=2,
            menu_code="MNU-0001",
            menu_name="Nasi Box",
            menu_type="CATERING",
            default_selling_price=25000,
            notes=None,
            is_active=True,
            updated_by=9,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("create_menu_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_update_menu_record_commits_changes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    menu = costing_transaction_service.Menu(menu_name="Lama", is_active=True)

    updated = costing_transaction_service.update_menu_record(
        menu,
        menu_name="Baru",
        menu_type="BOX",
        default_selling_price=30000,
        notes=None,
        is_active=False,
    )

    assert updated is menu
    assert menu.menu_name == "Baru"
    assert menu.menu_type == "BOX"
    assert menu.default_selling_price == 30000
    assert menu.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_menu_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    menu = costing_transaction_service.Menu(is_active=True)

    updated = costing_transaction_service.toggle_menu_active(menu)

    assert updated is menu
    assert menu.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_delete_recipe_item_record_marks_recipe_draft_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    recipe = SimpleNamespace(recipe_status="FINAL", finalized_at="x", finalized_by=1, updated_by=1)
    recipe_item = SimpleNamespace(recipe=recipe)

    updated_recipe = costing_transaction_service.delete_recipe_item_record(recipe_item, updated_by=9)

    assert updated_recipe is recipe
    assert recipe_item in session.deleted
    assert recipe.recipe_status == "DRAFT"
    assert recipe.finalized_at is None
    assert recipe.finalized_by is None
    assert recipe.updated_by == 9
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_save_recipe_header_record_updates_draft_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    fake_version = _FakeRecipeVersion
    fake_version.query = _FakeRecipeVersionQuery(existing=None)
    monkeypatch.setattr(costing_transaction_service, "RecipeVersion", fake_version)
    recipe = SimpleNamespace(
        id=12,
        branch_id=2,
        recipe_name="Resep Lama",
        base_portion=1,
        recipe_status="DRAFT",
        version_label="v1",
        version_note=None,
        notes=None,
        items=[],
        finalized_at="x",
        finalized_by=3,
    )
    menu = SimpleNamespace(branch_id=2, id=5, menu_name="Menu")

    updated, created_version = costing_transaction_service.save_recipe_header_record(
        recipe,
        menu=menu,
        recipe_name="Resep Baru",
        base_portion=10,
        recipe_status="DRAFT",
        version_label="v2",
        version_note="Catatan versi",
        notes="Catatan",
        is_active=True,
        updated_by=9,
    )

    assert updated is recipe
    assert created_version is None
    assert recipe.recipe_name == "Resep Baru"
    assert recipe.base_portion == 10
    assert recipe.recipe_status == "DRAFT"
    assert recipe.finalized_at is None
    assert recipe.finalized_by is None
    assert recipe.updated_by == 9
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_save_recipe_header_record_creates_final_version(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    fake_version = _FakeRecipeVersion
    fake_version.query = _FakeRecipeVersionQuery(existing=None)
    monkeypatch.setattr(costing_transaction_service, "RecipeVersion", fake_version)
    created = SimpleNamespace(id=88, version_number=1, version_label="v1", items=[])
    monkeypatch.setattr(costing_transaction_service, "create_recipe_version_snapshot", lambda *args, **kwargs: created)
    recipe = SimpleNamespace(
        id=12,
        branch_id=2,
        recipe_name="Resep Lama",
        base_portion=1,
        recipe_status="DRAFT",
        version_label="v1",
        version_note=None,
        notes=None,
        items=[SimpleNamespace()],
    )
    menu = SimpleNamespace(branch_id=2, id=5, menu_name="Menu")

    updated, created_version = costing_transaction_service.save_recipe_header_record(
        recipe,
        menu=menu,
        recipe_name="Resep Final",
        base_portion=10,
        recipe_status="FINAL",
        version_label="v1",
        version_note=None,
        notes=None,
        is_active=True,
        updated_by=9,
    )

    assert updated is recipe
    assert created_version is created
    assert recipe.recipe_status == "FINAL"
    assert recipe.finalized_by == 9
    assert recipe.finalized_at is not None
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_save_recipe_header_record_rolls_back_recipe_version_errors(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    fake_version = _FakeRecipeVersion
    fake_version.query = _FakeRecipeVersionQuery(existing=None)
    monkeypatch.setattr(costing_transaction_service, "RecipeVersion", fake_version)

    def raise_version_error(*args, **kwargs):
        raise costing_transaction_service.RecipeVersionError("Resep tidak valid")

    monkeypatch.setattr(costing_transaction_service, "create_recipe_version_snapshot", raise_version_error)
    recipe = SimpleNamespace(
        id=12,
        branch_id=2,
        recipe_name="Resep Lama",
        base_portion=1,
        recipe_status="DRAFT",
        version_label="v1",
        version_note=None,
        notes=None,
        items=[SimpleNamespace()],
    )
    menu = SimpleNamespace(branch_id=2, id=5, menu_name="Menu")

    try:
        costing_transaction_service.save_recipe_header_record(
            recipe,
            menu=menu,
            recipe_name="Resep Final",
            base_portion=10,
            recipe_status="FINAL",
            version_label="v1",
            version_note=None,
            notes=None,
            is_active=True,
            updated_by=9,
        )
    except costing_transaction_service.RecipeVersionError as error:
        assert str(error) == "Resep tidak valid"
    else:
        raise AssertionError("save_recipe_header_record should re-raise recipe version errors")

    assert session.commit_count == 0
    assert session.rollback_count == 1


def test_add_recipe_item_record_adds_item_marks_recipe_draft_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    recipe = SimpleNamespace(id=12, recipe_status="FINAL", finalized_at="x", finalized_by=1, updated_by=1)
    menu = SimpleNamespace(branch_id=2, id=5, menu_name="Menu")
    item = SimpleNamespace(id=99)

    updated_recipe, recipe_item = costing_transaction_service.add_recipe_item_record(
        recipe,
        menu=menu,
        item=item,
        qty_per_portion=2,
        unit="KG",
        notes="Bahan",
        updated_by=9,
    )

    assert updated_recipe is recipe
    assert recipe_item in session.added
    assert recipe_item.recipe_id == 12
    assert recipe_item.item_id == 99
    assert recipe_item.qty_per_portion == 2
    assert recipe.recipe_status == "DRAFT"
    assert recipe.finalized_at is None
    assert recipe.finalized_by is None
    assert recipe.updated_by == 9
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_and_update_packaging_profile_records_commit(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))

    profile = costing_transaction_service.create_packaging_profile_record(
        branch_id=2,
        profile_code="PKG-0001",
        profile_name="Box Premium",
        cost_per_portion=2500,
        notes="Dus",
        is_active=True,
        updated_by=9,
    )
    costing_transaction_service.update_packaging_profile_record(
        profile,
        profile_name="Box Baru",
        cost_per_portion=3000,
        notes=None,
        is_active=False,
        updated_by=10,
    )

    assert profile in session.added
    assert profile.profile_name == "Box Baru"
    assert profile.cost_per_portion == 3000
    assert profile.is_active is False
    assert profile.updated_by == 10
    assert session.commit_count == 2
    assert session.rollback_count == 0


def test_toggle_packaging_profile_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    profile = costing_transaction_service.PackagingProfile(is_active=True, updated_by=1)

    updated = costing_transaction_service.toggle_packaging_profile_active(profile, updated_by=9)

    assert updated is profile
    assert profile.is_active is False
    assert profile.updated_by == 9
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_and_update_overhead_profile_records_commit(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))

    profile = costing_transaction_service.create_overhead_profile_record(
        branch_id=2,
        profile_code="OVH-0001",
        profile_name="Dapur",
        gas_cost_per_portion=100,
        electricity_cost_per_portion=200,
        water_cost_per_portion=300,
        labor_cost_per_portion=400,
        spices_cost_per_portion=500,
        other_cost_per_portion=600,
        overhead_percentage=5,
        notes="Awal",
        is_active=True,
        updated_by=9,
    )
    costing_transaction_service.update_overhead_profile_record(
        profile,
        profile_name="Dapur Baru",
        gas_cost_per_portion=110,
        electricity_cost_per_portion=220,
        water_cost_per_portion=330,
        labor_cost_per_portion=440,
        spices_cost_per_portion=550,
        other_cost_per_portion=660,
        overhead_percentage=6,
        notes=None,
        is_active=False,
        updated_by=10,
    )

    assert profile in session.added
    assert profile.profile_name == "Dapur Baru"
    assert profile.gas_cost_per_portion == 110
    assert profile.overhead_percentage == 6
    assert profile.is_active is False
    assert profile.updated_by == 10
    assert session.commit_count == 2
    assert session.rollback_count == 0


def test_toggle_overhead_profile_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(costing_transaction_service, "db", _FakeDb(session))
    profile = costing_transaction_service.OverheadProfile(is_active=True, updated_by=1)

    updated = costing_transaction_service.toggle_overhead_profile_active(profile, updated_by=9)

    assert updated is profile
    assert profile.is_active is False
    assert profile.updated_by == 9
    assert session.commit_count == 1
    assert session.rollback_count == 0
