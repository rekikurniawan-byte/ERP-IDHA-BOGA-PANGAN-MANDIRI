from app.extensions import db
from app.models.base import BaseModel




class Delivery(BaseModel):
    __tablename__ = "deliveries"

    delivery_number = db.Column(db.String(50), nullable=False, unique=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    delivery_date = db.Column(db.Date, nullable=False, index=True)
    driver_id = db.Column(db.Integer, db.ForeignKey("drivers.id"), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="PREPARING")
    target_dispatch_time = db.Column(db.DateTime, nullable=True)
    target_arrival_time = db.Column(db.DateTime, nullable=True)
    actual_departure_time = db.Column(db.DateTime, nullable=True)
    late_tolerance_minutes = db.Column(db.Integer, nullable=True, default=15)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    driver = db.relationship("Driver", lazy=True)
    details = db.relationship("DeliveryDetail", backref="delivery", lazy=True)


class DeliveryDetail(BaseModel):
    __tablename__ = "delivery_details"

    delivery_id = db.Column(db.Integer, db.ForeignKey("deliveries.id"), nullable=False)
    daily_order_detail_id = db.Column(db.Integer, db.ForeignKey("daily_order_details.id"), nullable=False)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=False)
    delivery_location_id = db.Column(db.Integer, db.ForeignKey("delivery_locations.id"), nullable=False)
    planned_qty = db.Column(db.Integer, nullable=False, default=0)
    delivered_qty = db.Column(db.Integer, nullable=False, default=0)
    shortage_qty = db.Column(db.Integer, nullable=False, default=0)
    sla_status = db.Column(db.String(30), nullable=True)
    sla_minutes_late = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    daily_order_detail = db.relationship("DailyOrderDetail", lazy=True)
    mandor = db.relationship("Mandor", lazy=True)
    delivery_location = db.relationship("DeliveryLocation", lazy=True)
    receipt = db.relationship("DeliveryReceipt", backref="delivery_detail", lazy=True, uselist=False)

    __table_args__ = (
        db.UniqueConstraint("delivery_id", "daily_order_detail_id", name="uq_delivery_detail_delivery_order_detail"),
    )


class DeliveryReceipt(BaseModel):
    __tablename__ = "delivery_receipts"

    delivery_detail_id = db.Column(db.Integer, db.ForeignKey("delivery_details.id"), nullable=False)
    receiver_name = db.Column(db.String(150), nullable=False)
    receive_time = db.Column(db.DateTime, nullable=False)
    notes = db.Column(db.Text, nullable=True)
