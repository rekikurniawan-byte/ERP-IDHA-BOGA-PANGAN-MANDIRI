from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from email.message import EmailMessage
import hashlib
import logging
import secrets
import smtplib

from flask import current_app, render_template

from app.extensions import db
from app.models.contract import (
    ContractDocument,
    ContractHoliday,
    CustomerContract,
    DISPUTE_COURT_LABELS,
    DOC_STATUS_DRAFT,
    DOC_STATUS_PENDING,
    DOC_STATUS_SIGNED,
    DOC_TYPE_ADDENDUM,
    DOC_TYPE_CONTRACT,
    SIGNING_METHOD_OTP,
    SIGNING_METHOD_WET,
)
from app.models.master import Mandor, User
from app.models.system import DigitalAttachment
from app.services.atomic_transaction_service import atomic_business_action
from app.services.audit_log_service import record_audit_log
from app.services.company_settings_service import get_company_settings
from app.services.contract_rules_service import billing_mode_for
from app.services.credit_control_service import get_thresholds
from app.services.customer_contract_service import get_customer_contract
from app.services.digital_attachment_service import (
    AttachmentValidationError,
    stage_digital_attachment,
)
from app.services.pricing_service import quote_price
from app.utils.clock import now_wib, today_wib

logger = logging.getLogger(__name__)

CUSTOMER_CONTRACT_DOCUMENT_MODULE = "CUSTOMER_CONTRACT"
CUSTOMER_CONTRACT_REFERENCE_TYPE = "CUSTOMER_CONTRACT"
CONTRACT_DOCUMENT_TYPE = "CONTRACT_DOCUMENT"
CONTRACT_AMENDMENT_TYPE = "CONTRACT_AMENDMENT"
CONTRACT_TERMINATION_TYPE = "CONTRACT_TERMINATION"

ALLOWED_CONTRACT_ATTACHMENT_TYPES = {
    CONTRACT_DOCUMENT_TYPE,
    CONTRACT_AMENDMENT_TYPE,
    CONTRACT_TERMINATION_TYPE,
    "SIGNED_CONTRACT_SCAN",
}

ID_DAYS = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
ID_MONTHS = [
    "",
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]


class CustomerContractDocumentError(ValueError):
    pass


class _NullContext:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


def _format_id_date(d: date) -> str:
    return f"{d.day} {ID_MONTHS[d.month]} {d.year}"


def _get_contract_or_raise(contract_id: int, branch_id: int) -> CustomerContract:
    contract = get_customer_contract(contract_id, branch_id=branch_id)
    if not contract:
        raise CustomerContractDocumentError("Kontrak customer tidak ditemukan untuk branch ini.")
    return contract


def _normalize_attachment_type(attachment_type: str) -> str:
    normalized = str(attachment_type or "").strip().upper()
    if normalized not in ALLOWED_CONTRACT_ATTACHMENT_TYPES:
        allowed = ", ".join(sorted(ALLOWED_CONTRACT_ATTACHMENT_TYPES))
        raise CustomerContractDocumentError(f"Tipe dokumen kontrak tidak valid. Pilihan: {allowed}.")
    return normalized


def _contract_document_notes(attachment_type: str, notes: str | None) -> str:
    clean = str(notes or "").strip()
    prefix = attachment_type
    return f"{prefix}: {clean}" if clean else prefix


def attach_customer_contract_document(
    *,
    contract_id: int,
    branch_id: int,
    file_storage,
    uploaded_by: int | None,
    attachment_type: str = CONTRACT_DOCUMENT_TYPE,
    notes: str | None = None,
    commit: bool = True,
) -> DigitalAttachment:
    """Attach a private document to an existing customer contract."""
    contract = _get_contract_or_raise(contract_id, branch_id)
    attachment_type = _normalize_attachment_type(attachment_type)

    if commit:
        with atomic_business_action(
            module=CUSTOMER_CONTRACT_DOCUMENT_MODULE,
            action="CUSTOMER_CONTRACT_DOCUMENT_ATTACHED",
            description=f"Attach document to customer contract {contract.contract_number}.",
            reference_type=CUSTOMER_CONTRACT_REFERENCE_TYPE,
            reference_id=contract.id,
            user_id=uploaded_by,
            branch_id=contract.branch_id,
            severity="MEDIUM",
            metadata={
                "contract_number": contract.contract_number,
                "attachment_type": attachment_type,
                "mutation_scope": "ATTACHMENT_ONLY",
            },
        ) as boundary:
            attachment = _stage_contract_document(contract, file_storage, uploaded_by, attachment_type, notes)
            boundary.track_attachment(attachment)
            db.session.flush()
            _record_contract_document_audit(contract, attachment, uploaded_by)
    else:
        attachment = _stage_contract_document(contract, file_storage, uploaded_by, attachment_type, notes)
        db.session.flush()
        _record_contract_document_audit(contract, attachment, uploaded_by)

    return attachment


def list_customer_contract_documents(
    *,
    contract_id: int,
    branch_id: int,
    attachment_type: str | None = None,
    include_deleted: bool = False,
) -> list[DigitalAttachment]:
    contract = _get_contract_or_raise(contract_id, branch_id)
    query = DigitalAttachment.query.filter(
        DigitalAttachment.branch_id == contract.branch_id,
        DigitalAttachment.module == CUSTOMER_CONTRACT_DOCUMENT_MODULE,
        DigitalAttachment.reference_type == CUSTOMER_CONTRACT_REFERENCE_TYPE,
        DigitalAttachment.reference_id == contract.id,
    )
    if attachment_type:
        query = query.filter(DigitalAttachment.attachment_type == _normalize_attachment_type(attachment_type))
    if not include_deleted:
        query = query.filter(DigitalAttachment.is_deleted.is_(False))
    return query.order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc()).all()


def _stage_contract_document(contract, file_storage, uploaded_by: int | None, attachment_type: str, notes: str | None) -> DigitalAttachment:
    return stage_digital_attachment(
        file_storage=file_storage,
        module=CUSTOMER_CONTRACT_DOCUMENT_MODULE,
        reference_type=CUSTOMER_CONTRACT_REFERENCE_TYPE,
        reference_id=contract.id,
        attachment_type=attachment_type,
        branch_id=contract.branch_id,
        uploaded_by=uploaded_by,
        notes=_contract_document_notes(attachment_type, notes),
    )


def _record_contract_document_audit(contract, attachment: DigitalAttachment, uploaded_by: int | None) -> None:
    record_audit_log(
        module="CONTRACT",
        event_type="CUSTOMER_CONTRACT_DOCUMENT_ATTACHED",
        action="CREATE",
        table_name="digital_attachments",
        record_id=attachment.id,
        description=f"Dokumen kontrak customer diarsipkan: {contract.contract_number}.",
        metadata={
            "contract_id": contract.id,
            "contract_number": contract.contract_number,
            "attachment_type": attachment.attachment_type,
            "original_filename": attachment.original_filename,
            "file_size": attachment.file_size,
            "sha256": attachment.sha256_hash,
            "mutation_scope": "ATTACHMENT_ONLY",
        },
        user_id=uploaded_by,
        branch_id=contract.branch_id,
        commit=False,
    )


def build_contract_document_context(contract_id: int, branch_id: int) -> dict:
    """Susun konteks surat kontrak lengkap dari data riil sistem."""
    contract = _get_contract_or_raise(contract_id, branch_id)
    company = get_company_settings(branch_id)

    # Sub client & pihak tagih
    subclients = Mandor.query.filter_by(branch_id=branch_id, client_id=contract.client_id).order_by(Mandor.name.asc()).all()
    subclient_rows = []
    for sc in subclients:
        mode = billing_mode_for(sc.id, branch_id=branch_id)
        if mode == "VIA_CLIENT":
            mode_label = "Ditagih ke Kantor Pusat"
            mode_desc = "Invoice atas nama Kantor Pusat Client, Sub Client dapat memantau rincian pengiriman"
        elif mode == "DIRECT":
            mode_label = "Ditagih Langsung ke Sub Client"
            mode_desc = "Invoice atas nama Sub Client, Kantor Pusat Client bertindak sebagai Penjamin"
        else:
            mode_label = "Bayar di Muka (Tunai/Transfer)"
            mode_desc = "Pesanan wajib dilunasi sebelum makanan dikirim"
        subclient_rows.append({
            "id": sc.id,
            "name": sc.name,
            "phone": sc.phone,
            "billing_mode": mode,
            "billing_mode_label": mode_label,
            "billing_mode_desc": mode_desc,
        })

    # Harga per porsi dari pricing service
    quote = quote_price(branch_id, contract.client_id)
    price_per_portion = quote.price if quote else Decimal("0")

    # Ongkos kirim: tarif khusus kontrak bila ada, selain itu termasuk harga porsi
    # (aturan yang sama dengan pricing_service.quote_trip_fee untuk client kontrak).
    from app.services.pricing_service import fee_in_effect

    contract_fee = fee_in_effect(branch_id, client_id=contract.client_id, on_date=today_wib())
    if contract_fee is not None and Decimal(contract_fee.fee) > 0:
        delivery_fee_text = f"Rp{Decimal(contract_fee.fee):,.0f} per pengiriman per sesi makan".replace(",", ".")
    else:
        delivery_fee_text = "Sudah termasuk dalam harga per porsi"

    # Jam lock
    lunch_lock_time = contract.lunch_lock_time.strftime("%H.%M") if contract.lunch_lock_time else "10.00"
    dinner_lock_time = contract.dinner_lock_time.strftime("%H.%M") if contract.dinner_lock_time else "15.00"

    # Libur rutin & khusus
    day_numbers = [part.strip() for part in str(contract.weekly_holidays or "").split(",") if part.strip().isdigit()]
    weekly_holidays_label = (
        ", ".join(ID_DAYS[int(number) - 1] for number in day_numbers if 1 <= int(number) <= 7)
        or "Tidak ada (Pengiriman Setiap Hari)"
    )
    if contract.holidays:
        special_holidays_label = ", ".join(
            [h.holiday_date.strftime("%d-%m-%Y") + (f" ({h.note})" if h.note else "") for h in contract.holidays]
        )
    else:
        special_holidays_label = "Tidak ada hari libur khusus yang dijadwalkan"

    # Siklus tagihan
    cycle_map = {
        "WEEKLY": "Mingguan",
        "BIWEEKLY": "14 Hari (Dua Mingguan)",
        "MONTHLY": "Bulanan",
    }
    billing_cycle_label = cycle_map.get(contract.billing_cycle, contract.billing_cycle)
    billing_anchor_text = (
        contract.billing_anchor_date.strftime("%d-%m-%Y")
        if contract.billing_anchor_date
        else contract.start_date.strftime("%d-%m-%Y")
    )

    # Tempo pembayaran: teks tempo dibuat langsung dari angka due_days
    due_days_text = f"{contract.due_days} hari kalender setelah invoice diterbitkan"

    # Pengadilan
    dispute_court_label = DISPUTE_COURT_LABELS.get(contract.dispute_court, contract.dispute_court)

    # Tanggal cetak / tanda tangan
    today = today_wib()
    signed_day_name = ID_DAYS[today.weekday()]
    signed_date_text = _format_id_date(today)
    signed_date_formatted = today.strftime("%d-%m-%Y")

    thresholds = get_thresholds(branch_id)
    from app.services.tax_service import contract_tax_clause

    tax_clause = contract_tax_clause(branch_id, today)

    return {
        "contract": contract,
        "company": company,
        "subclient_rows": subclient_rows,
        "price_per_portion": price_per_portion,
        "delivery_fee_text": delivery_fee_text,
        "lunch_lock_time": lunch_lock_time,
        "dinner_lock_time": dinner_lock_time,
        "weekly_holidays_label": weekly_holidays_label,
        "special_holidays_label": special_holidays_label,
        "billing_cycle_label": billing_cycle_label,
        "billing_anchor_text": billing_anchor_text,
        "due_days_text": due_days_text,
        "dispute_court_label": dispute_court_label,
        "signed_day_name": signed_day_name,
        "signed_date_text": signed_date_text,
        "signed_date_formatted": signed_date_formatted,
        "thresholds": thresholds,
        "tax_clause": tax_clause,
    }


def render_contract_document_html(
    *,
    contract_id: int,
    branch_id: int,
    document_type: str = DOC_TYPE_CONTRACT,
    doc: ContractDocument | None = None,
) -> str:
    """Render template surat kontrak menjadi HTML utuh yang siap dibekukan (snapshot)."""
    context = build_contract_document_context(contract_id, branch_id)
    doc_title = (
        f"Adendum Kontrak {context['contract'].contract_number}"
        if document_type == DOC_TYPE_ADDENDUM
        else f"Surat Perjanjian Kontrak - {context['contract'].contract_number}"
    )
    context["doc"] = doc
    context["doc_title"] = doc_title
    # Surat juga bisa dibuat di luar request web (adendum dari tugas/CLI): template
    # memakai url_for, jadi sediakan konteks request bila belum ada.
    from flask import has_request_context

    if has_request_context():
        return render_template("contracts/contract_document_print.html", **context)
    with current_app.test_request_context("/"):
        return render_template("contracts/contract_document_print.html", **context)


def generate_contract_document(
    *,
    contract_id: int,
    branch_id: int,
    created_by: int,
    document_type: str = DOC_TYPE_CONTRACT,
    notes: str | None = None,
    commit: bool = True,
) -> ContractDocument:
    """Buat snapshot surat kontrak atau adendum dari data sistem dan simpan ke database."""
    contract = _get_contract_or_raise(contract_id, branch_id)
    doc_type = DOC_TYPE_ADDENDUM if str(document_type).upper() == DOC_TYPE_ADDENDUM else DOC_TYPE_CONTRACT

    existing = ContractDocument.query.filter_by(
        branch_id=branch_id,
        contract_id=contract.id,
        document_type=doc_type,
    ).order_by(ContractDocument.version_no.desc()).first()

    if doc_type == DOC_TYPE_CONTRACT and existing and existing.status in (DOC_STATUS_DRAFT, DOC_STATUS_PENDING):
        boundary = (
            atomic_business_action(
                module="CONTRACT",
                action="CUSTOMER_CONTRACT_DOCUMENT_UPDATED",
                description=f"Update draft snapshot for {contract.contract_number}.",
                reference_type="contract_documents",
                reference_id=existing.id,
                user_id=created_by,
                branch_id=branch_id,
                severity="LOW",
                metadata={"document_number": existing.document_number},
            )
            if commit
            else _NullContext()
        )
        with boundary:
            doc = existing
            doc.version_no = contract.version_no or 1
            doc.html_snapshot = render_contract_document_html(
                contract_id=contract.id,
                branch_id=branch_id,
                document_type=doc_type,
                doc=doc,
            )
            doc.notes = notes or doc.notes
            # OTP lama dikirim untuk isi surat lama; isi berubah = minta OTP baru.
            doc.otp_code_hash = None
            doc.otp_expires_at = None
            doc.updated_at = now_wib()
            db.session.flush()
        return doc

    # Dokumen baru
    if doc_type == DOC_TYPE_CONTRACT:
        version_no = (existing.version_no + 1) if existing else (contract.version_no or 1)
        doc_number = f"DOC/{contract.contract_number}/V{version_no}"
        title = f"Surat Perjanjian Kontrak - {contract.contract_number} (v{version_no})"
    else:
        addendum_count = ContractDocument.query.filter_by(
            branch_id=branch_id,
            contract_id=contract.id,
            document_type=DOC_TYPE_ADDENDUM,
        ).count()
        version_no = addendum_count + 1
        doc_number = f"ADENDUM-{version_no:02d}/{contract.contract_number}"
        title = f"Adendum #{version_no} Kontrak {contract.contract_number}"

    # Pastikan nomor unik
    suffix = 1
    base_number = doc_number
    while ContractDocument.query.filter_by(document_number=doc_number).first():
        doc_number = f"{base_number}-{suffix}"
        suffix += 1

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_DOCUMENT_GENERATED",
            description=f"Generate {doc_type} document for {contract.contract_number}.",
            reference_type="contract_documents",
            reference_id=contract.id,
            user_id=created_by,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"document_number": doc_number, "document_type": doc_type, "version_no": version_no},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        doc = ContractDocument(
            branch_id=branch_id,
            contract_id=contract.id,
            document_number=doc_number,
            document_type=doc_type,
            version_no=version_no,
            title=title,
            html_snapshot="",
            status=DOC_STATUS_PENDING,
            created_by=created_by,
            notes=notes,
        )
        db.session.add(doc)
        db.session.flush()

        doc.html_snapshot = render_contract_document_html(
            contract_id=contract.id,
            branch_id=branch_id,
            document_type=doc_type,
            doc=doc,
        )
        db.session.flush()

        record_audit_log(
            module="CONTRACT",
            event_type="CUSTOMER_CONTRACT_DOCUMENT_SNAPSHOT_CREATED",
            action="CREATE",
            table_name="contract_documents",
            record_id=doc.id,
            description=f"Snapshot dokumen surat {doc_type} dibuat: {doc.document_number}.",
            metadata={
                "contract_id": contract.id,
                "document_id": doc.id,
                "document_number": doc.document_number,
                "document_type": doc_type,
            },
            user_id=created_by,
            branch_id=branch_id,
            commit=False,
        )

    return doc


def generate_addendum_document(
    *,
    contract_id: int,
    branch_id: int,
    created_by: int,
    notes: str | None = None,
    commit: bool = True,
) -> ContractDocument:
    """Buat dokumen adendum resmi di tengah masa kontrak berjalan."""
    return generate_contract_document(
        contract_id=contract_id,
        branch_id=branch_id,
        created_by=created_by,
        document_type=DOC_TYPE_ADDENDUM,
        notes=notes,
        commit=commit,
    )


def sign_contract_document_wet(
    *,
    document_id: int,
    branch_id: int,
    file_storage,
    actor_id: int,
    notes: str | None = None,
    commit: bool = True,
) -> ContractDocument:
    """Tanda tangan basah di atas meterai Rp10.000 dengan mengunggah hasil scan."""
    doc = get_contract_document(document_id, branch_id)
    if not doc:
        raise CustomerContractDocumentError("Dokumen kontrak tidak ditemukan.")

    if not file_storage or not getattr(file_storage, "filename", None):
        raise CustomerContractDocumentError("File scan surat bermeterai wajib diunggah.")

    user = User.query.get(actor_id) if actor_id else None
    signer_name = (user.full_name or user.username) if user else "Admin Operasional"

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_DOCUMENT_WET_SIGNED",
            description=f"Sign contract document {doc.document_number} with wet stamp scan.",
            reference_type="contract_documents",
            reference_id=doc.id,
            user_id=actor_id,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"document_number": doc.document_number, "signer_name": signer_name},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        attachment = stage_digital_attachment(
            file_storage=file_storage,
            module="CONTRACT",
            reference_type="CONTRACT_DOCUMENT",
            reference_id=doc.id,
            attachment_type="SIGNED_CONTRACT_SCAN",
            branch_id=branch_id,
            uploaded_by=actor_id,
            notes=notes or f"Scan tanda tangan basah meterai dokumen {doc.document_number}",
        )
        db.session.flush()

        doc.status = DOC_STATUS_SIGNED
        doc.signing_method = SIGNING_METHOD_WET
        doc.scan_attachment_id = attachment.id
        doc.signed_at = now_wib()
        doc.signed_by_user_id = actor_id
        doc.signed_by_name = signer_name
        doc.updated_at = now_wib()
        db.session.flush()

        # Isi surat tetap snapshot saat dibuat (yang dibaca = yang ditandatangani);
        # cap tanda tangan ditambahkan saat dicetak lewat contract_document_print_html.

        record_audit_log(
            module="CONTRACT",
            event_type="CUSTOMER_CONTRACT_DOCUMENT_SIGNED",
            action="UPDATE",
            table_name="contract_documents",
            record_id=doc.id,
            description=f"Dokumen kontrak {doc.document_number} ditandatangani basah oleh {signer_name}.",
            metadata={
                "document_id": doc.id,
                "document_number": doc.document_number,
                "signing_method": SIGNING_METHOD_WET,
                "attachment_id": attachment.id,
            },
            user_id=actor_id,
            branch_id=branch_id,
            commit=False,
        )

    return doc


def send_contract_otp_email(to_email: str, contract_number: str, otp_code: str) -> tuple[bool, str | None]:
    """Kirim email OTP persetujuan kontrak ke email pengguna portal."""
    mail_server = current_app.config.get("MAIL_SERVER")
    mail_port = int(current_app.config.get("MAIL_PORT") or 587)
    mail_username = current_app.config.get("MAIL_USERNAME")
    mail_password = current_app.config.get("MAIL_PASSWORD")
    mail_use_tls = bool(current_app.config.get("MAIL_USE_TLS", True))
    mail_from = current_app.config.get("MAIL_FROM") or mail_username or "noreply@idhabogapangan.co.id"

    if not mail_server or not mail_username:
        # Kode OTP adalah tanda tangan: jangan pernah ditulis ke log.
        logger.warning("Konfigurasi SMTP belum lengkap; OTP kontrak %s tidak dikirim.", contract_number)
        return False, "Email perusahaan belum disetel (SMTP). Hubungi admin, atau tanda tangan basah."

    msg = EmailMessage()
    msg["Subject"] = f"Kode OTP Persetujuan Kontrak {contract_number} - PT Idha Boga Pangan Mandiri"
    msg["From"] = mail_from
    msg["To"] = to_email
    msg.set_content(
        f"Halo,\n\n"
        f"Berikut adalah kode verifikasi OTP untuk persetujuan dokumen Kontrak {contract_number}:\n\n"
        f"KODE OTP: {otp_code}\n\n"
        f"Kode OTP ini berlaku selama 15 menit. Masukkan kode ini pada portal untuk menandatangani surat perjanjian kerjasama secara digital.\n\n"
        f"Jika Anda tidak merasa mengajukan permintaan ini, silakan hubungi customer service kami.\n\n"
        f"Salam,\n"
        f"PT Idha Boga Pangan Mandiri\n"
    )

    try:
        server = smtplib.SMTP(mail_server, mail_port, timeout=15)
        if mail_use_tls:
            server.starttls()
        if mail_username and mail_password:
            server.login(mail_username, mail_password)
        server.send_message(msg)
        server.quit()
        return True, None
    except Exception as err:
        logger.exception("Gagal mengirim email OTP ke %s: %s", to_email, err)
        return False, str(err)


def send_contract_signing_otp(
    *,
    document_id: int,
    user_id: int,
    branch_id: int,
    commit: bool = True,
) -> tuple[bool, str]:
    """Buat dan kirim kode OTP 6 digit ke email akun pengguna portal."""
    doc = get_contract_document(document_id, branch_id)
    if not doc:
        raise CustomerContractDocumentError("Dokumen kontrak tidak ditemukan.")

    if doc.status == DOC_STATUS_SIGNED:
        raise CustomerContractDocumentError("Dokumen ini sudah ditandatangani.")

    user = User.query.get(user_id)
    if not user or not user.email:
        raise CustomerContractDocumentError("Akun portal wajib memiliki alamat email aktif untuk menerima OTP.")

    otp = f"{secrets.randbelow(1000000):06d}"
    otp_hash = hashlib.sha256(otp.encode("utf-8")).hexdigest()
    expires_at = now_wib() + timedelta(minutes=15)

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_DOCUMENT_OTP_REQUESTED",
            description=f"Request signing OTP for {doc.document_number}.",
            reference_type="contract_documents",
            reference_id=doc.id,
            user_id=user_id,
            branch_id=branch_id,
            severity="LOW",
            metadata={"document_number": doc.document_number},
        )
        if commit
        else _NullContext()
    )
    with boundary:
        doc.otp_code_hash = otp_hash
        doc.otp_expires_at = expires_at
        doc.updated_at = now_wib()
        db.session.flush()

    ok, err = send_contract_otp_email(user.email, doc.contract.contract_number, otp)
    if not ok:
        raise CustomerContractDocumentError(f"Gagal mengirimkan email OTP: {err}")

    # Return success message (masked email)
    parts = user.email.split("@")
    masked = parts[0][:2] + "***@" + parts[1] if len(parts) == 2 else user.email
    return True, f"Kode OTP telah dikirim ke {masked}. Berlaku selama 15 menit."


def verify_and_sign_contract_document_otp(
    *,
    document_id: int,
    user_id: int,
    otp_code: str,
    branch_id: int,
    commit: bool = True,
) -> ContractDocument:
    """Verifikasi kode OTP dan tandatangani dokumen kontrak secara digital melalui portal."""
    doc = get_contract_document(document_id, branch_id)
    if not doc:
        raise CustomerContractDocumentError("Dokumen kontrak tidak ditemukan.")

    if doc.status == DOC_STATUS_SIGNED:
        raise CustomerContractDocumentError("Dokumen ini sudah ditandatangani.")

    clean_otp = str(otp_code or "").strip()
    if not clean_otp:
        raise CustomerContractDocumentError("Kode OTP wajib diisi.")

    if not doc.otp_code_hash or not doc.otp_expires_at:
        raise CustomerContractDocumentError("Permintaan OTP belum diajukan atau telah kedaluwarsa.")

    if now_wib() > doc.otp_expires_at:
        raise CustomerContractDocumentError("Kode OTP telah kedaluwarsa. Silakan minta kode OTP baru.")

    submitted_hash = hashlib.sha256(clean_otp.encode("utf-8")).hexdigest()
    if submitted_hash != doc.otp_code_hash:
        raise CustomerContractDocumentError("Kode OTP tidak valid atau salah.")

    user = User.query.get(user_id)
    signer_name = (user.full_name or user.username) if user else "Pengguna Portal"

    boundary = (
        atomic_business_action(
            module="CONTRACT",
            action="CUSTOMER_CONTRACT_DOCUMENT_OTP_SIGNED",
            description=f"Sign contract document {doc.document_number} with Portal OTP.",
            reference_type="contract_documents",
            reference_id=doc.id,
            user_id=user_id,
            branch_id=branch_id,
            severity="MEDIUM",
            metadata={"document_number": doc.document_number, "signer_name": signer_name},
        )
        if commit
        else _NullContext()
    )

    with boundary:
        doc.status = DOC_STATUS_SIGNED
        doc.signing_method = SIGNING_METHOD_OTP
        doc.portal_signed_at = now_wib()
        doc.portal_signed_by_user_id = user_id
        doc.signed_by_name = signer_name
        doc.otp_code_hash = None
        doc.otp_expires_at = None
        doc.updated_at = now_wib()
        db.session.flush()

        # Isi surat tetap snapshot saat dibuat; cap TTD ditambahkan saat dicetak.

        record_audit_log(
            module="CONTRACT",
            event_type="CUSTOMER_CONTRACT_DOCUMENT_SIGNED",
            action="UPDATE",
            table_name="contract_documents",
            record_id=doc.id,
            description=f"Dokumen kontrak {doc.document_number} disetujui digital via OTP oleh {signer_name}.",
            metadata={
                "document_id": doc.id,
                "document_number": doc.document_number,
                "signing_method": SIGNING_METHOD_OTP,
                "signer_name": signer_name,
                "portal_signed_at": doc.portal_signed_at.isoformat() if doc.portal_signed_at else None,
            },
            user_id=user_id,
            branch_id=branch_id,
            commit=False,
        )

    return doc


def contract_document_print_html(doc: ContractDocument) -> str:
    """HTML cetak: snapshot terkunci + cap tanda tangan (bila sudah ditandatangani)."""
    html = doc.html_snapshot or ""
    if doc.status != DOC_STATUS_SIGNED:
        return html
    stamp = render_template("contracts/_signature_stamp.html", doc=doc)
    marker = "</body>"
    if marker in html:
        head, tail = html.rsplit(marker, 1)
        return head + stamp + marker + tail
    return html + stamp


def is_contract_signed(contract_id: int, branch_id: int) -> bool:
    """Periksa apakah kontrak utama memiliki dokumen KONTRAK yang telah berstatus DITANDATANGANI."""
    doc = ContractDocument.query.filter(
        ContractDocument.branch_id == branch_id,
        ContractDocument.contract_id == contract_id,
        ContractDocument.document_type == DOC_TYPE_CONTRACT,
        ContractDocument.status == DOC_STATUS_SIGNED,
    ).first()
    return doc is not None


def get_contract_document(document_id: int, branch_id: int) -> ContractDocument | None:
    return ContractDocument.query.filter_by(id=document_id, branch_id=branch_id).first()


def list_contract_documents_for_contract(contract_id: int, branch_id: int) -> list[ContractDocument]:
    return (
        ContractDocument.query.filter_by(contract_id=contract_id, branch_id=branch_id)
        .order_by(ContractDocument.version_no.desc(), ContractDocument.id.desc())
        .all()
    )
