from datetime import date, datetime, time, timedelta
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.extensions import db
from app.models.master import Branch, Client, DeliveryLocation, Mandor, User
from app.models.operational import DailyOrder
from app.models.system import DigitalAttachment, PortalOrderDraft, PortalUserMapping
from app.services.portal_order_draft_service import (
    create_portal_order_draft,
    session_closed_reason,
)
from app.services.portal_payment_proof_service import (
    PortalPaymentProofError,
    upload_portal_order_draft_payment_proof,
)
from app.services.portal_mapping_service import ACCESS_DRAFT_ORDER, PRINCIPAL_DELEGATE
from app.services.user_management_service import ROLE_PORTAL_CUSTOMER
from werkzeug.datastructures import FileStorage
from tests.test_portal_financial_visibility_service import (
    _create_client_family,
    _create_user,
)
import io


def _file_storage(filename="bukti.pdf", payload=b"%PDF-1.4 test"):
    return FileStorage(stream=io.BytesIO(payload), filename=filename, content_type="application/pdf")


def _setup_fixtures(branch_code="SESS"):
    user = _create_user(ROLE_PORTAL_CUSTOMER)
    client, _, mandor, location = _create_client_family(user.branch, branch_code)
    mapping = PortalUserMapping(
        user_id=user.id,
        principal_type=PRINCIPAL_DELEGATE,
        client_id=client.id,
        mandor_id=mandor.id,
        delivery_location_id=location.id,
        access_level=ACCESS_DRAFT_ORDER,
        is_active=True,
    )
    db.session.add(mapping)

    from app.models.pricing import PortionPrice
    pp = PortionPrice(
        branch_id=user.branch_id,
        price_per_portion=Decimal("25000"),
        effective_from=date(2026, 1, 1),
        created_by=user.id,
    )
    db.session.add(pp)
    db.session.flush()
    return user, user.branch, client, mandor, location


def test_session_closed_reason_scenarios(app):
    with app.app_context():
        user, branch, client, mandor, location = _setup_fixtures("SESS1")
        fixed_today = date(2026, 10, 6)

        # 1. Past date
        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today):
            reason = session_closed_reason(branch.id, fixed_today - timedelta(days=1), "LUNCH")
            assert reason is not None
            assert "tidak boleh sebelum hari ini" in reason

        # 2. Today before cutoff (09:00 WIB for LUNCH)
        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today), \
             patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 6, 9, 0)):
            reason = session_closed_reason(branch.id, fixed_today, "LUNCH")
            assert reason is None

        # 3. Today after cutoff (10:30 WIB for LUNCH)
        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today), \
             patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 6, 10, 30)):
            reason = session_closed_reason(branch.id, fixed_today, "LUNCH")
            assert reason is not None
            assert "Batas waktu pemesanan untuk Makan Siang hari ini sudah lewat" in reason

        # 4. Today before DINNER cutoff (14:00 WIB) -> DINNER open, LUNCH closed
        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today), \
             patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 6, 14, 0)):
            assert session_closed_reason(branch.id, fixed_today, "DINNER") is None
            assert session_closed_reason(branch.id, fixed_today, "LUNCH") is not None

        # 5. Future date but DailyOrder is locked
        future_date = fixed_today + timedelta(days=3)
        daily_order = DailyOrder(
            branch_id=branch.id,
            order_date=future_date,
            order_number=f"DO-TEST-{uuid4().hex[:6]}",
            status="LOCKED",
            is_locked=True,
            created_by=user.id,
        )
        db.session.add(daily_order)
        db.session.flush()

        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today), \
             patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 6, 9, 0)):
            reason = session_closed_reason(branch.id, future_date, "LUNCH")
            assert reason is not None
            assert "sudah dikunci oleh dapur" in reason

            # Unlocked date in future
            unlocked_future = fixed_today + timedelta(days=4)
            assert session_closed_reason(branch.id, unlocked_future, "LUNCH") is None


def test_create_draft_rejected_when_session_closed(app):
    with app.app_context():
        user, branch, client, mandor, location = _setup_fixtures("SESS2")
        fixed_today = date(2026, 10, 6)

        form = {
            "order_date": fixed_today.isoformat(),
            "meal_type": "LUNCH",
            "portion_qty": "5",
            "delivery_location_id": str(location.id),
            "idempotency_key": uuid4().hex,
        }

        # Mock time to 11:00 (after 10:00 cutoff)
        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today), \
             patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 6, 11, 0)):
            draft, created, error = create_portal_order_draft(user, form)
            assert draft is None
            assert error is not None
            assert "Batas waktu pemesanan untuk Makan Siang hari ini sudah lewat" in error

        # Mock time to 09:00 (before cutoff) -> accepted
        form["idempotency_key"] = uuid4().hex
        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today), \
             patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 6, 9, 0)):
            draft, created, error = create_portal_order_draft(user, form)
            assert error is None
            assert draft is not None
            assert draft.meal_type == "LUNCH"


def test_upload_proof_rejected_when_session_closed(app, tmp_path):
    app.config["DIGITAL_ATTACHMENT_UPLOAD_DIR"] = str(tmp_path)
    with app.app_context():
        user, branch, client, mandor, location = _setup_fixtures("SESS3")
        fixed_today = date(2026, 10, 6)

        # Create draft for today LUNCH
        draft = PortalOrderDraft(
            user_id=user.id,
            branch_id=branch.id,
            client_id=client.id,
            mandor_id=mandor.id,
            delivery_location_id=location.id,
            order_date=fixed_today,
            meal_type="LUNCH",
            portion_qty=5,
            price_per_portion=Decimal("25000"),
            delivery_fee=Decimal("0"),
            idempotency_key=uuid4().hex,
            status="PENDING_ADMIN_CONFIRMATION",
        )
        db.session.add(draft)
        db.session.flush()

        # At 10:30 WIB (past cutoff) -> upload proof should be rejected
        with patch("app.services.portal_order_draft_service.today_wib", return_value=fixed_today), \
             patch("app.services.portal_order_draft_service.now_wib", return_value=datetime(2026, 10, 6, 10, 30)):
            with pytest.raises(PortalPaymentProofError) as exc_info:
                upload_portal_order_draft_payment_proof(
                    user,
                    draft_id=draft.id,
                    file_storage=_file_storage("bukti.pdf"),
                    claimed_amount="125000",
                    sender_name="Pengirim Sesi",
                )
            assert "Pesanan ini sudah lewat batas waktu dan tidak bisa diproses. Hubungi admin." in str(exc_info.value)
