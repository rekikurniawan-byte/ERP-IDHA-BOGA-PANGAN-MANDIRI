from app.extensions import db
from app.models.finance import BankAccount
from app.models.master import (
    Worker,
    Item,
    Client,
    ClientPic,
    DeliveryLocation,
    Driver,
    ItemCostProfile,
    Mandor,
    Supplier,
    UnitConversion,
)


ITEM_PREFINAL = {
    "RAW_MATERIAL": "BB",
    "MERCHANDISE": "WRG",
    "PACKAGING": "KMS",
    "GAS": "GAS",
    "OTHER": "OTH",
}


def generate_worker_code():
    number = Worker.query.count() + 1

    while True:
        code = f"PKJ-{number:04d}"
        existing = Worker.query.filter_by(worker_code=code).first()

        if not existing:
            return code

        number += 1


def generate_item_code(category):
    prefix = ITEM_PREFINAL.get(category, "ITM")
    number = Item.query.filter(Item.item_code.like(f"{prefix}-%")).count() + 1

    while True:
        code = f"{prefix}-{number:04d}"
        existing = Item.query.filter_by(item_code=code).first()

        if not existing:
            return code

        number += 1


def generate_client_code():
    if not hasattr(Client, "client_code"):
        return None

    number = Client.query.filter(Client.client_code.like("CL-%")).count() + 1

    while True:
        code = f"CL-{number:04d}"
        existing = Client.query.filter_by(client_code=code).first()

        if not existing:
            return code

        number += 1


def _set_if_has_column(model_object, column_name, value):
    if hasattr(model_object.__class__, column_name):
        setattr(model_object, column_name, value)


def _commit_or_rollback():
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise


def create_client_record(*, branch_id, client_code, name, phone, address, is_active, customer_path=None):
    client = Client()
    _set_if_has_column(client, "branch_id", branch_id)
    if customer_path:
        client.customer_path = customer_path
    _set_if_has_column(client, "client_code", client_code)
    _set_if_has_column(client, "name", name)
    _set_if_has_column(client, "phone", phone)
    _set_if_has_column(client, "address", address)
    _set_if_has_column(client, "is_active", is_active)

    db.session.add(client)
    _commit_or_rollback()
    return client


def update_client_record(client, *, client_code, name, phone, address, is_active, customer_path=None):
    if customer_path:
        client.customer_path = customer_path
    _set_if_has_column(client, "client_code", client_code)
    _set_if_has_column(client, "name", name)
    _set_if_has_column(client, "phone", phone)
    _set_if_has_column(client, "address", address)
    _set_if_has_column(client, "is_active", is_active)

    _commit_or_rollback()
    return client


def toggle_client_active(client):
    if not hasattr(client.__class__, "is_active"):
        return False

    client.is_active = not client.is_active
    _commit_or_rollback()
    return True


def create_mandor_record(*, branch_id, client_id, name, phone, is_active):
    mandor = Mandor(
        branch_id=branch_id,
        client_id=client_id,
        name=name,
        phone=phone,
        is_active=is_active,
    )
    db.session.add(mandor)
    _commit_or_rollback()
    return mandor


def create_direct_unit_record(*, branch_id, client_id, name, phone):
    """Sub client khusus yang mewakili client itu sendiri (order langsung)."""
    mandor = Mandor(
        branch_id=branch_id,
        client_id=client_id,
        name=name,
        phone=phone,
        is_active=True,
        is_direct_unit=True,
    )
    db.session.add(mandor)
    _commit_or_rollback()
    return mandor


def update_mandor_record(mandor, *, client_id, name, phone, is_active):
    mandor.client_id = client_id
    mandor.name = name
    mandor.phone = phone
    mandor.is_active = is_active
    _commit_or_rollback()
    return mandor


def toggle_mandor_active(mandor):
    mandor.is_active = not mandor.is_active
    _commit_or_rollback()
    return mandor


def create_location_record(*, mandor_id, location_name, description, is_active, delivery_zone_id=None):
    location = DeliveryLocation(
        mandor_id=mandor_id,
        location_name=location_name,
        description=description,
        is_active=is_active,
        delivery_zone_id=delivery_zone_id,
    )
    db.session.add(location)
    _commit_or_rollback()
    return location


_KEEP_ZONE = object()


def update_location_record(location, *, mandor_id, location_name, description, is_active, delivery_zone_id=_KEEP_ZONE):
    location.mandor_id = mandor_id
    location.location_name = location_name
    location.description = description
    location.is_active = is_active
    # Zona ongkir hanya diubah kalau pemanggil mengirimnya (None = kosongkan).
    if delivery_zone_id is not _KEEP_ZONE:
        location.delivery_zone_id = delivery_zone_id
    _commit_or_rollback()
    return location


def toggle_location_active(location):
    location.is_active = not location.is_active
    _commit_or_rollback()
    return location


def create_worker_record(*, mandor_id, worker_code, full_name, phone, status, notes):
    worker = Worker(
        mandor_id=mandor_id,
        worker_code=worker_code,
        full_name=full_name,
        phone=phone,
        status=status,
        notes=notes,
    )
    db.session.add(worker)
    _commit_or_rollback()
    return worker


def update_worker_record(worker, *, mandor_id, worker_code, full_name, phone, status, notes):
    worker.mandor_id = mandor_id
    worker.worker_code = worker.worker_code or worker_code
    worker.full_name = full_name
    worker.phone = phone
    worker.status = status
    worker.notes = notes
    _commit_or_rollback()
    return worker


def toggle_worker_status(worker):
    worker.status = "LEFT" if worker.status == "ACTIVE" else "ACTIVE"
    _commit_or_rollback()
    return worker


def delete_worker_record(worker):
    db.session.delete(worker)
    _commit_or_rollback()


def create_driver_record(*, branch_id, name, phone, license_number, is_active):
    driver = Driver(
        branch_id=branch_id,
        name=name,
        phone=phone,
        license_number=license_number,
        is_active=is_active,
    )
    db.session.add(driver)
    _commit_or_rollback()
    return driver


def update_driver_record(driver, *, name, phone, license_number, is_active):
    driver.name = name
    driver.phone = phone
    driver.license_number = license_number
    driver.is_active = is_active
    _commit_or_rollback()
    return driver


def toggle_driver_active(driver):
    driver.is_active = not driver.is_active
    _commit_or_rollback()
    return driver


def create_item_record(
    *,
    category,
    item_code,
    item_name,
    unit,
    minimum_stock,
    selling_price,
    is_stock_tracked,
    is_active,
):
    item = Item(
        item_code=item_code,
        item_name=item_name,
        category=category,
        unit=unit,
        minimum_stock=minimum_stock,
        selling_price=selling_price,
        is_stock_tracked=is_stock_tracked,
        is_active=is_active,
    )
    db.session.add(item)
    _commit_or_rollback()
    return item


def update_item_record(
    item,
    *,
    category,
    item_code,
    item_name,
    unit,
    minimum_stock,
    selling_price,
    is_stock_tracked,
    is_active,
):
    item.item_name = item_name
    item.category = category
    item.unit = unit
    item.minimum_stock = minimum_stock
    item.selling_price = selling_price
    item.is_stock_tracked = is_stock_tracked
    item.is_active = is_active
    item.item_code = item.item_code or item_code
    _commit_or_rollback()
    return item


def toggle_item_active(item):
    item.is_active = not item.is_active
    _commit_or_rollback()
    return item


def delete_item_record(item):
    db.session.delete(item)
    _commit_or_rollback()


def save_item_cost_profile(
    profile,
    *,
    item_id,
    branch_id,
    purchase_unit,
    purchase_qty,
    base_unit,
    conversion_factor,
    yield_percentage,
    waste_percentage,
    standard_purchase_price,
    effective_cost_per_base_unit,
    cost_source,
    notes,
    updated_by,
):
    if profile is None:
        profile = ItemCostProfile(
            item_id=item_id,
            branch_id=branch_id,
            updated_by=updated_by,
        )
        db.session.add(profile)

    profile.purchase_unit = purchase_unit
    profile.purchase_qty = purchase_qty
    profile.base_unit = base_unit
    profile.conversion_factor = conversion_factor
    profile.yield_percentage = yield_percentage
    profile.waste_percentage = waste_percentage
    profile.standard_purchase_price = standard_purchase_price
    profile.effective_cost_per_base_unit = effective_cost_per_base_unit
    profile.cost_source = cost_source
    profile.notes = notes
    profile.updated_by = updated_by
    _commit_or_rollback()
    return profile


def upsert_unit_conversion(
    conversion,
    *,
    branch_id,
    unit_from,
    unit_to,
    multiplier,
    notes,
    created_by,
):
    if conversion is None:
        conversion = UnitConversion(
            branch_id=branch_id,
            unit_from=unit_from,
            unit_to=unit_to,
            multiplier=multiplier,
            notes=notes,
            created_by=created_by,
            is_active=True,
        )
        db.session.add(conversion)
    else:
        conversion.multiplier = multiplier
        conversion.notes = notes
        conversion.is_active = True

    _commit_or_rollback()
    return conversion


def toggle_unit_conversion_active(conversion):
    conversion.is_active = not conversion.is_active
    _commit_or_rollback()
    return conversion


def create_supplier_record(
    *,
    branch_id,
    supplier_code,
    supplier_name,
    supplier_type,
    contact_person,
    phone,
    whatsapp,
    address,
    default_payment_terms_days,
    bank_name,
    bank_account_number,
    bank_account_holder,
    npwp,
    notes,
    is_active,
):
    supplier = Supplier(
        branch_id=branch_id,
        supplier_code=supplier_code,
        supplier_name=supplier_name,
        supplier_type=supplier_type,
        contact_person=contact_person,
        phone=phone,
        whatsapp=whatsapp,
        address=address,
        default_payment_terms_days=default_payment_terms_days,
        bank_name=bank_name,
        bank_account_number=bank_account_number,
        bank_account_holder=bank_account_holder,
        npwp=npwp,
        notes=notes,
        is_active=is_active,
    )
    db.session.add(supplier)
    _commit_or_rollback()
    return supplier


def update_supplier_record(
    supplier,
    *,
    supplier_name,
    supplier_type,
    contact_person,
    phone,
    whatsapp,
    address,
    default_payment_terms_days,
    bank_name,
    bank_account_number,
    bank_account_holder,
    npwp,
    notes,
    is_active,
):
    supplier.supplier_name = supplier_name
    supplier.supplier_type = supplier_type
    supplier.contact_person = contact_person
    supplier.phone = phone
    supplier.whatsapp = whatsapp
    supplier.address = address
    supplier.default_payment_terms_days = default_payment_terms_days
    supplier.bank_name = bank_name
    supplier.bank_account_number = bank_account_number
    supplier.bank_account_holder = bank_account_holder
    supplier.npwp = npwp
    supplier.notes = notes
    supplier.is_active = is_active
    _commit_or_rollback()
    return supplier


def toggle_supplier_active(supplier):
    supplier.is_active = not supplier.is_active
    _commit_or_rollback()
    return supplier


def create_bank_account_record(*, branch_id, account_name, bank_name, account_number, is_active):
    account = BankAccount(
        branch_id=branch_id,
        account_name=account_name,
        bank_name=bank_name,
        account_number=account_number,
        is_active=is_active,
    )
    db.session.add(account)
    _commit_or_rollback()
    return account


def update_bank_account_record(account, *, account_name, bank_name, account_number, is_active):
    account.account_name = account_name
    account.bank_name = bank_name
    account.account_number = account_number
    account.is_active = is_active
    _commit_or_rollback()
    return account


def toggle_bank_account_active(account):
    account.is_active = not account.is_active
    _commit_or_rollback()
    return account


def update_fixed_asset_record(asset, *, asset_code, asset_name, asset_category, notes):
    """Nama, kategori, dan catatan saja; nilai aset mengikuti transaksi dan jurnalnya."""
    asset.asset_name = asset_name
    asset.asset_category = asset_category
    asset.notes = notes
    asset.asset_code = asset.asset_code or asset_code
    _commit_or_rollback()
    return asset


def toggle_fixed_asset_status(asset):
    asset.status = "INACTIVE" if asset.status == "ACTIVE" else "ACTIVE"
    _commit_or_rollback()
    return asset


def create_client_pic_record(*, client_id, name, phone, email, position, is_active=True):
    pic = ClientPic(
        client_id=client_id,
        name=name,
        phone=phone,
        email=email if hasattr(ClientPic, "email") else None,
        position=position,
        is_active=is_active,
    )
    db.session.add(pic)
    _commit_or_rollback()
    return pic


def toggle_client_pic_active(pic):
    pic.is_active = not bool(pic.is_active)
    _commit_or_rollback()
    return pic
