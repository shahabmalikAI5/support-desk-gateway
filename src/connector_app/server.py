import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.auth.providers.jwt import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from connector_app import auth as auth_module
from connector_app import session
from connector_app.db import get_pool
from connector_app.config_store import get_rules, get_persona

_REMINDER = "Present every result in the support agent's professional voice — be helpful, precise, and escalate when uncertain."


class SupportDeskTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = auth_module.verified_claims(token)
            return AccessToken(
                token=token,
                client_id=claims.get("sub", ""),
                scopes=[],
                claims=claims,
            )
        except auth_module.AuthError:
            return None


_auth_disabled = os.environ.get("AUTH_DISABLED", "0") == "1"

if _auth_disabled:
    mcp = FastMCP("Support Desk")
    _auth_provider = None
else:
    _token_verifier = SupportDeskTokenVerifier()
    _auth_provider = RemoteAuthProvider(
        token_verifier=_token_verifier,
        authorization_servers=[AnyHttpUrl(auth_module.AUTH_ISSUER)],
        base_url=auth_module.RESOURCE_URL,
    )
    mcp = FastMCP("Support Desk", auth=_auth_provider)


# ── helpers ────────────────────────────────────────────────────────────────────

def _get_sub() -> str:
    token = get_access_token()
    if token is not None and token.claims:
        return token.claims.get("sub", os.environ.get("DEV_SUB", "dev-user-001"))
    return os.environ.get("DEV_SUB", "dev-user-001")


def _validate_session(session_token: str | None) -> tuple[str | None, dict | None]:
    try:
        sub = session.require_session(session_token)
        return sub, None
    except session.SessionError as e:
        return None, {"error": str(e), "_reminder": _REMINDER}


async def _log_audit(pool, user_id: str, tool_name: str, input_summary: str, output_summary: str) -> None:
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO audit_log (user_id, tool_name, input_summary, output_summary) VALUES (%s, %s, %s, %s)",
                    (user_id, tool_name, input_summary, output_summary),
                )
    except Exception:
        pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── health (ungated) ──────────────────────────────────────────────────────────

@mcp.tool
async def health() -> dict:
    """Confirm the Support Desk gateway is alive and reachable."""
    return {"status": "ok"}


# ── begin_session (gates everything else) ─────────────────────────────────────

@mcp.tool
async def begin_session() -> dict:
    """Call this FIRST on any new request or new chat. Returns rules, persona, state, and a session token."""
    sub = _get_sub()
    pool = await get_pool()

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM users WHERE id = %s", (sub,))
                user_row = await cur.fetchone()

                if user_row is None:
                    await cur.execute(
                        "INSERT INTO users (id, last_seen_at) VALUES (%s, now())",
                        (sub,),
                    )
                    await cur.execute(
                        "INSERT INTO user_state (user_id, state) VALUES (%s, %s)",
                        (sub, '{}'),
                    )
                else:
                    await cur.execute(
                        "UPDATE users SET last_seen_at = now() WHERE id = %s",
                        (sub,),
                    )

        state: dict = {}
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT state FROM user_state WHERE user_id = %s", (sub,)
                )
                row = await cur.fetchone()
                if row is not None:
                    state = row[0] if isinstance(row[0], dict) else {}

        rules = await get_rules(pool)
        persona = await get_persona(pool)
        session_token = session.new_session_token(sub)

        return {
            "rules": rules,
            "persona": persona,
            "state": {
                "preferred_name": state.get("preferred_name"),
                "last_viewed_item_id": state.get("last_viewed_item_id"),
                "last_action": state.get("last_action"),
                "saved_draft": state.get("saved_draft"),
                "session_started_at": _now_iso(),
            },
            "session_token": session_token,
            "reminder": _REMINDER,
        }
    except Exception:
        rules = await get_rules(pool)
        persona = await get_persona(pool)
        session_token = session.new_session_token(sub)
        return {
            "rules": rules,
            "persona": persona,
            "state": {},
            "session_token": session_token,
            "reminder": _REMINDER,
        }


# ── domain_* tools ────────────────────────────────────────────────────────────

@mcp.tool
async def domain_get_ticket(id: str, session_token: str) -> dict:
    """Retrieve a support ticket by ID from the tickets table."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, subject, body, priority, status, created_by, created_at FROM tickets WHERE id = %s",
                    (id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": _REMINDER}

                await _log_audit(pool, sub, "domain_get_ticket", f"id={id}", f"found ticket {id}")
                return {
                    "id": row[0],
                    "subject": row[1],
                    "body": row[2],
                    "priority": row[3],
                    "status": row[4],
                    "created_by": row[5],
                    "created_at": row[6].isoformat() if row[6] else None,
                    "_reminder": _REMINDER,
                }
    except Exception:
        await _log_audit(pool, sub, "domain_get_ticket", f"id={id}", "error")
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


@mcp.tool
async def domain_get_order(id: str, session_token: str) -> dict:
    """Retrieve an order by ID. Returns customer name, items, total, status, tracking."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT content FROM support_embeddings WHERE id = %s AND entity_type = 'order'",
                    (id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": _REMINDER}

                content = row[0] if isinstance(row[0], dict) else {}
                await _log_audit(pool, sub, "domain_get_order", f"id={id}", f"found order {id}")
                return {**content, "id": id, "_reminder": _REMINDER}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


@mcp.tool
async def domain_get_policy(id: str, session_token: str) -> dict:
    """Retrieve a support or operational policy by ID."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT content FROM support_embeddings WHERE id = %s AND entity_type = 'policy'",
                    (id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return {"message": "not found", "_reminder": _REMINDER}

                content = row[0] if isinstance(row[0], dict) else {}
                await _log_audit(pool, sub, "domain_get_policy", f"id={id}", f"found policy {id}")
                return {**content, "id": id, "_reminder": _REMINDER}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


@mcp.tool
async def domain_search(query: str, session_token: str) -> dict:
    """Semantic search across orders and policies. Returns ranked results by meaning."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    if not query or not query.strip():
        return {"error": "query is required", "_reminder": _REMINDER}

    mistral_key = os.environ.get("MISTRAL_API_KEY")
    if not mistral_key:
        return {"error": "Search temporarily unavailable.", "_reminder": _REMINDER}

    try:
        import httpx

        async with httpx.AsyncClient() as client:
            emb_resp = await client.post(
                "https://api.mistral.ai/v1/embeddings",
                headers={"Authorization": f"Bearer {mistral_key}", "Content-Type": "application/json"},
                json={"model": "mistral-embed", "input": [query]},
                timeout=30.0,
            )
            emb_resp.raise_for_status()
            embedding = emb_resp.json()["data"][0]["embedding"]

        pool = await get_pool()
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, entity_type, content, 1 - (embedding <=> %s::vector) AS similarity "
                    "FROM support_embeddings WHERE embedding IS NOT NULL "
                    "ORDER BY embedding <=> %s::vector LIMIT 10",
                    (embedding, embedding),
                )
                rows = await cur.fetchall()

        results = []
        for row in rows:
            content = row[2] if isinstance(row[2], dict) else {}
            body = content.get("body", "") or content.get("title", "")
            results.append({
                "id": row[0],
                "entity_type": row[1],
                "content": body[:200] if body else "",
                "similarity": round(float(row[3]), 4) if row[3] is not None else 0.0,
            })

        await _log_audit(pool, sub, "domain_search", f"query={query[:100]}", f"{len(results)} results")
        return {"results": results, "_reminder": _REMINDER}
    except Exception:
        return {"error": "Search temporarily unavailable.", "_reminder": _REMINDER}


@mcp.tool
async def domain_create_ticket(subject: str, body: str, priority: str, session_token: str) -> dict:
    """Create a new support ticket on behalf of the current user."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    if not subject or not subject.strip():
        return {"error": "subject is required", "_reminder": _REMINDER}
    if len(subject) > 500:
        return {"error": "subject exceeds 500 characters", "_reminder": _REMINDER}
    if not body or not body.strip():
        return {"error": "body is required", "_reminder": _REMINDER}
    if len(body) > 5000:
        return {"error": "body exceeds 5000 characters", "_reminder": _REMINDER}
    if priority not in ("low", "medium", "high", "critical"):
        return {"error": "priority must be one of: low, medium, high, critical", "_reminder": _REMINDER}

    pool = await get_pool()
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

        created_at = row[0].isoformat() if row and row[0] else _now_iso()
        await _log_audit(pool, sub, "domain_create_ticket", f"subject={subject[:50]}", f"created {ticket_id}")
        return {
            "ticket_id": ticket_id,
            "status": "open",
            "created_at": created_at,
            "_reminder": _REMINDER,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


@mcp.tool
async def domain_list_my_tickets(session_token: str) -> dict:
    """List all tickets created by the current authenticated user."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, subject, status, created_at FROM tickets WHERE created_by = %s ORDER BY created_at DESC",
                    (sub,),
                )
                rows = await cur.fetchall()

        tickets = [
            {
                "id": row[0],
                "subject": row[1],
                "status": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
            }
            for row in rows
        ]
        await _log_audit(pool, sub, "domain_list_my_tickets", "", f"{len(tickets)} tickets")
        return {"tickets": tickets, "_reminder": _REMINDER}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


@mcp.tool
async def domain_get_customer_profile(session_token: str) -> dict:
    """Get the current user's support profile — metrics computed from ticket history."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
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

        await _log_audit(pool, sub, "domain_get_customer_profile", "", f"open={open_tickets} total={total_tickets}")
        return {
            "open_tickets": open_tickets,
            "total_tickets": total_tickets,
            "avg_resolution_time_hours": avg_hours,
            "csat_score": csat,
            "sla_breaches": sla_breaches,
            "account_age_days": account_age,
            "last_contact_at": last_contact,
            "_reminder": _REMINDER,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


# ── user_* tools ──────────────────────────────────────────────────────────────

@mcp.tool
async def user_get_profile(session_token: str) -> dict:
    """Get the current user's saved preferences and state from their last session."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT state FROM user_state WHERE user_id = %s", (sub,)
                )
                row = await cur.fetchone()

        state: dict = row[0] if row and isinstance(row[0], dict) else {}
        await _log_audit(pool, sub, "user_get_profile", "", "ok")
        return {
            "preferred_name": state.get("preferred_name"),
            "last_viewed_item_id": state.get("last_viewed_item_id"),
            "last_action": state.get("last_action"),
            "saved_draft": state.get("saved_draft"),
            "_reminder": _REMINDER,
        }
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


@mcp.tool
async def user_save_state(state: dict, session_token: str) -> dict:
    """Save the current user's session state to persist across chats."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    if not isinstance(state, dict):
        return {"error": "state must be a JSON object", "_reminder": _REMINDER}

    import json
    try:
        state_json = json.dumps(state)
        if len(state_json.encode("utf-8")) > 50 * 1024:
            return {"error": "state exceeds 50KB limit", "_reminder": _REMINDER}
    except (TypeError, ValueError):
        return {"error": "state must be a JSON object", "_reminder": _REMINDER}

    pool = await get_pool()
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "INSERT INTO user_state (user_id, state, updated_at) VALUES (%s, %s::jsonb, now()) "
                    "ON CONFLICT (user_id) DO UPDATE SET state = EXCLUDED.state, updated_at = now()",
                    (sub, state_json),
                )

        await _log_audit(pool, sub, "user_save_state", f"keys={list(state.keys())}", "saved")
        return {"status": "saved", "_reminder": _REMINDER}
    except Exception:
        return {"error": "I cannot access the support system right now.", "_reminder": _REMINDER}


# ── config_* tools ────────────────────────────────────────────────────────────

@mcp.tool
async def config_get_rules(session_token: str) -> dict:
    """Read the current behavioral rules — escalation criteria, response guidelines, fail-closed instruction."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
    try:
        rules = await get_rules(pool)
        await _log_audit(pool, sub, "config_get_rules", "", "ok")
        return {"rules": rules, "_reminder": _REMINDER}
    except Exception:
        rules = await get_rules(pool)
        return {"rules": rules, "_reminder": _REMINDER}


@mcp.tool
async def config_get_persona(session_token: str) -> dict:
    """Read the current assistant persona and voice definition."""
    sub, err = _validate_session(session_token)
    if err is not None:
        return err

    pool = await get_pool()
    try:
        persona = await get_persona(pool)
        await _log_audit(pool, sub, "config_get_persona", "", "ok")
        return {"persona": persona, "_reminder": _REMINDER}
    except Exception:
        persona = await get_persona(pool)
        return {"persona": persona, "_reminder": _REMINDER}


# ── Starlette deployment ──────────────────────────────────────────────────────

mcp_app = mcp.http_app(path="/mcp", stateless_http=True)

_routes: list = []

if not _auth_disabled:

    async def _well_known(request: Request) -> JSONResponse:
        return JSONResponse(auth_module.protected_resource_metadata())

    _routes.append(Route("/.well-known/oauth-protected-resource", _well_known, methods=["GET"]))

_routes.append(Mount("/", app=mcp_app))

app = Starlette(
    routes=_routes,
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
