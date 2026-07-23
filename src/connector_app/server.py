import os
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth.providers.descope import DescopeProvider
from starlette.applications import Starlette
from starlette.routing import Mount

from connector_app import auth as auth_module
from connector_app import session
from connector_app.db import get_pool
from connector_app.config_store import get_rules, get_persona
from connector_app.tools import domain as domain_tools
from connector_app.tools import user as user_tools
from connector_app.tools import config as config_tools
from connector_app import role_gate

_REMINDER = "Present every result in the support agent's professional voice — be helpful, precise, and escalate when uncertain."

_auth_disabled = os.environ.get("AUTH_DISABLED", "0") == "1"

if _auth_disabled:
    mcp = FastMCP("Support Desk")
else:
    _auth_provider = DescopeProvider(
        config_url=os.environ["DESCOPE_CONFIG_URL"],
        base_url=os.environ.get("BASE_URL", "http://localhost:8000"),
    )
    mcp = FastMCP("Support Desk", auth=_auth_provider)


# ── helpers ────────────────────────────────────────────────────────────────────

def _get_claims() -> tuple[str, str | None]:
    claims = auth_module.get_access_token_claims()
    if claims is not None:
        sub = claims.get("sub", os.environ.get("DEV_SUB", "dev-user-001"))
        role: str | None = None
        raw = claims.get("roles", None)
        if isinstance(raw, list) and len(raw) > 0:
            role = str(raw[0])
        elif isinstance(raw, str):
            role = raw
        if role is None:
            role = claims.get("role", None)
        return sub, role
    return os.environ.get("DEV_SUB", "dev-user-001"), None


def _validate_session(session_token: str | None) -> tuple[str | None, str | None, dict | None]:
    try:
        sub, role = session.require_session(session_token)
        return sub, role, None
    except session.SessionError as e:
        return None, None, {"error": str(e), "_reminder": _REMINDER}


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
    sub, role = _get_claims()
    pool = await get_pool()

    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id FROM users WHERE id = %s", (sub,))
                user_row = await cur.fetchone()

                if user_row is None:
                    await cur.execute(
                        "INSERT INTO users (id, last_seen_at) VALUES (%s, now())", (sub,),
                    )
                    await cur.execute(
                        "INSERT INTO user_state (user_id, state) VALUES (%s, %s)", (sub, '{}'),
                    )
                else:
                    await cur.execute(
                        "UPDATE users SET last_seen_at = now() WHERE id = %s", (sub,),
                    )

        state: dict = {}
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT state FROM user_state WHERE user_id = %s", (sub,))
                row = await cur.fetchone()
                if row is not None:
                    state = row[0] if isinstance(row[0], dict) else {}

        rules = await get_rules(pool)
        persona = await get_persona(pool)
        session_token = session.new_session_token(sub, role=role)

        return {
            "rules": rules, "persona": persona,
            "state": {
                "preferred_name": state.get("preferred_name"),
                "last_viewed_item_id": state.get("last_viewed_item_id"),
                "last_action": state.get("last_action"),
                "saved_draft": state.get("saved_draft"),
                "session_started_at": _now_iso(),
            },
            "session_token": session_token, "role": role, "reminder": _REMINDER,
        }
    except Exception:
        rules = await get_rules(pool)
        persona = await get_persona(pool)
        session_token = session.new_session_token(sub, role=role)
        return {
            "rules": rules, "persona": persona, "state": {},
            "session_token": session_token, "role": role, "reminder": _REMINDER,
        }


# ── domain_* tools ────────────────────────────────────────────────────────────

@mcp.tool
async def domain_get_ticket(id: str, session_token: str) -> dict:
    """Retrieve a support ticket by ID from the tickets table."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_ticket(pool, sub, id, _REMINDER)


@mcp.tool
async def domain_get_order(id: str, session_token: str) -> dict:
    """Retrieve an order by ID. Returns customer name, items, total, status, tracking."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_order(pool, sub, id, _REMINDER)


@mcp.tool
async def domain_get_policy(id: str, session_token: str) -> dict:
    """Retrieve a support or operational policy by ID."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_policy(pool, sub, id, _REMINDER)


@mcp.tool
async def domain_search(query: str, session_token: str) -> dict:
    """Semantic search across orders and policies. Returns ranked results by meaning."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.search(pool, sub, query, _REMINDER)


@mcp.tool
async def domain_create_ticket(subject: str, body: str, priority: str, session_token: str) -> dict:
    """Create a new support ticket on behalf of the current user."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.create_ticket(pool, sub, subject, body, priority, _REMINDER)


@mcp.tool
async def domain_list_my_tickets(session_token: str) -> dict:
    """List all tickets created by the current authenticated user."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.list_my_tickets(pool, sub, _REMINDER)


@mcp.tool
async def domain_get_customer_profile(session_token: str) -> dict:
    """Get the current user's support profile — metrics computed from ticket history."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_customer_profile(pool, sub, _REMINDER)


@mcp.tool
async def domain_assign_ticket(ticket_id: str, assigned_to: str, session_token: str) -> dict:
    """Assign a ticket to a support agent. Sets status to in_progress if currently open."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.assign_ticket(pool, sub, role, ticket_id, assigned_to, _REMINDER)


@mcp.tool
async def domain_reassign_ticket(ticket_id: str, new_assignee: str, session_token: str) -> dict:
    """Reassign an already-assigned ticket to a different agent."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.reassign_ticket(pool, sub, role, ticket_id, new_assignee, _REMINDER)


@mcp.tool
async def domain_update_ticket(ticket_id: str, session_token: str,
                                status: str | None = None,
                                priority: str | None = None,
                                body: str | None = None,
                                category: str | None = None) -> dict:
    """Update a ticket's status, priority, body, or category. Validates status transitions."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.update_ticket(pool, sub, role, ticket_id, _REMINDER,
                                             status=status, priority=priority,
                                             body=body, category=category)


@mcp.tool
async def domain_submit_csat(ticket_id: str, score: int, session_token: str) -> dict:
    """Submit a customer satisfaction score (1-5) for a resolved ticket."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.submit_csat(pool, sub, ticket_id, score, _REMINDER)


@mcp.tool
async def domain_draft_reply(ticket_id: str, session_token: str) -> dict:
    """AI-drafts a reply to a ticket for a human agent to review and send."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.draft_reply(pool, sub, role, ticket_id, _REMINDER)


@mcp.tool
async def domain_report_summary(period: str, session_token: str) -> dict:
    """Usage analytics summary for a period: daily, weekly, or monthly."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.report_summary(pool, sub, role, period, _REMINDER)


@mcp.tool
async def domain_agent_performance(agent: str, session_token: str) -> dict:
    """Performance metrics for a support agent: assigned, resolved, avg time."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.agent_performance(pool, sub, role, agent, _REMINDER)


@mcp.tool
async def domain_get_audit_log(session_token: str,
                                user_id: str | None = None,
                                tool_name: str | None = None,
                                since: str | None = None,
                                limit: int = 50) -> dict:
    """Read the audit log. Optional filters: user_id, tool_name, since (ISO timestamp), limit (max 200)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_audit_log(pool, sub, role, _REMINDER,
                                             user_id=user_id, tool_name=tool_name,
                                             since=since, limit=min(limit, 200))


@mcp.tool
async def domain_attach_file(ticket_id: str, file_name: str, file_data: str, session_token: str) -> dict:
    """Attach a file to a ticket. file_data is base64-encoded content."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.attach_file(pool, sub, role, ticket_id, file_name, file_data, _REMINDER)


@mcp.tool
async def domain_get_attachment(attachment_id: str, session_token: str) -> dict:
    """Retrieve an attachment by ID. Returns metadata and base64 file data."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_attachment(pool, sub, attachment_id, _REMINDER)


@mcp.tool
async def domain_sync_to_freshdesk(mode: str, session_token: str) -> dict:
    """Sync tickets to Freshdesk. mode: 'push' (one-shot) or 'pull' (fetch updates)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.sync_to_freshdesk(pool, sub, role, mode, _REMINDER)


# ── user_* tools ──────────────────────────────────────────────────────────────

@mcp.tool
async def user_get_profile(session_token: str) -> dict:
    """Get the current user's saved preferences and state from their last session."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await user_tools.get_profile(pool, sub, _REMINDER)


@mcp.tool
async def user_save_state(state: dict, session_token: str) -> dict:
    """Save the current user's session state to persist across chats."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await user_tools.save_state(pool, sub, state, _REMINDER)


@mcp.tool
async def user_configure_notifications(session_token: str,
                                        email: str | None = None,
                                        webhook_url: str | None = None,
                                        events: list[str] | None = None) -> dict:
    """Configure email/webhook notifications. events: ticket_status_change, csat_submitted, etc."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await user_tools.configure_notifications(pool, sub, _REMINDER,
                                                     email=email, webhook_url=webhook_url,
                                                     events=events)


# ── config_* tools ────────────────────────────────────────────────────────────

@mcp.tool
async def config_get_rules(session_token: str) -> dict:
    """Read the current behavioral rules — escalation criteria, response guidelines, fail-closed instruction."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.get_rules(pool, sub, _REMINDER)


@mcp.tool
async def config_get_persona(session_token: str) -> dict:
    """Read the current assistant persona and voice definition."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.get_persona(pool, sub, _REMINDER)


@mcp.tool
async def config_set_rules(rules: str, session_token: str) -> dict:
    """Update the behavioral rules. Previous version is saved in history for rollback."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.set_rules(pool, sub, role, rules, _REMINDER)


@mcp.tool
async def config_set_persona(persona: str, session_token: str) -> dict:
    """Update the assistant persona. Previous version is saved in history."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.set_persona(pool, sub, role, persona, _REMINDER)


@mcp.tool
async def config_restore_version(key: str, version_index: int, session_token: str) -> dict:
    """Restore a previous version of rules or persona from config_history."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.restore_version(pool, sub, role, key, version_index, _REMINDER)


@mcp.tool
async def config_set_freshdesk_creds(api_key: str, domain: str, session_token: str) -> dict:
    """Store Freshdesk API credentials (admin only). Requires server restart."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.set_freshdesk_creds(pool, sub, role, api_key, domain, _REMINDER)


@mcp.tool
async def config_set_shopify_creds(access_token: str, store_domain: str, session_token: str) -> dict:
    """Store Shopify API credentials (admin only). Requires server restart."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.set_shopify_creds(pool, sub, role, access_token, store_domain, _REMINDER)


# ── Starlette deployment ──────────────────────────────────────────────────────

mcp_app = mcp.http_app(path="/mcp", stateless_http=True)

_routes: list = []

if not _auth_disabled and _auth_provider is not None:
    _routes.extend(_auth_provider.get_well_known_routes(mcp_path="/mcp"))

_routes.append(Mount("/", app=mcp_app))

app = Starlette(
    routes=_routes,
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))