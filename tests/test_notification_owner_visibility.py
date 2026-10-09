"""OWNER ikut melihat notifikasi yang ditujukan ke ADMIN; role lain tetap terpisah."""
from types import SimpleNamespace

from app.services.notification_service import can_user_access_notification, visible_target_roles


def _user(role, user_id=1, branch_id=1):
    return SimpleNamespace(role=role, id=user_id, branch_id=branch_id, is_authenticated=True)


def _notification(target_role=None, target_user_id=None, branch_id=1):
    return SimpleNamespace(target_role=target_role, target_user_id=target_user_id, branch_id=branch_id)


def test_owner_sees_admin_and_owner_targets_only():
    assert {"OWNER", "ADMIN"} <= visible_target_roles("OWNER")
    assert "DAPUR" not in visible_target_roles("OWNER")
    assert "PORTAL_CUSTOMER" not in visible_target_roles("OWNER")


def test_admin_notification_visible_to_owner_not_to_kitchen_or_portal():
    admin_note = _notification(target_role="ADMIN")
    assert can_user_access_notification(admin_note, _user("OWNER"))
    assert can_user_access_notification(admin_note, _user("ADMIN"))
    assert not can_user_access_notification(admin_note, _user("DAPUR"))
    assert not can_user_access_notification(admin_note, _user("PORTAL_CUSTOMER"))


def test_owner_still_cannot_see_other_users_personal_notification():
    personal = _notification(target_user_id=99)
    assert not can_user_access_notification(personal, _user("OWNER", user_id=1))
