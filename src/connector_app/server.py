import os

from dotenv import load_dotenv

load_dotenv()

import uvicorn
from fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.routing import Mount

from connector_app.db import get_pool
from connector_app.config_store import get_rules, get_persona

_REMINDER = "Present every result in the support agent's professional voice — be helpful, precise, and escalate when uncertain."

mcp = FastMCP("Support Desk")


# ── health (ungated) ──────────────────────────────────────────────────────────

@mcp.tool
async def health() -> dict:
    """Confirm the Support Desk gateway is alive and reachable."""
    return {"status": "ok"}


# ── begin_session (gates everything else) ─────────────────────────────────────

@mcp.tool
async def begin_session() -> dict:
    """Call this FIRST on any new request or new chat. Returns rules, persona, state, and a session token."""
    return {
        "rules": "stub — real rules will come from config store",
        "persona": "stub — real persona will come from config store",
        "state": {},
        "session_token": "stub-session-token",
        "reminder": _REMINDER,
    }


# ── domain_* tools ────────────────────────────────────────────────────────────

@mcp.tool
async def domain_get_ticket(id: str, session_token: str) -> dict:
    """Retrieve a support ticket by ID from the tickets table."""
    return {
        "id": id,
        "subject": "stub",
        "body": "stub",
        "priority": "low",
        "status": "open",
        "created_by": "stub",
        "created_at": "2026-01-01T00:00:00Z",
        "_reminder": _REMINDER,
    }


@mcp.tool
async def domain_get_order(id: str, session_token: str) -> dict:
    """Retrieve an order by ID. Returns customer name, items, total, status, tracking."""
    return {
        "id": id,
        "customer": "stub",
        "items": ["stub"],
        "total": 0.0,
        "currency": "USD",
        "status": "stub",
        "tracking_number": "stub",
        "carrier": "stub",
        "ordered_at": "2026-01-01T00:00:00Z",
        "shipped_at": "2026-01-01T00:00:00Z",
        "estimated_delivery": "2026-01-01",
        "shipping_address": "stub",
        "_reminder": _REMINDER,
    }


@mcp.tool
async def domain_get_policy(id: str, session_token: str) -> dict:
    """Retrieve a support or operational policy by ID."""
    return {
        "id": id,
        "title": "stub",
        "body": "stub",
        "applies_to": "stub",
        "_reminder": _REMINDER,
    }


@mcp.tool
async def domain_search(query: str, session_token: str) -> dict:
    """Semantic search across orders and policies. Returns ranked results by meaning."""
    return {
        "results": [],
        "_reminder": _REMINDER,
    }


@mcp.tool
async def domain_create_ticket(subject: str, body: str, priority: str, session_token: str) -> dict:
    """Create a new support ticket on behalf of the current user."""
    return {
        "ticket_id": "stub-tkt-000",
        "status": "open",
        "created_at": "2026-01-01T00:00:00Z",
        "_reminder": _REMINDER,
    }


@mcp.tool
async def domain_list_my_tickets(session_token: str) -> dict:
    """List all tickets created by the current authenticated user."""
    return {
        "tickets": [],
        "_reminder": _REMINDER,
    }


@mcp.tool
async def domain_get_customer_profile(session_token: str) -> dict:
    """Get the current user's support profile — metrics computed from ticket history."""
    return {
        "open_tickets": 0,
        "total_tickets": 0,
        "avg_resolution_time_hours": 0.0,
        "csat_score": 0.0,
        "sla_breaches": 0,
        "account_age_days": 0,
        "last_contact_at": "2026-01-01T00:00:00Z",
        "_reminder": _REMINDER,
    }


# ── user_* tools ──────────────────────────────────────────────────────────────

@mcp.tool
async def user_get_profile(session_token: str) -> dict:
    """Get the current user's saved preferences and state from their last session."""
    return {
        "preferred_name": None,
        "last_viewed_item_id": None,
        "last_action": None,
        "saved_draft": None,
        "_reminder": _REMINDER,
    }


@mcp.tool
async def user_save_state(state: dict, session_token: str) -> dict:
    """Save the current user's session state to persist across chats."""
    return {
        "status": "saved",
        "_reminder": _REMINDER,
    }


# ── config_* tools ────────────────────────────────────────────────────────────

@mcp.tool
async def config_get_rules(session_token: str) -> dict:
    """Read the current behavioral rules — escalation criteria, response guidelines, fail-closed instruction."""
    return {
        "rules": "stub",
        "_reminder": _REMINDER,
    }


@mcp.tool
async def config_get_persona(session_token: str) -> dict:
    """Read the current assistant persona and voice definition."""
    return {
        "persona": "stub",
        "_reminder": _REMINDER,
    }


# ── Starlette deployment ──────────────────────────────────────────────────────

mcp_app = mcp.http_app(stateless_http=True)

app = Starlette(
    routes=[Mount("/", app=mcp_app)],
    lifespan=mcp_app.lifespan,
)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
