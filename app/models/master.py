from app.extensions import db
from app.models.base import BaseModel


class Branch(BaseModel):
    __tablename__ = "branches"

    code = db.Column(db.String(50), nullable=False, unique=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    settings = db.relationship("BranchSetting", backref="branch", lazy=True)
    users = db.relationship("User", backref="branch", lazy=True)
    mandors = db.relationship("Mandor", backref="branch", lazy=True)
    employees = db.relationship("Employee", backref="branch", lazy=True)
    drivers = db.relationship("Driver", backref="branch", lazy=True)
    suppliers = db.relationship("Supplier", backref="branch", lazy=True)


class BranchSetting(BaseModel):
    __tablename__ = "branch_settings"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    setting_key = db.Column(db.String(100), nullable=False)
    setting_value = db.Column(db.Text, nullable=True)


class User(BaseModel):
    __tablename__ = "users"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    username = db.Column(db.String(80), nullable=False, unique=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), nullable=False)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    def get_id(self):
        return str(self.id)

    @property
    def is_authenticated(self):
        return True

    @property
    def is_anonymous(self):
        return False


class Client(BaseModel):
    __tablename__ = "clients"

    client_code = db.Column(db.String(50), nullable=True, unique=True, index=True)
    name = db.Column(db.String(150), nullable=False)
    address = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    pics = db.relationship("ClientPic", backref="client", lazy=True)
    mandors = db.relationship("Mandor", backref="client", lazy=True)


class ClientPic(BaseModel):
    __tablename__ = "client_pics"

    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    position = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Mandor(BaseModel):
    __tablename__ = "mandors"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    # Identitas. Wajib untuk mandor yang ditagih langsung: tanpa ini, mandor
    # yang diblokir bisa mendaftar lagi besok sebagai baris baru dengan nama
    # sedikit berbeda dan sistem tidak akan tahu. Nullable supaya mandor lama
    # yang ditagih lewat PT tidak ikut terhambat.
    id_number = db.Column(db.String(32), nullable=True, index=True)
    address = db.Column(db.Text, nullable=True)
    guarantor_name = db.Column(db.String(150), nullable=True)
    guarantor_phone = db.Column(db.String(30), nullable=True)
    guarantor_id_number = db.Column(db.String(32), nullable=True)

    # Unit order langsung: sub client yang mewakili client itu sendiri, untuk
    # client kontrak yang memesan tanpa mandor. Seluruh alur order, produksi,
    # pengiriman, dan invoice terikat ke sub client, jadi client tanpa sub
    # client mendapat satu unit ini alih-alih membongkar kewajiban mandor di
    # enam tabel. Maksimal satu per client per cabang (index unik parsial).
    is_direct_unit = db.Column(db.Boolean, nullable=False, default=False, server_default="false")

    delivery_locations = db.relationship("DeliveryLocation", backref="mandor", lazy=True)
    workers = db.relationship("Worker", backref="mandor", lazy=True)


class DeliveryLocation(BaseModel):
    __tablename__ = "delivery_locations"

    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=False)
    location_name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.UniqueConstraint("mandor_id", "location_name", name="uq_delivery_location_mandor_location"),
    )


class Employee(BaseModel):
    __tablename__ = "employees"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    join_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE")

    skills = db.relationship("EmployeeSkill", backref="employee", lazy=True)


class EmployeeSkill(BaseModel):
    __tablename__ = "employee_skills"

    employee_id = db.Column(db.Integer, db.ForeignKey("employees.id"), nullable=False)
    skill_name = db.Column(db.String(100), nullable=False)


class Driver(BaseModel):
    __tablename__ = "drivers"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    license_number = db.Column(db.String(100), nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)


class Supplier(BaseModel):
    __tablename__ = "suppliers"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    supplier_code = db.Column(db.String(50), nullable=False, unique=True)
    supplier_name = db.Column(db.String(150), nullable=False)
    supplier_type = db.Column(db.String(50), nullable=False, default="GENERAL")
    contact_person = db.Column(db.String(150), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    whatsapp = db.Column(db.String(30), nullable=True)
    address = db.Column(db.Text, nullable=True)
    default_payment_terms_days = db.Column(db.Integer, nullable=False, default=0)
    bank_name = db.Column(db.String(100), nullable=True)
    bank_account_number = db.Column(db.String(100), nullable=True)
    bank_account_holder = db.Column(db.String(150), nullable=True)
    npwp = db.Column(db.String(100), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "supplier_name", name="uq_suppliers_branch_name"),
    )


class Item(BaseModel):
    __tablename__ = "items"

    item_code = db.Column(db.String(50), nullable=False, unique=True)
    item_name = db.Column(db.String(150), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    unit = db.Column(db.String(30), nullable=False)
    minimum_stock = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    selling_price = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    is_stock_tracked = db.Column(db.Boolean, nullable=False, default=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    cost_profile = db.relationship("ItemCostProfile", backref="item", lazy=True, uselist=False)


class UnitConversion(BaseModel):
    __tablename__ = "unit_conversions"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    unit_from = db.Column(db.String(30), nullable=False)
    unit_to = db.Column(db.String(30), nullable=False)
    multiplier = db.Column(db.Numeric(8, 4), nullable=False, default=1)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    created_by = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "unit_from", "unit_to", name="uq_unit_conversions_branch_units"),
    )


class ItemCostProfile(BaseModel):
    __tablename__ = "item_cost_profiles"

    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, unique=True, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    purchase_unit = db.Column(db.String(30), nullable=False)
    purchase_qty = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    base_unit = db.Column(db.String(30), nullable=False)
    conversion_factor = db.Column(db.Numeric(8, 4), nullable=False, default=1)
    yield_percentage = db.Column(db.Numeric(8, 4), nullable=False, default=100)
    waste_percentage = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    standard_purchase_price = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    effective_cost_per_base_unit = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    cost_source = db.Column(db.String(30), nullable=False, default="STANDARD")
    notes = db.Column(db.Text, nullable=True)
    updated_by = db.Column(db.Integer, nullable=False)


class Menu(BaseModel):
    __tablename__ = "menus"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    menu_code = db.Column(db.String(50), nullable=False, unique=True)
    menu_name = db.Column(db.String(150), nullable=False)
    menu_type = db.Column(db.String(50), nullable=False, default="CATERING")
    default_selling_price = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)

    recipe = db.relationship("RecipeHeader", backref="menu", lazy=True, uselist=False)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "menu_name", name="uq_menus_branch_name"),
    )


class RecipeHeader(BaseModel):
    __tablename__ = "recipe_headers"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    menu_id = db.Column(db.Integer, db.ForeignKey("menus.id"), nullable=False, unique=True, index=True)
    recipe_name = db.Column(db.String(150), nullable=False)
    base_portion = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    recipe_status = db.Column(db.String(20), nullable=False, default="DRAFT")
    version_label = db.Column(db.String(50), nullable=False, default="v1")
    version_note = db.Column(db.Text, nullable=True)
    finalized_at = db.Column(db.DateTime, nullable=True)
    finalized_by = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_by = db.Column(db.Integer, nullable=False)

    items = db.relationship("RecipeItem", backref="recipe", lazy=True, cascade="all, delete-orphan")


class RecipeItem(BaseModel):
    __tablename__ = "recipe_items"

    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe_headers.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)
    qty_per_portion = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    unit = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    item = db.relationship("Item", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("recipe_id", "item_id", "unit", name="uq_recipe_items_recipe_item_unit"),
    )


class RecipeVersion(BaseModel):
    __tablename__ = "recipe_versions"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe_headers.id"), nullable=False, index=True)
    menu_id = db.Column(db.Integer, db.ForeignKey("menus.id"), nullable=False, index=True)
    version_number = db.Column(db.Integer, nullable=False, default=1)
    version_label = db.Column(db.String(50), nullable=False, default="v1")
    version_note = db.Column(db.Text, nullable=True)
    recipe_name_snapshot = db.Column(db.String(150), nullable=False)
    menu_code_snapshot = db.Column(db.String(50), nullable=True)
    menu_name_snapshot = db.Column(db.String(150), nullable=False)
    base_portion = db.Column(db.Numeric(18, 4), nullable=False, default=1)
    status = db.Column(db.String(20), nullable=False, default="FINAL")
    finalized_at = db.Column(db.DateTime, nullable=True)
    finalized_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    recipe = db.relationship("RecipeHeader", backref="versions", lazy=True)
    menu = db.relationship("Menu", lazy=True)
    finalizer = db.relationship("User", foreign_keys=[finalized_by], lazy=True)
    items = db.relationship("RecipeVersionItem", backref="recipe_version", lazy=True, cascade="all, delete-orphan")

    __table_args__ = (
        db.UniqueConstraint("branch_id", "recipe_id", "version_number", name="uq_recipe_versions_branch_recipe_number"),
    )


class RecipeVersionItem(BaseModel):
    __tablename__ = "recipe_version_items"

    recipe_version_id = db.Column(db.Integer, db.ForeignKey("recipe_versions.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True, index=True)
    item_code_snapshot = db.Column(db.String(50), nullable=True)
    item_name_snapshot = db.Column(db.String(150), nullable=False)
    item_category_snapshot = db.Column(db.String(50), nullable=True)
    qty_per_portion = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    unit = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    item = db.relationship("Item", lazy=True)


class PackagingProfile(BaseModel):
    __tablename__ = "packaging_profiles"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    profile_code = db.Column(db.String(50), nullable=False, unique=True)
    profile_name = db.Column(db.String(150), nullable=False)
    cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_by = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "profile_name", name="uq_packaging_profiles_branch_name"),
    )


class OverheadProfile(BaseModel):
    __tablename__ = "overhead_profiles"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    profile_code = db.Column(db.String(50), nullable=False, unique=True)
    profile_name = db.Column(db.String(150), nullable=False)
    gas_cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    electricity_cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    water_cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    labor_cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    spices_cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    other_cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    overhead_percentage = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    updated_by = db.Column(db.Integer, nullable=False)

    __table_args__ = (
        db.UniqueConstraint("branch_id", "profile_name", name="uq_overhead_profiles_branch_name"),
    )

    @property
    def flat_cost_per_portion(self):
        return sum([
            float(self.gas_cost_per_portion or 0),
            float(self.electricity_cost_per_portion or 0),
            float(self.water_cost_per_portion or 0),
            float(self.labor_cost_per_portion or 0),
            float(self.spices_cost_per_portion or 0),
            float(self.other_cost_per_portion or 0),
        ])


class Worker(BaseModel):
    __tablename__ = "workers"

    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=False)
    full_name = db.Column(db.String(150), nullable=False)
    worker_code = db.Column(db.String(50), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE")
    notes = db.Column(db.Text, nullable=True)
