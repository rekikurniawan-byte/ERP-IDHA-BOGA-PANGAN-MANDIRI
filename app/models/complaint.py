from app.extensions import db
from app.models.base import BaseModel


class CustomerComplaint(BaseModel):
    __tablename__ = "customer_complaints"
    __table_args__ = (
        db.CheckConstraint(
            "category IN ('FOOD_SHORTAGE', 'DAMAGED_FOOD', 'WRONG_MENU', 'LATE_DELIVERY', 'PORTION_SHORTAGE', 'OTHER')",
            name="ck_customer_complaints_category",
        ),
        db.CheckConstraint(
            "status IN ('OPEN', 'IN_PROGRESS', 'RESOLVED', 'CLOSED')",
            name="ck_customer_complaints_status",
        ),
        db.Index("ix_customer_complaints_branch_status", "branch_id", "status"),
        db.Index("ix_customer_complaints_client_status", "client_id", "status"),
        db.Index("ix_customer_complaints_reference", "order_id", "delivery_id", "invoice_id"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    complaint_number = db.Column(db.String(60), nullable=False, unique=True, index=True)
    category = db.Column(db.String(40), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="OPEN", index=True)
    title = db.Column(db.String(180), nullable=False)
    description = db.Column(db.Text, nullable=False)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True, index=True)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=True, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("daily_orders.id"), nullable=True, index=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("deliveries.id"), nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True, index=True)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    assigned_to = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    resolved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    submitted_at = db.Column(db.DateTime, nullable=False)
    resolved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    resolution_note = db.Column(db.Text, nullable=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    client = db.relationship("Client", foreign_keys=[client_id], lazy="joined")
    mandor = db.relationship("Mandor", foreign_keys=[mandor_id], lazy="joined")
    order = db.relationship("DailyOrder", foreign_keys=[order_id], lazy="joined")
    delivery = db.relationship("Delivery", foreign_keys=[delivery_id], lazy="joined")
    invoice = db.relationship("Invoice", foreign_keys=[invoice_id], lazy="joined")
    submitter = db.relationship("User", foreign_keys=[submitted_by], lazy="joined")
    assignee = db.relationship("User", foreign_keys=[assigned_to], lazy="joined")
    resolver = db.relationship("User", foreign_keys=[resolved_by], lazy="joined")
    closer = db.relationship("User", foreign_keys=[closed_by], lazy="joined")
