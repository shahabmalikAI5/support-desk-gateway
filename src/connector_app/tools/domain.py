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

                await cur.execute(
                    "SELECT COUNT(*), COALESCE(array_agg(id ORDER BY id), '{}') "
                    "FROM attachments WHERE ticket_id = %s",
                    (id,),
                )
                att_row = await cur.fetchone()
                att_count = att_row[0] if att_row else 0
                att_ids = att_row[1] if att_row and att_row[1] else []

                await log_audit(pool, sub, "domain_get_ticket", f"id={id}", f"found ticket {id}")
                return {
                    "id": row[0], "subject": row[1], "body": row[2],
                    "priority": row[3], "status": row[4], "created_by": row[5],
                    "created_at": row[6].isoformat() if row[6] else None,
                    "assigned_to": row[7],
                    "updated_at": row[8].isoformat() if row[8] else None,
                    "category": row[9],
                    "attachment_count": att_count,
                    "attachment_ids": att_ids,
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

                if row is not None:
                    content = row[0] if isinstance(row[0], dict) else {}
                    await log_audit(pool, sub, "domain_get_order", f"id={id}", "found in catalog")
                    return {**content, "id": id, "source": "catalog", "_reminder": reminder}

        shop_token = os.environ.get("SHOPIFY_ACCESS_TOKEN")
        shop_domain = os.environ.get("SHOPIFY_STORE_DOMAIN")
        if not shop_token or not shop_domain:
            return {"message": "not found", "_reminder": reminder}

        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{shop_domain}/admin/api/2024-07/orders/{id}.json",
                headers={"X-Shopify-Access-Token": shop_token},
                timeout=10.0,
            )
            if resp.status_code == 200:
                shopify_order = resp.json().get("order", {})
                items = [li.get("name", "") for li in shopify_order.get("line_items", [])]
                total = float(shopify_order.get("total_price", 0))
                content = {
                    "customer": shopify_order.get("customer", {}).get("name", ""),
                    "items": items,
                    "total": total,
                    "currency": shopify_order.get("currency", "USD"),
                    "status": shopify_order.get("fulfillment_status", "unknown") or "pending",
                    "ordered_at": shopify_order.get("created_at"),
                }
                if shopify_order.get("fulfillments"):
                    f = shopify_order["fulfillments"][0]
                    content["tracking_number"] = f.get("tracking_number", "")
                    content["carrier"] = (f.get("tracking_company") or
                                          (f.get("tracking_numbers") or [""])[0])
                await log_audit(pool, sub, "domain_get_order", f"id={id}", "found on shopify")
                return {**content, "id": id, "source": "shopify", "_reminder": reminder}
            return {"message": "not found", "_reminder": reminder}
    except Exception:
        return {"error": "Live order lookup temporarily unavailable. Local catalog returned: not found.", "source": "catalog_only", "_reminder": reminder}


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


async def create_ticket(pool, sub: str, subject: str, body: str, priority: str, reminder: str, *, category: str = "other") -> dict:
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
    valid_categories = {"billing", "returns", "technical", "account", "shipping", "other"}
    if category not in valid_categories:
        return {"error": "category must be one of: billing, returns, technical, account, shipping, other", "_reminder": reminder}

    try:
        ticket_id = f"tkt-{uuid.uuid4().hex[:6]}"
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO tickets (id, subject, body, priority, status, created_by, category) "
                    "VALUES (%s, %s, %s, %s, 'open', %s, %s) RETURNING created_at",
                    (ticket_id, subject.strip(), body.strip(), priority, sub, category),
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

                await cur.execute(
                    "SELECT csat_score FROM tickets WHERE created_by = %s "
                    "AND csat_score IS NOT NULL ORDER BY csat_submitted_at DESC LIMIT 5",
                    (sub,),
                )
                csat_scores = [r[0] for r in await cur.fetchall()]
                csat_trend: str | None = None
                if len(csat_scores) >= 3:
                    trend_sum = sum(
                        csat_scores[i] - csat_scores[i + 1]
                        for i in range(len(csat_scores) - 1)
                    )
                    if trend_sum > 0:
                        csat_trend = "improving"
                    elif trend_sum < 0:
                        csat_trend = "declining"
                    else:
                        csat_trend = "stable"
                elif len(csat_scores) > 0:
                    csat_trend = "stable"

        await log_audit(pool, sub, "domain_get_customer_profile", "", f"open={open_tickets} total={total_tickets}")
        return {
            "open_tickets": open_tickets, "total_tickets": total_tickets,
            "avg_resolution_time_hours": avg_hours, "csat_score": csat,
            "sla_breaches": sla_breaches, "account_age_days": account_age,
            "last_contact_at": last_contact, "csat_trend": csat_trend,
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


# ── Validation helpers for v2 tools ─────────────────────────────────────────

_TRANSITIONS: dict[str, list[str]] = {
    "open": ["triaged"],
    "triaged": ["open", "in_progress"],
    "in_progress": ["pending", "resolved"],
    "pending": ["in_progress", "resolved"],
    "resolved": ["open", "closed"],
    "closed": [],
}


def validate_transition(current: str, new_status: str) -> bool:
    allowed = _TRANSITIONS.get(current, [])
    return new_status in allowed


# ── v2 / v3 ticket management tools ─────────────────────────────────────────

async def assign_ticket(pool, sub: str, role: str, ticket_id: str, agent: str, reminder: str) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if not agent or not agent.strip():
        return {"error": "agent is required", "_reminder": reminder}
    agent_normalized = agent.strip()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT status, assigned_to, created_by FROM tickets WHERE id = %s FOR UPDATE",
                    (ticket_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                current_status = row[0]
                current_assigned = row[1]
                ticket_creator = row[2]
                if current_status in ("resolved", "closed"):
                    return {"error": "ticket is already resolved — cannot reassign", "_reminder": reminder}
                if current_assigned and current_assigned.strip().lower() == agent_normalized.lower():
                    return {
                        "status": "assigned", "assigned_to": current_assigned,
                        "ticket_status": current_status, "note": "already assigned to this agent",
                        "_reminder": reminder,
                    }
                new_status = "in_progress" if current_status == "open" else current_status
                now_ts = _now_iso()
                await cur.execute(
                    "UPDATE tickets SET assigned_to = %s, assigned_at = %s, status = %s, updated_at = %s, last_activity_at = %s "
                    "WHERE id = %s",
                    (agent_normalized, now_ts, new_status, now_ts, now_ts, ticket_id),
                )
                await cur.execute(
                    "INSERT INTO ticket_notes (ticket_id, author_sub, author_role, body, note_type) "
                    "VALUES (%s, %s, %s, %s, 'system_event')",
                    (ticket_id, sub, role or "staff",
                     f"Ticket assigned to {agent_normalized} (status: {current_status} → {new_status})"),
                )
        if ticket_creator:
            from connector_app.notifications import dispatch as _dispatch
            await _dispatch(ticket_id, "agent_assigned", ticket_creator, pool)
        await log_audit(pool, sub, "domain_assign_ticket", f"ticket={ticket_id},agent={agent_normalized}", "assigned")
        return {
            "ticket_id": ticket_id, "assigned_to": agent_normalized,
            "status": new_status, "assigned_at": _now_iso(),
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def reassign_ticket(pool, sub: str, role: str, ticket_id: str, new_agent: str, reminder: str, *,
                           reason: str | None = None) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT status, assigned_to FROM tickets WHERE id = %s FOR UPDATE",
                    (ticket_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                previous_agent = row[1]
                now_ts = _now_iso()
                await cur.execute(
                    "UPDATE tickets SET assigned_to = %s, assigned_at = %s, updated_at = %s, last_activity_at = %s "
                    "WHERE id = %s",
                    (new_agent.strip(), now_ts, now_ts, now_ts, ticket_id),
                )
                reason_text = f" ({reason})" if reason else ""
                await cur.execute(
                    "INSERT INTO ticket_notes (ticket_id, author_sub, author_role, body, note_type) "
                    "VALUES (%s, %s, %s, %s, 'system_event')",
                    (ticket_id, sub, role or "staff",
                     f"Reassigned from {previous_agent or 'unassigned'} to {new_agent.strip()}{reason_text}"),
                )
        await log_audit(pool, sub, "domain_reassign_ticket",
                        f"ticket={ticket_id},agent={new_agent}", "reassigned")
        return {
            "ticket_id": ticket_id, "assigned_to": new_agent.strip(),
            "previous_agent": previous_agent, "reason": reason,
            "reassigned_at": now_ts, "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def update_ticket(pool, sub: str, role: str, ticket_id: str, reminder: str, *,
                        status: str | None = None, priority: str | None = None,
                        body: str | None = None, category: str | None = None,
                        reply_body: str | None = None) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    valid_categories = {"billing", "returns", "technical", "account", "shipping", "other"}
    if category is not None and category not in valid_categories:
        return {"error": "category must be one of: billing, returns, technical, account, shipping, other", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT status, created_by FROM tickets WHERE id = %s FOR UPDATE",
                    (ticket_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                current_status = row[0]
                ticket_creator = row[1]

                if status is not None and not validate_transition(current_status, status):
                    return {"error": f"cannot transition from {current_status} to {status}", "_reminder": reminder}

                is_reopen = (status == "open" and current_status == "resolved")

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
                    if is_reopen:
                        sets.append("resolved_at = NULL")
                        sets.append("csat_score = NULL")
                        sets.append("freshdesk_synced_at = NULL")
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

                if not sets and reply_body is None:
                    return {"error": "no fields to update", "_reminder": reminder}

                if sets:
                    sets.append("updated_at = %s")
                    params.append(_now_iso())
                    sets.append("last_activity_at = %s")
                    params.append(_now_iso())
                    params.append(ticket_id)

                    await cur.execute(
                        f"UPDATE tickets SET {', '.join(sets)} WHERE id = %s",
                        params,
                    )

                reply_sent = False
                if reply_body:
                    await cur.execute(
                        "INSERT INTO ticket_notes (ticket_id, author_sub, author_role, body, note_type) "
                        "VALUES (%s, %s, %s, %s, 'reply')",
                        (ticket_id, sub, role or "staff", reply_body),
                    )
                    reply_sent = True
                    if ticket_creator:
                        from connector_app.notifications import dispatch
                        event_type = "status_changed" if status else "agent_assigned"
                        await dispatch(ticket_id, event_type, ticket_creator, pool)

        await log_audit(pool, sub, "domain_update_ticket", f"ticket={ticket_id},fields={sets}", "updated")
        result = {"ticket_id": ticket_id, "status": status or current_status, "updated_at": _now_iso()}
        if reply_body:
            result["reply_sent"] = reply_sent
        result["_reminder"] = reminder
        return result
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def submit_csat(pool, sub: str, ticket_id: str, score: int, reminder: str) -> dict:
    if score < 1 or score > 5:
        return {"error": "score must be between 1 and 5", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, status, created_by, csat_score, csat_submitted_at FROM tickets WHERE id = %s FOR UPDATE",
                    (ticket_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}
                if row[2] != sub:
                    return {"message": "not found", "_reminder": reminder}
                if row[1] != "resolved":
                    return {"error": "ticket must be resolved before rating", "_reminder": reminder}
                if row[3] is not None:
                    orig_ts = row[4].isoformat() if row[4] else None
                    return {
                        "csat_score": int(row[3]), "already_rated": True,
                        "submitted_at": orig_ts, "_reminder": reminder,
                    }
                now_ts = _now_iso()
                await cur.execute(
                    "UPDATE tickets SET csat_score = %s, csat_submitted_at = %s, updated_at = %s, last_activity_at = %s "
                    "WHERE id = %s",
                    (score, now_ts, now_ts, now_ts, ticket_id),
                )
        await log_audit(pool, sub, "domain_submit_csat", f"ticket={ticket_id},score={score}", "submitted")
        return {"status": "submitted", "csat_score": score, "_reminder": reminder}
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
                    "SELECT id, subject, body, status, priority, created_by, assigned_to "
                    "FROM tickets WHERE id = %s",
                    (ticket_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                t_subject, t_body, t_status, t_priority = row[1], row[2], row[3], row[4]
                t_creator, t_assigned = row[5], row[6]

                if t_body:
                    keywords = " ".join(t_body.split()[:10])
                    await cur.execute(
                        "SELECT id, content FROM support_embeddings "
                        "WHERE entity_type = 'policy' AND content->>'title' ILIKE %s LIMIT 1",
                        (f"%{keywords[:50]}%",),
                    )
                    policy_row = await cur.fetchone()
                    if policy_row is None:
                        await cur.execute(
                            "SELECT id, content FROM support_embeddings "
                            "WHERE entity_type = 'policy' LIMIT 1",
                        )
                        policy_row = await cur.fetchone()
                else:
                    policy_row = None

                policy_id = policy_row[0] if policy_row else None
                policy_content = policy_row[1] if policy_row else None
                policy_title = policy_content.get("title") if policy_content else None
                policy_excerpt = (policy_content.get("body", "")[:300] if policy_content else None)

                await cur.execute(
                    "SELECT COUNT(*), AVG(csat_score) FROM tickets "
                    "WHERE created_by = %s AND csat_score IS NOT NULL",
                    (t_creator,),
                )
                hist_row = await cur.fetchone()
                hist_count = hist_row[0] if hist_row else 0
                hist_avg = round(float(hist_row[1]), 1) if hist_row and hist_row[1] is not None else None

                customer_history: str | None = None
                if hist_count > 0:
                    customer_history = f"{hist_count} previous tickets"
                    if hist_avg is not None:
                        customer_history += f", CSAT avg {hist_avg}"
                agent_name = t_assigned
                recommended_action: str | None = None
                if not agent_name:
                    recommended_action = "Assign an agent first before drafting a reply."
                elif not t_body:
                    recommended_action = "The ticket has no details yet — ask the customer to provide more information."
                elif policy_id:
                    recommended_action = f"Review {policy_title} ({policy_id}) and respond per policy guidelines."

        await log_audit(pool, sub, "domain_draft_reply", f"ticket={ticket_id}", "context generated")
        return {
            "ticket_id": ticket_id, "customer_name": t_creator,
            "ticket_subject": t_subject, "ticket_body": t_body or "",
            "ticket_status": t_status, "ticket_priority": t_priority,
            "policy_id": policy_id, "policy_title": policy_title,
            "policy_excerpt": policy_excerpt,
            "customer_history": customer_history,
            "agent_name": agent_name,
            "recommended_action": recommended_action,
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


def _period_bounds(period: str) -> tuple[str, str, str]:
    """Return (from_ts, to_ts, interval_label) for a given period."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "today":
        return midnight.isoformat(), now.isoformat(), "today"
    elif period == "yesterday":
        start = midnight - timedelta(days=1)
        return start.isoformat(), midnight.isoformat(), "yesterday"
    elif period == "week":
        start = midnight - timedelta(days=7)
        return start.isoformat(), midnight.isoformat(), "week"
    elif period == "month":
        start = midnight - timedelta(days=30)
        return start.isoformat(), midnight.isoformat(), "month"
    elif period == "quarter":
        start = midnight - timedelta(days=90)
        return start.isoformat(), midnight.isoformat(), "quarter"
    raise ValueError("invalid period")


async def report_summary(pool, sub: str, role: str, period: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if period not in ("today", "yesterday", "week", "month", "quarter"):
        return {"error": "period must be one of: today, yesterday, week, month, quarter", "_reminder": reminder}

    try:
        from_ts, to_ts, _ = _period_bounds(period)
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz",
                    (from_ts, to_ts),
                )
                tickets_created = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE resolved_at >= %s::timestamptz AND resolved_at < %s::timestamptz",
                    (from_ts, to_ts),
                )
                tickets_resolved = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT AVG(EXTRACT(EPOCH FROM (resolved_at - created_at)) / 3600.0) "
                    "FROM tickets WHERE resolved_at >= %s::timestamptz AND resolved_at < %s::timestamptz",
                    (from_ts, to_ts),
                )
                avg_row = await cur.fetchone()
                avg_resolution = round(float(avg_row[0]), 1) if avg_row and avg_row[0] is not None else None

                await cur.execute(
                    "SELECT AVG(csat_score) FROM tickets WHERE csat_score IS NOT NULL "
                    "AND resolved_at >= %s::timestamptz AND resolved_at < %s::timestamptz",
                    (from_ts, to_ts),
                )
                csat_row = await cur.fetchone()
                avg_csat = round(float(csat_row[0]), 1) if csat_row and csat_row[0] is not None else None

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE status NOT IN ('resolved', 'closed') "
                    "AND ((priority = 'critical' AND created_at < %s::timestamptz - INTERVAL '1 hour') "
                    "OR (priority = 'high' AND created_at < %s::timestamptz - INTERVAL '4 hours') "
                    "OR (priority = 'medium' AND created_at < %s::timestamptz - INTERVAL '24 hours') "
                    "OR (priority = 'low' AND created_at < %s::timestamptz - INTERVAL '72 hours'))",
                    (to_ts, to_ts, to_ts, to_ts),
                )
                sla_breaches = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT category, COUNT(*) as cnt FROM tickets "
                    "WHERE category IS NOT NULL AND created_at >= %s::timestamptz AND created_at < %s::timestamptz "
                    "GROUP BY category ORDER BY cnt DESC LIMIT 5",
                    (from_ts, to_ts),
                )
                top_categories = [{"category": r[0], "count": r[1]} for r in await cur.fetchall()]

                await cur.execute(
                    "SELECT priority, COUNT(*) FROM tickets "
                    "WHERE created_at >= %s::timestamptz AND created_at < %s::timestamptz "
                    "GROUP BY priority ORDER BY priority",
                    (from_ts, to_ts),
                )
                by_priority = {r[0]: r[1] for r in await cur.fetchall()}

        await log_audit(pool, sub, "domain_report_summary", f"period={period}", f"created={tickets_created}")
        return {
            "period": period, "from": from_ts, "to": to_ts,
            "tickets_created": tickets_created, "tickets_resolved": tickets_resolved,
            "avg_resolution_time_hours": avg_resolution,
            "avg_csat_score": avg_csat,
            "sla_breaches": sla_breaches,
            "top_categories": top_categories,
            "by_priority": by_priority,
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


async def agent_performance(pool, sub: str, role: str, agent: str, reminder: str, *,
                             period: str | None = None) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if period is not None and period not in ("today", "yesterday", "week", "month", "quarter"):
        return {"error": "period must be one of: today, yesterday, week, month, quarter, or omitted", "_reminder": reminder}
    agent_norm = agent.strip().lower()

    try:
        from_ts = None
        if period:
            from_ts, to_ts, _ = _period_bounds(period)
            time_filter = "AND created_at >= %s::timestamptz AND created_at < %s::timestamptz"
            time_params = [from_ts, to_ts]
        else:
            time_filter = ""
            time_params = []

        base = "SELECT COUNT(*) FROM tickets WHERE LOWER(assigned_to) = %s"
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(base + time_filter, [agent_norm] + time_params)
                tickets_assigned = (await cur.fetchone())[0]

                await cur.execute(
                    base + " AND status IN ('resolved', 'closed')" + time_filter,
                    [agent_norm] + time_params,
                )
                tickets_resolved = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT AVG(EXTRACT(EPOCH FROM (COALESCE(resolved_at, updated_at) - created_at)) / 3600.0) "
                    "FROM tickets WHERE LOWER(assigned_to) = %s AND status IN ('resolved', 'closed')"
                    + time_filter,
                    [agent_norm] + time_params,
                )
                avg_row = await cur.fetchone()
                avg_resolution = round(float(avg_row[0]), 1) if avg_row and avg_row[0] is not None else None

                await cur.execute(
                    "SELECT AVG(csat_score) FROM tickets WHERE LOWER(assigned_to) = %s AND csat_score IS NOT NULL"
                    + time_filter,
                    [agent_norm] + time_params,
                )
                csat_row = await cur.fetchone()
                avg_csat = round(float(csat_row[0]), 1) if csat_row and csat_row[0] is not None else None

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE LOWER(assigned_to) = %s "
                    "AND status NOT IN ('resolved', 'closed')" + time_filter,
                    [agent_norm] + time_params,
                )
                current_open = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE LOWER(assigned_to) = %s "
                    "AND status NOT IN ('resolved', 'closed') "
                    "AND ((priority = 'critical' AND created_at < now() - INTERVAL '1 hour') "
                    "OR (priority = 'high' AND created_at < now() - INTERVAL '4 hours') "
                    "OR (priority = 'medium' AND created_at < now() - INTERVAL '24 hours') "
                    "OR (priority = 'low' AND created_at < now() - INTERVAL '72 hours'))" + time_filter,
                    [agent_norm] + time_params,
                )
                sla_breaches = (await cur.fetchone())[0]

                await cur.execute(
                    "SELECT COUNT(*) FROM tickets WHERE LOWER(assigned_to) = %s "
                    "AND id IN (SELECT DISTINCT ticket_id FROM ticket_notes WHERE note_type = 'system_event' "
                    "AND body ILIKE '%%escalation%%')" + time_filter,
                    [agent_norm] + time_params,
                )
                escalations = (await cur.fetchone())[0]

        await log_audit(pool, sub, "domain_agent_performance", f"agent={agent}", f"assigned={tickets_assigned}")
        return {
            "agent": agent, "period": period or "all_time",
            "tickets_assigned": tickets_assigned, "tickets_resolved": tickets_resolved,
            "avg_resolution_time_hours": avg_resolution,
            "avg_csat_score": avg_csat,
            "sla_breaches": sla_breaches,
            "current_open_tickets": current_open,
            "escalations_handled": escalations,
            "resolution_rate": round(tickets_resolved / tickets_assigned, 2) if tickets_assigned > 0 else 0,
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
    actual_limit = min(limit, 500)
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
                    f"SELECT COUNT(*) FROM audit_log{where}",
                    params,
                )
                total = (await cur.fetchone())[0]

                await cur.execute(
                    f"SELECT id, user_id, tool_name, input_summary, output_summary, created_at "
                    f"FROM audit_log{where} ORDER BY created_at DESC LIMIT %s",
                    params + [actual_limit],
                )
                rows = await cur.fetchall()

        entries = [
            {"id": r[0], "user_id": r[1], "tool_name": r[2],
             "input_summary": r[3], "output_summary": r[4],
             "created_at": r[5].isoformat() if r[5] else None}
            for r in rows
        ]
        await log_audit(pool, sub, "domain_get_audit_log", f"limit={actual_limit}", f"{len(entries)} entries")
        return {"entries": entries, "total_matching": total, "returned": len(entries), "_reminder": reminder}
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
        stored = await _store_file(r2_key, raw_bytes)
        if not stored:
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

                r2_key = row[5]
                now_iso = _now_iso()
                expires_at = datetime.fromisoformat(now_iso).timestamp() + 900
                url_expires_at = datetime.fromtimestamp(expires_at, tz=timezone.utc).isoformat()

        presigned_url = await _presigned_url(r2_key)
        if presigned_url is None and r2_key in _ATTACHMENT_STORE:
            import base64
            await log_audit(pool, sub, "domain_get_attachment", f"attachment={attachment_id}", "retrieved (memory)")
            return {
                "attachment_id": row[0], "ticket_id": row[1], "file_name": row[2],
                "mime_type": row[3], "size_bytes": row[4],
                "file_data": base64.b64encode(_ATTACHMENT_STORE[r2_key]).decode(),
                "uploaded_by": row[6],
                "uploaded_at": row[7].isoformat() if row[7] else None,
                "url_expires_at": url_expires_at,
                "_reminder": reminder,
            }
        await log_audit(pool, sub, "domain_get_attachment", f"attachment={attachment_id}", "retrieved")
        return {
            "attachment_id": row[0], "ticket_id": row[1], "file_name": row[2],
            "mime_type": row[3], "size_bytes": row[4],
            "presigned_url": presigned_url,
            "url_expires_at": url_expires_at,
            "uploaded_by": row[6],
            "uploaded_at": row[7].isoformat() if row[7] else None,
            "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


# ── v3 tools ────────────────────────────────────────────────────────────────

_FD_STATUS_MAP = {"open": 2, "triaged": 2, "in_progress": 3, "pending": 3, "resolved": 4, "closed": 5}
_FD_PRIORITY_MAP = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_FD_STATUS_REVERSE = {3: "pending", 4: "resolved", 5: "closed"}
_FD_PRIORITY_REVERSE = {4: "critical", 3: "high", 2: "medium", 1: "low"}


async def _fd_creds(pool) -> tuple[str | None, str | None]:
    """Read Freshdesk credentials from config store, fall back to env vars."""
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM config WHERE key = 'freshdesk_api_key'")
                r1 = await cur.fetchone()
                await cur.execute("SELECT value FROM config WHERE key = 'freshdesk_domain'")
                r2 = await cur.fetchone()
                if r1 and r2:
                    return r1[0], r2[0]
    except Exception:
        pass
    return os.environ.get("FRESHDESK_API_KEY"), os.environ.get("FRESHDESK_DOMAIN")


async def _fd_request(method: str, path: str, api_key: str, domain: str, json_body: dict | None = None) -> dict | None:
    """Make a Freshdesk API request. Returns parsed JSON or None on failure."""
    import httpx
    auth = httpx.BasicAuth(api_key, "X")
    url = f"https://{domain}.freshdesk.com/api/v2{path}"
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.request(method, url, auth=auth, json=json_body, timeout=15.0)
            if resp.status_code in (200, 201):
                return resp.json()
            return None
    except Exception:
        return None


async def sync_to_freshdesk(pool, sub: str, role: str, ticket_id: str, action: str, reminder: str) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if action not in ("push", "pull", "sync_bi"):
        return {"error": "action must be one of: push, pull, sync_bi", "_reminder": reminder}
    api_key, domain = await _fd_creds(pool)
    if not api_key or not domain:
        return {"error": "Freshdesk not configured", "_reminder": reminder}

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, subject, body, status, priority, created_by, freshdesk_id "
                    "FROM tickets WHERE id = %s", (ticket_id,)
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": reminder}

                tid, subject, body, status, priority, creator, fd_id = row
                now_ts = _now_iso()
                result_fd_id = fd_id

                if action in ("push", "sync_bi"):
                    fd_status = _FD_STATUS_MAP.get(status, 2)
                    fd_priority = _FD_PRIORITY_MAP.get(priority, 2)
                    payload = {
                        "subject": f"[{tid}] {subject}",
                        "description": body or "",
                        "status": fd_status,
                        "priority": fd_priority,
                    }
                    if fd_id:
                        await _fd_request("PUT", f"/tickets/{fd_id}", api_key, domain, payload)
                    else:
                        resp = await _fd_request("POST", "/tickets", api_key, domain, payload)
                        if resp and "id" in resp:
                            fd_id = str(resp["id"])
                            result_fd_id = fd_id
                            await cur.execute(
                                "UPDATE tickets SET freshdesk_id = %s, freshdesk_synced_at = %s WHERE id = %s",
                                (fd_id, now_ts, tid),
                            )

                    if not fd_id:
                        return {"error": "Freshdesk sync unavailable. The ticket was not synced. Try again later.", "_reminder": reminder}

                if action in ("pull", "sync_bi") and fd_id:
                    fd_data = await _fd_request("GET", f"/tickets/{fd_id}", api_key, domain)
                    if fd_data:
                        fd_status_code = fd_data.get("status")
                        if fd_status_code and fd_status_code in _FD_STATUS_REVERSE:
                            new_status = _FD_STATUS_REVERSE[fd_status_code]
                            if new_status in ("resolved", "closed"):
                                await cur.execute(
                                    "UPDATE tickets SET status = %s, freshdesk_synced_at = %s",
                                    (new_status, now_ts),
                                )
                                if new_status == "resolved":
                                    await cur.execute(
                                        "UPDATE tickets SET resolved_at = %s WHERE id = %s",
                                        (now_ts, tid),
                                    )
                                elif new_status == "closed":
                                    await cur.execute(
                                        "UPDATE tickets SET closed_at = %s WHERE id = %s",
                                        (now_ts, tid),
                                    )
                        fd_priority_code = fd_data.get("priority")
                        if fd_priority_code and fd_priority_code in _FD_PRIORITY_REVERSE:
                            new_priority = _FD_PRIORITY_REVERSE[fd_priority_code]
                            await cur.execute(
                                "UPDATE tickets SET priority = %s WHERE id = %s",
                                (new_priority, tid),
                            )

        sync_status = "pushed" if action == "push" else ("pulled" if action == "pull" else "synced")
        await log_audit(pool, sub, "domain_sync_to_freshdesk", f"ticket={ticket_id},action={action}", sync_status)
        return {
            "ticket_id": ticket_id, "freshdesk_id": result_fd_id,
            "sync_status": sync_status, "synced_at": now_ts, "_reminder": reminder,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": reminder}


# ── Internal helpers ─────────────────────────────────────────────────────────

_ATTACHMENT_STORE: dict[str, bytes] = {}


def _r2_client():
    """Create a boto3 S3 client for Cloudflare R2. Returns None if not configured."""
    key_id = os.environ.get("R2_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SECRET_ACCESS_KEY")
    endpoint = os.environ.get("R2_ENDPOINT")
    if not key_id or not secret or not endpoint:
        return None
    import boto3
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=key_id,
        aws_secret_access_key=secret,
    )


async def _store_file(r2_key: str, raw_bytes: bytes) -> bool:
    """Upload bytes to R2. Falls back to in-memory store. Returns True on success."""
    client = _r2_client()
    if client is not None:
        bucket = os.environ.get("R2_BUCKET", "support-desk-attachments")
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, lambda: client.put_object(Bucket=bucket, Key=r2_key, Body=raw_bytes)
            )
            return True
        except Exception:
            return False
    _ATTACHMENT_STORE[r2_key] = raw_bytes
    return True


async def _presigned_url(r2_key: str, expires_in: int = 900) -> str | None:
    """Generate a presigned GET URL from R2. Falls back to None."""
    client = _r2_client()
    if client is not None:
        bucket = os.environ.get("R2_BUCKET", "support-desk-attachments")
        try:
            import asyncio
            loop = asyncio.get_running_loop()
            url = await loop.run_in_executor(
                None,
                lambda: client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": r2_key},
                    ExpiresIn=expires_in,
                ),
            )
            return url
        except Exception:
            return None
    return None