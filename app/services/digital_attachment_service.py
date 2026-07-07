from __future__ import annotations

import hashlib
import mimetypes
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple
from uuid import uuid4

from flask import current_app
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from app.extensions import db
from app.models.system import DigitalAttachment
from app.services.audit_log_service import record_audit_log


DEFAULT_ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp", "pdf"}
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
UPLOAD_SUBDIR = "digital_attachments"


class AttachmentValidationError(ValueError):
    pass


def _project_root() -> Path:
    return Path(current_app.root_path).resolve().parent


def get_upload_root() -> Path:
    configured = current_app.config.get("DIGITAL_ATTACHMENT_UPLOAD_DIR")
    if configured:
        root = Path(configured)
        if not root.is_absolute():
            root = (_project_root() / root).resolve()
    else:
        root = (_project_root() / "instance" / "uploads" / UPLOAD_SUBDIR).resolve()

    root.mkdir(parents=True, exist_ok=True)
    return root


def get_allowed_extensions() -> set[str]:
    configured = current_app.config.get("DIGITAL_ATTACHMENT_ALLOWED_EXTENSIONS")
    if not configured:
        return set(DEFAULT_ALLOWED_EXTENSIONS)
    if isinstance(configured, str):
        return {item.strip().lower().lstrip(".") for item in configured.split(",") if item.strip()}
    return {str(item).strip().lower().lstrip(".") for item in configured if str(item).strip()}


def get_max_upload_bytes() -> int:
    try:
        return int(current_app.config.get("DIGITAL_ATTACHMENT_MAX_BYTES", DEFAULT_MAX_BYTES))
    except Exception:
        return DEFAULT_MAX_BYTES


def _extension(filename: str) -> str:
    return Path(filename or "").suffix.lower().lstrip(".")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_token(value: object, fallback: str) -> str:
    safe = secure_filename(str(value or "").strip().upper().replace(" ", "_"))
    return safe or fallback



def _detect_safe_mime_type(path: Path, original_name: str, declared_mime: str | None = None) -> str:
    guessed = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    declared = declared_mime or guessed
    suffix = _extension(original_name)
    try:
        header = path.read_bytes()[:16]
    except OSError:
        header = b""

    # Minimal signature sniffing untuk mencegah executable/HTML disimpan sebagai bukti.
    if header.startswith(b"MZ"):
        raise AttachmentValidationError("File executable tidak diizinkan sebagai bukti digital.")
    if header.lstrip().lower().startswith((b"<html", b"<!doctype html", b"<script")):
        raise AttachmentValidationError("File HTML/script tidak diizinkan sebagai bukti digital.")
    if suffix == "pdf" and header and not header.startswith(b"%PDF"):
        raise AttachmentValidationError("File PDF tidak valid atau signature tidak sesuai.")
    if suffix in {"jpg", "jpeg"} and header and not header.startswith(b"\xff\xd8\xff"):
        raise AttachmentValidationError("File JPEG tidak valid atau signature tidak sesuai.")
    if suffix == "png" and header and not header.startswith(b"\x89PNG\r\n\x1a\n"):
        raise AttachmentValidationError("File PNG tidak valid atau signature tidak sesuai.")
    if suffix == "webp" and header and not (header.startswith(b"RIFF") and b"WEBP" in header[:16]):
        raise AttachmentValidationError("File WEBP tidak valid atau signature tidak sesuai.")

    # Pakai MIME aman hasil ekstensi supaya browser tidak menebak tipe berbahaya.
    if suffix == "pdf":
        return "application/pdf"
    if suffix in {"jpg", "jpeg"}:
        return "image/jpeg"
    if suffix == "png":
        return "image/png"
    if suffix == "webp":
        return "image/webp"
    return declared


def is_inline_view_safe(attachment: DigitalAttachment) -> bool:
    """Only allow inline view for safe image/PDF evidence files."""
    mime = (attachment.mime_type or "").lower()
    return mime in {"application/pdf", "image/jpeg", "image/png", "image/webp"}


def _validate_file(file_storage: FileStorage) -> Tuple[str, str]:
    if not file_storage or not getattr(file_storage, "filename", None):
        raise AttachmentValidationError("File lampiran belum dipilih.")

    original = secure_filename(file_storage.filename)
    if not original:
        raise AttachmentValidationError("Nama file lampiran tidak valid.")

    extension = _extension(original)
    if extension not in get_allowed_extensions():
        allowed = ", ".join(sorted(get_allowed_extensions()))
        raise AttachmentValidationError(f"Format file tidak diizinkan. Format aman: {allowed}.")

    return original, extension


def save_digital_attachment(
    *,
    file_storage: FileStorage,
    module: str,
    reference_type: str,
    reference_id: int,
    attachment_type: str,
    branch_id: Optional[int],
    uploaded_by: Optional[int],
    notes: Optional[str] = None,
    commit: bool = True,
) -> DigitalAttachment:
    """Save one attachment safely outside public static folder.

    File fisik disimpan di instance/uploads/digital_attachments, sedangkan DB hanya
    menyimpan metadata. Fungsi ini belum memaksa modul tertentu supaya bisa dipakai
    bertahap oleh delivery/procurement/payment pada patch berikutnya.
    """
    original_name, extension = _validate_file(file_storage)
    max_bytes = get_max_upload_bytes()

    module_safe = _safe_token(module, "GENERAL")
    ref_type_safe = _safe_token(reference_type, "REFERENCE")
    attachment_type_safe = _safe_token(attachment_type, "FILE")

    upload_root = get_upload_root()
    stored_name = f"{module_safe}_{ref_type_safe}_{int(reference_id or 0)}_{uuid4().hex}.{extension}"
    target_path = (upload_root / stored_name).resolve()

    if upload_root not in target_path.parents:
        raise AttachmentValidationError("Path lampiran tidak valid.")

    file_storage.save(str(target_path))

    try:
        size = target_path.stat().st_size
        if size <= 0:
            target_path.unlink(missing_ok=True)
            raise AttachmentValidationError("File lampiran kosong.")
        if size > max_bytes:
            target_path.unlink(missing_ok=True)
            max_mb = max_bytes / (1024 * 1024)
            raise AttachmentValidationError(f"Ukuran file terlalu besar. Maksimal {max_mb:.1f} MB.")

        sha256_hash = _sha256_file(target_path)
        mime_type = _detect_safe_mime_type(target_path, original_name, file_storage.mimetype)

        attachment = DigitalAttachment(
            branch_id=branch_id,
            module=module_safe,
            reference_type=ref_type_safe,
            reference_id=int(reference_id or 0),
            attachment_type=attachment_type_safe,
            original_filename=original_name,
            stored_filename=stored_name,
            file_path=str(target_path.relative_to(upload_root)),
            mime_type=mime_type,
            file_size=size,
            sha256_hash=sha256_hash,
            notes=notes,
            uploaded_by=uploaded_by,
            is_deleted=False,
            created_at=datetime.utcnow(),
        )
        db.session.add(attachment)
        if commit:
            db.session.commit()
            record_audit_log(
                module="ATTACHMENT",
                event_type="DIGITAL_ATTACHMENT_UPLOADED",
                action="CREATE",
                table_name="digital_attachments",
                record_id=attachment.id,
                description=f"Lampiran digital diunggah untuk {module_safe}/{ref_type_safe} #{reference_id}.",
                metadata={
                    "module": module_safe,
                    "reference_type": ref_type_safe,
                    "reference_id": reference_id,
                    "attachment_type": attachment_type_safe,
                    "original_filename": original_name,
                    "file_size": size,
                    "sha256": sha256_hash,
                },
            )
        return attachment
    except Exception:
        if target_path.exists():
            target_path.unlink(missing_ok=True)
        raise


def get_attachment_file_path(attachment: DigitalAttachment) -> Path:
    upload_root = get_upload_root().resolve()
    target_path = (upload_root / (attachment.file_path or attachment.stored_filename or "")).resolve()

    if upload_root not in target_path.parents and target_path != upload_root:
        raise FileNotFoundError("Path lampiran tidak valid.")
    if not target_path.exists() or not target_path.is_file():
        raise FileNotFoundError("File lampiran tidak ditemukan di folder upload.")

    return target_path


def get_attachment_or_none(attachment_id: int, branch_id: Optional[int] = None, include_deleted: bool = False) -> Optional[DigitalAttachment]:
    query = DigitalAttachment.query.filter(DigitalAttachment.id == attachment_id)
    if branch_id is not None:
        query = query.filter((DigitalAttachment.branch_id == branch_id) | (DigitalAttachment.branch_id.is_(None)))
    if not include_deleted:
        query = query.filter(DigitalAttachment.is_deleted.is_(False))
    return query.first()


def list_digital_attachments(
    *,
    branch_id: Optional[int] = None,
    module: Optional[str] = None,
    reference_type: Optional[str] = None,
    attachment_type: Optional[str] = None,
    q: Optional[str] = None,
    include_deleted: bool = False,
    limit: int = 300,
) -> Iterable[DigitalAttachment]:
    query = DigitalAttachment.query
    if branch_id is not None:
        query = query.filter((DigitalAttachment.branch_id == branch_id) | (DigitalAttachment.branch_id.is_(None)))
    if not include_deleted:
        query = query.filter(DigitalAttachment.is_deleted.is_(False))
    if module:
        query = query.filter(DigitalAttachment.module == module)
    if reference_type:
        query = query.filter(DigitalAttachment.reference_type == reference_type)
    if attachment_type:
        query = query.filter(DigitalAttachment.attachment_type == attachment_type)
    if q:
        like = f"%{q}%"
        query = query.filter(
            (DigitalAttachment.original_filename.ilike(like))
            | (DigitalAttachment.notes.ilike(like))
            | (DigitalAttachment.module.ilike(like))
            | (DigitalAttachment.reference_type.ilike(like))
            | (DigitalAttachment.attachment_type.ilike(like))
        )

    return query.order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc()).limit(limit).all()



def list_reference_attachments(
    *,
    module: str,
    reference_type: str,
    reference_id: int,
    branch_id: Optional[int] = None,
    include_deleted: bool = False,
) -> list[DigitalAttachment]:
    """List active attachments for one business record.

    Dipakai modul transaksi supaya bukti digital bisa ditampilkan langsung
    di detail dokumen tanpa membuka halaman sistem/lampiran umum.
    """
    query = DigitalAttachment.query.filter(
        DigitalAttachment.module == _safe_token(module, "GENERAL"),
        DigitalAttachment.reference_type == _safe_token(reference_type, "REFERENCE"),
        DigitalAttachment.reference_id == int(reference_id or 0),
    )
    if branch_id is not None:
        query = query.filter((DigitalAttachment.branch_id == branch_id) | (DigitalAttachment.branch_id.is_(None)))
    if not include_deleted:
        query = query.filter(DigitalAttachment.is_deleted.is_(False))
    return query.order_by(DigitalAttachment.created_at.desc(), DigitalAttachment.id.desc()).all()


def count_reference_attachments(
    *,
    module: str,
    reference_type: str,
    reference_id: int,
    branch_id: Optional[int] = None,
    include_deleted: bool = False,
) -> int:
    query = DigitalAttachment.query.filter(
        DigitalAttachment.module == _safe_token(module, "GENERAL"),
        DigitalAttachment.reference_type == _safe_token(reference_type, "REFERENCE"),
        DigitalAttachment.reference_id == int(reference_id or 0),
    )
    if branch_id is not None:
        query = query.filter((DigitalAttachment.branch_id == branch_id) | (DigitalAttachment.branch_id.is_(None)))
    if not include_deleted:
        query = query.filter(DigitalAttachment.is_deleted.is_(False))
    return query.count()

def get_attachment_filter_options(branch_id: Optional[int] = None) -> Dict[str, list[str]]:
    query = DigitalAttachment.query.filter(DigitalAttachment.is_deleted.is_(False))
    if branch_id is not None:
        query = query.filter((DigitalAttachment.branch_id == branch_id) | (DigitalAttachment.branch_id.is_(None)))

    modules = [row[0] for row in query.with_entities(DigitalAttachment.module).distinct().order_by(DigitalAttachment.module.asc()).all() if row[0]]
    reference_types = [row[0] for row in query.with_entities(DigitalAttachment.reference_type).distinct().order_by(DigitalAttachment.reference_type.asc()).all() if row[0]]
    attachment_types = [row[0] for row in query.with_entities(DigitalAttachment.attachment_type).distinct().order_by(DigitalAttachment.attachment_type.asc()).all() if row[0]]
    return {
        "modules": modules,
        "reference_types": reference_types,
        "attachment_types": attachment_types,
    }


def soft_delete_attachment(attachment: DigitalAttachment, *, deleted_by: Optional[int], note: Optional[str] = None) -> DigitalAttachment:
    if attachment.is_deleted:
        return attachment

    attachment.is_deleted = True
    attachment.deleted_by = deleted_by
    attachment.deleted_at = datetime.utcnow()
    attachment.delete_note = note
    db.session.commit()

    record_audit_log(
        module="ATTACHMENT",
        event_type="DIGITAL_ATTACHMENT_SOFT_DELETED",
        action="DELETE",
        table_name="digital_attachments",
        record_id=attachment.id,
        description=f"Lampiran digital dihapus lunak: {attachment.original_filename}.",
        metadata={
            "module": attachment.module,
            "reference_type": attachment.reference_type,
            "reference_id": attachment.reference_id,
            "attachment_type": attachment.attachment_type,
            "original_filename": attachment.original_filename,
            "note": note,
        },
    )
    return attachment


def format_file_size(size_bytes: Optional[int]) -> str:
    size = float(size_bytes or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if size < 1024 or unit == "GB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024
