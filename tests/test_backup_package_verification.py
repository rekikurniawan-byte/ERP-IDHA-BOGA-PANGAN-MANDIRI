import hashlib
import json
import zipfile
from pathlib import Path

from app.services.backup_service import (
    BACKUP_CONTRACT_VERSION,
    CHECKSUM_SUFFINAL,
    FULL_BACKUP_DATABASE_ARC_PATH,
    FULL_BACKUP_UPLOAD_ARC_ROOT,
    verify_full_backup_package,
)


def _write_full_backup(
    path: Path,
    upload_bytes: bytes = b"invoice-pdf",
    manifest_upload_bytes: bytes | None = None,
) -> Path:
    dump_bytes = b"PGDMP test dump bytes"
    expected_upload_bytes = manifest_upload_bytes if manifest_upload_bytes is not None else upload_bytes
    upload_arc = f"{FULL_BACKUP_UPLOAD_ARC_ROOT}/2026/invoice.pdf"
    manifest = {
        "contract_version": BACKUP_CONTRACT_VERSION,
        "database_arc_path": FULL_BACKUP_DATABASE_ARC_PATH,
        "database_sha256": hashlib.sha256(dump_bytes).hexdigest(),
        "database_size_bytes": len(dump_bytes),
        "uploads": {
            upload_arc: {
                "size_bytes": len(expected_upload_bytes),
                "sha256": hashlib.sha256(expected_upload_bytes).hexdigest(),
            }
        },
    }
    with zipfile.ZipFile(path, "w") as zipf:
        zipf.writestr(FULL_BACKUP_DATABASE_ARC_PATH, dump_bytes)
        zipf.writestr(upload_arc, upload_bytes)
        zipf.writestr("manifest.json", json.dumps(manifest))
        zipf.writestr("restore_readme.txt", "restore")

    sidecar = path.with_name(path.name + CHECKSUM_SUFFINAL)
    sidecar.write_text(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n", encoding="utf-8")
    return path


def test_verify_full_backup_package_accepts_matching_manifest(tmp_path: Path):
    backup = _write_full_backup(tmp_path / "backup.zip")

    result = verify_full_backup_package(backup)

    assert result["status"] == "PASS"
    assert not result["errors"]
    assert "SHA256 ZIP cocok dengan sidecar." in result["successes"]
    assert "SHA256 database dump cocok dengan manifest." in result["successes"]


def test_verify_full_backup_package_rejects_manifest_hash_mismatch(tmp_path: Path):
    backup = _write_full_backup(
        tmp_path / "backup.zip",
        upload_bytes=b"changed",
        manifest_upload_bytes=b"invoice-pdf",
    )
    backup.with_name(backup.name + CHECKSUM_SUFFINAL).write_text(
        f"{hashlib.sha256(b'old-zip').hexdigest()}  {backup.name}\n",
        encoding="utf-8",
    )

    result = verify_full_backup_package(backup)

    assert result["status"] == "FAIL"
    assert any("SHA256 ZIP tidak cocok" in error for error in result["errors"])
    assert any("SHA256 upload tidak cocok" in error for error in result["errors"])
