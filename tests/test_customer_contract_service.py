from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.extensions import db
from app.models.contract import CustomerContract
from app.services.customer_contract_service import (
    CONTRACT_STATUS_ACTIVE,
    CONTRACT_STATUS_DRAFT,
    CONTRACT_STATUS_EXPIRED,
    CONTRACT_STATUS_SUPERSEDED,
    CustomerContractError,
    activate_customer_contract,
    create_customer_contract,
    expire_due_customer_contracts,
    list_customer_contracts,
    renew_customer_contract,
)
from tests.test_portal_financial_visibility_service import _create_client_family, _create_user


def _contract_fixture():
    user = _create_user("ADMIN")
    client, pic, _, _ = _create_client_family(user.branch, "CONTRACT")
    return user, client, pic


def test_create_and_activate_customer_contract(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, pic = _contract_fixture()
            contract = create_customer_contract(
                branch_id=user.branch_id,
                client_id=client.id,
                client_pic_id=pic.id,
                title="Kontrak Catering PT QA",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=30),
                payment_terms="NET 14",
                credit_limit="2500000",
                created_by=user.id,
                commit=False,
            )

            assert contract.status == CONTRACT_STATUS_DRAFT
            assert contract.version_no == 1
            assert contract.credit_limit == Decimal("2500000.00")

            # Fase 9: kontrak baru aktif setelah surat kontraknya ditandatangani.
            import pytest

            from app.models.contract import DOC_STATUS_SIGNED
            from app.services.customer_contract_document_service import generate_contract_document
            from app.services.customer_contract_service import CustomerContractError

            with pytest.raises(CustomerContractError, match="ditandatangani"):
                activate_customer_contract(contract.id, branch_id=user.branch_id, updated_by=user.id, commit=False)
            document = generate_contract_document(
                contract_id=contract.id, branch_id=user.branch_id, created_by=user.id, commit=False
            )
            document.status = DOC_STATUS_SIGNED

            activate_customer_contract(contract.id, branch_id=user.branch_id, updated_by=user.id, commit=False)

            assert contract.status == CONTRACT_STATUS_ACTIVE
            assert list_customer_contracts(user.branch_id, status=CONTRACT_STATUS_ACTIVE)[0].id == contract.id
        finally:
            transaction.rollback()


def test_renew_customer_contract_supersedes_old_contract(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, pic = _contract_fixture()
            contract = create_customer_contract(
                branch_id=user.branch_id,
                client_id=client.id,
                client_pic_id=pic.id,
                title="Kontrak Renewal QA",
                start_date=date.today() - timedelta(days=30),
                end_date=date.today() + timedelta(days=1),
                payment_terms="NET 7",
                credit_limit="1000000",
                created_by=user.id,
                status=CONTRACT_STATUS_ACTIVE,
                commit=False,
            )

            renewed = renew_customer_contract(
                contract.id,
                branch_id=user.branch_id,
                start_date=date.today() + timedelta(days=2),
                end_date=date.today() + timedelta(days=60),
                payment_terms="NET 14",
                credit_limit="1500000",
                created_by=user.id,
                commit=False,
            )

            assert contract.status == CONTRACT_STATUS_SUPERSEDED
            assert renewed.parent_contract_id == contract.id
            assert renewed.version_no == 2
            assert renewed.status == CONTRACT_STATUS_ACTIVE
            assert renewed.credit_limit == Decimal("1500000.00")
        finally:
            transaction.rollback()


def test_expire_due_customer_contracts_marks_only_past_active(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, pic = _contract_fixture()
            past = create_customer_contract(
                branch_id=user.branch_id,
                client_id=client.id,
                client_pic_id=pic.id,
                title="Kontrak Expired QA",
                start_date=date.today() - timedelta(days=60),
                end_date=date.today() - timedelta(days=1),
                payment_terms="NET 7",
                credit_limit="1000000",
                created_by=user.id,
                status=CONTRACT_STATUS_ACTIVE,
                commit=False,
            )
            future = create_customer_contract(
                branch_id=user.branch_id,
                client_id=client.id,
                client_pic_id=pic.id,
                title="Kontrak Future QA",
                start_date=date.today(),
                end_date=date.today() + timedelta(days=30),
                payment_terms="NET 7",
                credit_limit="1000000",
                created_by=user.id,
                status=CONTRACT_STATUS_ACTIVE,
                commit=False,
            )

            expired = expire_due_customer_contracts(branch_id=user.branch_id, today=date.today(), updated_by=user.id, commit=False)

            assert [row.id for row in expired] == [past.id]
            assert past.status == CONTRACT_STATUS_EXPIRED
            assert future.status == CONTRACT_STATUS_ACTIVE
        finally:
            transaction.rollback()


def test_customer_contract_rejects_invalid_dates(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, pic = _contract_fixture()

            with pytest.raises(CustomerContractError):
                create_customer_contract(
                    branch_id=user.branch_id,
                    client_id=client.id,
                    client_pic_id=pic.id,
                    title="Invalid Date Contract",
                    start_date=date.today(),
                    end_date=date.today() - timedelta(days=1),
                    payment_terms="NET 7",
                    credit_limit="1000000",
                    created_by=user.id,
                    commit=False,
                )
        finally:
            transaction.rollback()


def test_customer_contract_rejects_pic_from_other_client(app):
    with app.app_context():
        transaction = db.session.begin_nested()
        try:
            user, client, _ = _contract_fixture()
            other_client, other_pic, _, _ = _create_client_family(user.branch, "CONTRACT-OTHER")

            with pytest.raises(CustomerContractError):
                create_customer_contract(
                    branch_id=user.branch_id,
                    client_id=client.id,
                    client_pic_id=other_pic.id,
                    title="Invalid PIC Contract",
                    start_date=date.today(),
                    end_date=date.today() + timedelta(days=30),
                    payment_terms="NET 7",
                    credit_limit="1000000",
                    created_by=user.id,
                    commit=False,
                )

            assert CustomerContract.query.filter_by(client_id=other_client.id).count() == 0
        finally:
            transaction.rollback()
