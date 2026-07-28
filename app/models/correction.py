from app.extensions import db
from app.models.base import BaseModel


class CustomerCorrection(BaseModel):
    __tablename__ = "customer_corrections"
    __table_args__ = (
        db.CheckConstraint(
            "correction_type IN ('RETURN', 'CORRECTION', 'COMPENSATION')",
            name="ck_customer_corrections_type",
        ),
        db.CheckConstraint(
            "status IN ('DRAFT', 'SUBMITTED', 'APPROVED', 'REJECTED', 'CLOSED', 'CANCELLED')",
            name="ck_customer_corrections_status",
        ),
        db.CheckConstraint(
            "stock_effect IN ('NONE', 'PENDING', 'POSTED', 'NOT_APPLICABLE')",
            name="ck_customer_corrections_stock_effect",
        ),
        db.CheckConstraint(
            "financial_effect IN ('NONE', 'PENDING', 'POSTED', 'NOT_APPLICABLE')",
            name="ck_customer_corrections_financial_effect",
        ),
        db.CheckConstraint("correction_amount >= 0", name="ck_customer_corrections_amount_nonnegative"),
        db.Index("ix_customer_corrections_branch_status", "branch_id", "status"),
        db.Index("ix_customer_corrections_complaint_status", "complaint_id", "status"),
        db.Index("ix_customer_corrections_reference", "order_id", "delivery_id", "invoice_id"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    correction_number = db.Column(db.String(60), nullable=False, unique=True, index=True)
    correction_type = db.Column(db.String(30), nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="DRAFT", index=True)
    complaint_id = db.Column(db.Integer, db.ForeignKey("customer_complaints.id"), nullable=True, index=True)
    order_id = db.Column(db.Integer, db.ForeignKey("daily_orders.id"), nullable=True, index=True)
    delivery_id = db.Column(db.Integer, db.ForeignKey("deliveries.id"), nullable=True, index=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoices.id"), nullable=True, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=True, index=True)
    mandor_id = db.Column(db.Integer, db.ForeignKey("mandors.id"), nullable=True, index=True)
    reason = db.Column(db.Text, nullable=False)
    proposed_action = db.Column(db.Text, nullable=False)
    correction_amount = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    stock_effect = db.Column(db.String(30), nullable=False, default="NONE", index=True)
    financial_effect = db.Column(db.String(30), nullable=False, default="NONE", index=True)
    approval_request_id = db.Column(db.Integer, db.ForeignKey("approval_requests.id"), nullable=True, index=True)
    submitted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    approved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    closed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    submitted_at = db.Column(db.DateTime, nullable=True)
    approved_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    complaint = db.relationship("CustomerComplaint", foreign_keys=[complaint_id], lazy="joined")
    order = db.relationship("DailyOrder", foreign_keys=[order_id], lazy="joined")
    delivery = db.relationship("Delivery", foreign_keys=[delivery_id], lazy="joined")
    invoice = db.relationship("Invoice", foreign_keys=[invoice_id], lazy="joined")
    client = db.relationship("Client", foreign_keys=[client_id], lazy="joined")
    mandor = db.relationship("Mandor", foreign_keys=[mandor_id], lazy="joined")
    approval_request = db.relationship("ApprovalRequest", foreign_keys=[approval_request_id], lazy="joined")
    submitter = db.relationship("User", foreign_keys=[submitted_by], lazy="joined")
    approver = db.relationship("User", foreign_keys=[approved_by], lazy="joined")
    closer = db.relationship("User", foreign_keys=[closed_by], lazy="joined")
