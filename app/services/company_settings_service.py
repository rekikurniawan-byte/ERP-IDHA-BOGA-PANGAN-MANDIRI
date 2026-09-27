from app.extensions import db
from app.models.master import Branch, BranchSetting
from app.services.ttl_cache_service import clear_cache


COMPANY_SETTINGS_SECTIONS = [
    {
        "title": "Identitas Perusahaan",
        "description": "Dipakai untuk header aplikasi, invoice, kwitansi, dan laporan.",
        "fields": [
            {"key": "company_name", "label": "Nama Perusahaan", "type": "text", "required": True},
            {"key": "company_subtitle", "label": "Subjudul Sistem/Dokumen", "type": "text", "required": False},
            {"key": "company_logo_url", "label": "URL Logo Perusahaan", "type": "hidden", "required": False},
            {"key": "company_address", "label": "Alamat", "type": "textarea", "required": False},
            {"key": "company_phone", "label": "Telepon", "type": "text", "required": False},
            {"key": "company_email", "label": "Email", "type": "text", "required": False},
            {"key": "company_npwp", "label": "NPWP", "type": "text", "required": False},
        ],
    },
    {
        "title": "Rekening Pembayaran",
        "description": "Dipakai sebagai informasi pembayaran pada invoice.",
        "fields": [
            {"key": "payment_bank_name", "label": "Nama Bank", "type": "text", "required": False},
            {"key": "payment_account_number", "label": "Nomor Rekening", "type": "text", "required": False},
            {"key": "payment_account_name", "label": "Nama Pemilik Rekening", "type": "text", "required": False},
            {"key": "payment_qris_label", "label": "Label QRIS Statis", "type": "text", "required": False},
            {"key": "payment_qris_image_url", "label": "URL/Path Gambar QRIS Statis", "type": "text", "required": False},
            {"key": "payment_qris_note", "label": "Catatan QRIS Statis", "type": "textarea", "required": False},
        ],
    },
    {
        "title": "Dokumen Invoice & Kwitansi",
        "description": "Dipakai untuk catatan, ketentuan, dan tanda tangan dokumen resmi.",
        "fields": [
            {"key": "invoice_footer", "label": "Footer Invoice", "type": "textarea", "required": False},
            {"key": "invoice_terms", "label": "Syarat & Ketentuan Invoice", "type": "textarea", "required": False},
            {"key": "invoice_authorized_name", "label": "Nama Penanggung Jawab Tanda Tangan", "type": "text", "required": False},
            {"key": "invoice_authorized_position", "label": "Jabatan Penanggung Jawab", "type": "text", "required": False},
        ],
    },
    {
        "title": "Istilah",
        "description": (
            "Kata yang dipakai di seluruh layar, portal, dan dokumen cabang ini. "
            "Sesuaikan dengan jenis pelanggan: proyek (Perusahaan / Mandor), sekolah "
            "(Yayasan / Kelas), kantor (Perusahaan / Divisi), rumah sakit (Rumah Sakit / "
            "Bangsal). Kosongkan untuk memakai istilah bawaan."
        ),
        "fields": [
            {"key": "term_client", "label": "Istilah untuk Client (bawaan: Client)", "type": "text", "required": False},
            {"key": "term_sub_client", "label": "Istilah untuk Sub Client (bawaan: Sub Client)", "type": "text", "required": False},
            {"key": "term_location", "label": "Istilah untuk Lokasi Antar (bawaan: Lokasi Antar)", "type": "text", "required": False},
            {"key": "term_worker", "label": "Istilah untuk Pekerja (bawaan: Pekerja)", "type": "text", "required": False},
        ],
    },
    {
        "title": "Prefix Nomor Dokumen",
        "description": "Catatan prefix untuk standar penomoran dokumen. Belum mengubah logic generate nomor transaksi.",
        "fields": [
            {"key": "document_prefix_invoice", "label": "Prefix Invoice", "type": "text", "required": False},
            {"key": "document_prefix_payment", "label": "Prefix Payment", "type": "text", "required": False},
            {"key": "document_prefix_order", "label": "Prefix Order", "type": "text", "required": False},
            {"key": "document_prefix_delivery", "label": "Prefix Delivery", "type": "text", "required": False},
            {"key": "document_prefix_journal", "label": "Prefix Jurnal", "type": "text", "required": False},
        ],
    },
]


SETTING_KEYS = [
    field["key"]
    for section in COMPANY_SETTINGS_SECTIONS
    for field in section["fields"]
]


DEFAULT_SETTINGS = {
    "company_name": "PT Idha Boga Pangan Mandiri",
    "company_subtitle": "Sistem Manajemen Catering",
    "company_logo_url": "",
    "company_address": "",
    "company_phone": "",
    "company_email": "",
    "company_npwp": "",
    "payment_bank_name": "",
    "payment_account_number": "",
    "payment_account_name": "",
    "payment_qris_label": "",
    "payment_qris_image_url": "",
    "payment_qris_note": "",
    "invoice_footer": "",
    "invoice_terms": "Mohon lakukan pembayaran sebelum tanggal jatuh tempo sesuai kesepakatan.",
    "invoice_authorized_name": "Admin/Owner",
    "invoice_authorized_position": "Penanggung Jawab",
    "document_prefix_invoice": "INV",
    "document_prefix_payment": "PAY",
    "document_prefix_order": "ORD",
    "document_prefix_delivery": "DLV",
    "document_prefix_journal": "JRN",
    # Istilah kosong = memakai bawaan di app/utils/terms.py. Sengaja tidak
    # diisi di sini supaya bawaannya tetap satu sumber.
    "term_client": "",
    "term_sub_client": "",
    "term_location": "",
    "term_worker": "",
}


def _clean_text(value):
    return str(value or "").strip()


def get_company_settings_schema():
    return COMPANY_SETTINGS_SECTIONS


def get_company_settings(branch_id):
    """Read company settings for one branch.

    Read-only helper. It does not create missing settings automatically.
    Missing keys are filled with safe display defaults so production pages do not crash.
    """
    settings = dict(DEFAULT_SETTINGS)

    branch = Branch.query.get(branch_id) if branch_id else None
    if branch:
        if not settings.get("company_address") and branch.address:
            settings["company_address"] = branch.address
        if not settings.get("company_phone") and branch.phone:
            settings["company_phone"] = branch.phone

    if branch_id:
        rows = BranchSetting.query.filter_by(branch_id=branch_id).order_by(
            BranchSetting.id.asc()
        ).all()
        for row in rows:
            if row.setting_key in SETTING_KEYS:
                settings[row.setting_key] = row.setting_value or ""

    return settings


def save_company_settings(branch_id, form_data):
    """Upsert company settings using existing branch_settings table.

    This function only writes company setting keys. It does not touch users,
    transactions, invoice/payment/journal logic, or master operational data.
    """
    saved_keys = []

    for key in SETTING_KEYS:
        value = _clean_text(form_data.get(key))

        setting = BranchSetting.query.filter_by(
            branch_id=branch_id,
            setting_key=key,
        ).order_by(
            BranchSetting.id.asc()
        ).first()

        if setting:
            setting.setting_value = value
        else:
            setting = BranchSetting(
                branch_id=branch_id,
                setting_key=key,
                setting_value=value,
            )
            db.session.add(setting)

        saved_keys.append(key)

    db.session.commit()
    clear_cache("company_settings")
    return saved_keys
