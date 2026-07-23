"""user_* tool implementations."""


async def get_profile(pool, sub: str, reminder: str) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT state FROM user_state WHERE user_id = %s", (sub,)
                )
                row = await cur.fetchone()

        state: dict = row[0] if row and isinstance(row[0], dict) else {}
        return {
            "preferred_name": state.get("preferred_name"),
            "last_viewed_item_id": state.get("last_viewed_item_id"),
            "last_action": state.get("last_action"),
            "saved_draft": state.get("saved_draft"),
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def save_state(pool, sub: str, state: dict, reminder: str) -> dict:
    if not isinstance(state, dict):
        return {"error": "state must be a JSON object", "_reminder": reminder}

    import json
    try:
        state_json = json.dumps(state)
        if len(state_json.encode("utf-8")) > 50 * 1024:
            return {"error": "state exceeds 50KB limit", "_reminder": reminder}
    except (TypeError, ValueError):
        return {"error": "state must be a JSON object", "_reminder": reminder}

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO user_state (user_id, state, updated_at) VALUES (%s, %s::jsonb, now()) "
                    "ON CONFLICT (user_id) DO UPDATE SET state = COALESCE(user_state.state, '{}'::jsonb) || EXCLUDED.state, updated_at = now()",
                    (sub, state_json),
                )
        return {"status": "saved", "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def configure_notifications(pool, sub: str, reminder: str, *,
                                   email: str | None = None,
                                   webhook_url: str | None = None,
                                   events: list[str] | None = None) -> dict:
    valid_events = {"status_changed", "agent_assigned", "resolution", "all"}
    if email is not None and email != "":
        if "@" not in email or "." not in email.split("@")[-1]:
            return {"error": "email is not a valid email address", "_reminder": reminder}
    if webhook_url is not None and webhook_url != "":
        if not webhook_url.startswith("https://"):
            return {"error": "webhook URL must start with https://", "_reminder": reminder}
    if events is not None:
        for e in events:
            if e not in valid_events:
                return {
                    "error": f"unknown event: {e}. Valid events: status_changed, agent_assigned, resolution, all",
                    "_reminder": reminder,
                }
    if email is None and webhook_url is None and events is None:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT email, webhook_url, events FROM notification_config WHERE user_sub = %s",
                    (sub,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"email": None, "webhook_url": None, "events": [], "_reminder": reminder}
                return {
                    "email": row[0], "webhook_url": row[1],
                    "events": row[2] if row[2] else [],
                    "_reminder": reminder,
                }

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT email, webhook_url, events FROM notification_config WHERE user_sub = %s",
                    (sub,),
                )
                existing = await cur.fetchone()

                final_email = email if email is not None else (existing[0] if existing else None)
                final_webhook = webhook_url if webhook_url is not None else (existing[1] if existing else None)
                final_events = events if events is not None else (existing[2] if existing else ["status_changed"])

                if "all" in (final_events or []):
                    final_events = ["status_changed", "agent_assigned", "resolution"]
                if final_events is None:
                    final_events = ["status_changed"]

                await cur.execute(
                    "INSERT INTO notification_config (user_sub, email, webhook_url, events, updated_at) "
                    "VALUES (%s, %s, %s, %s, now()) "
                    "ON CONFLICT (user_sub) DO UPDATE SET "
                    "email = EXCLUDED.email, webhook_url = EXCLUDED.webhook_url, "
                    "events = EXCLUDED.events, updated_at = now()",
                    (sub, final_email, final_webhook, final_events),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "user_configure_notifications", f"events={final_events}", "saved")
        return {"status": "saved", "email": final_email, "events": final_events, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}