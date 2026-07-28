from app.extensions import db
from app.models.base import BaseModel


class CustomerContract(BaseModel):
    __tablename__ = "customer_contracts"
    __table_args__ = (
        db.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'EXPIRED', 'TERMINATED', 'SUPERSEDED')",
            name="ck_customer_contracts_status",
        ),
        db.CheckConstraint("version_no > 0", name="ck_customer_contracts_version_positive"),
        db.CheckConstraint("end_date >= start_date", name="ck_customer_contracts_date_range"),
        db.Index("ix_customer_contracts_client_status", "client_id", "status"),
        db.Index("ix_customer_contracts_branch_end_date", "branch_id", "end_date"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    client_id = db.Column(db.Integer, db.ForeignKey("clients.id"), nullable=False, index=True)
    client_pic_id = db.Column(db.Integer, db.ForeignKey("client_pics.id"), nullable=True, index=True)
    parent_contract_id = db.Column(db.Integer, db.ForeignKey("customer_contracts.id"), nullable=True, index=True)
    contract_number = db.Column(db.String(60), nullable=False, unique=True, index=True)
    title = db.Column(db.String(180), nullable=False)
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    payment_terms = db.Column(db.String(120), nullable=False)
    credit_limit = db.Column(db.Numeric(18, 2), nullable=False, default=0)
    status = db.Column(db.String(30), nullable=False, default="DRAFT", index=True)
    version_no = db.Column(db.Integer, nullable=False, default=1)
    notes = db.Column(db.Text, nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    updated_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    client = db.relationship("Client", foreign_keys=[client_id], lazy="joined")
    client_pic = db.relationship("ClientPic", foreign_keys=[client_pic_id], lazy="joined")
    parent_contract = db.relationship("CustomerContract", remote_side="CustomerContract.id", lazy="joined")
    creator = db.relationship("User", foreign_keys=[created_by], lazy="joined")
    updater = db.relationship("User", foreign_keys=[updated_by], lazy="joined")
