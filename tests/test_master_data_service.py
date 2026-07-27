from datetime import date

from app.services import master_data_service


class _FakeClient:
    branch_id = None
    client_code = None
    name = None
    phone = None
    address = None
    is_active = None


class _FakeMandor:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeLocation:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


class _FakeSession:
    def __init__(self, *, fail_commit=False):
        self.added = []
        self.commit_count = 0
        self.rollback_count = 0
        self.fail_commit = fail_commit

    def add(self, obj):
        self.added.append(obj)

    def delete(self, obj):
        self.deleted = getattr(self, "deleted", [])
        self.deleted.append(obj)

    def commit(self):
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self):
        self.rollback_count += 1


class _FakeDb:
    def __init__(self, session):
        self.session = session


def test_create_client_record_commits_new_client(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "Client", _FakeClient)
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    client = master_data_service.create_client_record(
        branch_id=7,
        client_code="CL-0007",
        name="PT Contoh",
        phone="08123",
        address="Jakarta",
        is_active=True,
    )

    assert client in session.added
    assert client.branch_id == 7
    assert client.client_code == "CL-0007"
    assert client.name == "PT Contoh"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_client_record_rolls_back_when_commit_fails(monkeypatch):
    session = _FakeSession(fail_commit=True)
    monkeypatch.setattr(master_data_service, "Client", _FakeClient)
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    try:
        master_data_service.create_client_record(
            branch_id=7,
            client_code="CL-0007",
            name="PT Contoh",
            phone="08123",
            address="Jakarta",
            is_active=True,
        )
    except RuntimeError as error:
        assert str(error) == "commit failed"
    else:
        raise AssertionError("create_client_record should re-raise commit errors")

    assert session.commit_count == 1
    assert session.rollback_count == 1


def test_update_client_record_commits_changes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    client = _FakeClient()

    updated = master_data_service.update_client_record(
        client,
        client_code="CL-0008",
        name="PT Baru",
        phone="08456",
        address="Bandung",
        is_active=False,
    )

    assert updated is client
    assert client.client_code == "CL-0008"
    assert client.name == "PT Baru"
    assert client.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_client_active_commits_when_supported(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    client = _FakeClient()
    client.is_active = True

    changed = master_data_service.toggle_client_active(client)

    assert changed is True
    assert client.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_mandor_record_commits_new_mandor(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "Mandor", _FakeMandor)
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    mandor = master_data_service.create_mandor_record(
        branch_id=3,
        client_id=9,
        name="Mandor Satu",
        phone="08777",
        is_active=True,
    )

    assert mandor in session.added
    assert mandor.branch_id == 3
    assert mandor.client_id == 9
    assert mandor.name == "Mandor Satu"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_mandor_record_commits_changes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    mandor = _FakeMandor(client_id=1, name="Lama", phone="08000", is_active=True)

    updated = master_data_service.update_mandor_record(
        mandor,
        client_id=2,
        name="Baru",
        phone="08999",
        is_active=False,
    )

    assert updated is mandor
    assert mandor.client_id == 2
    assert mandor.name == "Baru"
    assert mandor.phone == "08999"
    assert mandor.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_mandor_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    mandor = _FakeMandor(is_active=True)

    updated = master_data_service.toggle_mandor_active(mandor)

    assert updated is mandor
    assert mandor.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_location_record_commits_new_location(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "DeliveryLocation", _FakeLocation)
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    location = master_data_service.create_location_record(
        mandor_id=11,
        location_name="Workshop",
        description="Area kerja",
        is_active=True,
    )

    assert location in session.added
    assert location.mandor_id == 11
    assert location.location_name == "Workshop"
    assert location.description == "Area kerja"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_location_record_commits_changes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    location = _FakeLocation(mandor_id=1, location_name="Lama", description="", is_active=True)

    updated = master_data_service.update_location_record(
        location,
        mandor_id=2,
        location_name="Baru",
        description="Keterangan",
        is_active=False,
    )

    assert updated is location
    assert location.mandor_id == 2
    assert location.location_name == "Baru"
    assert location.description == "Keterangan"
    assert location.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_location_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    location = _FakeLocation(is_active=True)

    updated = master_data_service.toggle_location_active(location)

    assert updated is location
    assert location.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_worker_record_commits_new_worker(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    worker = master_data_service.create_worker_record(
        mandor_id=12,
        worker_code="PKJ-0012",
        full_name="Pekerja Satu",
        phone="08111",
        status="ACTIVE",
        notes="Catatan",
    )

    assert worker in session.added
    assert worker.mandor_id == 12
    assert worker.worker_code == "PKJ-0012"
    assert worker.full_name == "Pekerja Satu"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_worker_record_keeps_existing_code_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    worker = master_data_service.Worker(worker_code="PKJ-0001")

    updated = master_data_service.update_worker_record(
        worker,
        mandor_id=2,
        worker_code="PKJ-9999",
        full_name="Nama Baru",
        phone="08222",
        status="MOVED",
        notes="Pindah",
    )

    assert updated is worker
    assert worker.worker_code == "PKJ-0001"
    assert worker.mandor_id == 2
    assert worker.full_name == "Nama Baru"
    assert worker.status == "MOVED"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_worker_record_generates_missing_code(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    worker = master_data_service.Worker(worker_code=None)

    master_data_service.update_worker_record(
        worker,
        mandor_id=2,
        worker_code="PKJ-0002",
        full_name="Nama Baru",
        phone="08222",
        status="ACTIVE",
        notes="",
    )

    assert worker.worker_code == "PKJ-0002"
    assert session.commit_count == 1


def test_toggle_worker_status_commits_active_to_left(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    worker = master_data_service.Worker(status="ACTIVE")

    updated = master_data_service.toggle_worker_status(worker)

    assert updated is worker
    assert worker.status == "LEFT"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_delete_worker_record_commits_delete(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    worker = master_data_service.Worker()

    result = master_data_service.delete_worker_record(worker)

    assert result is None
    assert worker in session.deleted
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_driver_record_commits_new_driver(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    driver = master_data_service.create_driver_record(
        branch_id=4,
        name="Driver Satu",
        phone="08333",
        license_number="SIM-A",
        is_active=True,
    )

    assert driver in session.added
    assert driver.branch_id == 4
    assert driver.name == "Driver Satu"
    assert driver.phone == "08333"
    assert driver.license_number == "SIM-A"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_driver_record_commits_changes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    driver = master_data_service.Driver(name="Lama", phone="", license_number="", is_active=True)

    updated = master_data_service.update_driver_record(
        driver,
        name="Driver Baru",
        phone="08444",
        license_number="SIM-B",
        is_active=False,
    )

    assert updated is driver
    assert driver.name == "Driver Baru"
    assert driver.phone == "08444"
    assert driver.license_number == "SIM-B"
    assert driver.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_driver_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    driver = master_data_service.Driver(is_active=True)

    updated = master_data_service.toggle_driver_active(driver)

    assert updated is driver
    assert driver.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_item_record_commits_new_item(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    item = master_data_service.create_item_record(
        category="RAW_MATERIAL",
        item_code="BB-0001",
        item_name="Beras",
        unit="KG",
        minimum_stock=10,
        selling_price=15000,
        is_stock_tracked=True,
        is_active=True,
    )

    assert item in session.added
    assert item.item_code == "BB-0001"
    assert item.item_name == "Beras"
    assert item.category == "RAW_MATERIAL"
    assert item.unit == "KG"
    assert item.is_stock_tracked is True
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_item_record_keeps_existing_code_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    item = master_data_service.Item(item_code="BB-0001")

    updated = master_data_service.update_item_record(
        item,
        category="PACKAGING",
        item_code="KMS-9999",
        item_name="Kemasan Baru",
        unit="PCS",
        minimum_stock=5,
        selling_price=2500,
        is_stock_tracked=False,
        is_active=False,
    )

    assert updated is item
    assert item.item_code == "BB-0001"
    assert item.category == "PACKAGING"
    assert item.item_name == "Kemasan Baru"
    assert item.unit == "PCS"
    assert item.is_stock_tracked is False
    assert item.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_item_record_generates_missing_code(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    item = master_data_service.Item(item_code=None)

    master_data_service.update_item_record(
        item,
        category="RAW_MATERIAL",
        item_code="BB-0002",
        item_name="Gula",
        unit="KG",
        minimum_stock=3,
        selling_price=14000,
        is_stock_tracked=True,
        is_active=True,
    )

    assert item.item_code == "BB-0002"
    assert session.commit_count == 1


def test_toggle_item_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    item = master_data_service.Item(is_active=True)

    updated = master_data_service.toggle_item_active(item)

    assert updated is item
    assert item.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_delete_item_record_commits_delete(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    item = master_data_service.Item()

    result = master_data_service.delete_item_record(item)

    assert result is None
    assert item in session.deleted
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_save_item_cost_profile_creates_profile_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    profile = master_data_service.save_item_cost_profile(
        None,
        item_id=10,
        branch_id=2,
        purchase_unit="KG",
        purchase_qty=25,
        base_unit="GRAM",
        conversion_factor=1000,
        yield_percentage=95,
        waste_percentage=5,
        standard_purchase_price=250000,
        effective_cost_per_base_unit=10.53,
        cost_source="STANDARD",
        notes="Harga standar",
        updated_by=9,
    )

    assert profile in session.added
    assert profile.item_id == 10
    assert profile.branch_id == 2
    assert profile.purchase_unit == "KG"
    assert profile.base_unit == "GRAM"
    assert profile.updated_by == 9
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_save_item_cost_profile_updates_existing_profile(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    profile = master_data_service.ItemCostProfile(
        item_id=10,
        branch_id=2,
        purchase_unit="KG",
        base_unit="GRAM",
        updated_by=1,
    )

    updated = master_data_service.save_item_cost_profile(
        profile,
        item_id=99,
        branch_id=99,
        purchase_unit="DUS",
        purchase_qty=2,
        base_unit="PCS",
        conversion_factor=12,
        yield_percentage=100,
        waste_percentage=0,
        standard_purchase_price=120000,
        effective_cost_per_base_unit=5000,
        cost_source="MANUAL",
        notes=None,
        updated_by=5,
    )

    assert updated is profile
    assert profile.item_id == 10
    assert profile.branch_id == 2
    assert profile.purchase_unit == "DUS"
    assert profile.base_unit == "PCS"
    assert profile.updated_by == 5
    assert session.added == []
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_upsert_unit_conversion_creates_conversion_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    conversion = master_data_service.upsert_unit_conversion(
        None,
        branch_id=2,
        unit_from="KG",
        unit_to="GRAM",
        multiplier=1000,
        notes="Metric",
        created_by=7,
    )

    assert conversion in session.added
    assert conversion.branch_id == 2
    assert conversion.unit_from == "KG"
    assert conversion.unit_to == "GRAM"
    assert conversion.multiplier == 1000
    assert conversion.is_active is True
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_upsert_unit_conversion_updates_existing_conversion(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    conversion = master_data_service.UnitConversion(
        branch_id=2,
        unit_from="KG",
        unit_to="GRAM",
        multiplier=900,
        notes=None,
        created_by=7,
        is_active=False,
    )

    updated = master_data_service.upsert_unit_conversion(
        conversion,
        branch_id=99,
        unit_from="DUS",
        unit_to="PCS",
        multiplier=12,
        notes="Isi dus",
        created_by=99,
    )

    assert updated is conversion
    assert conversion.branch_id == 2
    assert conversion.unit_from == "KG"
    assert conversion.unit_to == "GRAM"
    assert conversion.multiplier == 12
    assert conversion.notes == "Isi dus"
    assert conversion.is_active is True
    assert session.added == []
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_unit_conversion_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    conversion = master_data_service.UnitConversion(is_active=True)

    updated = master_data_service.toggle_unit_conversion_active(conversion)

    assert updated is conversion
    assert conversion.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_supplier_record_commits_new_supplier(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    supplier = master_data_service.create_supplier_record(
        branch_id=2,
        supplier_code="SUP-0001",
        supplier_name="Supplier Satu",
        supplier_type="RAW_MATERIAL",
        contact_person="Ibu Ani",
        phone="08111",
        whatsapp="08111",
        address="Jakarta",
        default_payment_terms_days=14,
        bank_name="BCA",
        bank_account_number="123",
        bank_account_holder="Supplier Satu",
        npwp="01",
        notes="Catatan",
        is_active=True,
    )

    assert supplier in session.added
    assert supplier.branch_id == 2
    assert supplier.supplier_code == "SUP-0001"
    assert supplier.supplier_name == "Supplier Satu"
    assert supplier.default_payment_terms_days == 14
    assert supplier.is_active is True
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_supplier_record_commits_changes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    supplier = master_data_service.Supplier(supplier_code="SUP-0001")

    updated = master_data_service.update_supplier_record(
        supplier,
        supplier_name="Supplier Baru",
        supplier_type="PACKAGING",
        contact_person="Pak Budi",
        phone="08222",
        whatsapp="08333",
        address="Bandung",
        default_payment_terms_days=30,
        bank_name="Mandiri",
        bank_account_number="456",
        bank_account_holder="Supplier Baru",
        npwp="02",
        notes="Baru",
        is_active=False,
    )

    assert updated is supplier
    assert supplier.supplier_code == "SUP-0001"
    assert supplier.supplier_name == "Supplier Baru"
    assert supplier.supplier_type == "PACKAGING"
    assert supplier.default_payment_terms_days == 30
    assert supplier.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_supplier_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    supplier = master_data_service.Supplier(is_active=True)

    updated = master_data_service.toggle_supplier_active(supplier)

    assert updated is supplier
    assert supplier.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_bank_account_record_commits_new_account(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    account = master_data_service.create_bank_account_record(
        branch_id=2,
        account_name="Operasional",
        bank_name="BCA",
        account_number="123",
        is_active=True,
    )

    assert account in session.added
    assert account.branch_id == 2
    assert account.account_name == "Operasional"
    assert account.bank_name == "BCA"
    assert account.account_number == "123"
    assert account.is_active is True
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_bank_account_record_commits_changes(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    account = master_data_service.BankAccount(account_name="Lama", is_active=True)

    updated = master_data_service.update_bank_account_record(
        account,
        account_name="Utama",
        bank_name="Mandiri",
        account_number="456",
        is_active=False,
    )

    assert updated is account
    assert account.account_name == "Utama"
    assert account.bank_name == "Mandiri"
    assert account.account_number == "456"
    assert account.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_bank_account_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    account = master_data_service.BankAccount(is_active=True)

    updated = master_data_service.toggle_bank_account_active(account)

    assert updated is account
    assert account.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_fixed_asset_record_commits_new_asset(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    asset = master_data_service.create_fixed_asset_record(
        branch_id=2,
        asset_code="AST-0001",
        asset_name="Kompor",
        asset_category="KITCHEN_EQUIPMENT",
        purchase_date=date(2026, 1, 2),
        purchase_value=5000000,
        useful_life_years=5,
        residual_value=500000,
        accumulated_depreciation=100000,
        book_value=4900000,
        status="ACTIVE",
        notes="Dapur",
    )

    assert asset in session.added
    assert asset.branch_id == 2
    assert asset.asset_code == "AST-0001"
    assert asset.asset_name == "Kompor"
    assert asset.book_value == 4900000
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_fixed_asset_record_keeps_existing_code_and_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    asset = master_data_service.FixedAsset(asset_code="AST-0001")

    updated = master_data_service.update_fixed_asset_record(
        asset,
        asset_code="AST-9999",
        asset_name="Mixer",
        asset_category="KITCHEN_EQUIPMENT",
        purchase_date=date(2026, 2, 3),
        purchase_value=7000000,
        useful_life_years=4,
        residual_value=700000,
        accumulated_depreciation=200000,
        book_value=6800000,
        status="INACTIVE",
        notes="Gudang",
    )

    assert updated is asset
    assert asset.asset_code == "AST-0001"
    assert asset.asset_name == "Mixer"
    assert asset.status == "INACTIVE"
    assert asset.book_value == 6800000
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_update_fixed_asset_record_generates_missing_code(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    asset = master_data_service.FixedAsset(asset_code=None)

    master_data_service.update_fixed_asset_record(
        asset,
        asset_code="AST-0002",
        asset_name="Freezer",
        asset_category="KITCHEN_EQUIPMENT",
        purchase_date=date(2026, 3, 4),
        purchase_value=3000000,
        useful_life_years=3,
        residual_value=0,
        accumulated_depreciation=0,
        book_value=3000000,
        status="ACTIVE",
        notes="",
    )

    assert asset.asset_code == "AST-0002"
    assert session.commit_count == 1


def test_toggle_fixed_asset_status_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    asset = master_data_service.FixedAsset(status="ACTIVE")

    updated = master_data_service.toggle_fixed_asset_status(asset)

    assert updated is asset
    assert asset.status == "INACTIVE"
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_create_client_pic_record_commits_new_pic(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))

    pic = master_data_service.create_client_pic_record(
        client_id=12,
        name="PIC Satu",
        phone="08111",
        email="pic@example.test",
        position="Admin",
        is_active=True,
    )

    assert pic in session.added
    assert pic.client_id == 12
    assert pic.name == "PIC Satu"
    assert pic.email == "pic@example.test"
    assert pic.position == "Admin"
    assert pic.is_active is True
    assert session.commit_count == 1
    assert session.rollback_count == 0


def test_toggle_client_pic_active_commits(monkeypatch):
    session = _FakeSession()
    monkeypatch.setattr(master_data_service, "db", _FakeDb(session))
    pic = master_data_service.ClientPic(is_active=True)

    updated = master_data_service.toggle_client_pic_active(pic)

    assert updated is pic
    assert pic.is_active is False
    assert session.commit_count == 1
    assert session.rollback_count == 0
