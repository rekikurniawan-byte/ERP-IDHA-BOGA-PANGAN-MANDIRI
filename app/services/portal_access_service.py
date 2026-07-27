from sqlalchemy import func, select

from app.extensions import db
from app.models.delivery import Delivery
from app.models.finance import Invoice, Payment, SupplierBill
from app.models.master import Client, ClientPic, DeliveryLocation, Mandor
from app.models.operational import DailyOrder, DailyOrderDetail
from app.models.production import Production


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


def _financial_queries(role, branch_id):
    invoice_query = Invoice.query
    payment_query = Payment.query
    supplier_bill_query = SupplierBill.query
    if role == "ADMIN":
        invoice_query = invoice_query.filter(Invoice.branch_id == branch_id)
        payment_query = payment_query.filter(Payment.branch_id == branch_id)
        supplier_bill_query = supplier_bill_query.filter(SupplierBill.branch_id == branch_id)
    return invoice_query, payment_query, supplier_bill_query


def _sum_or_zero(query, column):
    return query.with_entities(func.coalesce(func.sum(column), 0)).scalar() or 0


def build_portal_financial_visibility(user, limit=10):
    allowed, role, branch_id, reason = _scope_allowed(user)
    if not allowed:
        return {
            "allowed": False,
            "reason": reason,
            "role": role,
            "branch_id": branch_id,
            "scope_mode": "NO_PORTAL_SCOPE",
            "summary": {},
            "recent_invoices": [],
        }

    invoice_query, payment_query, supplier_bill_query = _financial_queries(role, branch_id)
    active_invoice_query = invoice_query.filter(~Invoice.status.in_(["CANCELLED", "VOID"]))
    open_supplier_bill_query = supplier_bill_query.filter(~SupplierBill.status.in_(["PAID", "CANCELLED", "VOID"]))

    recent_invoices = []
    for invoice in active_invoice_query.order_by(Invoice.invoice_date.desc(), Invoice.id.desc()).limit(limit).all():
        recent_invoices.append(
            {
                "invoice_number": invoice.invoice_number,
                "invoice_date": invoice.invoice_date,
                "bill_to": invoice.client_name_snapshot
                or (invoice.client.name if invoice.client else None)
                or (invoice.mandor.name if invoice.mandor else None)
                or "-",
                "status": invoice.status,
                "total_amount": invoice.total_amount,
                "paid_amount": invoice.paid_amount,
                "remaining_amount": invoice.remaining_amount,
            }
        )

    return {
        "allowed": True,
        "reason": None,
        "role": role,
        "branch_id": branch_id,
        "scope_mode": "OWNER_ALL_BRANCH_FINANCIAL_PREVIEW" if role == "OWNER" else "ADMIN_BRANCH_FINANCIAL_PREVIEW",
        "summary": {
            "invoice_count": active_invoice_query.count(),
            "invoice_total": _sum_or_zero(active_invoice_query, Invoice.total_amount),
            "invoice_paid": _sum_or_zero(active_invoice_query, Invoice.paid_amount),
            "invoice_remaining": _sum_or_zero(active_invoice_query, Invoice.remaining_amount),
            "payment_count": payment_query.count(),
            "payment_total": _sum_or_zero(payment_query, Payment.amount),
            "open_supplier_bill_count": open_supplier_bill_query.count(),
            "open_supplier_bill_remaining": _sum_or_zero(open_supplier_bill_query, SupplierBill.remaining_amount),
        },
        "recent_invoices": recent_invoices,
        "limit": limit,
    }


def build_portal_order_status_visibility(user, limit=10):
    allowed, role, branch_id, reason = _scope_allowed(user)
    if not allowed:
        return {
            "allowed": False,
            "reason": reason,
            "role": role,
            "branch_id": branch_id,
            "scope_mode": "NO_PORTAL_SCOPE",
            "summary": {},
            "recent_orders": [],
        }

    order_query = DailyOrder.query
    production_query = Production.query
    delivery_query = Delivery.query
    if role == "ADMIN":
        order_query = order_query.filter(DailyOrder.branch_id == branch_id)
        production_query = production_query.filter(Production.branch_id == branch_id)
        delivery_query = delivery_query.filter(Delivery.branch_id == branch_id)

    detail_query = DailyOrderDetail.query.join(DailyOrder)
    if role == "ADMIN":
        detail_query = detail_query.filter(DailyOrder.branch_id == branch_id)

    recent_orders = []
    for order in order_query.order_by(DailyOrder.order_date.desc(), DailyOrder.id.desc()).limit(limit).all():
        total_qty = sum(int(detail.total_qty or 0) for detail in order.details)
        mandor_count = len({detail.mandor_id for detail in order.details})
        production_count = production_query.filter(Production.production_date == order.order_date).count()
        delivery_count = delivery_query.filter(Delivery.delivery_date == order.order_date).count()
        recent_orders.append(
            {
                "order_number": order.order_number,
                "order_date": order.order_date,
                "status": order.status,
                "is_locked": order.is_locked,
                "total_qty": total_qty,
                "mandor_count": mandor_count,
                "production_count": production_count,
                "delivery_count": delivery_count,
            }
        )

    return {
        "allowed": True,
        "reason": None,
        "role": role,
        "branch_id": branch_id,
        "scope_mode": "OWNER_ALL_BRANCH_ORDER_PREVIEW" if role == "OWNER" else "ADMIN_BRANCH_ORDER_PREVIEW",
        "summary": {
            "order_count": order_query.count(),
            "locked_order_count": order_query.filter(DailyOrder.is_locked.is_(True)).count(),
            "draft_order_count": order_query.filter(DailyOrder.is_locked.is_(False)).count(),
            "total_portion": detail_query.with_entities(func.coalesce(func.sum(DailyOrderDetail.total_qty), 0)).scalar() or 0,
            "production_count": production_query.count(),
            "delivery_count": delivery_query.count(),
        },
        "recent_orders": recent_orders,
        "limit": limit,
    }
