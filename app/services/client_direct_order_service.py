"""Order langsung untuk client kontrak yang tidak punya sub client.

Setiap order terikat ke sub client (mandor): detail order, pengiriman, lokasi
antar, pekerja, draft portal, dan alokasi HPP semuanya mewajibkan mandor_id.
Keputusan owner 2026-09-25: client yang memesan sendiri mendapat satu sub
client khusus, "PT X — Langsung" (Mandor.is_direct_unit), sehingga seluruh
alur yang sudah ada langsung berlaku tanpa dibongkar.

Unit ini ditagih ke client (bukan ditagih langsung ke mandor), jadi invoice
atas nama PT dengan PIC client dan jatuh tempo mengikuti termin kontrak.
Client boleh punya unit langsung sekaligus sub client biasa.
"""
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.master import Mandor


DIRECT_UNIT_SUFFIX = " — Langsung"


class DirectOrderError(ValueError):
    """Aktivasi order langsung ditolak; pesannya aman ditampilkan."""


def direct_unit_name(client):
    return f"{client.name}{DIRECT_UNIT_SUFFIX}"


def get_direct_unit(branch_id, client_id):
    if not branch_id or not client_id:
        return None
    return Mandor.query.filter_by(
        branch_id=branch_id, client_id=client_id, is_direct_unit=True
    ).first()


def activate_direct_ordering(client, branch_id):
    """Buat unit order langsung untuk client ini di cabang ini.

    Aman diklik dua kali: kalau unitnya sudah ada, unit itu yang dikembalikan.
    Index unik parsial di database menjaga dua klik bersamaan. Mengembalikan
    (unit, dibuat_baru).
    """
    from app.services.master_data_service import create_direct_unit_record

    if not getattr(client, "is_active", True):
        raise DirectOrderError("Client nonaktif tidak bisa diaktifkan order langsungnya.")

    existing = get_direct_unit(branch_id, client.id)
    if existing is not None:
        return existing, False

    name = direct_unit_name(client)
    name_taken = Mandor.query.filter(
        Mandor.branch_id == branch_id, func.lower(Mandor.name) == name.lower()
    ).first()
    if name_taken is not None:
        raise DirectOrderError(
            f"Sudah ada sub client bernama '{name}' di cabang ini. Ganti namanya dulu."
        )

    try:
        unit = create_direct_unit_record(
            branch_id=branch_id, client_id=client.id, name=name, phone=getattr(client, "phone", None),
        )
    except IntegrityError:
        # Klik bersamaan: satu berhasil, yang lain ditolak index unik.
        db.session.rollback()
        existing = get_direct_unit(branch_id, client.id)
        if existing is None:
            raise
        return existing, False
    return unit, True


def direct_unit_ids(mandor_ids):
    """Id unit order langsung di antara mandor_ids (untuk membatasi akses PT)."""
    if not mandor_ids:
        return set()
    return {
        row.id
        for row in Mandor.query.filter(
            Mandor.id.in_(sorted(mandor_ids)), Mandor.is_direct_unit.is_(True)
        ).with_entities(Mandor.id).all()
    }
