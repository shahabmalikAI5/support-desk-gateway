"""config_* tool implementations."""

from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_rules(pool, sub: str, reminder: str) -> dict:
    from connector_app.config_store import get_rules as _get_rules
    try:
        rules = await _get_rules(pool)
        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_get_rules", "", "ok")
        return {"rules": rules, "_reminder": reminder}
    except Exception:
        rules = await _get_rules(pool)
        return {"rules": rules, "_reminder": reminder}


async def get_persona(pool, sub: str, reminder: str) -> dict:
    from connector_app.config_store import get_persona as _get_persona
    try:
        persona = await _get_persona(pool)
        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_get_persona", "", "ok")
        return {"persona": persona, "_reminder": reminder}
    except Exception:
        persona = await _get_persona(pool)
        return {"persona": persona, "_reminder": reminder}


async def set_rules(pool, sub: str, role: str, rules: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value, updated_at FROM config WHERE key = 'rules'")
                current = await cur.fetchone()
                current_value = current[0] if current else ""
                current_updated = current[1] if current else None

                await cur.execute(
                    "SELECT COALESCE(MAX(version_index), -1) FROM config_history WHERE key = 'rules'"
                )
                max_v = (await cur.fetchone())[0]

                await cur.execute(
                    "INSERT INTO config_history (key, value, version_index, updated_by) VALUES (%s, %s, %s, %s)",
                    ("rules", current_value, max_v + 1, sub),
                )
                await cur.execute(
                    "INSERT INTO config (key, value, updated_at) VALUES ('rules', %s, now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                    (rules,),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_set_rules", f"len={len(rules)}", "saved")
        return {"status": "saved", "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def set_persona(pool, sub: str, role: str, persona: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM config WHERE key = 'persona'")
                current = await cur.fetchone()
                current_value = current[0] if current else ""

                await cur.execute(
                    "SELECT COALESCE(MAX(version_index), -1) FROM config_history WHERE key = 'persona'"
                )
                max_v = (await cur.fetchone())[0]

                await cur.execute(
                    "INSERT INTO config_history (key, value, version_index, updated_by) VALUES (%s, %s, %s, %s)",
                    ("persona", current_value, max_v + 1, sub),
                )
                await cur.execute(
                    "INSERT INTO config (key, value, updated_at) VALUES ('persona', %s, now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                    (persona,),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_set_persona", f"len={len(persona)}", "saved")
        return {"status": "saved", "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def restore_version(pool, sub: str, role: str, key: str, version_index: int, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if key not in ("rules", "persona"):
        return {"error": "key must be 'rules' or 'persona'", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT value FROM config_history WHERE key = %s AND version_index = %s ORDER BY updated_at DESC LIMIT 1",
                    (key, version_index),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                old_value = row[0]
                await cur.execute("SELECT value FROM config WHERE key = %s", (key,))
                current = await cur.fetchone()
                current_value = current[0] if current else ""

                await cur.execute(
                    "SELECT COALESCE(MAX(version_index), -1) FROM config_history WHERE key = %s",
                    (key,),
                )
                max_v = (await cur.fetchone())[0]

                await cur.execute(
                    "INSERT INTO config_history (key, value, version_index, updated_by) VALUES (%s, %s, %s, %s)",
                    (key, current_value, max_v + 1, sub),
                )
                await cur.execute(
                    "INSERT INTO config (key, value, updated_at) VALUES (%s, %s, now()) "
                    "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                    (key, old_value),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_restore_version", f"key={key},version={version_index}", "restored")
        return {"status": "restored", "key": key, "version_index": version_index, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def set_freshdesk_creds(pool, sub: str, role: str, api_key: str, domain: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    from connector_app.tools.domain import log_audit
    await log_audit(pool, sub, "config_set_freshdesk_creds", "", "saved (env vars)")
    return {
        "status": "saved",
        "note": "Freshdesk credentials stored in environment variables. Restart the server for changes to take effect.",
        "_reminder": reminder,
    }


async def set_shopify_creds(pool, sub: str, role: str, access_token: str, store_domain: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    from connector_app.tools.domain import log_audit
    await log_audit(pool, sub, "config_set_shopify_creds", "", "saved (env vars)")
    return {
        "status": "saved",
        "note": "Shopify credentials stored in environment variables. Restart the server for changes to take effect.",
        "_reminder": reminder,
    }