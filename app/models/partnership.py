from app.extensions import db
from app.models.base import BaseModel


class PartnershipRequest(BaseModel):
    """Pengajuan kerja sama katering proyek/perusahaan dari halaman publik."""

    __tablename__ = "partnership_requests"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=True, index=True)
    request_number = db.Column(db.String(30), nullable=False, unique=True, index=True)
    company_name = db.Column(db.String(150), nullable=False)
    contact_name = db.Column(db.String(150), nullable=False)
    contact_role = db.Column(db.String(100), nullable=True)
    phone = db.Column(db.String(40), nullable=False)
    email = db.Column(db.String(150), nullable=True)
    project_name = db.Column(db.String(150), nullable=False)
    project_address = db.Column(db.Text, nullable=True)
    latitude = db.Column(db.Numeric(10, 7), nullable=True)
    longitude = db.Column(db.Numeric(10, 7), nullable=True)
    workers_count = db.Column(db.Integer, nullable=True)
    portions_per_day = db.Column(db.Integer, nullable=True)
    meals = db.Column(db.String(20), nullable=False, default="LUNCH")
    start_date = db.Column(db.Date, nullable=True)
    duration_months = db.Column(db.Integer, nullable=True)
    payment_preference = db.Column(db.String(30), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="NEW", index=True)
    handled_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    handled_at = db.Column(db.DateTime, nullable=True)
    follow_up_notes = db.Column(db.Text, nullable=True)
    source_ip = db.Column(db.String(64), nullable=True)

    handler = db.relationship("User", foreign_keys=[handled_by], lazy="joined")
