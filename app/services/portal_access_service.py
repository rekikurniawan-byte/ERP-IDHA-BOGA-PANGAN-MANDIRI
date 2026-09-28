from sqlalchemy import func, select

from app.extensions import db
from app.models.master import Client, ClientPic, DeliveryLocation, Mandor
from app.services.portal_mapping_service import (
    build_portal_external_scope,
    is_portal_external_role,
    list_active_portal_mappings,
)
from app.utils.terms import L


PORTAL_PREVIEW_ROLES = {"OWNER", "ADMIN"}

PORTAL_STATUS_ROWS = [
    {
        "area": "Portal",
        "availability": "READY",
        "label": "Aktif",
        "source": "Portal",
        "note": "Portal siap digunakan sesuai akun masing-masing.",
    },
    {
        "area": L("Akses {client} dan {sub_client}"),
        "availability": "READY",
        "label": "Aktif",
        "source": "Master Data",
        "note": L("Data mengikuti perusahaan, {sub_client_lower}, dan lokasi yang sudah ditentukan admin."),
    },
    {
        "area": L("Akun eksternal {client}/{sub_client}"),
        "availability": "READY",
        "label": "Aktif",
        "source": "Akun",
        "note": "Setiap akun hanya melihat data yang menjadi haknya.",
    },
    {
        "area": "Draft order portal",
        "availability": "READY",
        "label": "Pending admin",
        "source": "Pesanan",
        "note": "Pesanan baru masuk antrian admin sebelum diproses.",
    },
    {
        "area": "Prepayment pelanggan umum",
        "availability": "READY",
        "label": "Guard aktif",
        "source": "Pelanggan",
        "note": "Pelanggan umum wajib membayar di awal sebelum pesanan diproses.",
    },
    {
        "area": "Status order portal",
        "availability": "APPROVAL_REQUIRED",
        "label": "Bertahap",
        "source": "Pesanan",
        "note": "Status pesanan ditampilkan sesuai alur operasional.",
    },
    {
        "area": "Invoice/payment portal",
        "availability": "APPROVAL_REQUIRED",
        "label": "Bertahap",
        "source": "Keuangan",
        "note": "Invoice dan pembayaran ditampilkan sesuai hak akses.",
    },
]


def _empty_scope(role, branch_id, reason):
    return {
        "allowed": False,
        "role": role,
        "branch_id": branch_id,
        "scope_mode": "NO_PORTAL_SCOPE",
        "reason": reason,
        "approval_required": True,
        "approval_note": "Akun belum tersambung ke data pelanggan.",
        "counts": {
            "clients": 0,
            "client_pics": 0,
            "mandors": 0,
            "locations": 0,
        },
        "active_counts": {
            "clients": 0,
            "mandors": 0,
            "locations": 0,
        },
        "distinct_client_from_mandor": 0,
        "client_preview": [],
        "mandor_preview": [],
        "location_preview": [],
    }


def _query_by_ids(model, ids):
    if not ids:
        return model.query.filter(model.id.in_([-1]))
    return model.query.filter(model.id.in_(sorted(ids)))


def _external_queries(user):
    scope = build_portal_external_scope(user)
    return scope, {
        "scope_mode": scope.scope_mode,
        "client_query": _query_by_ids(Client, scope.client_ids),
        "mandor_query": _query_by_ids(Mandor, scope.mandor_ids),
        "location_query": _query_by_ids(DeliveryLocation, scope.delivery_location_ids),
        "client_pic_query": _query_by_ids(ClientPic, scope.client_pic_ids),
    }


def _client_preview(query):
    return [
        {
            "id": client.id,
            "name": client.name,
            "code": client.client_code,
            "is_active": client.is_active,
        }
        for client in query.order_by(Client.name.asc()).limit(5).all()
    ]


def _mandor_preview(query):
    return [
        {
            "id": mandor.id,
            "name": mandor.name,
            "client_id": mandor.client_id,
            "branch_id": mandor.branch_id,
            "is_active": mandor.is_active,
        }
        for mandor in query.order_by(Mandor.name.asc()).limit(5).all()
    ]


def _location_preview(query):
    return [
        {
            "id": location.id,
            "name": location.location_name,
            "mandor_id": location.mandor_id,
            "is_active": location.is_active,
        }
        for location in query.order_by(DeliveryLocation.location_name.asc()).limit(5).all()
    ]


def _scope_queries(role, branch_id):
    if role == "OWNER":
        return {
            "scope_mode": "OWNER_ALL_BRANCH_PREVIEW",
            "client_query": Client.query,
            "mandor_query": Mandor.query,
            "location_query": DeliveryLocation.query,
            "client_pic_query": ClientPic.query,
        }

    branch_client_ids = (
        select(Mandor.client_id)
        .filter(Mandor.branch_id == branch_id)
        .filter(Mandor.client_id.isnot(None))
        .distinct()
    )
    return {
        "scope_mode": "ADMIN_BRANCH_PREVIEW",
        "client_query": Client.query.filter(Client.id.in_(branch_client_ids)),
        "mandor_query": Mandor.query.filter(Mandor.branch_id == branch_id),
        "location_query": DeliveryLocation.query.join(Mandor).filter(Mandor.branch_id == branch_id),
        "client_pic_query": ClientPic.query.filter(ClientPic.client_id.in_(branch_client_ids)),
    }


def _scope_allowed(user):
    role = getattr(user, "role", None)
    branch_id = getattr(user, "branch_id", None)

    if role not in PORTAL_PREVIEW_ROLES:
        return False, role, branch_id, "Akun ini belum memiliki akses portal."

    if role == "ADMIN" and not branch_id:
        return False, role, branch_id, "Cabang admin belum valid."

    return True, role, branch_id, None


def build_portal_access_scope(user):
    """Build portal access preview from master data."""
    role = getattr(user, "role", None)
    if is_portal_external_role(role):
        external_scope, queries = _external_queries(user)
        if not external_scope.allowed:
            return _empty_scope(role, getattr(user, "branch_id", None), external_scope.reason)

        client_query = queries["client_query"]
        mandor_query = queries["mandor_query"]
        location_query = queries["location_query"]
        client_pic_query = queries["client_pic_query"]
        return {
            "allowed": True,
            "role": role,
            "branch_id": getattr(user, "branch_id", None),
            "scope_mode": external_scope.scope_mode,
            "reason": external_scope.reason,
            "approval_required": False,
            "approval_note": "Akses akun aktif.",
            "counts": {
                "clients": client_query.count(),
                "client_pics": client_pic_query.count(),
                "mandors": mandor_query.count(),
                "locations": location_query.count(),
            },
            "active_counts": {
                "clients": client_query.filter(Client.is_active.is_(True)).count(),
                "mandors": mandor_query.filter(Mandor.is_active.is_(True)).count(),
                "locations": location_query.filter(DeliveryLocation.is_active.is_(True)).count(),
            },
            "distinct_client_from_mandor": len(external_scope.client_ids),
            "client_preview": _client_preview(client_query),
            "mandor_preview": _mandor_preview(mandor_query),
            "location_preview": _location_preview(location_query),
        }

    allowed, role, branch_id, reason = _scope_allowed(user)
    if not allowed:
        return _empty_scope(role, branch_id, reason)

    queries = _scope_queries(role, branch_id)
    scope_mode = queries["scope_mode"]
    client_query = queries["client_query"]
    mandor_query = queries["mandor_query"]
    location_query = queries["location_query"]
    client_pic_query = queries["client_pic_query"]

    return {
        "allowed": True,
        "role": role,
        "branch_id": branch_id,
        "scope_mode": scope_mode,
        "reason": "Akses akun aktif.",
        "approval_required": False,
        "approval_note": "Akses mengikuti data yang ditentukan admin.",
        "counts": {
            "clients": client_query.count(),
            "client_pics": client_pic_query.count(),
            "mandors": mandor_query.count(),
            "locations": location_query.count(),
        },
        "active_counts": {
            "clients": client_query.filter(Client.is_active.is_(True)).count(),
            "mandors": mandor_query.filter(Mandor.is_active.is_(True)).count(),
            "locations": location_query.filter(DeliveryLocation.is_active.is_(True)).count(),
        },
        "distinct_client_from_mandor": _distinct_client_from_mandor_count(role, branch_id),
        "client_preview": _client_preview(client_query),
        "mandor_preview": _mandor_preview(mandor_query),
        "location_preview": _location_preview(location_query),
    }


def _distinct_client_from_mandor_count(role, branch_id):
    query = db.session.query(func.count(func.distinct(Mandor.client_id))).filter(Mandor.client_id.isnot(None))
    if role == "ADMIN":
        query = query.filter(Mandor.branch_id == branch_id)
    return query.scalar()


def build_portal_mandor_directory(user, limit=50):
    role = getattr(user, "role", None)
    if is_portal_external_role(role):
        external_scope, queries = _external_queries(user)
        if not external_scope.allowed:
            return {
                "allowed": False,
                "reason": external_scope.reason,
                "scope_mode": external_scope.scope_mode,
                "rows": [],
            }
        rows = []
        for mandor in queries["mandor_query"].order_by(Mandor.name.asc()).limit(limit).all():
            location_query = DeliveryLocation.query.filter(
                DeliveryLocation.id.in_(sorted(external_scope.delivery_location_ids))
            ).filter(DeliveryLocation.mandor_id == mandor.id)
            rows.append(
                {
                    "id": mandor.id,
                    "name": mandor.name,
                    "phone": mandor.phone,
                    "client_id": mandor.client_id,
                    "client_name": mandor.client.name if mandor.client else "-",
                    "branch_id": mandor.branch_id,
                    "is_active": mandor.is_active,
                    "location_count": location_query.count(),
                }
            )
        return {
            "allowed": True,
            "scope_mode": external_scope.scope_mode,
            "rows": rows,
            "limit": limit,
        }

    allowed, role, branch_id, reason = _scope_allowed(user)
    if not allowed:
        return {
            "allowed": False,
            "reason": reason,
            "scope_mode": "NO_PORTAL_SCOPE",
            "rows": [],
        }

    queries = _scope_queries(role, branch_id)
    rows = []
    for mandor in queries["mandor_query"].order_by(Mandor.name.asc()).limit(limit).all():
        location_query = DeliveryLocation.query.filter(DeliveryLocation.mandor_id == mandor.id)
        rows.append(
            {
                "id": mandor.id,
                "name": mandor.name,
                "phone": mandor.phone,
                "client_id": mandor.client_id,
                "client_name": mandor.client.name if mandor.client else "-",
                "branch_id": mandor.branch_id,
                "is_active": mandor.is_active,
                "location_count": location_query.count(),
            }
        )

    return {
        "allowed": True,
        "scope_mode": queries["scope_mode"],
        "rows": rows,
        "limit": limit,
    }


def _portal_mapping_row(mapping):
    return {
        "id": mapping.id,
        "principal_type": mapping.principal_type,
        "access_level": mapping.access_level,
        "client": mapping.client.name if mapping.client else "-",
        "mandor": mapping.mandor.name if mapping.mandor else "-",
        "client_pic": mapping.client_pic.name if mapping.client_pic else "-",
        "delivery_location": mapping.delivery_location.location_name if mapping.delivery_location else "-",
        "is_active": mapping.is_active,
    }


def build_portal_profile(user):
    role = getattr(user, "role", None)
    branch_id = getattr(user, "branch_id", None)

    if is_portal_external_role(role):
        external_scope = build_portal_external_scope(user)
        mappings = list_active_portal_mappings(user)
        return {
            "allowed": external_scope.allowed,
            "role": role,
            "branch_id": branch_id,
            "scope_mode": external_scope.scope_mode,
            "reason": external_scope.reason,
            "access_levels": sorted(external_scope.access_levels),
            "mapping_rows": [_portal_mapping_row(mapping) for mapping in mappings],
            "summary": {
                "clients": len(external_scope.client_ids),
                "client_pics": len(external_scope.client_pic_ids),
                "mandors": len(external_scope.mandor_ids),
                "locations": len(external_scope.delivery_location_ids),
            },
        }

    scope = build_portal_access_scope(user)
    return {
        "allowed": scope["allowed"],
        "role": role,
        "branch_id": branch_id,
        "scope_mode": scope["scope_mode"],
        "reason": scope["reason"],
        "access_levels": ["INTERNAL_PREVIEW"] if scope["allowed"] else [],
        "mapping_rows": [],
        "summary": {
            "clients": scope["counts"]["clients"],
            "client_pics": scope["counts"]["client_pics"],
            "mandors": scope["counts"]["mandors"],
            "locations": scope["counts"]["locations"],
        },
    }


