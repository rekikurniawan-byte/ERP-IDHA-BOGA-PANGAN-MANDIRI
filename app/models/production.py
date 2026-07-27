from app.extensions import db
from app.models.base import BaseModel


class Production(BaseModel):
    __tablename__ = "productions"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False)
    production_date = db.Column(db.Date, nullable=False)
    production_type = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="DRAFT")
    target_ready_time = db.Column(db.DateTime, nullable=True)
    actual_completed_time = db.Column(db.DateTime, nullable=True)
    late_tolerance_minutes = db.Column(db.Integer, nullable=True, default=0)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, nullable=False)

    details = db.relationship("ProductionDetail", backref="production", lazy=True)


class ProductionDetail(BaseModel):
    __tablename__ = "production_details"

    production_id = db.Column(db.Integer, db.ForeignKey("productions.id"), nullable=False)
    item_id = db.Column(db.Integer, db.ForeignKey("items.id"), nullable=False)
    planned_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    actual_qty = db.Column(db.Numeric(18, 4), nullable=False, default=0)
    unit = db.Column(db.String(30), nullable=False)
    notes = db.Column(db.Text, nullable=True)

    item = db.relationship("Item", lazy=True)
