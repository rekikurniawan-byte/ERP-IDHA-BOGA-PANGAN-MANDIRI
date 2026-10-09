from app.extensions import db
from app.models.base import BaseModel
from app.utils.clock import now_wib


class DailyOrder(BaseModel):
    __tablename__ = "daily_orders"

    order_number = db.Column(db.String(50), nullable=False, unique=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    order_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="DRAFT")
    is_locked = db.Column(db.Boolean, nullable=False, default=False)
    locked_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    lunch_menu_id = db.Column(db.Integer, db.ForeignKey("menus.id"), nullable=True)
    dinner_menu_id = db.Column(db.Integer, db.ForeignKey("menus.id"), nullable=True)
    packaging_profile_id = db.Column(db.Integer, db.ForeignKey("packaging_profiles.id"), nullable=True)
    overhead_profile_id = db.Column(db.Integer, db.ForeignKey("overhead_profiles.id"), nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    details = db.relationship("DailyOrderDetail", backref="daily_order", lazy=True)
    snapshots = db.relationship("OrderSnapshot", backref="daily_order", lazy=True)
    lunch_menu = db.relationship("Menu", foreign_keys=[lunch_menu_id], lazy=True)
    dinner_menu = db.relationship("Menu", foreign_keys=[dinner_menu_id], lazy=True)
    packaging_profile = db.relationship("PackagingProfile", lazy=True)
    overhead_profile = db.relationship("OverheadProfile", lazy=True)


class DailyOrderDetail(BaseModel):
    __tablename__ = "daily_order_details"

    daily_order_id = db.Column(db.Integer, db.ForeignKey("daily_orders.id"), nullable=False)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=False)
    delivery_location_id = db.Column(db.Integer, db.ForeignKey("delivery_locations.id"), nullable=False)
    price_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    # Asal harga yang dikunci: KONTRAK / STANDAR / OWNER (diubah OWNER).
    # Kosong = order lama, harga diketik manual sebelum daftar harga ada.
    price_source = db.Column(db.String(20), nullable=True)
    lunch_qty = db.Column(db.Integer, nullable=False, default=0)
    dinner_qty = db.Column(db.Integer, nullable=False, default=0)
    total_qty = db.Column(db.Integer, nullable=False, default=0)
    # Ongkir per pengiriman yang dikunci saat pengiriman itu dibuat (siang dan
    # malam = dua kali jalan). 0 = gratis / termasuk harga kontrak.
    lunch_delivery_fee = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    dinner_delivery_fee = db.Column(db.Numeric(18, 2), nullable=False, default=0, server_default="0")
    notes = db.Column(db.Text, nullable=True)

    mandor = db.relationship("Mandor", lazy=True)
    delivery_location = db.relationship("DeliveryLocation", lazy=True)
    revisions = db.relationship("OrderRevision", backref="daily_order_detail", lazy=True)

    __table_args__ = (
        db.UniqueConstraint(
            "daily_order_id",
            "mandor_id",
            "delivery_location_id",
            name="uq_daily_order_detail_order_mandor_location"
        ),
    )


class OrderRevision(BaseModel):
    __tablename__ = "order_revisions"

    daily_order_detail_id = db.Column(db.Integer, db.ForeignKey("daily_order_details.id"), nullable=False)
    revision_time = db.Column(db.DateTime, nullable=False)
    revision_type = db.Column(db.String(30), nullable=False)
    revision_direction = db.Column(db.String(30), nullable=False)
    lunch_qty_change = db.Column(db.Integer, nullable=False, default=0)
    dinner_qty_change = db.Column(db.Integer, nullable=False, default=0)
    price_per_portion = db.Column(db.Numeric(18, 2), nullable=True)
    reason = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)


class OrderSnapshot(BaseModel):
    __tablename__ = "order_snapshots"

    daily_order_id = db.Column(db.Integer, db.ForeignKey("daily_orders.id"), nullable=False)
    snapshot_time = db.Column(db.DateTime, nullable=False)
    snapshot_data = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, nullable=False)


class OrderHppSnapshot(BaseModel):
    __tablename__ = "order_hpp_snapshots"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    daily_order_id = db.Column(db.Integer, db.ForeignKey("daily_orders.id"), nullable=False, index=True)
    snapshot_number = db.Column(db.String(50), nullable=False, unique=True)
    snapshot_date = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="LOCKED")
    total_portion = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    food_cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    packaging_cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    overhead_cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    hpp_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    hpp_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    revenue_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    gross_margin_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    gross_margin_percentage = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    target_margin_percentage = db.Column(db.Numeric(8, 4), nullable=False, default=30)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    daily_order = db.relationship("DailyOrder", backref="hpp_snapshots", lazy=True)
    lines = db.relationship(
        "OrderHppSnapshotLine",
        backref="snapshot",
        lazy=True,
        cascade="all, delete-orphan",
    )


class OrderHppSnapshotLine(BaseModel):
    __tablename__ = "order_hpp_snapshot_lines"

    snapshot_id = db.Column(db.Integer, db.ForeignKey("order_hpp_snapshots.id"), nullable=False, index=True)
    meal_type = db.Column(db.String(30), nullable=False)
    menu_id = db.Column(db.Integer, db.ForeignKey("menus.id"), nullable=True)
    menu_code_snapshot = db.Column(db.String(50), nullable=True)
    menu_name_snapshot = db.Column(db.String(150), nullable=True)
    recipe_id = db.Column(db.Integer, db.ForeignKey("recipe_headers.id"), nullable=True)
    recipe_name_snapshot = db.Column(db.String(150), nullable=True)
    packaging_profile_id = db.Column(db.Integer, db.ForeignKey("packaging_profiles.id"), nullable=True)
    packaging_name_snapshot = db.Column(db.String(150), nullable=True)
    overhead_profile_id = db.Column(db.Integer, db.ForeignKey("overhead_profiles.id"), nullable=True)
    overhead_name_snapshot = db.Column(db.String(150), nullable=True)
    portion_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    selling_price_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    food_cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    packaging_cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    overhead_cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    hpp_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    hpp_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    revenue_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    gross_margin_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    gross_margin_percentage = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    calculation_status = db.Column(db.String(30), nullable=False, default="COMPLETE")
    warning_text = db.Column(db.Text, nullable=True)

    menu = db.relationship("Menu", lazy=True)
    recipe = db.relationship("RecipeHeader", lazy=True)
    packaging_profile = db.relationship("PackagingProfile", lazy=True)
    overhead_profile = db.relationship("OverheadProfile", lazy=True)
    components = db.relationship(
        "OrderHppSnapshotComponent",
        backref="snapshot_line",
        lazy=True,
        cascade="all, delete-orphan",
    )


class OrderHppSnapshotComponent(BaseModel):
    __tablename__ = "order_hpp_snapshot_components"

    snapshot_line_id = db.Column(db.Integer, db.ForeignKey("order_hpp_snapshot_lines.id"), nullable=False, index=True)
    component_type = db.Column(db.String(30), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=True)
    item_code_snapshot = db.Column(db.String(50), nullable=True)
    item_name_snapshot = db.Column(db.String(150), nullable=True)
    qty_per_portion = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    recipe_unit = db.Column(db.String(30), nullable=True)
    base_unit = db.Column(db.String(30), nullable=True)
    conversion_multiplier = db.Column(db.Numeric(8, 4), nullable=True)
    base_qty_per_portion = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    base_qty_total = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    cost_per_base_unit_snapshot = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    cost_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    source_profile_id = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    item = db.relationship("Item", lazy=True)


class OrderHppSnapshotAllocation(BaseModel):
    __tablename__ = "order_hpp_snapshot_allocations"

    snapshot_id = db.Column(db.Integer, db.ForeignKey("order_hpp_snapshots.id"), nullable=False, index=True)
    snapshot_line_id = db.Column(db.Integer, db.ForeignKey("order_hpp_snapshot_lines.id"), nullable=False, index=True)
    daily_order_detail_id = db.Column(db.Integer, db.ForeignKey("daily_order_details.id"), nullable=False, index=True)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=False, index=True)
    delivery_location_id = db.Column(db.Integer, db.ForeignKey("delivery_locations.id"), nullable=False, index=True)
    source_type = db.Column(db.String(50), nullable=False, default="ORDER_DETAIL", index=True)
    source_id = db.Column(db.Integer, nullable=False, index=True)
    meal_type = db.Column(db.String(30), nullable=False, index=True)
    allocation_method = db.Column(db.String(50), nullable=False, default="PORTION_RATIO")
    allocation_ratio = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    mandor_name_snapshot = db.Column(db.String(150), nullable=True)
    delivery_location_name_snapshot = db.Column(db.String(150), nullable=True)
    portion_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    selling_price_per_portion = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    revenue_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    food_cost_allocated_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    packaging_cost_allocated_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    overhead_cost_allocated_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    hpp_allocated_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    hpp_per_portion_snapshot = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    gross_margin_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    gross_margin_percentage = db.Column(db.Numeric(8, 4), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)

    snapshot = db.relationship("OrderHppSnapshot", backref=db.backref("allocations", lazy=True), lazy=True)
    snapshot_line = db.relationship("OrderHppSnapshotLine", backref=db.backref("allocations", lazy=True), lazy=True)
    daily_order_detail = db.relationship("DailyOrderDetail", lazy=True)
    mandor = db.relationship("Mandor", lazy=True)
    delivery_location = db.relationship("DeliveryLocation", lazy=True)

    __table_args__ = (
        db.UniqueConstraint(
            "snapshot_line_id",
            "daily_order_detail_id",
            "meal_type",
            name="uq_hpp_snapshot_allocation_line_detail_meal",
        ),
    )


class OrderHppStockConsumption(BaseModel):
    __tablename__ = "order_hpp_stock_consumptions"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    daily_order_id = db.Column(db.Integer, db.ForeignKey("daily_orders.id"), nullable=False, index=True)
    snapshot_id = db.Column(db.Integer, db.ForeignKey("order_hpp_snapshots.id"), nullable=False, unique=True, index=True)
    consumption_number = db.Column(db.String(50), nullable=False, unique=True)
    consumption_date = db.Column(db.Date, nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="COMMITTED")
    total_item_count = db.Column(db.Integer, nullable=False, default=0)
    total_required_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    total_cost = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    committed_by = db.Column(db.Integer, nullable=False)
    committed_at = db.Column(db.DateTime, nullable=False)

    daily_order = db.relationship("DailyOrder", lazy=True)
    snapshot = db.relationship("OrderHppSnapshot", backref=db.backref("stock_consumption", uselist=False), lazy=True)
    lines = db.relationship(
        "OrderHppStockConsumptionLine",
        backref="consumption",
        lazy=True,
        cascade="all, delete-orphan",
    )


class OrderHppStockConsumptionLine(BaseModel):
    __tablename__ = "order_hpp_stock_consumption_lines"

    consumption_id = db.Column(db.Integer, db.ForeignKey("order_hpp_stock_consumptions.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)
    stock_movement_id = db.Column(db.Integer, db.ForeignKey("stock_movements.id"), nullable=True, index=True)
    item_code_snapshot = db.Column(db.String(50), nullable=True)
    item_name_snapshot = db.Column(db.String(150), nullable=True)
    stock_unit_snapshot = db.Column(db.String(30), nullable=True)
    required_stock_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    stock_before_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    stock_after_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    estimated_cost_total = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    component_count = db.Column(db.Integer, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)

    item = db.relationship("Item", lazy=True)
    stock_movement = db.relationship("StockMovement", lazy=True)

    __table_args__ = (
        db.UniqueConstraint("consumption_id", "item_id", name="uq_hpp_stock_consumption_line_item"),
    )


class StandingOrderState(BaseModel):
    __tablename__ = "standing_order_states"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=False, index=True)
    delivery_location_id = db.Column(db.Integer, db.ForeignKey("delivery_locations.id"), nullable=False, index=True)
    meal_type = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="ACTIVE", server_default="ACTIVE")
    resume_date = db.Column(db.Date, nullable=True)
    last_nonzero_qty = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    updated_at = db.Column(db.DateTime, nullable=False, default=now_wib)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    branch = db.relationship("Branch", lazy=True)
    mandor = db.relationship("Mandor", lazy=True)
    delivery_location = db.relationship("DeliveryLocation", lazy=True)
    updater = db.relationship("User", foreign_keys=[updated_by], lazy=True)

    __table_args__ = (
        db.UniqueConstraint(
            "branch_id",
            "mandor_id",
            "delivery_location_id",
            "meal_type",
            name="uq_standing_order_states_scope",
        ),
    )


class OrderQtyChange(BaseModel):
    __tablename__ = "order_qty_changes"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=True, index=True)
    daily_order_detail_id = db.Column(db.Integer, db.ForeignKey("daily_order_details.id"), nullable=False, index=True)
    meal_type = db.Column(db.String(20), nullable=False)
    old_qty = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    new_qty = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    reason_code = db.Column(db.String(50), nullable=True)
    note = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(20), nullable=False, default="AUTO", server_default="AUTO")
    changed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    changed_at = db.Column(db.DateTime, nullable=False, default=now_wib)

    branch = db.relationship("Branch", lazy=True)
    daily_order_detail = db.relationship("DailyOrderDetail", backref=db.backref("qty_changes", lazy=True), lazy=True)
    user = db.relationship("User", foreign_keys=[changed_by], lazy=True)
