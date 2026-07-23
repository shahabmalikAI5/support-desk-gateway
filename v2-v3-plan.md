# Technical Plan: v2 + v3 Implementation

## 1. Stack (no new frameworks)

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | FastMCP + Starlette | Unchanged from v1 |
| Auth | DescopeProvider + session.py | Unchanged; extended with `role` claim |
| DB | Neon PostgreSQL + psycopg async | Unchanged; new tables, column migrations |
| Embeddings | Mistral API + httpx | Unchanged |
| Attachments | Cloudflare R2 via **boto3** (`pip install boto3`) | The single new dep; S3-compatible presigned URLs are non-trivial to hand-roll |
| Email | **Raw httpx** to SendGrid REST API | No SDK needed — one POST endpoint, avoid extra dep |
| External APIs | Raw httpx (Freshdesk, Shopify) | Reuses existing pattern from `domain_search` |
| Admin dashboard | Single static HTML file, inline JS/CSS | No framework, no build step; served via `FileResponse` |
| Background sync | asyncio `Task` in the same process | No separate service, no cron |

## 2. Proposed File Structure

```
src/connector_app/
├── __init__.py
├── auth.py              # GIVEN — wrapper added: `get_access_token_claims()` alongside it, never rewritten
├── session.py           # GIVEN — extended: token carries `role` claim
├── server.py            # FastMCP app, Starlette routes, ~all tool definitions
├── db.py                # Pool + DDL migration helpers
├── config_store.py      # Extended: set_rules, set_persona, restore_version, config_history
├── tools/               # NEW — extracted tool implementations (no MCP registration here)
│   ├── __init__.py
│   ├── domain.py        # get_ticket, get_order, get_policy, search, create_ticket,
│   │                    # list_my_tickets, get_customer_profile,
│   │                    # assign_ticket, reassign_ticket, update_ticket, submit_csat,
│   │                    # attach_file, get_attachment, draft_reply,
│   │                    # report_summary, agent_performance, get_audit_log,
│   │                    # sync_to_freshdesk (v3)
│   ├── user.py          # get_profile, save_state, configure_notifications (v3)
│   └── config.py        # get_rules, get_persona, set_rules, set_persona,
│                        # restore_version, set_freshdesk_creds, set_shopify_creds
├── catalog.py           # NEW — catalog ops: set_policy, set_order, delete_item, list_all embedding pipeline
├── notifications.py     # NEW — SendGrid + webhook dispatch (stateless functions)
│                        # Imported by tools/domain.py (domain_update_ticket fires
│                        # notifications synchronously on reply_body/reopen)
├── sync.py              # NEW — background Freshdesk sync asyncio Task
└── role_gate.py         # NEW — require_role() decorator/filter, tools/list role filtering
admin/
└── index.html           # NEW — single static admin dashboard
```

**Decision: Split tools vs. keep in server.py**

- **Option A (chosen):** Extract implementation to `tools/*.py`, keep `@mcp.tool` registration in `server.py`
- **Trade-off:** Server.py stays the "table of contents" (~300 lines of registrations calling thin wrappers). `tools/domain.py` handles all DB logic (~800 lines). Avoids a 2500-line monolith but doesn't over-engineer — registration and logic are in exactly two layers, no complex DI.
- **Alternative rejected:** Keep everything in server.py → 2000+ lines, unreadable for debugging.

## 3. Key Decisions

### 3.1 Role gating: HMAC-embedded claim in session token

**Decision:** Extend `session.new_session_token(sub, role)` to include `role` as a claim. `require_session()` returns both `sub` and `role`. A new `require_role(session_token, allowed_roles)` function wraps role checks. For admin tools: `require_role(token, ["admin"])` → returns `"not found"` (not "unauthorized"). For agent tools: `require_role(token, ["admin", "staff"])`.

**Trade-off:** Embedding role in the session token means role changes take up to 30 min to propagate (session TTL). Accepted per spec: "role changes are not real-time." Not embedding it would require checking Descope on every tool call, adding ~50ms per call.

**What changes where:**
- `session.py` — `new_session_token(sub, role=None)` adds `role` claim
- `session.py` — `require_session()` returns `tuple[str, str | None]` (sub, role)
- `auth.py` — Add a `get_access_token_claims()` wrapper alongside the existing GIVEN code (don't rewrite it — the Connector-Native Apps course marks this file as GIVEN for a reason, but we need the full claims dict, not just `sub`). The wrapper calls the existing DescopeProvider, validates the token, and returns the full claims dictionary.
- `server.py` — `_get_sub()` becomes `_get_claims()` returning `(sub, role)`
- `begin_session()` embeds role in session token, returns `role` field

### 3.2 boto3 for R2 presigned URLs

**Decision:** Add `boto3` as the single new dependency. R2 is S3-compatible; boto3 handles the presigned URL signing logic that is error-prone to reimplement.

**Trade-off:** Adds a 40MB dependency (boto3 + botocore). Alternative is hand-rolling S3 sigv4 with raw httpx (~80 lines of crypto, high bug risk). boto3 is the standard tool for this job and the Docker image already has copious space.

### 3.3 SendGrid: raw httpx, no SDK

**Decision:** POST to `https://api.sendgrid.com/v3/mail/send` with `Authorization: Bearer` header using raw httpx. One endpoint, one function, ~15 lines.

**Trade-off:** No typing or helper classes from the SDK. But for a single-method API call with a 4-field JSON body, the SDK adds 3MB of deps for zero benefit beyond what we get from httpx. All error handling is identical (check status code, log on failure).

### 3.4 Admin dashboard: inline static HTML

**Decision:** Single `admin/index.html` with inline CSS and JS. Served via `starlette.responses.FileResponse` at route `/admin` (GET only). No build step, no npm, no framework.

**Trade-off:** No TypeScript, no reactive framework, no component library. For a single-business-admin tool with ~5 textareas and a table, this is sufficient. If the admin needs grew to team-scale, this would be rewritten — but that's v4+ territory. The key win: zero build infrastructure, zero maintenance.

### 3.5 Background Freshdesk sync: asyncio Task

**Decision:** On server startup `lifespan`, spawn an `asyncio.create_task()` that loops every 15 minutes, pulls Freshdesk status for synced tickets. Runs in the same Python process.

**Trade-off:** No resilience (if the server crashes, sync stops). But adding a separate worker/cron job doubles deployment complexity and cost. At free-tier scale with 15-minute polling, the simplicity trade-off is correct. The on-demand `domain_sync_to_freshdesk` tool is the fallback.

### 3.6 Config history: append-only table

**Decision:** Every `config_set_rules`/`config_set_persona` inserts a row into `config_history` *before* upserting the current value. `config_restore_version` reads from it and writes the restored value as a new current + new history row.

**Trade-off:** No diffs, no branching, no rollback. Simple append-only. For rules and persona texts (typically < 5KB each), storing full copies is negligible in storage. Extracting diffs would add complexity with no user value for single-admin scenarios.

### 3.7 Embedding tickets for semantic search (v3)

**Decision:** `domain_create_ticket` calls Mistral API to generate an embedding of subject + body, stores it in `support_embeddings` with `entity_type="ticket"`. `domain_search` with `include_my_tickets=True` queries embeddings filtered by `created_by`.

**Trade-off:** Adds ~500ms to ticket creation (Mistral API latency). Tickets without embeddings (Mistral temporarily down) are excluded from search but fully accessible by ID. This matches the catalog embedding behavior — degrade gracefully, never block.

### 3.8 Schema migrations

**Decision:** No migration framework. Agent applies DDL changes via Neon MCP tools (`run_sql`). Add columns with `DEFAULT` values to avoid table rewrites; add constraints with `NOT VALID` → validate later for zero-downtime.

**Trade-off:** No rollback automation. But we're in development, not production — re-running seed data is the rollback plan. For production (future), Fly.io's `fly secrets` + backup would be the recovery path.

## 4. Required Schema Changes

| Table | Change | 
|-------|--------|
| `tickets` | Add: `category TEXT`, `assigned_at TIMESTAMPTZ`, `closed_at TIMESTAMPTZ`, `freshdesk_id TEXT`, `freshdesk_synced_at TIMESTAMPTZ`, `csat_submitted_at TIMESTAMPTZ`, `tags TEXT[]`, `updated_at TIMESTAMPTZ DEFAULT now()`, `last_activity_at TIMESTAMPTZ DEFAULT now()`, `source TEXT DEFAULT 'mcp'`. Extend status check constraint to include `'pending'` |
| `config_history` | **New table**: `id SERIAL PK`, `key TEXT`, `value TEXT`, `version_index INTEGER`, `updated_by TEXT`, `updated_at TIMESTAMPTZ` |
| `attachments` | **New table**: `id TEXT PK`, `ticket_id TEXT FK`, `file_name TEXT`, `mime_type TEXT`, `size_bytes INTEGER`, `r2_key TEXT`, `uploaded_by TEXT`, `uploaded_at TIMESTAMPTZ` |
| `notification_config` | **New table**: `user_sub TEXT PK`, `email TEXT`, `webhook_url TEXT`, `events TEXT[]`, `created_at TIMESTAMPTZ`, `updated_at TIMESTAMPTZ` |
| `ticket_notes` | **New table**: `id SERIAL PK`, `ticket_id TEXT FK`, `author_sub TEXT`, `author_role TEXT`, `body TEXT`, `note_type TEXT`, `created_at TIMESTAMPTZ` |
| `support_embeddings` | No schema change. Tickets use existing `entity_type` + `content` columns. |

## 5. New Environment Variables

| Var | Required | Purpose |
|-----|----------|---------|
| `SENDGRID_API_KEY` | v2 | Email notifications (free tier: 100/day) |
| `R2_ACCESS_KEY_ID` | v2 | Attachment storage |
| `R2_SECRET_ACCESS_KEY` | v2 | Attachment storage |
| `R2_ENDPOINT` | v2 | R2 endpoint URL |
| `R2_BUCKET` | v2 | R2 bucket name |
| `FRESHDESK_API_KEY` | v3 | Freshdesk sync |
| `FRESHDESK_DOMAIN` | v3 | Freshdesk domain |
| `SHOPIFY_ACCESS_TOKEN` | v3 | Shopify live order lookup |
| `SHOPIFY_STORE_DOMAIN` | v3 | Shopify store domain |
| `WEBHOOK_SECRET` | v3 | HMAC signing for webhook notifications |
| `DESCOPE_MANAGEMENT_API_KEY` | v2 (fallback) | Only if Descope plan lacks custom JWT claims |
| `AUTH_ISSUER` | v1 | Documented for completeness — already set in v1 |
| `AUTH_JWKS_URL` | v1 | Documented for completeness — already set in v1 |
| `RESOURCE_URL` | v1 | Documented for completeness — already set in v1 |

## 6. Implementation Order

The spec is large. I propose 3 phases within v2, then v3:

**Phase 1: Foundation (schema + role gating)**
1. Run DDL migrations on Neon (new columns, new tables)
2. Extend `session.py` — `role` claim in tokens, `require_role()` function
3. Extend `begin_session` — extract role from Descope JWT + fallback to Management API
4. Add `role_gate.py` — decorator, tools/list filtering
5. Update all existing tools to use new `require_session` signature

**Phase 2: v2 Core Tools**
6. `domain_assign_ticket`, `domain_reassign_ticket`, `domain_update_ticket`
   - Implement `_validate_transition(current_status, new_status) -> bool` in `tools/domain.py`
   - The helper encodes the allowed transition map from the spec's state machine diagram
   - Used by all three tools: assign transitions `open→in_progress`, reassign checks status,
     update_ticket validates arbitrary transitions
7. `domain_submit_csat`, `domain_draft_reply`
8. `domain_report_summary`, `domain_agent_performance`
9. `domain_get_audit_log`
10. Update `domain_get_ticket` (attachments), `domain_get_customer_profile` (csat_trend)

**Phase 3: v2 Admin + Catalog**
11. `config_set_rules`, `config_set_persona` (with config_history)
12. `config_restore_version`
13. `catalog_set_policy`, `catalog_set_order`, `catalog_delete_item`, `catalog_list_all`
14. `config_set_freshdesk_creds`, `config_set_shopify_creds`
15. Admin dashboard HTML/JS page
16. Seed `config_history` with current rules and persona as version_index=0

**Phase 4: v2 Attachments**
17. `domain_attach_file`, `domain_get_attachment` (R2 + boto3)
18. Seed attachments data

**Phase 5: v3 Integration**
19. `user_configure_notifications` (SendGrid + webhook dispatch)
20. `domain_sync_to_freshdesk` + background sync task
    - **Bootstrap note:** Background sync only pulls existing `freshdesk_id` tickets. The first sync for any ticket requires a manual `domain_sync_to_freshdesk("push")` call. The background task will find zero tickets to sync until at least one manual push has occurred.
21. Shopify live lookup in `domain_get_order`
22. `domain_search` with `include_my_tickets`
23. Multi-tenant hardening (identity checks on ticket/attachment access)
24. Seed data for v3 tables

**Phase ordering rationale:** Attachments (Phase 4) is placed after Admin tools (Phase 3) because the admin dashboard is needed for smoke-testing the catalog and config changes before adding the file-upload pipeline. The ordering is: make the desk work (Phases 1-2) → let admins configure it (Phase 3) → add file handling (Phase 4) → connect to outside platforms (Phase 5). Each phase is independently testable.

**Role gating across phases:** After Phase 1 adds `role_gate.py`, every tool added in Phases 2-5 must be wrapped with the appropriate role check:
- Agent tools (Phases 2, 4, 5): `require_role(token, ["admin", "staff"])`
- Admin tools (Phase 3): `require_role(token, ["admin"])`
- Customer tools: no role check (default — all authenticated users)

## 7. Invariant Preservation Checklist

| # | Invariant | How preserved |
|---|-----------|---------------|
| 1 | One gateway | All new tools are `@mcp.tool` on the same FastMCP instance. No second server. |
| 2 | Tools only | No resources, no prompts. Admin dashboard uses tools via fetch(), not a new API. |
| 3 | Prove, don't trust | All tools use `sub` from session token. No `user_id` parameter. `require_role()` checks the HMAC-signed role claim. |
| 4 | Fail closed | Every tool still returns `_reminder`. Admin tools return `"not found"` for unauthorized callers (identical to nonexistent). |

## 8. Files That Change

| File | Change scope |
|------|-------------|
| `session.py` | +15 lines (role claim, `require_role`) |
| `server.py` | Structural: extract tools to modules; +Admin route, +health route; `begin_session` gains role. **Dockerfile** must add `COPY admin/ ./admin/` to serve the dashboard. |
| `config_store.py` | +80 lines (set_rules, set_persona, history, restore) |
| `db.py` | +30 lines (migration helpers) |
| **New**: `tools/domain.py` | ~1100 lines (existing 7 domain tools + 10 new + state machine helper + notification dispatch calls) |
| **New**: `tools/user.py` | ~100 lines (existing 2 + configure_notifications) |
| **New**: `tools/config.py` | ~150 lines (existing 2 + 8 new admin/catalog tools) |
| **New**: `catalog.py` | ~120 lines (embedding pipeline, upsert/delete) |
| **New**: `notifications.py` | ~80 lines (SendGrid + webhook) |
| **New**: `sync.py` | ~60 lines (background Freshdesk polling) |
| **New**: `role_gate.py` | ~40 lines |
| **New**: `admin/index.html` | ~500 lines (static dashboard) |
| `pyproject.toml` | +1 dep: `boto3` |
| `.env` | +12 optional vars |
