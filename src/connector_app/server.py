import os
import random
import string
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=False)

import uvicorn
from fastmcp import FastMCP
from fastmcp.server.auth import OAuthProxy
from fastmcp.server.auth.providers.jwt import JWTVerifier
from starlette.applications import Starlette
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Mount, Route

from connector_app import auth as auth_module
from connector_app import session
from connector_app.db import get_pool
from connector_app.config_store import get_rules, get_persona
from connector_app.tools import domain as domain_tools
from connector_app.tools import user as user_tools
from connector_app.tools import config as config_tools
from connector_app import catalog as catalog_tools
from connector_app.tools import admin as admin_tools
from connector_app import role_gate

_REMINDER = "Present every result in the support agent's professional voice — be helpful, precise, and escalate when uncertain."

_auth_disabled = os.environ.get("AUTH_DISABLED", "0") == "1"
_auth_provider = None

_AUTH_PROVIDER_SWITCH = os.environ.get("AUTH_PROVIDER", "clerk").lower()

if _auth_disabled:
    mcp = FastMCP("Support Desk")
elif _AUTH_PROVIDER_SWITCH == "descope":
    from fastmcp.server.auth.providers.descope import DescopeProvider
    _auth_provider = DescopeProvider(
        config_url=os.environ["DESCOPE_CONFIG_URL"],
        base_url=os.environ.get("BASE_URL", "http://localhost:8000"),
        required_scopes=[],
        scopes_supported=["mcp:read", "mcp:write", "admin", "staff"],
    )
    mcp = FastMCP("Support Desk", auth=_auth_provider)
else:
    _token_verifier = JWTVerifier(
        jwks_uri=f"{os.environ['CLERK_ISSUER_URL']}/.well-known/jwks.json",
        issuer=os.environ["CLERK_ISSUER_URL"],
        audience=os.environ["CLERK_CLIENT_ID"],
        required_claims=["sub", "exp"],
    )
    _auth_provider = OAuthProxy(
        issuer_url=os.environ["CLERK_ISSUER_URL"],
        client_id=os.environ["CLERK_CLIENT_ID"],
        client_secret=os.environ["CLERK_CLIENT_SECRET"],
        token_verifier=_token_verifier,
        base_url=os.environ.get("BASE_URL", "http://localhost:8000"),
        scopes_supported=["openid", "profile", "email", "mcp:read", "mcp:write"],
    )
    mcp = FastMCP("Support Desk", auth=_auth_provider)


# ── helpers ────────────────────────────────────────────────────────────────────

def _get_sub() -> str:
    claims = auth_module.get_access_token_claims()
    if claims is not None:
        return claims.get("sub", os.environ.get("DEV_SUB", "dev-user-001"))
    return os.environ.get("DEV_SUB", "dev-user-001")


def _validate_session(session_token: str | None) -> tuple[str | None, str | None, dict | None]:
    try:
        sub, role = session.require_session(session_token)
        return sub, role, None
    except session.SessionError as e:
        return None, None, {"error": str(e), "_reminder": _REMINDER}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_chars = string.ascii_lowercase + string.digits


def _generate_code(length: int = 8) -> str:
    return "".join(random.choices(_chars, k=length))


# ── tools/list role filtering ─────────────────────────────────────────────────

import json as _json

_CUSTOMER_TOOLS = frozenset({
    "health", "begin_session",
    "domain_get_ticket", "domain_get_order", "domain_get_policy", "domain_search",
    "domain_create_ticket", "domain_list_my_tickets", "domain_get_customer_profile",
    "domain_submit_csat", "domain_attach_file", "domain_get_attachment",
    "user_get_profile", "user_save_state", "user_configure_notifications",
    "config_get_rules", "config_get_persona",
})

_STAFF_TOOLS = _CUSTOMER_TOOLS | frozenset({
    "domain_assign_ticket", "domain_reassign_ticket", "domain_update_ticket",
    "domain_draft_reply", "domain_get_audit_log", "domain_sync_to_freshdesk",
})

_ADMIN_TOOLS = _STAFF_TOOLS | frozenset({
    "domain_report_summary", "domain_agent_performance",
    "config_set_rules", "config_set_persona", "config_restore_version",
    "config_set_freshdesk_creds", "config_set_shopify_creds",
    "catalog_set_policy", "catalog_set_order", "catalog_delete_item", "catalog_list_all",
    "admin_list_users", "admin_set_user_role", "config_list_history",
    "admin_get_dashboard_token", "admin_list_all_tickets",
})


def _allowed_tool_names(role: str | None) -> frozenset[str]:
    if role == "admin":
        return _ADMIN_TOOLS
    elif role == "staff":
        return _STAFF_TOOLS
    return _CUSTOMER_TOOLS


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
        role: str | None = os.environ.get("DEV_ROLE")

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT id, role FROM users WHERE id = %s", (sub,))
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
                    if user_row[1] is not None:
                        role = user_row[1]

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
        fallback_role = os.environ.get("DEV_ROLE")
        session_token = session.new_session_token(sub, role=fallback_role)
        return {
            "rules": rules, "persona": persona, "state": {},
            "session_token": session_token, "role": fallback_role, "reminder": _REMINDER,
        }


# ── domain_* tools ────────────────────────────────────────────────────────────

@mcp.tool
async def domain_get_ticket(id: str, session_token: str) -> dict:
    """Retrieve a support ticket by ID. Non-staff users can only see their own tickets."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_ticket(pool, sub, id, _REMINDER, role=role)


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
async def domain_search(query: str, session_token: str, include_my_tickets: bool = False) -> dict:
    """Semantic search across orders, policies, and optionally your own tickets. Returns ranked results by meaning."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.search(pool, sub, query, _REMINDER, include_my_tickets=include_my_tickets)


@mcp.tool
async def domain_create_ticket(subject: str, body: str, priority: str, session_token: str, category: str = "other") -> dict:
    """Create a new support ticket. Category: billing, returns, technical, account, shipping, other (default)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.create_ticket(pool, sub, subject, body, priority, _REMINDER, category=category)


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
async def domain_assign_ticket(ticket_id: str, agent: str, session_token: str) -> dict:
    """Assign a ticket to a support agent. Sets status to in_progress if currently open."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.assign_ticket(pool, sub, role, ticket_id, agent, _REMINDER)


@mcp.tool
async def domain_reassign_ticket(ticket_id: str, new_agent: str, session_token: str, reason: str | None = None) -> dict:
    """Reassign an already-assigned ticket to a different agent. Optionally provide a reason."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.reassign_ticket(pool, sub, role, ticket_id, new_agent, _REMINDER, reason=reason)


@mcp.tool
async def domain_update_ticket(ticket_id: str, session_token: str,
                                status: str | None = None,
                                priority: str | None = None,
                                body: str | None = None,
                                category: str | None = None,
                                reply_body: str | None = None) -> dict:
    """Update a ticket's status, priority, body, category, or send a reply. Validates status transitions."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.update_ticket(pool, sub, role, ticket_id, _REMINDER,
                                             status=status, priority=priority,
                                             body=body, category=category,
                                             reply_body=reply_body)


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


@mcp.tool(auth=None)
async def domain_report_summary(period: str, session_token: str) -> dict:
    """Usage analytics summary for a period: daily, weekly, or monthly."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.report_summary(pool, sub, role, period, _REMINDER)


@mcp.tool
async def domain_agent_performance(agent: str, session_token: str, period: str | None = None) -> dict:
    """Performance metrics for a support agent. Period: today, yesterday, week, month, quarter, or omit for all time."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.agent_performance(pool, sub, role, agent, _REMINDER, period=period)


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
async def domain_attach_file(ticket_id: str, file_name: str, file_data: str, mime_type: str, session_token: str) -> dict:
    """Attach a file to a ticket. file_data is base64-encoded content, mime_type must be image/jpeg, image/png, image/gif, application/pdf, text/plain, or text/csv. Max 10MB, max 10 per ticket."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.attach_file(pool, sub, role, ticket_id, file_name, file_data, mime_type, _REMINDER)


@mcp.tool
async def domain_get_attachment(attachment_id: str, session_token: str) -> dict:
    """Retrieve an attachment by ID. Returns metadata and base64 file data."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.get_attachment(pool, sub, attachment_id, _REMINDER, role=role)


@mcp.tool
async def domain_sync_to_freshdesk(ticket_id: str, session_token: str, action: str = "push") -> dict:
    """Sync a ticket to Freshdesk. action: push (send), pull (fetch), sync_bi (both)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await domain_tools.sync_to_freshdesk(pool, sub, role, ticket_id, action, _REMINDER)


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
async def config_list_history(key: str, session_token: str) -> dict:
    """List all previous versions of rules or persona from config_history (admin only)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await config_tools.list_history(pool, sub, role, key, _REMINDER)


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


# ── catalog_* tools ──────────────────────────────────────────────────────────

@mcp.tool
async def catalog_set_policy(policy_id: str, title: str, body: str, applies_to: str, session_token: str) -> dict:
    """Create or update a policy in the catalog. Generates embedding for semantic search."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await catalog_tools.set_policy(pool, sub, role, policy_id, title, body, applies_to, _REMINDER)


@mcp.tool
async def catalog_set_order(order_id: str, content: dict, session_token: str) -> dict:
    """Create or update an order in the catalog. Generates embedding for semantic search."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await catalog_tools.set_order(pool, sub, role, order_id, content, _REMINDER)


@mcp.tool
async def catalog_delete_item(item_id: str, entity_type: str, session_token: str) -> dict:
    """Delete a catalog item (policy or order)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await catalog_tools.delete_item(pool, sub, role, item_id, entity_type, _REMINDER)


@mcp.tool
async def catalog_list_all(session_token: str, entity_type: str | None = None, limit: int = 50, offset: int = 0) -> dict:
    """List catalog items. entity_type: policy, order, or omit for all. Paginate with limit/offset."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await catalog_tools.list_all(pool, sub, role, entity_type, _REMINDER, limit=limit, offset=offset)


# ── admin_* tools ──────────────────────────────────────────────────────────

@mcp.tool
async def admin_list_users(session_token: str) -> dict:
    """List all users with their assigned roles (admin only)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await admin_tools.list_users(pool, sub, role, _REMINDER)


@mcp.tool
async def admin_set_user_role(user_id: str, new_role: str, session_token: str) -> dict:
    """Set a user's role: admin, staff, or customer. Only admin can use this."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await admin_tools.set_user_role(pool, sub, role, user_id, new_role, _REMINDER)


@mcp.tool
async def admin_get_dashboard_token(session_token: str) -> dict:
    """Get the admin dashboard access token for the web admin console. Admin only."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await admin_tools.get_dashboard_token(
        pool, sub, role, session_token,
        os.environ.get("BASE_URL", "http://localhost:8000"),
        _REMINDER,
    )


@mcp.tool
async def admin_list_all_tickets(session_token: str) -> dict:
    """List all tickets in the system (admin only)."""
    sub, role, err = _validate_session(session_token)
    if err is not None:
        return err
    pool = await get_pool()
    return await admin_tools.list_all_tickets(pool, sub, role, _REMINDER)


# ── Admin dashboard route ─────────────────────────────────────────────────────

_ADMIN_HTML = Path(__file__).resolve().parent.parent.parent / "admin" / "index.html"


async def _admin_page(request):
    return FileResponse(str(_ADMIN_HTML))


# ── Root landing page ────────────────────────────────────────────────────────

async def _root_page(request):
    return JSONResponse({
        "service": "Support Desk Gateway",
        "version": "v2/v3",
        "endpoints": {
            "mcp": "/mcp",
            "admin": "/admin",
            "health": "/health",
            "well_known": "/.well-known/oauth-protected-resource/mcp"
        },
        "docs": "https://github.com/shahabmalikAI5/support-desk-gateway"
    })


# ── Health endpoint ──────────────────────────────────────────────────────────

async def _health_endpoint(request):
    return JSONResponse({"status": "ok"})


# ── Token refresh endpoint ───────────────────────────────────────────────────

async def _token_refresh(request):
    try:
        body = await request.json()
        old_token = body.get("session_token", "")
        sub, role = session.require_session(old_token)
        new_token = session.new_session_token(sub, role=role)
        return JSONResponse({"dashboard_token": new_token, "sub": sub, "role": role})
    except session.SessionError:
        return JSONResponse({"error": "invalid or expired session"}, status_code=401)
    except Exception:
        return JSONResponse({"error": "refresh failed"}, status_code=500)


async def _token_exchange(request):
    try:
        body = await request.json()
        secret = body.get("secret", "").strip()
        expected = os.environ.get("ADMIN_DASHBOARD_SECRET", "")
        if not secret or secret != expected:
            return JSONResponse({"error": "Invalid secret phrase"}, status_code=401)
        sub = os.environ.get("DEV_SUB", "admin")
        role = "admin"
        token = session.new_session_token(sub, role=role)
        return JSONResponse({"dashboard_token": token, "sub": sub, "role": role})
    except Exception:
        return JSONResponse({"error": "login failed"}, status_code=500)


# ── MCP Admin proxy (dashboard uses session tokens, not Descope JWT) ───────

_TOOL_PROXY = {
    "config_get_rules": config_get_rules,
    "config_get_persona": config_get_persona,
    "config_set_rules": config_set_rules,
    "config_set_persona": config_set_persona,
    "config_restore_version": config_restore_version,
    "config_list_history": config_list_history,
    "config_set_freshdesk_creds": config_set_freshdesk_creds,
    "config_set_shopify_creds": config_set_shopify_creds,
    "catalog_list_all": catalog_list_all,
    "catalog_set_policy": catalog_set_policy,
    "catalog_set_order": catalog_set_order,
    "catalog_delete_item": catalog_delete_item,
    "admin_list_users": admin_list_users,
    "admin_set_user_role": admin_set_user_role,
    "admin_get_dashboard_token": admin_get_dashboard_token,
    "domain_report_summary": domain_report_summary,
    "domain_get_customer_profile": domain_get_customer_profile,
    "domain_get_ticket": domain_get_ticket,
    "domain_get_order": domain_get_order,
    "domain_get_policy": domain_get_policy,
    "domain_search": domain_search,
    "domain_get_audit_log": domain_get_audit_log,
    "domain_agent_performance": domain_agent_performance,
    "admin_list_all_tickets": admin_list_all_tickets,
}


async def _mcp_admin(request):
    try:
        body = await request.json()
        tok = body.get("session_token", "")
        sub, role = session.require_session(tok)
    except session.SessionError:
        return JSONResponse({"error": "invalid or expired session"}, status_code=401)

    tool_name = body.get("tool", "")
    args = body.get("args") or {}

    fn = _TOOL_PROXY.get(tool_name)
    if fn is None:
        return JSONResponse({"error": f"unknown tool: {tool_name}"}, status_code=400)

    try:
        result = await fn(**args, session_token=tok)
        if isinstance(result, dict):
            return JSONResponse(result)
        return JSONResponse({"result": result})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


# ── Background sync ──────────────────────────────────────────────────────────

_sync_task = None


@asynccontextmanager
async def _combined_lifespan(app_):
    global _sync_task
    async with _mcp_router.lifespan(app_):
        try:
            from connector_app import sync
            pool = await get_pool()
            _sync_task = sync.start_background_sync(pool)
        except Exception:
            pass
        try:
            yield
        finally:
            if _sync_task is not None:
                _sync_task.cancel()
                _sync_task = None


# ── Starlette deployment ──────────────────────────────────────────────────────

mcp_app = mcp.http_app(path="/mcp", stateless_http=True, json_response=True)
_mcp_router = mcp_app

_routes: list = []

if not _auth_disabled and _auth_provider is not None:
    _routes.extend(_auth_provider.get_well_known_routes(mcp_path="/mcp"))

_routes.append(Route("/", endpoint=_root_page))
_routes.append(Route("/health", endpoint=_health_endpoint, methods=["GET"]))
_routes.append(Route("/admin", endpoint=_admin_page))
_routes.append(Route("/admin/refresh", endpoint=_token_refresh, methods=["POST"]))
_routes.append(Route("/admin/exchange", endpoint=_token_exchange, methods=["POST"]))
_routes.append(Route("/mcp/admin", endpoint=_mcp_admin, methods=["POST"]))
_routes.append(Mount("/", app=mcp_app))

app = Starlette(
    routes=_routes,
    lifespan=_combined_lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))