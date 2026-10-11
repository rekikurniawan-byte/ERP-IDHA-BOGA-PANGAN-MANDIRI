"""Siklus hidup kontrak pelanggan: kedaluwarsa otomatis dan pengingatnya.

Keputusan owner 2026-09-28:
- kontrak yang lewat tanggal berakhir otomatis Kedaluwarsa (sapuan harian);
- pengingat H-30, naik jadi mendesak di H-7;
- setelah kedaluwarsa, invoice baru memakai termin bawaan (7 hari) dan limit
  kontrak tidak berlaku -- keduanya otomatis karena hanya kontrak ACTIVE yang
  dibaca (credit_control_service.active_contract);
- pesanan baru dari PT yang kontraknya sudah berakhir perlu persetujuan OWNER
  sampai kontraknya diperpanjang.

Dijalankan bersama penyapu kredit harian (credit_account_service), jadi satu
jadwal dan satu kunci untuk semua pekerjaan harian. Tidak commit.
"""
from datetime import date

from app.models.contract import CustomerContract
from app.utils.clock import today_wib
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.customer_contract_expiry_notification_service import (
    CONTRACT_EXPIRY_ACTION_URL,
    generate_contract_expiry_notifications,
)
from app.services.customer_contract_service import (
    CONTRACT_STATUS_ACTIVE,
    CONTRACT_STATUS_EXPIRED,
    expire_due_customer_contracts,
)
from app.services.notification_service import create_or_update_notification, resolve_generated_notifications_not_in
from app.utils.terms import T

LAPSED_KEY_PREFIX = "contract-lapsed"


def lapsed_contract(branch_id, client_id):
    """Kontrak terakhir yang sudah berakhir, kalau client ini tidak punya kontrak aktif lagi.

    None kalau client punya kontrak aktif, atau memang belum pernah berkontrak
    (pelanggan tanpa kontrak mengikuti aturan kredit biasa).
    """
    if not branch_id or not client_id:
        return None
    base = CustomerContract.query.filter(
        CustomerContract.branch_id == branch_id,
        CustomerContract.client_id == client_id,
    )
    if base.filter(CustomerContract.status == CONTRACT_STATUS_ACTIVE).first() is not None:
        return None
    return (
        base.filter(CustomerContract.status == CONTRACT_STATUS_EXPIRED)
        .order_by(CustomerContract.end_date.desc(), CustomerContract.id.desc())
        .first()
    )


def lapsed_contract_message(contract):
    client_name = getattr(contract.client, "name", None) or T.client
    return (
        f"Kontrak {client_name} ({contract.contract_number}) berakhir "
        f"{contract.end_date.strftime('%d-%m-%Y')} dan belum diperpanjang."
    )


def sweep_contracts(branch_id, today, actor_id=None):
    """Pekerjaan kontrak harian untuk satu cabang. Tidak commit."""
    expired = expire_due_customer_contracts(branch_id=branch_id, today=today, updated_by=actor_id, commit=False)
    for contract in expired:
        record_audit_log(
            module="CONTRACT",
            event_type="CUSTOMER_CONTRACT_EXPIRED",
            action="UPDATE",
            table_name="customer_contracts",
            record_id=contract.id,
            description=f"Kontrak {contract.contract_number} berakhir {contract.end_date.isoformat()} dan otomatis Kedaluwarsa.",
            metadata={"client_id": contract.client_id, "end_date": contract.end_date.isoformat()},
            user_id=actor_id,
            branch_id=branch_id,
            commit=False,
        )
    reminders = generate_contract_expiry_notifications(
        branch_id=branch_id, as_of_date=today, due_days=30, generated_by=actor_id, commit=False
    )
    lapsed = _lapsed_notifications(branch_id)
    return {"expired": len(expired), "reminders": reminders.get("active", 0), "lapsed": lapsed}


def run_contract_sweep_now(branch_id, actor_id=None, today=None):
    """Tombol "Periksa Kontrak Sekarang", juga dipanggil sesudah perpanjangan
    supaya pemberitahuan "kontrak berakhir" langsung hilang. Commit."""
    today = today or today_wib()
    with atomic_business_action(
        module="CONTRACT",
        action="CUSTOMER_CONTRACT_SWEEP",
        description="Periksa kontrak: kedaluwarsa otomatis dan pengingat.",
        reference_type="customer_contracts",
        user_id=actor_id,
        branch_id=branch_id,
        severity="LOW",
    ):
        return sweep_contracts(branch_id, today, actor_id=actor_id)


def _lapsed_notifications(branch_id):
    """Satu pemberitahuan mendesak per client yang kontraknya berakhir dan belum diperpanjang."""
    prefix = f"{LAPSED_KEY_PREFIX}:{int(branch_id)}:"
    client_ids = {
        row.client_id
        for row in CustomerContract.query.filter(
            CustomerContract.branch_id == branch_id,
            CustomerContract.status == CONTRACT_STATUS_EXPIRED,
        ).all()
        if row.client_id
    }
    keys = []
    for client_id in sorted(client_ids):
        contract = lapsed_contract(branch_id, client_id)
        if contract is None:
            continue
        key = f"{prefix}{client_id}"
        keys.append(key)
        create_or_update_notification(
            branch_id=branch_id,
            notification_type="CUSTOMER_CONTRACT_LAPSED",
            title=f"Kontrak {getattr(contract.client, 'name', '-')} sudah berakhir",
            message=(
                f"{lapsed_contract_message(contract)} Termin kembali ke bawaan dan pesanan baru perlu "
                f"persetujuan OWNER. Perpanjang di Pelanggan > Kontrak."
            ),
            target_role="ADMIN",
            priority="CRITICAL",
            reference_type="CUSTOMER_CONTRACT",
            reference_id=contract.id,
            action_url=CONTRACT_EXPIRY_ACTION_URL,
            due_date=contract.end_date,
            generated_key=key,
            metadata={"client_id": client_id, "contract_id": contract.id},
            status="UNREAD",
            commit=False,
        )
    resolve_generated_notifications_not_in(branch_id=branch_id, generated_keys=keys, key_prefix=prefix, commit=False)
    return len(keys)
