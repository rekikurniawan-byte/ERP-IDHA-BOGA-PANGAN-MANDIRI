from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any

from app.extensions import db
from app.models.contract import (
    COURT_PANGKALAN_BALAI,
    ContractHoliday,
    CustomerContract,
)
from app.models.master import Client, ClientPic
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.business_logic_guard_service import decimal_money
from app.utils.roles import effective_role
from app.utils.terms import T


CONTRACT_STATUS_DRAFT = "DRAFT"
CONTRACT_STATUS_ACTIVE = "ACTIVE"
CONTRACT_STATUS_EXPIRED = "EXPIRED"
CONTRACT_STATUS_TERMINATED = "TERMINATED"
CONTRACT_STATUS_SUPERSEDED = "SUPERSEDED"


class CustomerContractError(ValueError):
    pass


def _parse_and_validate_time(value: Any, default_value: time, label: str) -> time:
    if value is None or value == "":
        return default_value
    if isinstance(value, time):
        t = value
    elif isinstance(value, str):
        cleaned = value.strip().replace(".", ":")
        try:
            parts = [int(p) for p in cleaned.split(":") if p.strip()]
            if len(parts) == 2:
                t = time(parts[0], parts[1])
            elif len(parts) == 3:
                t = time(parts[0], parts[1], parts[2])
            else:
                raise ValueError()
        except Exception:
            raise CustomerContractError(f"Format {label} tidak valid: {value}")
    else:
        raise CustomerContractError(f"Format {label} tidak valid: {value}")

    if t < time(5, 0) or t > time(20, 0):
        raise CustomerContractError(f"{label} harus di antara 05:00 dan 20:00 WIB.")
    return t


def _normalize_weekly_holidays(weekly_holidays: Any) -> str:
    if not weekly_holidays:
        return ""
    if isinstance(weekly_holidays, (list, tuple, set)):
        tokens = [str(x).strip() for x in weekly_holidays if str(x).strip()]
    else:
        tokens = [t.strip() for t in str(weekly_holidays).split(",") if t.strip()]
    for token in tokens:
        if not token.isdigit() or int(token) < 1 or int(token) > 7:
            raise CustomerContractError("Hari libur rutin harus berupa angka hari ISO 1–7 (Senin=1, Minggu=7).")
    unique_sorted = sorted({int(x) for x in tokens})
    return ",".join(str(x) for x in unique_sorted)


def _validate_contract_rules(
    lunch_time: time,
    dinner_time: time,
    due_days: int,
    tazir_amount: Decimal,
    default_billing_mode: str,
    billing_cycle: str,
    dispute_court: str,
    weekly_holidays: str | None,
) -> None:
    if lunch_time >= dinner_time:
        raise CustomerContractError("Jam lock siang harus lebih awal dari jam lock malam.")
    if due_days < 1 or due_days > 60:
        raise CustomerContractError("Jatuh tempo harus antara 1 sampai 60 hari.")
    if tazir_amount < 0:
        raise CustomerContractError("Nominal ta'zir tidak boleh negatif.")
    if default_billing_mode not in ("VIA_CLIENT", "DIRECT", "CASH"):
        raise CustomerContractError("Pihak yang ditagih tidak valid.")
    if billing_cycle not in ("WEEKLY", "BIWEEKLY", "MONTHLY"):
        raise CustomerContractError("Siklus tagihan tidak valid.")
    if dispute_court not in ("PN_PANGKALAN_BALAI", "PN_KAYUAGUNG"):
        raise CustomerContractError("Pilihan pengadilan sengketa tidak valid.")
    if weekly_holidays:
        _normalize_weekly_holidays(weekly_holidays)


def _save_contract_holidays(
    contract: CustomerContract,
    holidays: list[Any] | None,
    start_date: date,
    end_date: date,
) -> None:
    if holidays is None:
        return
    contract.holidays.clear()
    for item in holidays:
        if isinstance(item, (date, datetime)):
            h_date = item if isinstance(item, date) else item.date()
            note = None
        elif isinstance(item, dict):
            raw_d = item.get("holiday_date")
            if isinstance(raw_d, str):
                h_date = date.fromisoformat(raw_d.strip())
            elif isinstance(raw_d, date):
                h_date = raw_d
            else:
                continue
            note = item.get("note")
        elif isinstance(item, str):
            h_date = date.fromisoformat(item.strip())
            note = None
        else:
            continue

        if h_date < start_date or h_date > end_date:
            raise CustomerContractError(
                f"Tanggal libur khusus {h_date.strftime('%d-%m-%Y')} berada di luar masa kontrak ({start_date.strftime('%d-%m-%Y')} s/d {end_date.strftime('%d-%m-%Y')})."
            )
        contract.holidays.append(ContractHoliday(holiday_date=h_date, note=note))


def _save_subclient_billing_modes(branch_id: int, modes: dict[int, str] | None) -> None:
    if not modes:
        return
    from app.models.credit import BILLING_CASH, BILLING_DIRECT, BILLING_VIA_CLIENT, PARTY_MANDOR
    from app.services.credit_control_service import get_or_create_credit_account

    for mandor_id, mode_val in modes.items():
        mode_clean = str(mode_val or "").strip().upper()
        if mode_clean in (BILLING_VIA_CLIENT, BILLING_DIRECT, BILLING_CASH):
            acc = get_or_create_credit_account(branch_id, PARTY_MANDOR, int(mandor_id))
            acc.billing_mode = mode_clean


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
    client_pic_id: int | None = None,
    title: str,
    start_date: date,
    end_date: date,
    payment_terms: str,
    credit_limit=0,
    created_by: int,
    notes: str | None = None,
    status: str = CONTRACT_STATUS_DRAFT,
    lunch_lock_time: time | str | None = None,
    dinner_lock_time: time | str | None = None,
    weekly_holidays: str | None = None,
    default_billing_mode: str = "VIA_CLIENT",
    billing_cycle: str = "BIWEEKLY",
    billing_anchor_date: date | str | None = None,
    due_days: int = 7,
    dispute_court: str = COURT_PANGKALAN_BALAI,
    tazir_amount=0,
    holidays: list[Any] | None = None,
    subclient_billing_modes: dict[int, str] | None = None,
    commit: bool = True,
) -> CustomerContract:
    _assert_valid_contract_dates(start_date, end_date)
    _assert_valid_status(status, allowed={CONTRACT_STATUS_DRAFT, CONTRACT_STATUS_ACTIVE})
    _assert_client_scope(branch_id, client_id, client_pic_id)

    lunch_t = _parse_and_validate_time(lunch_lock_time, time(10, 0), "Jam lock siang")
    dinner_t = _parse_and_validate_time(dinner_lock_time, time(15, 0), "Jam lock malam")
    due_days_int = int(due_days) if due_days is not None else 7
    tazir_dec = Decimal(str(tazir_amount or 0))
    def_billing = str(default_billing_mode or "VIA_CLIENT").strip().upper()
    cycle = str(billing_cycle or "BIWEEKLY").strip().upper()
    court = str(dispute_court or COURT_PANGKALAN_BALAI).strip().upper()
    weekly_h = _normalize_weekly_holidays(weekly_holidays)

    _validate_contract_rules(
        lunch_t, dinner_t, due_days_int, tazir_dec, def_billing, cycle, court, weekly_h
    )

    if billing_anchor_date:
        if isinstance(billing_anchor_date, str):
            anchor_d = date.fromisoformat(billing_anchor_date.strip())
        else:
            anchor_d = billing_anchor_date
    else:
        anchor_d = start_date

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
        lunch_lock_time=lunch_t,
        dinner_lock_time=dinner_t,
        weekly_holidays=weekly_h,
        default_billing_mode=def_billing,
        billing_cycle=cycle,
        billing_anchor_date=anchor_d,
        due_days=due_days_int,
        dispute_court=court,
        tazir_amount=tazir_dec,
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

        _save_contract_holidays(contract, holidays, start_date, end_date)
        _save_subclient_billing_modes(branch_id, subclient_billing_modes)

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
            lunch_lock_time=old_contract.lunch_lock_time,
            dinner_lock_time=old_contract.dinner_lock_time,
            weekly_holidays=old_contract.weekly_holidays,
            default_billing_mode=old_contract.default_billing_mode,
            billing_cycle=old_contract.billing_cycle,
            billing_anchor_date=start_date,
            due_days=old_contract.due_days,
            dispute_court=old_contract.dispute_court,
            tazir_amount=old_contract.tazir_amount,
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


def update_customer_contract_rules(
    contract_id: int,
    *,
    branch_id: int,
    actor: Any,
    lunch_lock_time: time | str,
    dinner_lock_time: time | str,
    weekly_holidays: str | None = None,
    default_billing_mode: str = "VIA_CLIENT",
    billing_cycle: str = "BIWEEKLY",
    billing_anchor_date: date | str | None = None,
    due_days: int = 7,
    dispute_court: str = COURT_PANGKALAN_BALAI,
    tazir_amount=0,
    holidays: list[Any] | None = None,
    subclient_billing_modes: dict[int, str] | None = None,
    commit: bool = True,
) -> CustomerContract:
    actor_role = effective_role(getattr(actor, "role", None) if not isinstance(actor, str) else actor)
    if actor_role not in ("OWNER", "ADMIN"):
        raise CustomerContractError("Hanya OWNER dan ADMIN yang boleh mengubah pengaturan kontrak.")

    actor_id = getattr(actor, "id", None) if not isinstance(actor, (str, int)) else (actor if isinstance(actor, int) else None)
    contract = _get_contract_or_raise(contract_id, branch_id)

    lunch_t = _parse_and_validate_time(lunch_lock_time, time(10, 0), "Jam lock siang")
    dinner_t = _parse_and_validate_time(dinner_lock_time, time(15, 0), "Jam lock malam")
    due_days_int = int(due_days) if due_days is not None else 7
    tazir_dec = Decimal(str(tazir_amount or 0))
    def_billing = str(default_billing_mode or "VIA_CLIENT").strip().upper()
    cycle = str(billing_cycle or "BIWEEKLY").strip().upper()
    court = str(dispute_court or COURT_PANGKALAN_BALAI).strip().upper()
    weekly_h = _normalize_weekly_holidays(weekly_holidays)

    _validate_contract_rules(
        lunch_t, dinner_t, due_days_int, tazir_dec, def_billing, cycle, court, weekly_h
    )

    if billing_anchor_date:
        if isinstance(billing_anchor_date, str):
            anchor_d = date.fromisoformat(billing_anchor_date.strip())
        else:
            anchor_d = billing_anchor_date
    else:
        anchor_d = contract.start_date

    old_values = {
        "lunch_lock_time": contract.lunch_lock_time.strftime("%H:%M") if contract.lunch_lock_time else None,
        "dinner_lock_time": contract.dinner_lock_time.strftime("%H:%M") if contract.dinner_lock_time else None,
        "weekly_holidays": contract.weekly_holidays,
        "default_billing_mode": contract.default_billing_mode,
        "billing_cycle": contract.billing_cycle,
        "billing_anchor_date": contract.billing_anchor_date.isoformat() if contract.billing_anchor_date else None,
        "due_days": contract.due_days,
        "dispute_court": contract.dispute_court,
        "tazir_amount": str(contract.tazir_amount),
    }

    new_values = {
        "lunch_lock_time": lunch_t.strftime("%H:%M"),
        "dinner_lock_time": dinner_t.strftime("%H:%M"),
        "weekly_holidays": weekly_h,
        "default_billing_mode": def_billing,
        "billing_cycle": cycle,
        "billing_anchor_date": anchor_d.isoformat() if anchor_d else None,
        "due_days": due_days_int,
        "dispute_court": court,
        "tazir_amount": str(tazir_dec),
    }

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_RULES_UPDATE",
            description=f"Update aturan kontrak {contract.contract_number}.",
            reference_type="customer_contracts",
            reference_id=contract.id,
            user_id=actor_id,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"old_values": old_values, "new_values": new_values},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        contract.lunch_lock_time = lunch_t
        contract.dinner_lock_time = dinner_t
        contract.weekly_holidays = weekly_h
        contract.default_billing_mode = def_billing
        contract.billing_cycle = cycle
        contract.billing_anchor_date = anchor_d
        contract.due_days = due_days_int
        contract.dispute_court = court
        contract.tazir_amount = tazir_dec
        contract.updated_by = actor_id

        _save_contract_holidays(contract, holidays, contract.start_date, contract.end_date)
        _save_subclient_billing_modes(branch_id, subclient_billing_modes)

        db.session.flush()

        record_audit_log(
            module="CONTRACT",
            event_type="CUSTOMER_CONTRACT_RULES_UPDATED",
            action="UPDATE",
            table_name="customer_contracts",
            record_id=contract.id,
            description=f"Aturan kontrak diubah: {contract.contract_number}.",
            old_value=old_values,
            new_value=new_values,
            metadata={"old_values": old_values, "new_values": new_values},
            user_id=actor_id,
            branch_id=branch_id,
            commit=False,
        )

    return contract


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
