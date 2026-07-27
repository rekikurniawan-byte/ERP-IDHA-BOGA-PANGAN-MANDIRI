"""Maker-checker approval center routes."""

from app.routes.settings_routes import *  # noqa: F401,F403
from app.models.system import ApprovalRequest
from app.services.approval_service import ApprovalError, approve_request, reject_request


@settings_bp.route("/approvals")
@role_required("OWNER", "ADMIN")
def approvals():
    status = (request.args.get("status") or "").strip().upper()
    query = ApprovalRequest.query.filter_by(branch_id=current_user.branch_id)
    if status:
        query = query.filter_by(status=status)
    requests = query.order_by(ApprovalRequest.id.desc()).limit(200).all()
    return render_template(
        "settings/approvals.html",
        approval_requests=requests,
        current_status=status,
    )


@settings_bp.route("/approvals/<int:approval_id>/approve", methods=["POST"])
@role_required("OWNER", "ADMIN")
def approve_approval_request(approval_id):
    request_row = ApprovalRequest.query.get_or_404(approval_id)
    if request_row.branch_id != current_user.branch_id:
        abort(404)
    note = (request.form.get("review_note") or "").strip()
    try:
        approve_request(request_row, reviewed_by=current_user.id, review_note=note, commit=True)
        flash("Approval request disetujui.", "success")
    except ApprovalError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("settings.approvals"))


@settings_bp.route("/approvals/<int:approval_id>/reject", methods=["POST"])
@role_required("OWNER", "ADMIN")
def reject_approval_request(approval_id):
    request_row = ApprovalRequest.query.get_or_404(approval_id)
    if request_row.branch_id != current_user.branch_id:
        abort(404)
    note = (request.form.get("review_note") or "").strip()
    try:
        reject_request(request_row, reviewed_by=current_user.id, review_note=note, commit=True)
        flash("Approval request ditolak.", "success")
    except ApprovalError as exc:
        flash(str(exc), "warning")
    return redirect(url_for("settings.approvals"))
