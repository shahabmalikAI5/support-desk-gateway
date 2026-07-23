"""role_gate.py — role-based access helpers for admin/agent tool gating."""

from connector_app import session

_ADMIN_ROLES = ["admin"]
_STAFF_ROLES = ["admin", "staff"]


def gate_admin(sub: str | None, role: str | None, err: dict | None, reminder: str) -> tuple[str | None, dict | None]:
    """Gate an admin-only tool. Returns (sub, None) or (None, not-found response)."""
    if err is not None:
        return None, err
    if role is None or role not in _ADMIN_ROLES:
        return None, {"message": "not found", "_reminder": reminder}
    return sub, None


def gate_staff(sub: str | None, role: str | None, err: dict | None, reminder: str) -> tuple[str | None, dict | None]:
    """Gate a staff/agent tool. Returns (sub, None) or (None, not-found response)."""
    if err is not None:
        return None, err
    if role is None or role not in _STAFF_ROLES:
        return None, {"message": "not found", "_reminder": reminder}
    return sub, None


def is_admin(role: str | None) -> bool:
    return role is not None and role in _ADMIN_ROLES


def is_staff(role: str | None) -> bool:
    return role is not None and role in _STAFF_ROLES