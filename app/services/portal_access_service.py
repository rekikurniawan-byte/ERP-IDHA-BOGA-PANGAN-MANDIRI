from sqlalchemy import func, select

from app.extensions import db
from app.models.master import Client, ClientPic, DeliveryLocation, Mandor


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
        "availability": "APPROVAL_REQUIRED",
        "label": "Belum aktif",
        "source": "Belum ada mapping user eksternal yang disetujui",
        "note": "Butuh approval karena menyentuh role, permission, dan ownership data.",
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
        "approval_note": "Mapping user eksternal ke client/mandor/PT belum disetujui.",
        "counts": {
            "clients": 0,
            "client_pics": 0,
            "mandors": 0,
            "locations": 0,
        },
        "client_preview": [],
        "mandor_preview": [],
        "location_preview": [],
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
        "approval_note": "Role eksternal dan mapping portal masih ditunda sampai approval owner.",
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
