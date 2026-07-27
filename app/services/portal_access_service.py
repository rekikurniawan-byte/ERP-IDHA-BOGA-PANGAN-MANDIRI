from sqlalchemy import func, select

from app.extensions import db
from app.models.master import Client, ClientPic, DeliveryLocation, Mandor
from app.services.portal_mapping_service import build_portal_external_scope, is_portal_external_role


PORTAL_PREVIEW_ROLES = {"OWNER", "ADMIN"}

PORTAL_STATUS_ROWS = [
    {
        "area": "Portal foundation",
        "availability": "READY",
        "label": "Aktif terbatas",
        "source": "Route /portal dan feature flag PORTAL_ENABLED",
        "note": "Shell portal internal tersedia untuk OWNER/ADMIN saat feature flag aktif.",
    },
    {
        "area": "Scope Client/PT dan Mandor",
        "availability": "READY",
        "label": "Read-only",
        "source": "Master Client, Mandor, Client PIC, Delivery Location",
        "note": "Data hanya dibaca dari master existing. Tidak ada create/edit/delete portal.",
    },
    {
        "area": "Akun eksternal Client/PT/Mandor",
        "availability": "READY",
        "label": "Mapping aktif",
        "source": "portal_user_mappings",
        "note": "Role portal memakai auth existing dan scope eksplisit ke client/mandor/PIC/lokasi.",
    },
    {
        "area": "Draft order portal",
        "availability": "APPROVAL_REQUIRED",
        "label": "Belum aktif",
        "source": "Order existing belum dibuka ke portal",
        "note": "Butuh approval karena menyentuh workflow order dan confirmation bridge.",
    },
    {
        "area": "Status order portal",
        "availability": "APPROVAL_REQUIRED",
        "label": "Belum aktif",
        "source": "Order, production, delivery existing",
        "note": "Belum menampilkan data transaksi agar tidak mengubah ekspektasi user eksternal.",
    },
    {
        "area": "Invoice/payment portal",
        "availability": "APPROVAL_REQUIRED",
        "label": "Ditunda",
        "source": "Invoice, payment, receivable existing",
        "note": "Tetap ditunda karena menyentuh data keuangan sensitif.",
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
        "approval_note": "User belum memiliki mapping portal aktif yang cocok dengan role-nya.",
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
        return False, role, branch_id, "Role belum termasuk preview portal internal."

    if role == "ADMIN" and not branch_id:
        return False, role, branch_id, "ADMIN tidak memiliki branch_id yang valid."

    return True, role, branch_id, None


def build_portal_access_scope(user):
    """Build a read-only portal scope preview from existing master data.

    Batch 1B deliberately does not create external-user mappings, roles, or
    transactional access. OWNER receives a global preview; ADMIN receives a
    branch-scoped preview based on mandors in the user's branch.
    """
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
            "approval_note": "Mapping portal aktif. Akses tetap read-only pada batch ini.",
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
        "reason": "Preview read-only dari master data existing.",
        "approval_required": False,
        "approval_note": "OWNER/ADMIN melihat preview internal. User eksternal memakai mapping portal eksplisit.",
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


def build_portal_customer_directory(user, limit=50):
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
        for client in queries["client_query"].order_by(Client.name.asc()).limit(limit).all():
            mandor_query = Mandor.query.filter(Mandor.id.in_(sorted(external_scope.mandor_ids))).filter(
                Mandor.client_id == client.id
            )
            location_query = DeliveryLocation.query.filter(
                DeliveryLocation.id.in_(sorted(external_scope.delivery_location_ids))
            ).join(Mandor).filter(Mandor.client_id == client.id)
            rows.append(
                {
                    "id": client.id,
                    "name": client.name,
                    "code": client.client_code,
                    "phone": client.phone,
                    "is_active": client.is_active,
                    "pic_count": ClientPic.query.filter(ClientPic.id.in_(sorted(external_scope.client_pic_ids))).filter(
                        ClientPic.client_id == client.id
                    ).count(),
                    "mandor_count": mandor_query.count(),
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
    for client in queries["client_query"].order_by(Client.name.asc()).limit(limit).all():
        mandor_query = Mandor.query.filter(Mandor.client_id == client.id)
        location_query = DeliveryLocation.query.join(Mandor).filter(Mandor.client_id == client.id)
        if role == "ADMIN":
            mandor_query = mandor_query.filter(Mandor.branch_id == branch_id)
            location_query = location_query.filter(Mandor.branch_id == branch_id)

        rows.append(
            {
                "id": client.id,
                "name": client.name,
                "code": client.client_code,
                "phone": client.phone,
                "is_active": client.is_active,
                "pic_count": ClientPic.query.filter(ClientPic.client_id == client.id).count(),
                "mandor_count": mandor_query.count(),
                "location_count": location_query.count(),
            }
        )

    return {
        "allowed": True,
        "scope_mode": queries["scope_mode"],
        "rows": rows,
        "limit": limit,
    }


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


def build_portal_status_shell(user):
    role = getattr(user, "role", None)
    if is_portal_external_role(role):
        external_scope = build_portal_external_scope(user)
        rows = [dict(row) for row in PORTAL_STATUS_ROWS]
        return {
            "allowed": external_scope.allowed,
            "reason": external_scope.reason,
            "role": role,
            "branch_id": getattr(user, "branch_id", None),
            "rows": rows,
            "ready_count": sum(1 for row in rows if row["availability"] == "READY"),
            "approval_required_count": sum(1 for row in rows if row["availability"] == "APPROVAL_REQUIRED"),
        }

    allowed, role, branch_id, reason = _scope_allowed(user)
    if not allowed:
        return {
            "allowed": False,
            "reason": reason,
            "role": role,
            "branch_id": branch_id,
            "rows": [],
            "ready_count": 0,
            "approval_required_count": 0,
        }

    rows = [dict(row) for row in PORTAL_STATUS_ROWS]
    return {
        "allowed": True,
        "reason": None,
        "role": role,
        "branch_id": branch_id,
        "rows": rows,
        "ready_count": sum(1 for row in rows if row["availability"] == "READY"),
        "approval_required_count": sum(1 for row in rows if row["availability"] == "APPROVAL_REQUIRED"),
    }


def build_portal_ownership_analysis(user):
    allowed, role, branch_id, reason = _scope_allowed(user)
    if not allowed:
        return {
            "allowed": False,
            "reason": reason,
            "role": role,
            "branch_id": branch_id,
            "summary": {},
            "relationship_rows": [],
            "decision_rows": [],
        }

    queries = _scope_queries(role, branch_id)
    client_query = queries["client_query"]
    mandor_query = queries["mandor_query"]
    location_query = queries["location_query"]
    client_pic_query = queries["client_pic_query"]

    scoped_mandor_client_ids = (
        mandor_query.with_entities(Mandor.client_id)
        .filter(Mandor.client_id.isnot(None))
        .distinct()
        .subquery()
    )
    scoped_location_mandor_ids = (
        location_query.with_entities(DeliveryLocation.mandor_id)
        .filter(DeliveryLocation.mandor_id.isnot(None))
        .distinct()
        .subquery()
    )
    client_count = client_query.count()
    mandor_count = mandor_query.count()
    client_with_mandor_count = db.session.query(func.count()).select_from(scoped_mandor_client_ids).scalar() or 0
    mandor_with_location_count = db.session.query(func.count()).select_from(scoped_location_mandor_ids).scalar() or 0

    summary = {
        "scope_mode": queries["scope_mode"],
        "clients": client_count,
        "client_pics": client_pic_query.count(),
        "mandors": mandor_count,
        "locations": location_query.count(),
        "clients_without_mandor": max(client_count - client_with_mandor_count, 0),
        "mandors_without_location": max(mandor_count - mandor_with_location_count, 0),
    }
    relationship_rows = [
        {
            "principal": "Client/PT",
            "existing_source": "clients",
            "current_link": "Client.id -> Mandor.client_id",
            "portal_readiness": "READ_ONLY_SOURCE",
            "risk": "Belum ada user eksternal yang mengikat satu akun ke satu Client/PT.",
        },
        {
            "principal": "Mandor",
            "existing_source": "mandors",
            "current_link": "Mandor.branch_id, Mandor.client_id",
            "portal_readiness": "READ_ONLY_SOURCE",
            "risk": "Mandor bisa menjadi pemilik portal, tetapi butuh mapping user dan aturan delegasi.",
        },
        {
            "principal": "Client PIC",
            "existing_source": "client_pics",
            "current_link": "ClientPic.client_id",
            "portal_readiness": "CONTACT_ONLY",
            "risk": "PIC saat ini kontak bisnis, belum identitas login/authorization.",
        },
        {
            "principal": "Delivery Location",
            "existing_source": "delivery_locations",
            "current_link": "DeliveryLocation.mandor_id",
            "portal_readiness": "CHILD_SCOPE",
            "risk": "Lokasi boleh terlihat jika mandor/client pemiliknya sudah jelas.",
        },
        {
            "principal": "User internal",
            "existing_source": "users",
            "current_link": "User.branch_id, User.role",
            "portal_readiness": "INTERNAL_ONLY",
            "risk": "Model User belum punya client_id, mandor_id, atau portal principal type.",
        },
    ]
    decision_rows = [
        {
            "decision": "Principal type eksternal",
            "safe_default": "PT, Mandor, Pelanggan Umum, Delegate harus dipilih eksplisit.",
            "status": "APPROVAL_REQUIRED",
        },
        {
            "decision": "Mapping user ke owner data",
            "safe_default": "Tambahkan mapping additive setelah desain disetujui; jangan memakai branch_id saja.",
            "status": "APPROVAL_REQUIRED",
        },
        {
            "decision": "Data yang boleh dibaca",
            "safe_default": "Mulai dari master read-only, bukan order/invoice/payment.",
            "status": "READY_FOR_READ_ONLY",
        },
        {
            "decision": "Mutasi portal",
            "safe_default": "Tetap OFF sampai order/payment ownership test tersedia.",
            "status": "APPROVAL_REQUIRED",
        },
    ]
    return {
        "allowed": True,
        "reason": None,
        "role": role,
        "branch_id": branch_id,
        "summary": summary,
        "relationship_rows": relationship_rows,
        "decision_rows": decision_rows,
    }
