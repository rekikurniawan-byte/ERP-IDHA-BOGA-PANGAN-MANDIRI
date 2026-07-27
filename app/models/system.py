from app.extensions import db
from app.models.base import BaseModel


class Notification(BaseModel):
    __tablename__ = "notifications"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    notification_type = db.Column(db.String(50), nullable=False, index=True)
    title = db.Column(db.String(150), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="UNREAD", index=True)
    target_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    target_role = db.Column(db.String(30), nullable=True, index=True)
    priority = db.Column(db.String(20), nullable=False, default="INFO", index=True)
    reference_type = db.Column(db.String(80), nullable=True, index=True)
    reference_id = db.Column(db.Integer, nullable=True, index=True)
    action_url = db.Column(db.String(500), nullable=True)
    due_date = db.Column(db.Date, nullable=True, index=True)
    read_at = db.Column(db.DateTime, nullable=True)
    dismissed_at = db.Column(db.DateTime, nullable=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    generated_key = db.Column(db.String(180), nullable=True, unique=True, index=True)
    metadata_json = db.Column(db.Text, nullable=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    target_user = db.relationship("User", foreign_keys=[target_user_id], lazy="joined")


class AuditLog(BaseModel):
    __tablename__ = "audit_logs"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    username_snapshot = db.Column(db.String(100), nullable=True)
    user_role_snapshot = db.Column(db.String(50), nullable=True)
    module = db.Column(db.String(80), nullable=False, default="SYSTEM", index=True)
    event_type = db.Column(db.String(100), nullable=False, default="GENERAL", index=True)
    table_name = db.Column(db.String(100), nullable=True, index=True)
    record_id = db.Column(db.Integer, nullable=True, index=True)
    action = db.Column(db.String(50), nullable=False, default="INFO", index=True)
    description = db.Column(db.Text, nullable=True)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    ip_address = db.Column(db.String(80), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)

    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")
    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")


class DigitalAttachment(BaseModel):
    __tablename__ = "digital_attachments"

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=True, index=True)
    module = db.Column(db.String(60), nullable=False, index=True)
    reference_type = db.Column(db.String(80), nullable=False, index=True)
    reference_id = db.Column(db.Integer, nullable=False, index=True)
    attachment_type = db.Column(db.String(80), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=False, unique=True)
    file_path = db.Column(db.String(500), nullable=False)
    mime_type = db.Column(db.String(120), nullable=True)
    file_size = db.Column(db.Integer, nullable=False, default=0)
    sha256_hash = db.Column(db.String(64), nullable=False, index=True)
    notes = db.Column(db.Text, nullable=True)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    is_deleted = db.Column(db.Boolean, nullable=False, default=False, index=True)
    deleted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    deleted_at = db.Column(db.DateTime, nullable=True)
    delete_note = db.Column(db.Text, nullable=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    uploader = db.relationship("User", foreign_keys=[uploaded_by], lazy="joined")
    deleter = db.relationship("User", foreign_keys=[deleted_by], lazy="joined")


class IdempotencyKey(BaseModel):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        db.UniqueConstraint("scope", "key", name="uq_idempotency_scope_key"),
    )

    scope = db.Column(db.String(120), nullable=False, index=True)
    key = db.Column(db.String(120), nullable=False, index=True)
    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=True, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    request_hash = db.Column(db.String(64), nullable=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="STARTED", index=True)
    reference_type = db.Column(db.String(80), nullable=True, index=True)
    reference_id = db.Column(db.Integer, nullable=True, index=True)
    response_payload_json = db.Column(db.Text, nullable=True)
    error_message = db.Column(db.Text, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    user = db.relationship("User", foreign_keys=[user_id], lazy="joined")


class ApprovalRequest(BaseModel):
    __tablename__ = "approval_requests"
    __table_args__ = (
        db.Index("ix_approval_requests_action_status", "action_key", "status"),
        db.Index("ix_approval_requests_reference", "reference_type", "reference_id"),
    )

    branch_id = db.Column(db.Integer, db.ForeignKey("branches.id"), nullable=False, index=True)
    action_key = db.Column(db.String(120), nullable=False, index=True)
    reference_type = db.Column(db.String(80), nullable=False, index=True)
    reference_id = db.Column(db.Integer, nullable=False, index=True)
    status = db.Column(db.String(30), nullable=False, default="SUBMITTED", index=True)
    requested_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    reviewed_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True, index=True)
    requested_reason = db.Column(db.Text, nullable=False)
    review_note = db.Column(db.Text, nullable=True)
    payload_json = db.Column(db.Text, nullable=True)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    branch = db.relationship("Branch", foreign_keys=[branch_id], lazy="joined")
    requester = db.relationship("User", foreign_keys=[requested_by], lazy="joined")
    reviewer = db.relationship("User", foreign_keys=[reviewed_by], lazy="joined")
