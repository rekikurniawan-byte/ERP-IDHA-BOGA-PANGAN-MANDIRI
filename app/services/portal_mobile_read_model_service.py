from __future__ import annotations


from app.models.master import DeliveryLocation, Worker
from app.services.portal_access_service import build_portal_mandor_directory
from app.services.portal_debt_visibility_service import build_portal_worker_debt_read_model
from app.services.portal_financial_visibility_service import build_portal_invoice_read_model
from app.services.portal_mapping_service import build_portal_external_scope
from app.utils.terms import T


def build_portal_mobile_worker_cards(user, *, limit: int = 100) -> dict:
    scope = build_portal_external_scope(user)
    if not scope.allowed:
        return {
            "allowed": False,
            "scope_mode": scope.scope_mode,
            "reason": scope.reason,
            "workers": [],
            "totals": {"worker_count": 0, "active_count": 0},
        }

    if not scope.mandor_ids:
        query = Worker.query.filter(Worker.id.in_([-1]))
    else:
        query = Worker.query.filter(Worker.mandor_id.in_(sorted(scope.mandor_ids)))

    workers = query.order_by(Worker.full_name.asc(), Worker.id.asc()).limit(limit).all()
    rows = [
        {
            "worker_id": worker.id,
            "worker_code": worker.worker_code,
            "full_name": worker.full_name,
            "phone": worker.phone,
            "status": worker.status,
            "notes": worker.notes,
            "mandor_id": worker.mandor_id,
            "mandor_name": worker.mandor.name if worker.mandor else "-",
        }
        for worker in workers
    ]

    return {
        "allowed": True,
        "scope_mode": scope.scope_mode,
        "reason": f"{T.worker} dibatasi oleh ownership {T.sub_client_lower} portal.",
        "workers": rows,
        "totals": {
            "worker_count": len(rows),
            "active_count": sum(1 for row in rows if str(row["status"] or "").upper() == "ACTIVE"),
        },
    }


def build_portal_mobile_mandor_cards(user, *, limit: int = 100) -> dict:
    directory = build_portal_mandor_directory(user, limit=limit)
    if not directory.get("allowed"):
        return {
            "allowed": False,
            "scope_mode": directory.get("scope_mode"),
            "reason": directory.get("reason"),
            "mandors": [],
            "totals": {"mandor_count": 0, "location_count": 0},
        }

    mandor_ids = [row["id"] for row in directory["rows"]]
    locations_by_mandor = {mandor_id: [] for mandor_id in mandor_ids}
    if mandor_ids:
        locations = (
            DeliveryLocation.query.filter(DeliveryLocation.mandor_id.in_(mandor_ids))
            .order_by(DeliveryLocation.location_name.asc(), DeliveryLocation.id.asc())
            .all()
        )
        for location in locations:
            locations_by_mandor.setdefault(location.mandor_id, []).append(
                {
                    "id": location.id,
                    "name": location.location_name,
                    "description": location.description,
                    "is_active": location.is_active,
                }
            )

    rows = []
    for row in directory["rows"]:
        locations = locations_by_mandor.get(row["id"], [])
        rows.append(
            {
                **row,
                "locations": locations,
                "active_location_count": sum(1 for location in locations if location["is_active"]),
            }
        )

    return {
        "allowed": True,
        "scope_mode": directory.get("scope_mode"),
        "reason": f"{T.sub_client} dan lokasi dibatasi oleh {T.client_lower} ownership mapping.",
        "mandors": rows,
        "totals": {
            "mandor_count": len(rows),
            "location_count": sum(len(row["locations"]) for row in rows),
        },
    }


def build_portal_mobile_invoice_cards(user, *, limit: int = 100) -> dict:
    return build_portal_invoice_read_model(user, limit=limit)


def build_portal_mobile_debt_cards(user, *, limit: int = 100) -> dict:
    return build_portal_worker_debt_read_model(user, limit=limit)


