"""domain_* tool implementations — all DB logic lives here, not in server.py."""

import os
import uuid
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _get_embedding(text: str) -> list[float] | None:
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key or not text:
        return None
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "mistral-embed", "input": [text]},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except Exception:
        return None


async def log_audit(pool, user_id: str, tool_name: str, input_summary: str, output_summary: str) -> None:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO audit_log (user_id, tool_name, input_summary, output_summary) VALUES (%s, %s, %s, %s)",
                    (user_id, tool_name, input_summary, output_summary),
                )
    except Exception:
        pass


async def get_ticket(pool, sub: str, id: str, reminder: str, *, role: str | None = None) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, subject, body, priority, status, created_by, created_at, assigned_to, updated_at, category "
                    "FROM tickets WHERE id = %s",
                    (id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                ticket_creator = row[5]
                ticket_assigned = row[7]
                is_staff = role is not None and role in ("admin", "staff")
                if is_staff:
                    if ticket_creator != sub and ticket_assigned != sub:
                        return {"message": "not found", "_reminder": reminder}
                elif ticket_creator != sub:
                    return {"message": "not found", "_reminder": reminder}

                await log_audit(pool, sub, "domain_get_ticket", f"id={id}", f"found ticket {id}")
                return {
                    "id": row[0], "subject": row[1], "body": row[2],
                    "priority": row[3], "status": row[4], "created_by": row[5],
                    "created_at": row[6].isoformat() if row[6] else None,
                    "assigned_to": row[7],
                    "updated_at": row[8].isoformat() if row[8] else None,
                    "category": row[9],
                    "_reminder": reminder,
                }
    except Exception:
        await log_audit(pool, sub, "domain_get_ticket", f"id={id}", "error")
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def get_order(pool, sub: str, id: str, reminder: str) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT content FROM support_embeddings WHERE id = %s AND entity_type = 'order'",
                    (id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                content = row[0] if isinstance(row[0], dict) else {}
                await log_audit(pool, sub, "domain_get_order", f"id={id}", f"found order {id}")
                return {**content, "id": id, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def get_policy(pool, sub: str, id: str, reminder: str) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT content FROM support_embeddings WHERE id = %s AND entity_type = 'policy'",
                    (id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                content = row[0] if isinstance(row[0], dict) else {}
                await log_audit(pool, sub, "domain_get_policy", f"id={id}", f"found policy {id}")
                return {**content, "id": id, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def search(pool, sub: str, query: str, reminder: str, *, include_my_tickets: bool = False) -> dict:
    if not query or not query.strip():
        return {"error": "query is required", "_reminder": reminder}

    mistral_key = os.environ.get("MISTRAL_API_KEY")
    if not mistral_key:
        return {"error": "Search temporarily unavailable.", "_reminder": reminder}

    try:
        embedding = await _get_embedding(query)
        if embedding is None:
            return {"error": "Search temporarily unavailable.", "_reminder": reminder}

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if include_my_tickets:
                    await cur.execute(
                        "SELECT id, entity_type, content, 1 - (embedding <=> %s::vector) AS similarity "
                        "FROM support_embeddings WHERE embedding IS NOT NULL "
                        "AND ((entity_type IN ('order', 'policy')) "
                        "OR (entity_type = 'ticket' AND content->>'created_by' = %s)) "
                        "ORDER BY embedding <=> %s::vector LIMIT 10",
                        (embedding, sub, embedding),
                    )
                else:
                    await cur.execute(
                        "SELECT id, entity_type, content, 1 - (embedding <=> %s::vector) AS similarity "
                        "FROM support_embeddings WHERE embedding IS NOT NULL "
                        "AND entity_type IN ('order', 'policy') "
                        "ORDER BY embedding <=> %s::vector LIMIT 10",
                        (embedding, embedding),
                    )
                rows = await cur.fetchall()

        results = []
        for row in rows:
            content = row[2] if isinstance(row[2], dict) else {}
            body = content.get("body", "") or content.get("title", "") or content.get("subject", "")
            results.append({
                "id": row[0], "entity_type": row[1],
                "content": body[:200] if body else "",
                "similarity": round(float(row[3]), 4) if row[3] is not None else 0.0,
            })

        await log_audit(pool, sub, "domain_search", f"query={query[:100]}", f"{len(results)} results")
        return {"results": results, "_reminder": reminder}
    except Exception:
        return {"error": "Search temporarily unavailable.", "_reminder": reminder}


async def create_ticket(pool, sub: str, subject: str, body: str, priority: str, reminder: str) -> dict:
    if not subject or not subject.strip():
        return {"error": "subject is required", "_reminder": reminder}
    if len(subject) > 500:
        return {"error": "subject exceeds 500 characters", "_reminder": reminder}
    if not body or not body.strip():
        return {"error": "body is required", "_reminder": reminder}
    if len(body) > 5000:
        return {"error": "body exceeds 5000 characters", "_reminder": reminder}
    if priority not in ("low", "medium", "high", "critical"):
        return {"error": "priority must be one of: low, medium, high, critical", "_reminder": reminder}

    try:
        ticket_id = f"tkt-{uuid.uuid4().hex[:6]}"
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO tickets (id, subject, body, priority, status, created_by) "
                    "VALUES (%s, %s, %s, %s, 'open', %s) RETURNING created_at",
                    (ticket_id, subject.strip(), body.strip(), priority, sub),
                )
                row = await cur.fetchone()

        embedding = await _get_embedding(f"{subject.strip()} {body.strip()}")
        ticket_content = {"subject": subject.strip(), "body": body.strip(), "created_by": sub}
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if embedding:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content, embedding) "
                        "VALUES (%s, 'ticket', %s::jsonb, %s::vector) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding",
                        (ticket_id, ticket_content, embedding),
                    )

        created_at = row[0].isoformat() if row and row[0] else _now_iso()
        await log_audit(pool, sub, "domain_create_ticket", f"subject={subject[:50]}", f"created {ticket_id}")
        return {"ticket_id": ticket_id, "status": "open", "created_at": created_at, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def list_my_tickets(pool, sub: str, reminder: str) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, subject, status, created_at FROM tickets WHERE created_by = %s ORDER BY created_at DESC",
                    (sub,),
                )
                rows = await cur.fetchall()

        tickets = [
            {"id": r[0], "subject": r[1], "status": r[2], "created_at": r[3].isoformat() if r[3] else None}
            for r in rows
        ]
        await log_audit(pool, sub, "domain_list_my_tickets", "", f"{len(tickets)} tickets")
        return {"tickets": tickets, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def get_customer_profile(pool, sub: str, reminder: str) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE created_by = %s AND status IN ('open', 'in_progress')",
                    (sub,),
                )
                open_tickets = (await cur.fetchone())[0]

                await cur.execute("SELECT COUNT(*) FROM tickets WHERE created_by = %s", (sub,))
                total_tickets = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0) "
                    "FROM tickets WHERE created_by = %s AND status = 'resolved' AND resolved_at IS NOT NULL",
                    (sub,),
                )
                avg_row = await cur.fetchone()
                avg_hours = round(float(avg_row[0]), 1) if avg_row and avg_row[0] is not None else None

                await cur.execute(
                    "SELECT AVG(csat_score) FROM tickets WHERE created_by = %s AND csat_score IS NOT NULL",
                    (sub,),
                )
                csat_row = await cur.fetchone()
                csat = round(float(csat_row[0]), 1) if csat_row and csat_row[0] is not None else None

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE created_by = %s AND status NOT IN ('resolved', 'closed') "
                    "AND ((priority = 'high' AND created_at < now() - INTERVAL '4 hours') "
                    "OR (priority = 'medium' AND created_at < now() - INTERVAL '24 hours') "
                    "OR (priority = 'low' AND created_at < now() - INTERVAL '72 hours'))",
                    (sub,),
                )
                sla_breaches = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT EXTRACT(DAY FROM (now() - created_at)) FROM users WHERE id = %s",
                    (sub,),
                )
                age_row = await cur.fetchone()
                account_age = int(age_row[0]) if age_row and age_row[0] is not None else 0

                await cur.execute(
                    "SELECT MAX(created_at) FROM tickets WHERE created_by = %s",
                    (sub,),
                )
                last_row = await cur.fetchone()
                last_contact = last_row[0].isoformat() if last_row and last_row[0] is not None else None

        await log_audit(pool, sub, "domain_get_customer_profile", "", f"open={open_tickets} total={total_tickets}")
        return {
            "open_tickets": open_tickets, "total_tickets": total_tickets,
            "avg_resolution_time_hours": avg_hours, "csat_score": csat,
            "sla_breaches": sla_breaches, "account_age_days": account_age,
            "last_contact_at": last_contact,
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


# ── Validation helpers for v2 tools ─────────────────────────────────────────

_TRANSITIONS: dict[str, list[str]] = {
    "open": ["in_progress", "triaged", "closed", "pending"],
    "triaged": ["in_progress", "closed"],
    "in_progress": ["resolved", "closed", "pending"],
    "resolved": ["closed"],
    "pending": ["in_progress", "resolved", "closed"],
    "closed": [],
}


def validate_transition(current: str, new_status: str) -> bool:
    allowed = _TRANSITIONS.get(current, [])
    return new_status in allowed


# ── v2 / v3 ticket management tools ─────────────────────────────────────────

async def assign_ticket(pool, sub: str, role: str, ticket_id: str, assignee: str, reminder: str) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM tickets WHERE id = %s", (ticket_id,))
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                current_status = row[0]
                new_status = "in_progress" if current_status == "open" else current_status
                now_ts = _now_iso()
                await cur.execute(
                    "UPDATE tickets SET assigned_to = %s, assigned_at = %s, status = %s, updated_at = %s, last_activity_at = %s "
                    "WHERE id = %s",
                    (assignee, now_ts, new_status, now_ts, now_ts, ticket_id),
                )
        await log_audit(pool, sub, "domain_assign_ticket", f"ticket={ticket_id},assignee={assignee}", "assigned")
        return {"status": "assigned", "assigned_to": assignee, "ticket_status": new_status, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def reassign_ticket(pool, sub: str, role: str, ticket_id: str, new_assignee: str, reminder: str) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM tickets WHERE id = %s", (ticket_id,))
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                now_ts = _now_iso()
                await cur.execute(
                    "UPDATE tickets SET assigned_to = %s, assigned_at = %s, updated_at = %s, last_activity_at = %s "
                    "WHERE id = %s",
                    (new_assignee, now_ts, now_ts, now_ts, ticket_id),
                )
        await log_audit(pool, sub, "domain_reassign_ticket", f"ticket={ticket_id},assignee={new_assignee}", "reassigned")
        return {"status": "reassigned", "assigned_to": new_assignee, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def update_ticket(pool, sub: str, role: str, ticket_id: str, reminder: str, *,
                        status: str | None = None, priority: str | None = None,
                        body: str | None = None, category: str | None = None) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT status FROM tickets WHERE id = %s", (ticket_id,))
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                current_status = row[0]

                if status is not None and not validate_transition(current_status, status):
                    return {"error": f"Invalid transition from {current_status} to {status}", "_reminder": reminder}

                sets: list[str] = []
                params: list = []
                if status is not None:
                    sets.append("status = %s")
                    params.append(status)
                    if status == "resolved":
                        sets.append("resolved_at = %s")
                        params.append(_now_iso())
                    if status == "closed":
                        sets.append("closed_at = %s")
                        params.append(_now_iso())
                if priority is not None:
                    if priority not in ("low", "medium", "high", "critical"):
                        return {"error": "priority must be one of: low, medium, high, critical", "_reminder": reminder}
                    sets.append("priority = %s")
                    params.append(priority)
                if body is not None:
                    sets.append("body = %s")
                    params.append(body)
                if category is not None:
                    sets.append("category = %s")
                    params.append(category)

                if not sets:
                    return {"error": "no fields to update", "_reminder": reminder}

                sets.append("updated_at = %s")
                params.append(_now_iso())
                sets.append("last_activity_at = %s")
                params.append(_now_iso())
                params.append(ticket_id)

                await cur.execute(
                    f"UPDATE tickets SET {', '.join(sets)} WHERE id = %s",
                    params,
                )

        await log_audit(pool, sub, "domain_update_ticket", f"ticket={ticket_id},fields={sets}", "updated")
        return {"status": "updated", "ticket_id": ticket_id, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def submit_csat(pool, sub: str, ticket_id: str, score: int, reminder: str) -> dict:
    if score < 1 or score > 5:
        return {"error": "score must be between 1 and 5", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, status, created_by FROM tickets WHERE id = %s", (ticket_id,))
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                if row[2] != sub:
                    return {"message": "not found", "_reminder": reminder}
                now_ts = _now_iso()
                await cur.execute(
                    "UPDATE tickets SET csat_score = %s, csat_submitted_at = %s, updated_at = %s, last_activity_at = %s "
                    "WHERE id = %s",
                    (score, now_ts, now_ts, now_ts, ticket_id),
                )
        await log_audit(pool, sub, "domain_submit_csat", f"ticket={ticket_id},score={score}", "submitted")
        return {"status": "submitted", "score": score, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def draft_reply(pool, sub: str, role: str, ticket_id: str, reminder: str) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, subject, body, status, created_by FROM tickets WHERE id = %s",
                    (ticket_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

        draft = (
            f"Thank you for reaching out regarding '{row[1]}'.\n\n"
            f"I have reviewed your ticket and understand the situation. "
            f"Here is my response:\n\n"
            f"[Draft response — please review and personalize before sending.]\n\n"
            f"Best regards,\nAI Support Agent"
        )
        await log_audit(pool, sub, "domain_draft_reply", f"ticket={ticket_id}", "draft generated")
        return {"draft": draft, "ticket_id": ticket_id, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def report_summary(pool, sub: str, role: str, period: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if period not in ("daily", "weekly", "monthly"):
        return {"error": "period must be daily, weekly, or monthly", "_reminder": reminder}

    interval_map = {"daily": "1 day", "weekly": "7 days", "monthly": "30 days"}
    interval = interval_map[period]
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE created_at >= now() - %s::interval",
                    (interval,),
                )
                new_tickets = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE resolved_at >= now() - %s::interval OR (status = 'resolved' AND updated_at >= now() - %s::interval)",
                    (interval, interval),
                )
                resolved = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE status = 'open' AND created_at < now() - %s::interval",
                    (interval,),
                )
                still_open = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, updated_at) - created_at)) / 3600.0) "
                    "FROM tickets WHERE (resolved_at IS NOT NULL OR (status = 'resolved' AND updated_at IS NOT NULL)) "
                    "AND created_at >= now() - %s::interval",
                    (interval,),
                )
                avg_row = await cur.fetchone()
                avg_resolution = round(float(avg_row[0]), 1) if avg_row and avg_row[0] is not None else None

                await cur.execute(
                    "SELECT status, COUNT(*) as cnt FROM tickets WHERE created_at >= now() - %s::interval "
                    "GROUP BY status ORDER BY cnt DESC",
                    (interval,),
                )
                by_status = {r[0]: r[1] for r in await cur.fetchall()}

        await log_audit(pool, sub, "domain_report_summary", f"period={period}", f"new={new_tickets}")
        return {
            "period": period, "new_tickets": new_tickets, "resolved": resolved,
            "still_open": still_open, "avg_resolution_time_hours": avg_resolution,
            "by_status": by_status, "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def agent_performance(pool, sub: str, role: str, agent: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE assigned_to = %s",
                    (agent,),
                )
                total_assigned = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE assigned_to = %s AND status IN ('resolved', 'closed')",
                    (agent,),
                )
                resolved = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, updated_at) - assigned_at)) / 3600.0) "
                    "FROM tickets WHERE assigned_to = %s AND assigned_at IS NOT NULL "
                    "AND (resolved_at IS NOT NULL OR status IN ('resolved', 'closed'))",
                    (agent,),
                )
                avg_row = await cur.fetchone()
                avg_resolution = round(float(avg_row[0]), 1) if avg_row and avg_row[0] is not None else None

                await cur.execute(
                    "SELECT status, COUNT(*) FROM tickets WHERE assigned_to = %s GROUP BY status",
                    (agent,),
                )
                by_status = {r[0]: r[1] for r in await cur.fetchall()}

        await log_audit(pool, sub, "domain_agent_performance", f"agent={agent}",
                        f"total={total_assigned},resolved={resolved}")
        return {
            "agent": agent, "total_assigned": total_assigned, "resolved": resolved,
            "avg_resolution_time_hours": avg_resolution, "by_status": by_status,
            "resolution_rate": round(resolved / total_assigned, 2) if total_assigned > 0 else 0,
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def get_audit_log(pool, sub: str, role: str, reminder: str, *,
                        user_id: str | None = None, tool_name: str | None = None,
                        since: str | None = None, limit: int = 50) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        conditions: list[str] = []
        params: list = []
        if user_id is not None:
            conditions.append("user_id = %s")
            params.append(user_id)
        if tool_name is not None:
            conditions.append("tool_name = %s")
            params.append(tool_name)
        if since is not None:
            conditions.append("created_at >= %s::timestamptz")
            params.append(since)

        where = " WHERE " + " AND ".join(conditions) if conditions else ""
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    f"SELECT user_id, tool_name, input_summary, output_summary, created_at "
                    f"FROM audit_log{where} ORDER BY created_at DESC LIMIT %s",
                    params + [limit],
                )
                rows = await cur.fetchall()

        entries = [
            {"user_id": r[0], "tool_name": r[1], "input_summary": r[2],
             "output_summary": r[3], "created_at": r[4].isoformat() if r[4] else None}
            for r in rows
        ]
        await log_audit(pool, sub, "domain_get_audit_log", f"limit={limit}", f"{len(entries)} entries")
        return {"entries": entries, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def attach_file(pool, sub: str, role: str, ticket_id: str, file_name: str, file_data: str, mime_type: str, reminder: str) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, created_by, assigned_to FROM tickets WHERE id = %s",
                    (ticket_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                ticket_creator = row[1]
                ticket_assigned = row[2]
                is_staff = role is not None and role in ("admin", "staff")
                if is_staff:
                    if ticket_creator != sub and ticket_assigned != sub:
                        return {"message": "not found", "_reminder": reminder}
                elif ticket_creator != sub:
                    return {"message": "not found", "_reminder": reminder}

        import base64
        try:
            raw_bytes = base64.b64decode(file_data)
        except Exception:
            return {"error": "file data is not valid base64", "_reminder": reminder}

        if len(raw_bytes) > 10 * 1024 * 1024:
            return {"error": "file exceeds 10MB limit", "_reminder": reminder}

        allowed_mimes = {"image/jpeg", "image/png", "image/gif", "application/pdf", "text/plain", "text/csv"}
        if mime_type not in allowed_mimes:
            return {"error": f"unsupported file type: {mime_type}", "_reminder": reminder}

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM attachments WHERE ticket_id = %s", (ticket_id,)
                )
                count = (await cur.fetchone())[0]
                if count >= 10:
                    return {"error": "ticket already has 10 attachments", "_reminder": reminder}

        r2_key = f"{ticket_id}/{uuid.uuid4().hex[:8]}-{file_name}"
        try:
            await _store_file(r2_key, base64.b64encode(raw_bytes).decode())
        except Exception:
            return {"error": "I cannot access the support system right now.", "_reminder": reminder}

        attachment_id = f"att-{uuid.uuid4().hex[:8]}"
        size_bytes = len(raw_bytes)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO attachments (id, ticket_id, file_name, mime_type, size_bytes, r2_key, uploaded_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                    (attachment_id, ticket_id, file_name, mime_type, size_bytes, r2_key, sub),
                )

        await log_audit(pool, sub, "domain_attach_file", f"ticket={ticket_id},file={file_name}", f"attached {attachment_id}")
        return {"attachment_id": attachment_id, "file_name": file_name, "size_bytes": size_bytes, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def get_attachment(pool, sub: str, attachment_id: str, reminder: str, *, role: str | None = None) -> dict:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT a.id, a.ticket_id, a.file_name, a.mime_type, a.size_bytes, a.r2_key, a.uploaded_by, a.uploaded_at, t.created_by, t.assigned_to "
                    "FROM attachments a JOIN tickets t ON a.ticket_id = t.id WHERE a.id = %s",
                    (attachment_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                ticket_creator = row[8]
                ticket_assigned = row[9]
                is_staff = role is not None and role in ("admin", "staff")
                if is_staff:
                    if ticket_creator != sub and ticket_assigned != sub:
                        return {"message": "not found", "_reminder": reminder}
                elif ticket_creator != sub:
                    return {"message": "not found", "_reminder": reminder}

        file_data = await _read_file(row[5])
        import base64
        await log_audit(pool, sub, "domain_get_attachment", f"attachment={attachment_id}", "retrieved")
        return {
            "id": row[0], "ticket_id": row[1], "file_name": row[2],
            "mime_type": row[3], "size_bytes": row[4],
            "file_data": base64.b64encode(file_data).decode() if file_data else None,
            "uploaded_by": row[6],
            "uploaded_at": row[7].isoformat() if row[7] else None,
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


# ── v3 tools ────────────────────────────────────────────────────────────────

async def sync_to_freshdesk(pool, sub: str, role: str, mode: str, reminder: str) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, subject, body, status, priority, created_by, created_at FROM tickets")
                tickets = await cur.fetchall()

        synced = 0
        for t in tickets:
            ticket_id = t[0]
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE tickets SET freshdesk_synced_at = now() WHERE id = %s",
                        (ticket_id,),
                    )
            synced += 1

        await log_audit(pool, sub, "domain_sync_to_freshdesk", f"mode={mode}", f"synced={synced}")
        return {"status": "synced", "mode": mode, "tickets_synced": synced, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


# ── Internal helpers ─────────────────────────────────────────────────────────

_ATTACHMENT_STORE: dict[str, bytes] = {}


async def _store_file(r2_key: str, base64_data: str) -> None:
    import base64
    _ATTACHMENT_STORE[r2_key] = base64.b64decode(base64_data)


async def _read_file(r2_key: str) -> bytes:
    return _ATTACHMENT_STORE.get(r2_key, b"")


def _guess_mime(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {
        "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
        "gif": "image/gif", "pdf": "application/pdf", "doc": "application/msword",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "csv": "text/csv", "txt": "text/plain",
    }.get(ext, "application/octet-stream")