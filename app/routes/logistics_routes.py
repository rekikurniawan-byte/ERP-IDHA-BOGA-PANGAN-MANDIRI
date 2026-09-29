import logging
from datetime import date, datetime, timedelta
from uuid import uuid4

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, send_file
from flask_login import current_user

from app.models.master import Item, Supplier
from app.services.stock_service import (
    get_stock_items,
    get_stock_summary,
    get_recent_movements,
    get_item_stock,
    get_item_movements,
    create_stock_movement,
)
from app.utils.decorators import role_required
from app.services.global_filter_service import resolve_date_filter, build_filter_bar_context, apply_date_range_to_query
from app.services.audit_log_service import record_audit_log
from app.services.atomic_transaction_service import atomic_business_action
from app.services.business_logic_guard_service import validate_stock_movement_guard
from app.services.idempotency_service import (
    IdempotencyConflictError,
    mark_idempotency_completed,
    mark_idempotency_failed,
    reserve_idempotency_key,
)
from app.services.logistics_transaction_service import (
    approve_item_request_record,
    create_item_request_record,
    create_stock_audit_movement,
    fulfill_item_request_record,
    reject_item_request_record,
)
from app.services.material_forecast_service import build_material_requirement_forecast
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    format_file_size,
    get_allowed_extensions,
    get_attachment_file_path,
    get_attachment_or_none,
    get_max_upload_bytes,
    list_reference_attachments,
    count_reference_attachments,
    save_digital_attachment,
    soft_delete_attachment,
)

logger = logging.getLogger(__name__)


logistics_bp = Blueprint("logistics", __name__, url_prefix="/logistics")


PROCUREMENT_ATTACHMENT_MODULE = "PROCUREMENT"
PROCUREMENT_ATTACHMENT_REFERENCE = "PROCUREMENT"


def _procurement_or_404(procurement_id):
    from app.models.logistics import Procurement

    procurement = Procurement.query.get_or_404(procurement_id)
    if procurement.branch_id != current_user.branch_id:
        abort(404)
    return procurement


def _procurement_attachment_or_404(attachment_id):
    attachment = get_attachment_or_none(attachment_id, branch_id=current_user.branch_id)
    if not attachment or attachment.module != PROCUREMENT_ATTACHMENT_MODULE or attachment.reference_type != PROCUREMENT_ATTACHMENT_REFERENCE:
        abort(404)

    procurement = _procurement_or_404(attachment.reference_id)
    return attachment, procurement


# Domain route modules. Imported after shared helpers are defined so decorators bind to the same blueprint.
from app.routes.logistics import stock_routes as _logistics_stock_routes  # noqa: F401,E402
from app.routes.logistics import procurement_routes as _logistics_procurement_routes  # noqa: F401,E402
from app.routes.logistics import stock_audit_routes as _logistics_stock_audit_routes  # noqa: F401,E402
from app.routes.logistics import item_request_routes as _logistics_item_request_routes  # noqa: F401,E402
