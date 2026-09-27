from app.models.master import Client, ClientPic, Mandor
from app.extensions import db
from app.services.company_settings_service import get_company_settings
from app.utils.terms import T


def clean_text(value):
    return str(value or "").strip()


def _run_in_transaction(action):
    try:
        result = action()
        db.session.commit()
        return result
    except Exception:
        db.session.rollback()
        raise


def get_active_client_pics(client_id):
    if not client_id:
        return []
    return ClientPic.query.filter_by(client_id=client_id, is_active=True).order_by(
        ClientPic.name.asc(),
        ClientPic.id.asc(),
    ).all()


def pick_default_client_pic(client_id):
    if not client_id:
        return None
    return ClientPic.query.filter_by(client_id=client_id, is_active=True).order_by(
        ClientPic.id.asc(),
    ).first()


def get_required_client_pic(client_id, client_pic_id=None):
    if not client_id:
        return None, f"{T.client} invoice belum valid."

    pic = None
    if client_pic_id:
        pic = ClientPic.query.filter_by(
            id=client_pic_id,
            client_id=client_id,
            is_active=True,
        ).first()
        if not pic:
            return None, f"PIC {T.client_lower} tidak valid / tidak aktif untuk {T.client_lower} ini."
    else:
        pic = pick_default_client_pic(client_id)

    if not pic:
        return None, f"{T.client} belum punya PIC resmi aktif. Tambahkan PIC {T.client_lower} dulu di Master {T.client}."

    return pic, None


def invoice_contact_snapshot(client, mandor, client_pic_id, bill_to_type):
    """Kontak yang dicetak di invoice, sebagai kolom snapshot siap pakai.

    Invoice untuk mandor yang ditagih langsung ditujukan ke mandor itu sendiri
    -- PT pemilik proyek tidak menjamin pembayarannya -- jadi kontaknya mandor,
    bukan PIC client, dan PIC client tidak diwajibkan. Invoice lain tetap
    wajib memakai PIC resmi client seperti sebelumnya.
    """
    if bill_to_type == "MANDOR" and mandor is not None:
        return {
            "client_pic_id": None,
            "client_pic_name_snapshot": mandor.name,
            "client_pic_position_snapshot": f"{T.sub_client} (ditagih langsung)",
            "client_pic_phone_snapshot": getattr(mandor, "phone", None),
            "client_pic_email_snapshot": None,
        }, None

    pic, error = get_required_client_pic(getattr(client, "id", None), client_pic_id)
    if error:
        return None, error
    return {
        "client_pic_id": pic.id,
        "client_pic_name_snapshot": pic.name,
        "client_pic_position_snapshot": getattr(pic, "position", None),
        "client_pic_phone_snapshot": getattr(pic, "phone", None),
        "client_pic_email_snapshot": getattr(pic, "email", None),
    }, None


def build_company_bank_snapshot(branch_id):
    settings = get_company_settings(branch_id)
    return {
        "company_bank_name_snapshot": clean_text(settings.get("payment_bank_name")),
        "company_bank_account_number_snapshot": clean_text(settings.get("payment_account_number")),
        "company_bank_account_name_snapshot": clean_text(settings.get("payment_account_name")),
    }


def build_invoice_identity_snapshot(client, client_pic, branch_id):
    data = {
        "client_name_snapshot": clean_text(getattr(client, "name", "")),
        "client_code_snapshot": clean_text(getattr(client, "client_code", "")),
        "client_pic_id": getattr(client_pic, "id", None),
        "client_pic_name_snapshot": clean_text(getattr(client_pic, "name", "")),
        "client_pic_position_snapshot": clean_text(getattr(client_pic, "position", "")),
        "client_pic_phone_snapshot": clean_text(getattr(client_pic, "phone", "")),
        "client_pic_email_snapshot": clean_text(getattr(client_pic, "email", "")),
    }
    data.update(build_company_bank_snapshot(branch_id))
    return data


def apply_invoice_identity_snapshot(invoice, client=None, client_pic=None, branch_id=None):
    if client is None and getattr(invoice, "client_id", None):
        client = Client.query.get(invoice.client_id)

    if client_pic is None and getattr(invoice, "client_pic_id", None):
        client_pic = ClientPic.query.get(invoice.client_pic_id)

    if branch_id is None:
        branch_id = getattr(invoice, "branch_id", None)

    snapshot = build_invoice_identity_snapshot(client, client_pic, branch_id)
    for key, value in snapshot.items():
        if hasattr(invoice, key):
            setattr(invoice, key, value)
    return invoice


def refresh_invoice_identity_snapshot_record(invoice, *, client=None, client_pic=None, branch_id=None):
    return _run_in_transaction(lambda: apply_invoice_identity_snapshot(
        invoice,
        client=client,
        client_pic=client_pic,
        branch_id=branch_id,
    ))


def get_invoice_official_identity(invoice):
    client = Client.query.get(invoice.client_id) if getattr(invoice, "client_id", None) else None
    pic = ClientPic.query.get(invoice.client_pic_id) if getattr(invoice, "client_pic_id", None) else None
    mandor = Mandor.query.get(invoice.mandor_id) if getattr(invoice, "mandor_id", None) else None

    bill_to_type = clean_text(getattr(invoice, "bill_to_type", "")).upper()

    client_name = clean_text(getattr(invoice, "client_name_snapshot", "")) or clean_text(getattr(client, "name", ""))
    if bill_to_type == "MANDOR":
        client_name = client_name or clean_text(getattr(mandor, "name", ""))

    client_code = clean_text(getattr(invoice, "client_code_snapshot", "")) or clean_text(getattr(client, "client_code", ""))
    pic_name = clean_text(getattr(invoice, "client_pic_name_snapshot", "")) or clean_text(getattr(pic, "name", ""))
    pic_position = clean_text(getattr(invoice, "client_pic_position_snapshot", "")) or clean_text(getattr(pic, "position", ""))
    pic_phone = clean_text(getattr(invoice, "client_pic_phone_snapshot", "")) or clean_text(getattr(pic, "phone", ""))
    if bill_to_type == "MANDOR" and not pic_phone:
        pic_phone = clean_text(getattr(mandor, "phone", ""))
    pic_email = clean_text(getattr(invoice, "client_pic_email_snapshot", "")) or clean_text(getattr(pic, "email", ""))

    bank_name = clean_text(getattr(invoice, "company_bank_name_snapshot", ""))
    bank_number = clean_text(getattr(invoice, "company_bank_account_number_snapshot", ""))
    bank_account_name = clean_text(getattr(invoice, "company_bank_account_name_snapshot", ""))

    if not bank_name or not bank_number or not bank_account_name:
        live_bank = build_company_bank_snapshot(getattr(invoice, "branch_id", None))
        bank_name = bank_name or live_bank["company_bank_name_snapshot"]
        bank_number = bank_number or live_bank["company_bank_account_number_snapshot"]
        bank_account_name = bank_account_name or live_bank["company_bank_account_name_snapshot"]

    missing = []
    if bill_to_type == "CLIENT":
        if not client_code:
            missing.append(f"Kode {T.client_lower}")
        if not pic_name:
            missing.append(f"PIC resmi {T.client_lower}")
    elif bill_to_type == "MANDOR":
        if not client_name:
            missing.append("Nama pihak ditagih")
    else:
        if not client_name:
            missing.append("Nama pihak ditagih")

    if not bank_name or not bank_number or not bank_account_name:
        missing.append("rekening pembayaran perusahaan")

    return {
        "client_name": client_name,
        "client_code": client_code,
        "pic_name": pic_name,
        "pic_position": pic_position,
        "pic_phone": pic_phone,
        "pic_email": pic_email,
        "bank_name": bank_name,
        "bank_account_number": bank_number,
        "bank_account_name": bank_account_name,
        "missing": missing,
        "is_complete": not missing,
        "bill_to_type": bill_to_type,
    }
