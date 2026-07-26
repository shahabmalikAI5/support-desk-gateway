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
    if not rules or not rules.strip():
        return {"error": "rules text is required", "_reminder": reminder}
    if len(rules) > 10000:
        return {"error": "rules text exceeds 10000 characters", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM config WHERE key = 'rules'")
                current = await cur.fetchone()
                current_value = current[0] if current else ""

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
                    (rules.strip(),),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_set_rules", f"len={len(rules)}", "saved")
        return {"status": "updated", "key": "rules", "updated_at": _now_iso(), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def set_persona(pool, sub: str, role: str, persona: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if not persona or not persona.strip():
        return {"error": "persona text is required", "_reminder": reminder}
    if len(persona) > 5000:
        return {"error": "persona text exceeds 5000 characters", "_reminder": reminder}
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
                    (persona.strip(),),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_set_persona", f"len={len(persona)}", "saved")
        return {"status": "updated", "key": "persona", "updated_at": _now_iso(), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def restore_version(pool, sub: str, role: str, key: str, version_index: int, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if key not in ("rules", "persona"):
        return {"error": "key must be 'rules' or 'persona'", "_reminder": reminder}
    if version_index == 0:
        return {"error": "version_index 0 is the current version — cannot restore to itself", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COALESCE(MAX(version_index), -1) FROM config_history WHERE key = %s",
                    (key,),
                )
                max_v = (await cur.fetchone())[0]
                if max_v <= 0:
                    return {"error": f"no previous versions available for key '{key}'", "_reminder": reminder}
                if version_index > max_v:
                    return {
                        "error": f"version {version_index} not found for key '{key}' (latest previous version is {max_v})",
                        "_reminder": reminder,
                    }

                await cur.execute(
                    "SELECT value FROM config_history WHERE key = %s AND version_index = %s LIMIT 1",
                    (key, version_index),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"error": f"version {version_index} not found for key '{key}'", "_reminder": reminder}

                old_value = row[0]
                await cur.execute("SELECT value FROM config WHERE key = %s", (key,))
                current = await cur.fetchone()
                current_value = current[0] if current else ""

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
        return {"key": key, "restored_from_version": version_index, "new_version": max_v + 1,
                "restored_at": _now_iso(), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def list_history(pool, sub: str, role: str, key: str, reminder: str) -> dict:
    """List all previous versions of a config key from config_history. Admin only."""
    if role != "admin":
        return {"message": "not found", "_reminder": reminder}
    if key not in ("rules", "persona"):
        return {"error": "key must be 'rules' or 'persona'", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT version_index, updated_by, updated_at FROM config_history WHERE key = %s ORDER BY version_index DESC",
                    (key,),
                )
                rows = await cur.fetchall()

        versions = [
            {
                "version_index": r[0],
                "updated_by": r[1],
                "updated_at": r[2].isoformat() if r[2] else None,
            }
            for r in rows
        ]
        return {"key": key, "versions": versions, "total": len(versions), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def _config_upsert(pool, key: str, value: str) -> None:
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                "INSERT INTO config (key, value, updated_at) VALUES (%s, %s, now()) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
                (key, value),
            )


async def set_freshdesk_creds(pool, sub: str, role: str, api_key: str, domain: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if not api_key:
        return {"error": "api_key is required", "_reminder": reminder}
    if not domain:
        return {"error": "domain is required", "_reminder": reminder}
    try:
        await _config_upsert(pool, "freshdesk_api_key", api_key)
        await _config_upsert(pool, "freshdesk_domain", domain)
        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_set_freshdesk_creds",
                        f"key={api_key[:4]}...,domain={domain}", "saved")
        return {"platform": "freshdesk", "status": "configured", "updated_at": _now_iso(), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def set_shopify_creds(pool, sub: str, role: str, access_token: str, store_domain: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if not access_token:
        return {"error": "access_token is required", "_reminder": reminder}
    if not store_domain:
        return {"error": "store_domain is required", "_reminder": reminder}
    try:
        await _config_upsert(pool, "shopify_access_token", access_token)
        await _config_upsert(pool, "shopify_store_domain", store_domain)
        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "config_set_shopify_creds",
                        "token=****,store_domain={store_domain}", "saved")
        return {"platform": "shopify", "status": "configured", "updated_at": _now_iso(), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}