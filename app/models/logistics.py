from app.extensions import db
from app.models.base import BaseModel


class Procurement(BaseModel):
    __tablename__ = "procurements"

    purchase_place = db.Column(db.String(150), nullable=False, default="Pembelian sendiri")

    procurement_number = db.Column(db.String(50), nullable=False, unique=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    supplier_id = db.Column(db.Integer, db.ForeignKey("suppliers.id"), nullable=True, index=True)
    procurement_date = db.Column(db.Date, nullable=False, index=True)
    purchase_type = db.Column(db.String(30), nullable=False)
    supplier_name = db.Column(db.String(150), nullable=False)
    total_amount = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    supplier = db.relationship("Supplier", lazy=True)
    items = db.relationship("ProcurementItem", backref="procurement", lazy=True)

class ProcurementItem(BaseModel):
    __tablename__ = "procurement_items"

    procurement_id = db.Column(db.Integer, db.ForeignKey("procurements.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    qty = db.Column(db.Float, nullable=False, default=0)
    unit_price = db.Column(db.Float, nullable=False, default=0)
    subtotal = db.Column(db.Float, nullable=False, default=0)

    item = db.relationship("Item", lazy=True)

class StockMovement(BaseModel):
    __tablename__ = "stock_movements"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)
    movement_date = db.Column(db.Date, nullable=False, index=True)
    movement_type = db.Column(db.String(30), nullable=False)
    reference_type = db.Column(db.String(50), nullable=False)
    reference_id = db.Column(db.Integer, nullable=True)
    qty = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    item = db.relationship("Item", lazy=True)

class DamagedItem(BaseModel):
    __tablename__ = "damaged_items"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    damage_date = db.Column(db.Date, nullable=False)
    qty = db.Column(db.Float, nullable=False, default=0)
    reason = db.Column(db.Text, nullable=False)
    reported_by = db.Column(db.Integer, nullable=False)


class StockAdjustment(BaseModel):
    __tablename__ = "stock_adjustments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    adjustment_date = db.Column(db.Date, nullable=False)
    system_qty = db.Column(db.Float, nullable=False, default=0)
    actual_qty = db.Column(db.Float, nullable=False, default=0)
    difference_qty = db.Column(db.Float, nullable=False, default=0)
    reason = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, nullable=False)


class ItemRequest(BaseModel):
    __tablename__ = "item_requests"

    __table_args__ = {"extend_existing": True}
    request_number = db.Column(db.String(50), nullable=False, unique=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    request_date = db.Column(db.Date, nullable=False, index=True)
    requested_by = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="PENDING")
    purpose = db.Column(db.String(100), nullable=False, default="Kebutuhan produksi dapur")
    notes = db.Column(db.Text, nullable=True)

    details = db.relationship(
        lambda: ItemRequestDetail,
        backref="item_request",
        lazy=True,
        cascade="all, delete-orphan"
    )


class ItemRequestDetail(BaseModel):
    __tablename__ = "item_request_details"

    __table_args__ = {"extend_existing": True}
    item_request_id = db.Column(db.Integer, db.ForeignKey("item_requests.id"), nullable=False, index=True)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False, index=True)

    # Kolom legacy yang sudah ada di database awal.
    # Tetap dipertahankan agar data lama dan form lama tidak rusak.
    qty = db.Column(db.Float, nullable=False, default=0)
    unit = db.Column(db.String(30), nullable=False)

    # Kolom alur permintaan barang dapur yang dipakai modul logistik aktif.
    requested_qty = db.Column(db.Float, nullable=False, default=0)
    approved_qty = db.Column(db.Float, nullable=False, default=0)
    fulfilled_qty = db.Column(db.Float, nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)

    item = db.relationship("Item", lazy=True)
