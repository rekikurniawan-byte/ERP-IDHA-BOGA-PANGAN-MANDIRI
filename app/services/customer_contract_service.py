from __future__ import annotations

from datetime import date

from app.extensions import db
from app.models.contract import CustomerContract
from app.models.master import Client, ClientPic
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.business_logic_guard_service import decimal_money
from app.utils.terms import T


CONTRACT_STATUS_DRAFT = "DRAFT"
CONTRACT_STATUS_ACTIVE = "ACTIVE"
CONTRACT_STATUS_EXPIRED = "EXPIRED"
CONTRACT_STATUS_TERMINATED = "TERMINATED"
CONTRACT_STATUS_SUPERSEDED = "SUPERSEDED"


class CustomerContractError(ValueError):
    pass


def generate_customer_contract_number(contract_date: date) -> str:
    prefix = f"CC-{contract_date.strftime('%Y%m%d')}"
    counter = CustomerContract.query.filter(CustomerContract.contract_number.like(f"{prefix}-%")).count() + 1
    while True:
        number = f"{prefix}-{counter:03d}"
        if not CustomerContract.query.filter_by(contract_number=number).first():
            return number
        counter += 1


def create_customer_contract(
    *,
    branch_id: int,
    client_id: int,
    client_pic_id: int | None,
    title: str,
    start_date: date,
    end_date: date,
    payment_terms: str,
    credit_limit,
    created_by: int,
    notes: str | None = None,
    status: str = CONTRACT_STATUS_DRAFT,
    commit: bool = True,
) -> CustomerContract:
    _assert_valid_contract_dates(start_date, end_date)
    _assert_valid_status(status, allowed={CONTRACT_STATUS_DRAFT, CONTRACT_STATUS_ACTIVE})
    _assert_client_scope(branch_id, client_id, client_pic_id)

    contract = CustomerContract(
        branch_id=branch_id,
        client_id=client_id,
        client_pic_id=client_pic_id,
        contract_number=generate_customer_contract_number(start_date),
        title=_required_text(title, "Judul kontrak"),
        start_date=start_date,
        end_date=end_date,
        payment_terms=_required_text(payment_terms, "Termin pembayaran"),
        credit_limit=decimal_money(credit_limit, label="Limit kredit"),
        status=status,
        version_no=1,
        notes=_optional_text(notes),
        created_by=created_by,
    )

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_CREATE",
            description="Create customer contract.",
            reference_type="customer_contracts",
            user_id=created_by,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"client_id": client_id, "status": status},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        db.session.add(contract)
        db.session.flush()
        record_audit_log(
            module="CONTRACT",
            event_type="CUSTOMER_CONTRACT_CREATED",
            action="CREATE",
            table_name="customer_contracts",
            record_id=contract.id,
            description=f"Kontrak customer dibuat: {contract.contract_number}.",
            metadata={"client_id": client_id, "status": status, "credit_limit": str(contract.credit_limit)},
            user_id=created_by,
            branch_id=branch_id,
            commit=False,
        )

    return contract


def activate_customer_contract(contract_id: int, *, branch_id: int, updated_by: int, commit: bool = True) -> CustomerContract:
    contract = _get_contract_or_raise(contract_id, branch_id)
    if contract.status != CONTRACT_STATUS_DRAFT:
        raise CustomerContractError("Hanya kontrak DRAFT yang bisa diaktifkan.")
    return _set_contract_status(contract, CONTRACT_STATUS_ACTIVE, updated_by=updated_by, commit=commit)


def renew_customer_contract(
    contract_id: int,
    *,
    branch_id: int,
    start_date: date,
    end_date: date,
    payment_terms: str | None = None,
    credit_limit=None,
    created_by: int,
    notes: str | None = None,
    commit: bool = True,
) -> CustomerContract:
    old_contract = _get_contract_or_raise(contract_id, branch_id)
    if old_contract.status not in {CONTRACT_STATUS_ACTIVE, CONTRACT_STATUS_EXPIRED}:
        raise CustomerContractError("Hanya kontrak ACTIVE/EXPIRED yang bisa diperpanjang.")
    _assert_valid_contract_dates(start_date, end_date)

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_RENEW",
            description=f"Renew customer contract {old_contract.contract_number}.",
            reference_type="customer_contracts",
            reference_id=old_contract.id,
            user_id=created_by,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"old_contract_id": old_contract.id},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        old_contract.status = CONTRACT_STATUS_SUPERSEDED
        old_contract.updated_by = created_by
        new_contract = CustomerContract(
            branch_id=old_contract.branch_id,
            client_id=old_contract.client_id,
            client_pic_id=old_contract.client_pic_id,
            parent_contract_id=old_contract.id,
            contract_number=generate_customer_contract_number(start_date),
            title=old_contract.title,
            start_date=start_date,
            end_date=end_date,
            payment_terms=_required_text(payment_terms if payment_terms is not None else old_contract.payment_terms, "Termin pembayaran"),
            credit_limit=decimal_money(credit_limit if credit_limit is not None else old_contract.credit_limit, label="Limit kredit"),
            status=CONTRACT_STATUS_ACTIVE,
            version_no=(old_contract.version_no or 1) + 1,
            notes=_optional_text(notes),
            created_by=created_by,
        )
        db.session.add(new_contract)
        db.session.flush()
        record_audit_log(
            module="CONTRACT",
            event_type="CUSTOMER_CONTRACT_RENEWED",
            action="CREATE",
            table_name="customer_contracts",
            record_id=new_contract.id,
            description=f"Kontrak customer diperpanjang: {old_contract.contract_number} -> {new_contract.contract_number}.",
            metadata={"old_contract_id": old_contract.id, "new_contract_id": new_contract.id},
            user_id=created_by,
            branch_id=branch_id,
            commit=False,
        )

    return new_contract


def expire_due_customer_contracts(*, branch_id: int, today: date, updated_by: int, commit: bool = True) -> list[CustomerContract]:
    contracts = CustomerContract.query.filter(
        CustomerContract.branch_id == branch_id,
        CustomerContract.status == CONTRACT_STATUS_ACTIVE,
        CustomerContract.end_date < today,
    ).order_by(CustomerContract.end_date.asc(), CustomerContract.id.asc()).all()

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_EXPIRE_DUE",
            description="Expire due customer contracts.",
            reference_type="customer_contracts",
            user_id=updated_by,
            branch_id=branch_id,
            severity="LOW",
            metadata={"count": len(contracts)},
        )
        if commit and contracts
        else _NullContext()
    )

    with boundary:
        for contract in contracts:
            contract.status = CONTRACT_STATUS_EXPIRED
            contract.updated_by = updated_by
    return contracts


def get_customer_contract(contract_id: int, *, branch_id: int) -> CustomerContract | None:
    return CustomerContract.query.filter_by(id=contract_id, branch_id=branch_id).first()


def list_customer_contracts(branch_id: int, *, status: str = "ALL", client_id: int | None = None) -> list[CustomerContract]:
    query = CustomerContract.query.filter_by(branch_id=branch_id)
    if status and status != "ALL":
        query = query.filter(CustomerContract.status == status)
    if client_id:
        query = query.filter(CustomerContract.client_id == client_id)
    return query.order_by(CustomerContract.start_date.desc(), CustomerContract.id.desc()).all()


def _set_contract_status(contract: CustomerContract, status: str, *, updated_by: int, commit: bool) -> CustomerContract:
    _assert_valid_status(status)
    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action=f"CUSTOMER_CONTRACT_{status}",
            description=f"Set customer contract {contract.contract_number} status to {status}.",
            reference_type="customer_contracts",
            reference_id=contract.id,
            user_id=updated_by,
            branch_id=contract.branch_id,
            severity="MEDIUM",
            metadata={"contract_number": contract.contract_number, "status": status},
        )
        if commit
        else _NullContext()
    )
    with boundary:
        contract.status = status
        contract.updated_by = updated_by
        db.session.flush()
    return contract


def _get_contract_or_raise(contract_id: int, branch_id: int) -> CustomerContract:
    contract = get_customer_contract(contract_id, branch_id=branch_id)
    if not contract:
        raise CustomerContractError("Kontrak customer tidak ditemukan.")
    return contract


def _assert_client_scope(branch_id: int, client_id: int, client_pic_id: int | None) -> None:
    client = Client.query.filter_by(id=client_id).first()
    if not client:
        raise CustomerContractError(f"{T.client} kontrak tidak ditemukan.")
    if client_pic_id:
        pic = ClientPic.query.filter_by(id=client_pic_id, client_id=client_id).first()
        if not pic:
            raise CustomerContractError(f"PIC kontrak tidak sesuai {T.client_lower}.")
    if branch_id is None:
        raise CustomerContractError("Branch kontrak wajib diisi.")


def _assert_valid_contract_dates(start_date: date, end_date: date) -> None:
    if not start_date or not end_date:
        raise CustomerContractError("Tanggal mulai dan selesai kontrak wajib diisi.")
    if end_date < start_date:
        raise CustomerContractError("Tanggal selesai kontrak tidak boleh sebelum tanggal mulai.")


def _assert_valid_status(status: str, allowed: set[str] | None = None) -> None:
    allowed = allowed or {
        CONTRACT_STATUS_DRAFT,
        CONTRACT_STATUS_ACTIVE,
        CONTRACT_STATUS_EXPIRED,
        CONTRACT_STATUS_TERMINATED,
        CONTRACT_STATUS_SUPERSEDED,
    }
    if status not in allowed:
        raise CustomerContractError("Status kontrak tidak valid.")


def _required_text(value: object, label: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise CustomerContractError(f"{label} wajib diisi.")
    return text


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False
