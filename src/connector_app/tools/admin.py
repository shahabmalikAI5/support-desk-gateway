"""admin_* tool implementations — admin-only user role management."""

import random
import string
from datetime import datetime, timezone

_chars = string.ascii_lowercase + string.digits
_VALID_ROLES = {"admin", "staff", "customer", None}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _generate_code(length: int = 8) -> str:
    return "".join(random.choices(_chars, k=length))


async def list_all_tickets(pool, sub: str, role: str, reminder: str) -> dict:
    if role != "admin":
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, subject, priority, status, category, created_by, created_at FROM tickets ORDER BY created_at DESC LIMIT 50"
                )
                rows = await cur.fetchall()
        tickets = [
            {
                "id": r[0],
                "subject": r[1],
                "priority": r[2],
                "status": r[3],
                "category": r[4],
                "created_by": r[5],
                "created_at": r[6].isoformat() if r[6] else None,
            }
            for r in rows
        ]
        return {"tickets": tickets, "total": len(tickets), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def list_users(pool, sub: str, role: str, reminder: str) -> dict:
    if role != "admin":
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, email, role, created_at, last_seen_at FROM users ORDER BY last_seen_at DESC"
                )
                rows = await cur.fetchall()

        users = [
            {
                "id": r[0],
                "email": r[1],
                "role": r[2],
                "created_at": r[3].isoformat() if r[3] else None,
                "last_seen_at": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ]

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "admin_list_users", f"count={len(users)}", "ok")
        return {"users": users, "total": len(users), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def set_user_role(pool, sub: str, role: str, user_id: str, new_role: str, reminder: str) -> dict:
    if role != "admin":
        return {"message": "not found", "_reminder": reminder}
    if new_role not in ("admin", "staff", "customer"):
        return {
            "error": "new_role must be one of: admin, staff, customer",
            "_reminder": reminder,
        }
    if new_role == "customer":
        new_role = None

    if not user_id or not user_id.strip():
        return {"error": "user_id is required", "_reminder": reminder}

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, role FROM users WHERE id = %s", (user_id.strip(),)
                )
                existing = await cur.fetchone()
                if existing is None:
                    return {
                        "error": f"user '{user_id.strip()}' not found — they must connect at least once before a role can be assigned",
                        "_reminder": reminder,
                    }

                old_role = existing[1]
                await cur.execute(
                    "UPDATE users SET role = %s WHERE id = %s", (new_role, user_id.strip())
                )

        from connector_app.tools.domain import log_audit
        await log_audit(
            pool, sub, "admin_set_user_role",
            f"user_id={user_id.strip()},old_role={old_role},new_role={new_role}",
            "updated",
        )
        return {
            "status": "updated",
            "user_id": user_id.strip(),
            "previous_role": old_role,
            "new_role": new_role,
            "updated_at": _now_iso(),
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def get_dashboard_token(pool, sub: str, role: str, session_token: str, base_url: str, reminder: str) -> dict:
    if role != "admin":
        return {"message": "not found", "_reminder": reminder}

    code = _generate_code()
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO admin_codes (code, sub, session_token, created_at) VALUES (%s, %s, %s, now())",
                (code, sub, session_token),
            )

    return {
        "dashboard_url": f"{base_url}/admin",
        "access_code": code,
        "display_instruction": (
            f"Tell the user: 'Go to {base_url}/admin, enter access code {code} "
            "in the Access Code field, and click Enter. The code expires in 60 seconds.'"
        ),
        "_reminder": reminder,
    }
