from dataclasses import dataclass, field

from app.models.master import ClientPic, DeliveryLocation, Mandor
from app.models.system import PortalUserMapping
from app.services.user_management_service import (
    PORTAL_EXTERNAL_ROLES,
    ROLE_PORTAL_CLIENT,
    ROLE_PORTAL_CUSTOMER,
    ROLE_PORTAL_DELEGATE,
    ROLE_PORTAL_SUBCLIENT,
)


PRINCIPAL_CLIENT = "CLIENT"
PRINCIPAL_MANDOR = "MANDOR"
PRINCIPAL_CLIENT_PIC = "CLIENT_PIC"
PRINCIPAL_DELEGATE = "DELEGATE"

ACCESS_READ_ONLY = "READ_ONLY"
ACCESS_DRAFT_ORDER = "DRAFT_ORDER"


@dataclass
class PortalResolvedScope:
    allowed: bool
    role: str | None
    user_id: int | None
    branch_id: int | None
    scope_mode: str
    reason: str | None = None
    access_levels: set[str] = field(default_factory=set)
    client_ids: set[int] = field(default_factory=set)
    mandor_ids: set[int] = field(default_factory=set)
    client_pic_ids: set[int] = field(default_factory=set)
    delivery_location_ids: set[int] = field(default_factory=set)


def is_portal_external_role(role):
    return role in PORTAL_EXTERNAL_ROLES


def list_active_portal_mappings(user):
    user_id = getattr(user, "id", None)
    if not user_id:
        return []
    return (
        PortalUserMapping.query.filter(PortalUserMapping.user_id == user_id)
        .filter(PortalUserMapping.is_active.is_(True))
        .order_by(PortalUserMapping.principal_type.asc(), PortalUserMapping.id.asc())
        .all()
    )


def _add_client_scope(scope, client_id):
    if not client_id:
        return
    scope.client_ids.add(client_id)
    mandors = Mandor.query.filter(Mandor.client_id == client_id).all()
    scope.mandor_ids.update(mandor.id for mandor in mandors)
    if mandors:
        scope.delivery_location_ids.update(
            location.id
            for location in DeliveryLocation.query.filter(
                DeliveryLocation.mandor_id.in_([mandor.id for mandor in mandors])
            ).all()
        )
    scope.client_pic_ids.update(pic.id for pic in ClientPic.query.filter(ClientPic.client_id == client_id).all())


def _add_client_identity(scope, client_id):
    if client_id:
        scope.client_ids.add(client_id)


def _add_mandor_scope(scope, mandor):
    if not mandor:
        return
    scope.mandor_ids.add(mandor.id)
    _add_client_identity(scope, mandor.client_id)
    scope.delivery_location_ids.update(
        location.id for location in DeliveryLocation.query.filter(DeliveryLocation.mandor_id == mandor.id).all()
    )


def _add_location_scope(scope, location):
    if not location:
        return
    scope.delivery_location_ids.add(location.id)
    if location.mandor:
        scope.mandor_ids.add(location.mandor.id)
        _add_client_identity(scope, location.mandor.client_id)


def _apply_mapping(scope, mapping):
    scope.access_levels.add(mapping.access_level or ACCESS_READ_ONLY)

    if mapping.principal_type == PRINCIPAL_CLIENT:
        _add_client_scope(scope, mapping.client_id)
        return

    if mapping.principal_type == PRINCIPAL_MANDOR:
        _add_mandor_scope(scope, mapping.mandor)
        return

    if mapping.principal_type == PRINCIPAL_CLIENT_PIC:
        if mapping.client_pic_id:
            scope.client_pic_ids.add(mapping.client_pic_id)
        _add_client_identity(scope, mapping.client_pic.client_id if mapping.client_pic else mapping.client_id)
        return

    if mapping.principal_type == PRINCIPAL_DELEGATE:
        _add_client_identity(scope, mapping.client_id)
        _add_mandor_scope(scope, mapping.mandor)
        _add_location_scope(scope, mapping.delivery_location)
        if mapping.client_pic_id:
            scope.client_pic_ids.add(mapping.client_pic_id)
        return


def build_portal_external_scope(user):
    role = getattr(user, "role", None)
    branch_id = getattr(user, "branch_id", None)
    user_id = getattr(user, "id", None)

    if not is_portal_external_role(role):
        return PortalResolvedScope(
            allowed=False,
            role=role,
            user_id=user_id,
            branch_id=branch_id,
            scope_mode="NOT_PORTAL_EXTERNAL_ROLE",
            reason="Akun ini belum memiliki akses portal.",
        )

    mappings = list_active_portal_mappings(user)
    if not mappings:
        return PortalResolvedScope(
            allowed=False,
            role=role,
            user_id=user_id,
            branch_id=branch_id,
            scope_mode="NO_ACTIVE_PORTAL_MAPPING",
            reason="User portal belum memiliki mapping aktif. Hubungi admin.",
        )

    if role == ROLE_PORTAL_CLIENT:
        # Client and PT always resolved to this same branch and the same ids;
        # the merge just drops the second label.
        expected_principals = {PRINCIPAL_CLIENT, PRINCIPAL_DELEGATE}
        scope_mode = "PORTAL_CLIENT_SCOPE"
    elif role == ROLE_PORTAL_SUBCLIENT:
        expected_principals = {PRINCIPAL_MANDOR, PRINCIPAL_DELEGATE}
        scope_mode = "PORTAL_SUBCLIENT_SCOPE"
    elif role == ROLE_PORTAL_DELEGATE:
        expected_principals = {PRINCIPAL_CLIENT_PIC, PRINCIPAL_DELEGATE}
        scope_mode = "PORTAL_DELEGATE_SCOPE"
    elif role == ROLE_PORTAL_CUSTOMER:
        expected_principals = {PRINCIPAL_DELEGATE}
        scope_mode = "PORTAL_CUSTOMER_SCOPE"
    else:
        expected_principals = set()
        scope_mode = "PORTAL_CUSTOMER_PENDING_SCOPE"

    scope = PortalResolvedScope(
        allowed=True,
        role=role,
        user_id=user_id,
        branch_id=branch_id,
        scope_mode=scope_mode,
        reason="Akses akun aktif.",
    )

    for mapping in mappings:
        if mapping.principal_type in expected_principals:
            _apply_mapping(scope, mapping)

    if not scope.client_ids and not scope.mandor_ids and not scope.delivery_location_ids:
        scope.allowed = False
        scope.reason = "User portal belum memiliki mapping aktif. Hubungi admin."

    return scope
