from datetime import date
from decimal import Decimal
from uuid import uuid4

from app.extensions import db
from app.models.master import BranchSetting
from app.services.portal_mapping_service import PRINCIPAL_CLIENT, PRINCIPAL_MANDOR
from app.services.portal_payment_instruction_service import build_portal_payment_instruction
from app.services.user_management_service import ROLE_PORTAL_CLIENT, ROLE_PORTAL_CUSTOMER, ROLE_PORTAL_SUBCLIENT
from tests.test_portal_financial_visibility_service import (
    _create_client_family,
    _create_invoice,
    _create_mapping,
    _create_user,
)


def _set_branch_setting(branch_id, key, value):
    setting = BranchSetting(branch_id=branch_id, setting_key=key, setting_value=value)
    db.session.add(setting)
    db.session.flush()
    return setting


def test_portal_payment_instruction_returns_static_bank_and_qris_for_owned_invoice(app, monkeypatch):
    monkeypatch.setattr(db.session, "commit", lambda: (_ for _ in ()).throw(AssertionError("instruction must not commit")))
    monkeypatch.setattr(db.session, "rollback", lambda: (_ for _ in ()).throw(AssertionError("instruction must not rollback")))

    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, pic, mandor, _ = _create_client_family(user.branch, "PAYINST")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            _set_branch_setting(user.branch_id, "payment_bank_name", "BCA")
            _set_branch_setting(user.branch_id, "payment_account_number", "1234567890")
            _set_branch_setting(user.branch_id, "payment_account_name", "PT Idha Boga")
            _set_branch_setting(user.branch_id, "payment_qris_label", "QRIS PT Idha Boga")
            _set_branch_setting(user.branch_id, "payment_qris_image_url", "/uploads/qris-static.png")
            _set_branch_setting(user.branch_id, "payment_qris_note", "Gunakan nominal sesuai sisa tagihan.")
            invoice = _create_invoice(
                user,
                invoice_number=f"T-PINST-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
                client_pic=pic,
                total="125000",
                paid="25000",
                remaining="100000",
                status="PARTIAL",
            )

            instruction = build_portal_payment_instruction(user, invoice_id=invoice.id)

            assert instruction["allowed"] is True
            assert instruction["payable"] is True
            assert instruction["amount_due"] == Decimal("100000")
            assert instruction["mutation_allowed"] is False
            assert instruction["bank_transfer"]["available"] is True
            assert instruction["bank_transfer"]["bank_name"] == "BCA"
            assert instruction["bank_transfer"]["account_number"] == "1234567890"
            assert instruction["qris"]["available"] is True
            assert instruction["qris"]["label"] == "QRIS PT Idha Boga"
            assert "upload" not in instruction
            assert "payment_id" not in instruction
        finally:
            transaction.rollback()


def test_portal_payment_instruction_rejects_invoice_outside_user_ownership(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_SUBCLIENT)
            client, _, owned_mandor, _ = _create_client_family(user.branch, "OWNMANDOR")
            _, _, other_mandor, _ = _create_client_family(user.branch, "OTHMANDOR")
            _create_mapping(user, PRINCIPAL_MANDOR, mandor=owned_mandor)
            other_invoice = _create_invoice(
                user,
                invoice_number=f"T-PINST-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=other_mandor,
            )

            instruction = build_portal_payment_instruction(user, invoice_id=other_invoice.id)

            assert instruction["allowed"] is False
            assert instruction["invoice"] is None
            assert instruction["payable"] is False
            assert instruction["amount_due"] == Decimal("0")
        finally:
            transaction.rollback()


def test_portal_customer_payment_instruction_is_blocked_even_with_mapping(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CUSTOMER)
            client, _, mandor, _ = _create_client_family(user.branch, "CUSTOMERPINST")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            invoice = _create_invoice(
                user,
                invoice_number=f"T-PINST-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
            )

            instruction = build_portal_payment_instruction(user, invoice_id=invoice.id)

            assert instruction["allowed"] is False
            assert instruction["scope_mode"] == "PORTAL_CUSTOMER_FINANCIAL_BLOCKED"
            assert instruction["payable"] is False
        finally:
            transaction.rollback()


def test_cancelled_invoice_instruction_is_visible_but_not_payable(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, _, mandor, _ = _create_client_family(user.branch, "CANCELPINST")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            invoice = _create_invoice(
                user,
                invoice_number=f"T-PINST-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
                total="50000",
                paid="0",
                remaining="50000",
                status="CANCELLED",
            )

            instruction = build_portal_payment_instruction(user, invoice_id=invoice.id)

            assert instruction["allowed"] is True
            assert instruction["invoice"]["status"] == "CANCELLED"
            assert instruction["payable"] is False
            assert instruction["amount_due"] == Decimal("0")
        finally:
            transaction.rollback()


def test_payment_instruction_uses_invoice_bank_snapshot_before_live_settings(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user = _create_user(ROLE_PORTAL_CLIENT)
            client, _, mandor, _ = _create_client_family(user.branch, "SNAPPINST")
            _create_mapping(user, PRINCIPAL_CLIENT, client=client)
            _set_branch_setting(user.branch_id, "payment_bank_name", "LIVE BANK")
            _set_branch_setting(user.branch_id, "payment_account_number", "999")
            _set_branch_setting(user.branch_id, "payment_account_name", "LIVE ACCOUNT")
            invoice = _create_invoice(
                user,
                invoice_number=f"T-PINST-INV-{uuid4().hex[:10]}",
                client=client,
                mandor=mandor,
            )
            invoice.company_bank_name_snapshot = "SNAP BANK"
            invoice.company_bank_account_number_snapshot = "111"
            invoice.company_bank_account_name_snapshot = "SNAP ACCOUNT"
            db.session.flush()

            instruction = build_portal_payment_instruction(user, invoice_id=invoice.id)

            assert instruction["bank_transfer"]["bank_name"] == "SNAP BANK"
            assert instruction["bank_transfer"]["account_number"] == "111"
            assert instruction["bank_transfer"]["account_name"] == "SNAP ACCOUNT"
        finally:
            transaction.rollback()
