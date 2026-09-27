# Split from app.services.manual_backfill_billing_service.
import sys

from app.services.manual_backfill_billing_service import *  # noqa: F401,F403
from app.utils.terms import T


def _root_attr(name, fallback):
    root = sys.modules.get("app.services.manual_backfill_billing_service")
    return getattr(root, name, fallback)

def _clean_text(value):
    return str(value or "").strip()


def _normalize_bill_to_type(value):
    normalized = _clean_text(value).upper()
    normalized = BILL_TO_ALIASES.get(normalized, normalized)
    if normalized not in FLEXIBLE_BILL_TO_TYPES:
        raise ManualBackfillBillingError("Tipe pihak ditagih tidak valid.")
    return normalized


def _normalize_party_name(value):
    return " ".join(_clean_text(value).lower().split())


def _infer_bill_to_type(value=None, mandor_id=None, client_id=None, name=None):
    """Normalize bill-to type while keeping older test/data objects compatible.

    Tahap 10 stored manual/realtime invoices as MANDOR or CLIENT. Tahap 10.5
    stores manual backfill batches with the wider type set. For duplicate guard
    and lightweight unit fakes, infer the old mandor/client meaning when the type
    field is absent but ids are present.
    """
    raw = _clean_text(value)
    if raw:
        return _normalize_bill_to_type(raw)
    if mandor_id:
        return BILL_TO_MANDOR_EXISTING
    if client_id:
        return BILL_TO_CLIENT_EXISTING
    if _clean_text(name):
        return BILL_TO_CLIENT_LAIN
    return None


def _legacy_invoice_bill_to_type(value):
    normalized = _normalize_bill_to_type(value or BILL_TO_MANDOR_EXISTING)
    if normalized == BILL_TO_MANDOR_EXISTING:
        return "MANDOR"
    if normalized == BILL_TO_CLIENT_EXISTING:
        return "CLIENT"
    return normalized


def _bill_to_display_label(value):
    mapping = {
        BILL_TO_MANDOR_EXISTING: f"{T.sub_client} existing",
        BILL_TO_CLIENT_EXISTING: f"{T.client} existing",
        BILL_TO_KELOMPOK: "Kelompok",
        BILL_TO_PERORANGAN: "Perorangan",
        BILL_TO_CLIENT_LAIN: f"{T.client} lain",
    }
    return mapping.get(_clean_text(value).upper(), _clean_text(value) or "-")


def _resolve_manual_backfill_bill_to(
    *,
    branch_id,
    bill_to_type=None,
    mandor_id=None,
    client_id=None,
    bill_to_name_snapshot=None,
    bill_to_phone_snapshot=None,
    bill_to_address_snapshot=None,
    bill_to_notes=None,
):
    bill_to_type = _normalize_bill_to_type(bill_to_type or BILL_TO_MANDOR_EXISTING)
    mandor = None
    client = None

    if bill_to_type == BILL_TO_MANDOR_EXISTING:
        MandorModel = _root_attr("Mandor", Mandor)
        try:
            mandor_id = int(mandor_id)
        except (TypeError, ValueError):
            raise ManualBackfillBillingError(f"{T.sub_client} existing wajib dipilih.")
        mandor = MandorModel.query.filter_by(id=mandor_id, branch_id=branch_id, is_active=True).first()
        if not mandor:
            raise ManualBackfillBillingError(f"{T.sub_client}/PIC lapangan tidak ditemukan atau nonaktif.")
        client = getattr(mandor, "client", None)
        return {
            "bill_to_type": bill_to_type,
            "mandor": mandor,
            "client": client,
            "mandor_id": getattr(mandor, "id", None),
            "client_id": getattr(client, "id", None) or getattr(mandor, "client_id", None),
            "bill_to_name_snapshot": _clean_text(bill_to_name_snapshot) or _clean_text(getattr(mandor, "name", "")),
            "bill_to_phone_snapshot": _clean_text(bill_to_phone_snapshot) or _clean_text(getattr(mandor, "phone", "")),
            "bill_to_address_snapshot": _clean_text(bill_to_address_snapshot),
            "bill_to_notes": _clean_text(bill_to_notes),
        }

    if bill_to_type == BILL_TO_CLIENT_EXISTING:
        ClientModel = _root_attr("Client", Client)
        try:
            client_id = int(client_id)
        except (TypeError, ValueError):
            raise ManualBackfillBillingError(f"{T.client} existing wajib dipilih.")
        client = ClientModel.query.filter_by(id=client_id, is_active=True).first()
        if not client:
            raise ManualBackfillBillingError(f"{T.client} tidak ditemukan atau nonaktif.")
        return {
            "bill_to_type": bill_to_type,
            "mandor": None,
            "client": client,
            "mandor_id": None,
            "client_id": getattr(client, "id", None),
            "bill_to_name_snapshot": _clean_text(bill_to_name_snapshot) or _clean_text(getattr(client, "name", "")),
            "bill_to_phone_snapshot": _clean_text(bill_to_phone_snapshot) or _clean_text(getattr(client, "phone", "")),
            "bill_to_address_snapshot": _clean_text(bill_to_address_snapshot) or _clean_text(getattr(client, "address", "")),
            "bill_to_notes": _clean_text(bill_to_notes),
        }

    bill_to_name_snapshot = _clean_text(bill_to_name_snapshot)
    if not bill_to_name_snapshot:
        raise ManualBackfillBillingError("Nama pihak ditagih wajib diisi untuk pihak bebas.")
    return {
        "bill_to_type": bill_to_type,
        "mandor": None,
        "client": None,
        "mandor_id": None,
        "client_id": None,
        "bill_to_name_snapshot": bill_to_name_snapshot,
        "bill_to_phone_snapshot": _clean_text(bill_to_phone_snapshot),
        "bill_to_address_snapshot": _clean_text(bill_to_address_snapshot),
        "bill_to_notes": _clean_text(bill_to_notes),
    }
