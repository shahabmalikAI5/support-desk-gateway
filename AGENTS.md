# Support Desk Gateway — Agent Brief (v1 Complete, v2/v3 Ready)

You build; the human directs and verifies. Write the code, run it, show the command and its
output, and prove each step before the next. When the live MCP / FastMCP / provider docs disagree
with anything here, **the live docs win** — say so and adjust.

---

## What We Built (v1)

A single remote MCP server — a "Support Desk Gateway" — that any Claude user adds with one connector
URL and one Descope Authorize click. The user's chat app brings the model and the loop; this server
brings tools, persistent state across chats, and verified multi-user identity. There is **no agent loop**
in this project (that's v4).

### Tools (13 total, 3 groups)

| Group | Tools | Purpose |
|---|---|---|
| Ungated | `health`, `begin_session` | Liveness check; session gate (must be called first) |
| **domain_\*** | `get_ticket`, `get_order`, `get_policy`, `search`, `create_ticket`, `list_my_tickets`, `get_customer_profile` | Support desk: lookup tickets/orders/policies, semantic search, create/list tickets, customer metrics |
| **user_\*** | `get_profile`, `save_state` | Cross-chat memory: preferences persisted in Neon, restored next session |
| **config_\*** | `get_rules`, `get_persona` | Behavioral config from DB: escalation criteria, voice, fail-closed rules |

### How it works

```
claude.ai (model + loop)
    │  OAuth 2.1 PKCE S256 (Descope DCR)
    ▼
Descope Agentic Identity Hub → JWT (aud = tunnel URL)
    │  Bearer token
    ▼
Cloudflare quick-tunnel → 127.0.0.1:8000
    │
Starlette + FastMCP (DescopeProvider)
    │  └─ session.py (HS256 internal gate)
    │
Neon PostgreSQL (6 tables)
    ├─ users, user_state          (identity + cross-chat state)
    ├─ tickets                    (support tickets, seed + user-created)
    ├─ support_embeddings         (orders/policies with pgvector)
    ├─ config                     (rules, persona — editable without deploy)
    └─ audit_log                  (tool call audit trail)
```

---

## Current State (v1 Complete)

### Files

```
src/connector_app/
├── __init__.py           # package marker
├── auth.py               # GIVEN — OAuth 4 checks (read, never regenerate)
├── session.py            # GIVEN — session token gate (read, never regenerate)
├── server.py             # FastMCP app, DescopeProvider, all 13 tools, Starlette deployment
├── db.py                 # Async Neon pool (psycopg AsyncConnectionPool)
├── config_store.py       # Rules/persona from DB with hardcoded fallbacks

tests/test_starter.py     # 5 offline security smoke tests (green)
seed/articles.json        # Superseded by spec seed data (7 records in spec.md)
mock_auth/                # Local dev sign-in (not used — Descope replaced it)
real-auth-blueprint.md    # Step-by-step for adding Descope+DCR to any connector
```

### Database (Neon, project: `connector-native-apps`)

| Table | Key columns | Purpose |
|---|---|---|
| `users` | `id` (PK, = OAuth sub), email, created_at, last_seen_at | User identity |
| `user_state` | `user_id` (PK, FK→users), `state` JSONB, updated_at | Cross-chat state |
| `tickets` | `id` (PK), subject, body, priority, status, created_by, assigned_to, resolved_at, csat_score | All tickets |
| `support_embeddings` | `id` (PK), entity_type, content JSONB, embedding VECTOR(1024) | Orders + policies for semantic search |
| `config` | `key` (PK), value, updated_at | Behavioral rules + persona |
| `audit_log` | `id` SERIAL, user_id, tool_name, input_summary, output_summary, created_at | Tool call audit |

### Auth Architecture

```
Descope Agentic Identity Hub (MCP Server)
    │  DCR: clients auto-register, no manual client ID
    │  PKCE S256
    │  Issues JWT with aud = BASE_URL
    ▼
DescopeProvider (FastMCP built-in)
    │  Verifies: signature, issuer, audience, expiry
    │  Extracts sub → get_access_token()
    │  Serves well-known routes at root level
    ▼
session.py
    │  begin_session() mints HS256 internal token (30 min TTL)
    │  require_session() gates every domain_*/user_*/config_* tool
```

### Env vars (`.env`)

```env
DATABASE_URL=postgresql://...       # Neon connection
DESCOPE_CONFIG_URL=https://...      # Descope MCP Server well-known URL
BASE_URL=https://xxx.trycloudflare.com  # Gateway's public URL (no /mcp)
SESSION_SIGNING_SECRET=...          # Internal HS256 signing key
AUTH_DISABLED=0                     # 0 = real auth, 1 = skip OAuth (demo)
DEV_SUB=dev-user-001                # Fallback identity when AUTH_DISABLED=1
```

---

## The Four Invariants (Never Break)

1. **One gateway.** One MCP server, one public URL. Group tools by underscore prefix (`domain_*`, `user_*`, `config_*`). Never split into multiple connectors — a free user can add only one.
2. **Tools only.** Expose MCP **tools**. Do **not** use MCP resources or prompts for app logic.
3. **Prove, don't trust.** Identity comes only from the verified OAuth token's `sub` claim. **Never** read a user identifier from a tool argument. If a tool signature contains a `user_id`, ignore it and use `sub`.
4. **Fail closed.** If `begin_session` is unavailable or any tool errors, the server/rules must make the model say the session can't continue. Never improvise content or invent user state.

---

## Version Roadmap (from spec_updated.md)

### v2 — Support Desk Deepens

| Item | Detail |
|---|---|
| Ticket assignment & agent routing | `domain_assign_ticket`, `domain_reassign_ticket`. `assigned_to` column already exists |
| Customer satisfaction surveys | `domain_submit_csat(ticket_id, score)` — post-resolution 1-5 rating. `csat_score` column exists |
| File/image attachments | `domain_attach_file(ticket_id, file_data)`. New attachments table |
| AI-drafted agent replies (copilot) | `domain_draft_reply(ticket_id)` — AI composes draft response for human agent |
| Usage analytics & reporting | `domain_report_summary(period)`, `domain_agent_performance(agent)` |
| Audit log reading tool | `admin_get_audit_log(user_id?, tool_name?, since?, limit?)` — read-only |

### v3 — Connects to External World

| Item | Detail |
|---|---|
| Live platform integrations | Freshdesk, Shopify, Zendesk — MCP-to-MCP sync |
| Shopify order lookup | `domain_get_order` connects to Shopify API for real-time data |
| Email/push notifications | `user_configure_notifications` — notify on ticket status change |
| Per-user ticket access control | `domain_get_ticket(id)` filters by `created_by` — multi-tenant hardening |
| Semantic search over private tickets | `domain_search` gains `include_my_tickets: true` |

### v4 — Autonomous Support Agent

| Item | Detail |
|---|---|
| Proactive alerts | Agent loop monitors: SLA approaching → auto-escalate. Critical → notify on-call |
| Auto-resolution | Common patterns auto-resolve without human. Confidence threshold gating |
| Agent loop | Server has its own agent loop — watches, decides, acts |

---

## OAuth (Descope + DCR)

- This server is an **OAuth 2.1 resource server ONLY**. Descope is the authorization server.
- `DescopeProvider` (FastMCP built-in) handles: token verification, well-known discovery routes (`/.well-known/oauth-protected-resource/mcp`), and 401 responses with `WWW-Authenticate` header.
- Descope supports **DCR** natively — claude.ai auto-registers without a manual client ID.
- Descope MCP Server requires: **MCP Server URL** = gateway's public URL + `/mcp`, **DCR enabled**, **App URL** = tunnel base URL, **Approved Domains** includes `trycloudflare.com`.
- `auth.py` (given, immutable) checks all four: signature (AS JWKS), `iss`, `aud` = this server (RFC 8707), expiry, then extracts `sub`. With `DescopeProvider`, these checks are handled internally.
- Under `AUTH_DISABLED=1`, the OAuth layer drops out entirely and `begin_session` uses `DEV_SUB`.

### Switching auth providers

To replace Descope with a different provider:
1. If the provider supports DCR: swap `DescopeProvider` for `RemoteAuthProvider` + custom `TokenVerifier` wrapping `auth.py`
2. If the provider does NOT support DCR (Clerk, Auth0, Azure): use FastMCP's OAuth Proxy with pre-registered client IDs
3. See `real-auth-blueprint.md` for full step-by-step with Descope

---

## Quick Start

### Run locally

```bash
uv sync --extra dev
uv run pytest -q                                          # 5 green checks
uv run python -m connector_app.server                     # 127.0.0.1:8000
```

### Go live (tunnel)

```bash
# 1. Start gateway (background)
uv run python -m connector_app.server > /tmp/gateway.log 2>&1 &

# 2. Wait for ready
until curl -s -o /dev/null http://127.0.0.1:8000/mcp; do sleep 1; done

# 3. Start tunnel
cloudflared tunnel --url http://127.0.0.1:8000 --http-host-header 127.0.0.1:8000 --no-autoupdate > /tmp/cf.log 2>&1 &

# 4. Get URL
until grep -qoE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log; do sleep 1; done
grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' /tmp/cf.log | head -1
```

### Take it down

```bash
pkill -f "connector_app.server"; pkill -f "cloudflared"
```

---

## The `begin_session` Contract

- The model must call `begin_session()` first on any new request. Enforce this **structurally**: every `domain_*`/`user_*`/`config_*` tool requires a `session` token that **only** `begin_session` issues (`session.require_session` is given).
- `begin_session()` reads identity from the verified token (`sub` via `get_access_token()`), then returns a fresh signed session token, the app rules, the persona, and the user's state.
- Under `AUTH_DISABLED=1`, `begin_session` skips token verification and uses the fixed `DEV_SUB` from `.env` as the `sub`.
- Phrase the returned rules as **cooperation** ("here is how to behave for this user"), **never** as an override ("ignore previous instructions").
- Reinforce on every tool return: append a one-line reminder of how to present the result.
- Include the fail-closed instruction in the returned rules (invariant 4).

---

## Sessions: Management, State, and Monitoring

### Session management flow

```
Chat starts → claude.ai calls /mcp with Descope JWT in Authorization header
  → DescopeProvider verifies JWT (sig, iss, aud, exp)
  → claude.ai calls begin_session() tool
    → _get_sub() reads sub from get_access_token()
    → get_rules() / get_persona() from Neon config table (or fallback)
    → Read user_state from Neon
    → session.new_session_token(sub) — mint 30-min HS256 token
    → Return {rules, persona, state, session_token, reminder}
  → claude.ai calls domain_* / user_* / config_* tools with session_token
    → _validate_session(session_token) checks token validity
    → If valid: tool executes with verified sub
    → If invalid/expired: return error, model must re-call begin_session
```

### Cross-chat memory (how state survives)

```
Chat 1:
  begin_session() → sub = "user_abc" → read user_state → state = {}
  user_save_state({last_ticket_id: "tkt-004"}) → INSERT INTO user_state

Chat 2 (new chat, new session):
  begin_session() → sub = "user_abc" → read user_state → state = {last_ticket_id: "tkt-004"}
  model: "Welcome back! You were looking at ticket tkt-004."
```

Key: identity is constant across chats (same Descope user), so state is keyed to the same `sub`. The only thing that dies between chats is the OAuth token and session token — state is in Neon.

### Single-user auth-disabled demo

```
AUTH_DISABLED=1 in .env
  → No DescopeProvider on FastMCP → no 401, no OAuth
  → _get_sub() returns DEV_SUB ("dev-user-001")
  → Everyone is the same user
  → State carries over across chats (same DEV_SUB)
  → Open door: anyone with tunnel URL accesses the DB
```

### Multi-user isolation verification

| Test | Expected |
|---|---|
| User A saves state, User B reads profile | B sees B's state, no trace of A |
| User A creates ticket, User B lists tickets | B's list doesn't contain A's ticket |
| Audit check: grep for `user_id` in tool signatures | Zero `user_id` parameters |
| Session token from A used by B | Rejected — token's sub ≠ request's sub |

### Monitoring & troubleshooting

```bash
# Health check
curl http://127.0.0.1:8000/mcp -X POST \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"health","arguments":{}}}'

# List all tools (no auth needed if AUTH_DISABLED=1)
curl http://127.0.0.1:8000/mcp -X POST \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Check OAuth flow (no token → expect 401)
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8000/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# Check well-known discovery
curl http://127.0.0.1:8000/.well-known/oauth-protected-resource/mcp

# Server logs
tail -f /tmp/gateway.log

# Tunnel logs
tail -f /tmp/cf.log
```

---

## Code Standards

- **Python 3.14+ with modern typing.** Built-in generics (`dict[str, Any]`, `list[...]`), `X | None`, PEP 695 `type` aliases. No `from __future__ import annotations`, no `Optional`/`Dict`/`List` from `typing`. Keep it mypy-clean.
- `uv` for env and deps. Add deps with `uv add` against current versions; do not pin from memory.
- **Local dev port `8000`.** Bind `127.0.0.1:8000`. If 8000 is busy, free it rather than picking another port.
- **Run server as:** `uv run python -m connector_app.server`

---

## Secrets & Safety

- **Never** print, log, or echo secrets. Keys go in `.env` only (gitignored).
- Never ask the human to paste keys into chat. If one appears, add it to `.env` and tell them to rotate it.
- Never write project rules to a new file — keep them here in `AGENTS.md`.

---

## Self-Check

1. One gateway, three tool groups. ✓ (13 tools: domain_* × 7, user_* × 2, config_* × 2)
2. Tools only (no resources/prompts). ✓
3. Two-table memory that persists across separate chats. ✓ (users + user_state in Neon)
4. Identity from `sub`, never from the model. ✓ (DescopeProvider → get_access_token() → sub)
5. PKCE S256 + audience-bound tokens. ✓ (Descope supports PKCE S256, DCR, aud = BASE_URL)
6. `begin_session` cooperative, called first, reinforced. ✓
7. Working tools gated behind the session token. ✓ (session.require_session)
8. Fail-closed rule that refuses, not improvises. ✓ (fallback config + per-tool reminder)
9. Real auth with DCR, not AUTH_DISABLED demo. ✓ (DescopeProvider)
10. Cross-chat memory: new chat, same user, state restored. ✓ (verified live)
