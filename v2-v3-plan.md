# Technical Plan: v2 + v3 Full Spec Implementation

## Status

v1 is complete. v2/v3 code was partially implemented from an earlier draft of this plan.
This document supersedes that work and defines the **full v2-v3-spec.md compliance build**.
Every gap identified by the gap analysis is addressed below.

**56 gaps identified (28 HIGH, 19 MEDIUM, 9 LOW).** All are covered in the phases below.

---

## 1. Stack

| Layer | Choice | Rationale |
|-------|--------|-----------|
| Framework | FastMCP + Starlette | Unchanged from v1 |
| Auth | DescopeProvider + session.py | Unchanged; role claim already implemented |
| DB | Neon PostgreSQL + psycopg async | Unchanged; 6 tables exist, `ticket_notes` needs creation |
| Embeddings | Mistral API + httpx | Unchanged |
| Attachments | Cloudflare R2 via **boto3** | Installed; R2 client needs wiring into domain.py |
| Email | Raw httpx to SendGrid REST API | notifications.py exists but never called from tools |
| External APIs | Raw httpx (Freshdesk, Shopify) | domain_sync_to_freshdesk needs real implementation |
| Admin dashboard | Single static HTML file | admin/index.html exists; route path needs hardening |
| Background sync | asyncio Task | sync.py exists; scope and credential reading need fixes |
| Deployment | Dockerfile + fly.toml | **Missing** — must be created |

---

## 2. Full File Structure

```
src/connector_app/
├── __init__.py
├── auth.py              # GIVEN — never rewritten
├── session.py           # GIVEN — role claim already implemented
├── server.py            # FastMCP app, Starlette routes, all 34 tool registrations
├── db.py                # Async Neon pool
├── config_store.py      # get_rules, get_persona with fallbacks
├── role_gate.py         # gate_admin/gate_staff helpers + TOOLS_LIST_FILTERING
├── catalog.py           # Embedding pipeline for policies/orders
├── notifications.py     # SendGrid + webhook dispatch (needs wiring)
├── sync.py              # Background Freshdesk polling (needs fixes)
├── tools/
│   ├── __init__.py
│   ├── domain.py        # 18 domain_* implementations
│   ├── user.py          # 3 user_* implementations
│   └── config.py        # 7 config_* implementations
admin/
└── index.html           # Static admin dashboard
seed/
├── tickets.json         # MISSING — 5 sample tickets
├── attachments.json     # MISSING — 2 sample attachment rows
└── notifications.json   # MISSING — 1 notification config row
Dockerfile               # MISSING
fly.toml                 # MISSING
```

---

## 3. All Changes Required (by spec compliance)

Spec references are to `v2-v3-spec.md` line numbers.

### 3.1 Role Gating Matrix (spec lines 308–340)

| Tool | Current role gate | Spec requires | Fix |
|------|------------------|---------------|-----|
| `domain_agent_performance` | staff+ | admin-only | Tighten to admin |
| `domain_report_summary` | staff+ | admin-only | Tighten to admin |
| `catalog_list_all` | staff+ | admin-only | Tighten to admin |
| `domain_get_ticket` | staff sees ALL tickets | staff & admin see own + assigned | Fix identity check |
| `domain_get_attachment` | staff sees ALL attachments | staff & admin see own + assigned | Fix identity check |
| `domain_attach_file` | staff+ only | customers can attach to own tickets | Allow customers |

**Note on get_ticket hardening**: Per spec line 1468, staff AND admins both follow the same
`created_by = sub OR assigned_to = sub` rule. Admins do NOT get unrestricted global visibility
to all tickets — reporting tools serve aggregate data. This prevents casual admin browsing
of other users' tickets.

### 3.2 tools/list Role Filtering (spec lines 1456–1461)

The MCP `tools/list` response must exclude tools based on role:
- **Customer (no role):** 15 tools (health, begin_session, domain_create_ticket,
  domain_get_ticket, domain_search, domain_get_policy, domain_get_order, domain_submit_csat,
  domain_attach_file, domain_get_attachment, domain_get_customer_profile,
  domain_list_my_tickets, user_save_state, user_get_profile, user_configure_notifications)
- **Staff (role="staff"):** 21 tools (customer + domain_assign_ticket, domain_reassign_ticket,
  domain_update_ticket, domain_draft_reply, domain_get_audit_log, domain_sync_to_freshdesk)
- **Admin (role="admin"):** all ~28 tools (staff + domain_report_summary,
  domain_agent_performance, config_set_rules, config_set_persona, config_restore_version,
  catalog_set_policy, catalog_set_order, catalog_delete_item, catalog_list_all,
  config_set_freshdesk_creds, config_set_shopify_creds)

**Implementation challenge:** `tools/list` is called BEFORE any session token exists (the
client needs to discover `begin_session` first). The role cannot come from the session token
— it must come from the **Descope JWT** in the Authorization header (`get_access_token()` →
`claims.role`).

The filtering must happen at the Starlette middleware level, not inside FastMCP. Approach:
1. Mount a custom ASGI or Starlette middleware before the `/mcp` route
2. Intercept `POST /mcp` with JSON-RPC body `{"method": "tools/list"}`
3. Read the Descope JWT from the `Authorization` header
4. Extract the `role` claim from the JWT
5. After the MCP handler returns the tool list, filter it by role
6. Return the filtered list

This is the only approach since FastMCP's `add_tool_transformation()` runs at
registration time, not at request time, and has no access to the request context.

### 3.3 Multi-Tenant Identity Checks (spec lines 1463–1481)

**`domain_get_ticket`** (domain.py lines 42–80):
- Current: `if not is_staff and ticket_creator != sub → "not found"`
- Required: `if is_staff → allow if created_by=sub OR assigned_to=sub. If customer → allow only if created_by=sub.`

**`domain_get_attachment`** (domain.py lines 643–673):
- Same pattern: join attachments→tickets, check `t.created_by = sub OR (is_staff AND t.assigned_to = sub)`

### 3.4 `domain_get_ticket` Output — attachment fields (spec lines 1273–1284)

Must always include:
- `attachment_count` — COUNT query on attachments table
- `attachment_ids` — list of IDs query on attachments table
Add to the SELECT or as a second query.

### 3.5 `domain_get_customer_profile` — csat_trend (spec lines 1286–1297)

Must return `csat_trend` field. Algorithm:
1. Query last 5 rated tickets for this user, ordered by `csat_submitted_at DESC`,
   non-null `csat_score` only.
2. If 0 rated tickets: `null`.
3. If < 3 rated tickets: `"stable"`.
4. If ≥ 3: compute the trend as `sign(sum(last_n - second_last_n for each adjacent pair))`.
   Positive sum → `"improving"`, negative → `"declining"`, zero → `"stable"`.
   Example: scores [5, 4, 3] → differences [-1, -1] → sum -2 → "declining".
   Example: scores [3, 4, 5] → differences [+1, +1] → sum +2 → "improving".
   Example: scores [4, 4, 5] → differences [0, +1] → sum +1 → "improving".

### 3.6 `domain_create_ticket` — category param (spec line 400)

Add optional `category: str = 'other'` parameter.
Validate against enum: billing, returns, technical, account, shipping, other.
Store in the `category` column.

### 3.7 `domain_assign_ticket` (spec lines 412–452)

Changes from current:
- Rename param `assigned_to` → `agent`
- Add resolved/closed rejection: `"ticket is already resolved — cannot reassign"`
- Normalize agent name: `.strip().lower()`, case-insensitive comparison
- Existing same-agent assignment → no change, no error
- Add `SELECT ... FOR UPDATE` for concurrent assignment safety
- Create ticket_notes row with `note_type='system_event'` on assignment

### 3.8 `domain_reassign_ticket` (spec lines 454–480)

Changes from current:
- Rename param `new_assignee` → `new_agent`
- Add optional `reason: str | None = None` param
- Query `assigned_to` BEFORE update → include as `previous_agent` in output
- Add `reassigned_at` timestamp to output
- Create ticket_notes row with `note_type='system_event'` on reassignment

### 3.9 `domain_update_ticket` (spec lines 482–533)

**Parameter clarification:** The existing `body` param replaces the ticket's body text.
The new `reply_body` param appends an agent reply as a ticket note (INSERT into
`ticket_notes`). They are independent — providing both updates the body AND appends a note.

Major changes:
- Add `reply_body: str | None = None` param
  → When provided, INSERT into `ticket_notes` with `note_type='reply'`,
    `author_role='staff'` (or 'admin'), `author_sub=sub`
  → Trigger `notifications.dispatch()` for the ticket creator
  → Output includes `reply_sent: true`
- Add category validation: must be one of billing, returns, technical, account, shipping, other
  → Reject with: `"category must be one of: billing, returns, technical, account, shipping, other"`
- Reopen behavior (status="open" from resolved):
  → Clear `resolved_at = NULL`
  → Clear `csat_score = NULL`
  → Clear `freshdesk_synced_at = NULL`
- All params optional — calling with just `ticket_id` returns current state (no-op)
- Use `SELECT ... FOR UPDATE` for concurrent safety
- Output when reply_body provided: `{"ticket_id": "...", "status": "...", "reply_sent": true,
  "updated_at": "..."}`

### 3.10 `domain_submit_csat` (spec lines 536–569)

Changes from current:
- **Resolved-only gate:** Reject if `status != 'resolved'`:
  `"ticket must be resolved before rating"`
- **Already-rated handling:** If `csat_score IS NOT NULL`:
  Return `{"csat_score": existing, "already_rated": true, "submitted_at": original_ts}`
  Do NOT overwrite.
- Use `SELECT ... FOR UPDATE` on the ticket row to prevent race condition: if two
  concurrent calls both read `csat_score IS NULL` before either commits, only the
  first write should succeed. The second call sees `csat_score` set and returns `already_rated`.

### 3.11 `domain_attach_file` (spec lines 571–611)

Rewrite from current:
- **MIME type as required input param** (not guessed from filename)
- **MIME allowlist:** Only accept: image/jpeg, image/png, image/gif, application/pdf,
  text/plain, text/csv. Reject others: `"unsupported file type: {mime_type}"`
- **10MB size limit:** Reject: `"file exceeds 10MB limit"`
- **10-attachment limit:** Reject: `"ticket already has 10 attachments"`
- **Base64 validation:** Catch `binascii.Error`: `"file data is not valid base64"`
- **Customer access:** Customers can attach to own tickets. Staff+ to own + assigned.
- **R2 storage:** Upload decoded bytes to R2 bucket. Store `r2_key` in DB.
- On R2 upload failure: delete the DB row, return error (DB+R2 consistency)

### 3.12 `domain_get_attachment` (spec lines 613–663)

Rewrite from current:
- **Remove inline base64 return** — NEVER return file content inline
- **R2 presigned URL:** Generate S3-compatible presigned GET URL with 15-min expiry
- **Output fields:**
  ```json
  {
    "attachment_id": "att-001",
    "ticket_id": "tkt-004",
    "file_name": "photo.jpg",
    "mime_type": "image/jpeg",
    "size_bytes": 245760,
    "presigned_url": "https://<bucket>.r2.cloudflarestorage.com/...?X-Amz-Expires=900...",
    "url_expires_at": "2026-07-24T10:15:00Z"
  }
  ```
- **Identity check:** Join with tickets table. Staff → own + assigned. Customer → own only.

### 3.13 `domain_draft_reply` (spec lines 665–708)

**Complete rewrite** from current fixed-text draft to structured context:
- Query ticket details (subject, body, status, priority, assigned_to)
- Look up matching policy: match keywords from ticket body against policy titles in
  `support_embeddings WHERE entity_type='policy'`. Return first match's ID, title, and
  body excerpt (first 300 chars).
- Fetch customer history: count of previous tickets, avg CSAT
- **Note:** The codebase stores only `created_by` (an opaque `sub` string), not a display name.
  There is no Descope profile lookup. Return `created_by` as `customer_name` (it will be the
  OAuth sub). The AI model may resolve it to a name if it has context from the conversation.
- Return structured:
  ```json
  {
    "ticket_id": "tkt-004",
    "customer_name": "user-priya-88",
    "ticket_subject": "Damaged item...",
    "ticket_body": "I received...",
    "ticket_status": "in_progress",
    "ticket_priority": "high",
    "policy_id": "pol-001",
    "policy_title": "Refund & Return Policy",
    "policy_excerpt": "Customers may return defective items within 30 days...",
    "customer_history": "2 previous tickets, CSAT avg 4.5",
    "agent_name": "Ravi",
    "recommended_action": "Offer full refund with prepaid return label per pol-001"
  }
  ```
- If no agent: `agent_name: null`, `recommended_action`: "Assign an agent first..."
- If empty body: `recommended_action`: "The ticket has no details yet..."
- If first ticket: `customer_history: null`
- If no policy match: `policy_id: null`, `policy_excerpt: null`

### 3.14 `domain_report_summary` (spec lines 711–769)

Changes from current:
- **Period values:** "today", "yesterday", "week" (7 days), "month" (30), "quarter" (90)
  (NOT "daily", "weekly", "monthly")
- **Admin-only** (NOT staff+)
- **Add output fields:**
  - `from` / `to` — computed period boundaries (ISO 8601 UTC)
  - `avg_csat_score` — average of `csat_score` for tickets resolved within period
  - `top_categories` — tickets grouped by `category`, ranked by count, at most 5
  - `by_priority` — count of tickets per priority level
- **SLA breaches:** Current-backlog metric: count of tickets STILL open at period end
  past their SLA (critical > 1h, high > 4h, medium > 24h, low > 72h).

### 3.15 `domain_agent_performance` (spec lines 773–809)

Changes from current:
- **Admin-only** (NOT staff+)
- **Add optional `period` param** — same values as report_summary
- **Add output fields:**
  - `period` — the period string or "all_time"
  - `avg_csat_score` — average CSAT for this agent's tickets
  - `sla_breaches` — count of this agent's tickets that breached SLA
  - `current_open_tickets` — tickets assigned to agent NOT resolved/closed
  - `escalations_handled` — tickets reassigned TO this agent where reason contained "escalation"
  - `resolution_rate` — already exists (rename to match spec if needed)
- **Case-insensitive agent matching** — `.strip().lower()` on agent param

### 3.16 `domain_get_audit_log` (spec lines 811–854)

Changes from current:
- **Add `total_matching`** — run a separate `SELECT COUNT(*)` query with the same WHERE
  filters but WITHOUT the LIMIT clause
- **Add `returned`** — len(entries) in this response (same as min(limit, total_matching))
- **Add `id`** to each entry
- **Max limit: 500** (currently 200)
- Entry format:
  ```json
  {
    "id": 1042,
    "user_id": "user_abc",
    "tool_name": "domain_get_ticket",
    "input_summary": "id=tkt-004",
    "output_summary": "found ticket tkt-004",
    "created_at": "2026-07-24T09:15:00Z"
  }
  ```

### 3.17 `domain_sync_to_freshdesk` (spec lines 1303–1369)

**Complete rewrite** from current batch-sync to per-ticket:
- **Input:** `ticket_id` (required), `action` (optional, default "push")
  (NOT `mode`)
- **Actions:** "push" (send to FD), "pull" (fetch from FD), "sync_bi" (both directions)
- **Push mapping:**
  - `subject` → FD `subject` (prefixed: `"[tkt-008] subject"`)
  - `body` → FD `description`
  - `status` → FD `status` (open→2, triaged→2, in_progress→3, pending→3, resolved→4, closed→5)
  - `priority` → FD `priority` (critical→4, high→3, medium→2, low→1)
- **Pull mapping:**
  - FD status 2 (Open) → **ignored** (local is authoritative for open/triaged)
  - FD status 3 → "pending", 4 → "resolved", 5 → "closed"
  - FD priority: 4→critical, 3→high, 2→medium, 1→low
- **Credentials:** Read from config store first, fall back to env vars
- **Auth format:** Freshdesk uses HTTP Basic Auth with `api_key` as username and `X` as password
  (`httpx.BasicAuth(api_key, "X")`)
- **API endpoints:** `POST /api/v2/tickets` (create), `PUT /api/v2/tickets/{id}` (update),
  `GET /api/v2/tickets/{id}` (fetch)
- **Error handling:** FD API unreachable → graceful error, no crash

### 3.18 `domain_get_order` — Shopify fallback (spec lines 1483–1495)

Changes from current:
- **Add `source` field** to output: "catalog" or "shopify"
- **Shopify fallback:** If not found locally, query Shopify API:
  `GET https://{store_domain}/admin/api/2024-07/orders/{order_id}.json`
  with `X-Shopify-Access-Token` header
- **Shopify down:** Return `{"error": "Live order lookup temporarily unavailable. Local catalog returned: not found.", "source": "catalog_only"}` — do not crash
- **No creds configured:** Skip Shopify lookup, local catalog only, no error (`source: "catalog"`)

### 3.19 `user_configure_notifications` (spec lines 1373–1413)

Changes from current:
- **Email validation:** Reject invalid format: `"email is not a valid email address"`
- **Webhook URL validation:** Must start with `https://`. Reject: `"webhook URL must start with https://"`
- **Event validation:** Valid: status_changed, agent_assigned, resolution, all.
  Reject: `"unknown event: {name}. Valid events: status_changed, agent_assigned, resolution, all"`
- **"all" expansion:** Expand to ["status_changed", "agent_assigned", "resolution"] before storage
- **Read-mode:** If all params are None, only SELECT and return current config without UPSERT
- **Default events:** ["status_changed"]

### 3.20 Notification Dispatch Wiring (spec lines 1396–1410, 1624–1647)

**`notifications.dispatch()` is never called from any tool. Must wire it:**
- After `domain_update_ticket` with `reply_body` or `status` change
- After `domain_assign_ticket` (event: "agent_assigned")
- Only dispatches for the ticket's `created_by` user (not any user with matching config)
- `dispatch()` reads `notification_config` WHERE `user_sub = created_by` AND event matches
- Email via SendGrid API; webhook POST with `X-Webhook-Signature` header
- Fix header name: `X-Webhook-Signature` (NOT `X-Support-Desk-Signature`)
- Fire-and-forget: failure logged, ticket update proceeds

### 3.21 Background Sync Fixes (spec lines 1900–1916)

Changes from current:
- Query tickets with `freshdesk_id IS NOT NULL` AND `status IN ('open', 'in_progress')`
  (currently queries ALL statuses)
- Read Freshdesk creds from config store first, env vars as fallback
- Ignore FD Status 2 on pull (local is authoritative for open/triaged)
- Each ticket sync is independent (error on one doesn't block others)

### 3.22 Config Tools (spec lines 858–1178)

**`config_set_rules`** (spec lines 865–892):
- Add empty-text validation: `"rules text is required"`
- Add max length: 10000 chars
- Output format: `{"status": "updated", "key": "rules", "updated_at": "..."}`

**`config_set_persona`** (spec lines 896–914):
- Same pattern: empty-text validation, max 5000 chars, correct output format

**`config_restore_version`** (spec lines 1069–1106):
- version_index=0 → rejected: `"version_index 0 is the current version — cannot restore to itself"`
- Version exceeds history → clear error with latest available version
- Key never edited → `"no previous versions available for key '{key}'"`
- Invalid key → `"key must be 'rules' or 'persona'"`

**`config_set_freshdesk_creds`** (spec lines 1109–1141):
- Actually store in config table (NOT just log audit and say "restart required")
- Take effect immediately (background sync reads from config table)
- Audit log: mask API key — log only first 4 chars: `"key=abcd..."`
- Validation: empty domain/api_key → rejected
- Output: `{"platform": "freshdesk", "status": "configured", "updated_at": "..."}`

**`config_set_shopify_creds`** (spec lines 1144–1177):
- Same pattern as freshdesk: actual storage, immediate effect, token mask in audit
- Audit: `"token=****"` (never include the actual token)

### 3.23 Catalog Tools (spec lines 918–1065)

**`catalog_set_policy`** (spec lines 918–959):
- Return `embedding_regenerated: true/false` (NOT `embedded`)
- When Mistral down: return `embedding_regenerated: false` AND
  `warning: "Embedding unavailable. Policy saved but will not appear in semantic search results until re-indexed."`
- Validations: empty title/body/applies_to → rejected

**`catalog_set_order`** (spec lines 963–992):
- Same embedding_regenerated pattern
- Validate: content is a dict, serialized size ≤ 50KB

**`catalog_delete_item`** (spec lines 996–1023):
- Add `deleted_at` timestamp to output
- If item doesn't exist → "not found" (idempotent return)
- Output: `{"id": "...", "status": "deleted", "deleted_at": "..."}`

**`catalog_list_all`** (spec lines 1026–1065):
- **Admin-only** (NOT staff+)
- Add optional `limit` (default 50, max 200), `offset` (default 0) params
- Make `entity_type` optional (None/absent returns all types)
- Add `total` and `returned` to output
- Not audit logged

### 3.24 Database — ticket_notes Table (spec lines 1717–1734)

**This table does NOT exist.** Must create:
```sql
CREATE TABLE IF NOT EXISTS ticket_notes (
  id SERIAL PRIMARY KEY,
  ticket_id TEXT NOT NULL REFERENCES tickets(id),
  author_sub TEXT NOT NULL,
  author_role TEXT NOT NULL,   -- 'customer', 'staff', 'admin', or 'system'
  body TEXT NOT NULL,
  note_type TEXT NOT NULL,     -- 'reply', 'internal_note', or 'system_event'
  created_at TIMESTAMPTZ DEFAULT now()
);
```

**note_type values** (spec line 1728):
- `'reply'` — agent/customer reply (used by `domain_update_ticket` with `reply_body`)
- `'internal_note'` — internal agent note (not exposed to the ticket creator)
- `'system_event'` — auto-generated audit note (assignment, reassignment, status change)

### 3.25 Seed Data Files (spec lines 2376–2384)

**`seed/tickets.json`** — 5 sample tickets:
- 1 with `created_by` set to dev-user-001
- 1 with `assigned_to` set
- 1 with `csat_score`
- 1 with `freshdesk_id`
- Varied statuses (open, triaged, in_progress, pending, resolved)

**`seed/attachments.json`** — 2 attachment rows linked to seed tickets.

**`seed/notifications.json`** — 1 notification config for dev-user-001.

### 3.26 Deployment Files

**`Dockerfile`:**
```dockerfile
FROM python:3.14-slim
WORKDIR /app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen
COPY src/ ./src/
COPY seed/ ./seed/
COPY admin/ ./admin/
EXPOSE 8080
CMD ["uv", "run", "python", "-m", "connector_app.server"]
```

**`fly.toml`:** App name "support-desk", region "iad", PORT=8080, health check on /health.

### 3.27 server.py Infrastructure (spec lines 2326–2367)

- **`/health` GET endpoint** — returns `{"status": "ok"}` without auth (for Fly.io health checks)
- **Admin route path resolution** — use `Path(__file__).resolve().parent.parent.parent / 'admin' / 'index.html'`
  instead of relative string (which breaks from different CWDs)
- **`tools/list` filtering** — implement role-based tool filtering (see 3.2)

---

## 4. Implementation Order (12 Phases, 36 Steps)

### Phase 1: Database & Seed Data (3 steps)

| Step | What | Files |
|------|------|-------|
| 1.1 | Verify all 6 DDL tables exist in Neon. Create `ticket_notes` table. | (Neon SQL) |
| 1.2 | Seed `config_history` (version_index=0 for rules+persona if missing). Verify config rows current. | (Neon SQL) |
| 1.3 | Create seed data files: `seed/tickets.json`, `seed/attachments.json`, `seed/notifications.json`. | New files |

### Phase 2: Role Gating Correction (5 steps)

| Step | What | Files |
|------|------|-------|
| 2.1 | Fix role gates: `report_summary`→admin, `agent_performance`→admin, `catalog_list_all`→admin | tools/domain.py, tools/config.py, server.py |
| 2.2 | Implement `tools/list` role-based filtering in server.py | server.py, role_gate.py |
| 2.3 | Fix `get_ticket` identity: staff sees own+assigned, not all | tools/domain.py |
| 2.4 | Fix `get_attachment` identity: same pattern as get_ticket | tools/domain.py |
| 2.5 | Fix `attach_file` customer access: customers can attach to own tickets | tools/domain.py, server.py |

### Phase 3: Core v2 Tool Fixes (5 steps)

| Step | What | Files |
|------|------|-------|
| 3.1 | `get_ticket`: add `attachment_count`, `attachment_ids` | tools/domain.py |
| 3.2 | `get_customer_profile`: add `csat_trend` | tools/domain.py |
| 3.3 | `submit_csat`: resolved-only gate, `already_rated` handling | tools/domain.py |
| 3.4 | `create_ticket`: add `category` param, validation, embedding | tools/domain.py, server.py |
| 3.5 | `assign_ticket`: rename `agent`, resolved rejection, case-insensitive, FOR UPDATE | tools/domain.py, server.py |

### Phase 4: Attachment System — R2 (3 steps)

| Step | What | Files |
|------|------|-------|
| 4.1 | Implement R2 S3 client helpers in domain.py (upload, presigned URL) | tools/domain.py |
| 4.2 | Rewrite `attach_file`: MIME allowlist, 10MB limit, 10-attach limit, base64 validation, R2 upload | tools/domain.py |
| 4.3 | Rewrite `get_attachment`: presigned URL (15-min expiry), remove inline base64 | tools/domain.py |

### Phase 5: Notification Config & Dispatch (2 steps)

| Step | What | Files |
|------|------|-------|
| 5.1 | `configure_notifications`: email/HTTPS/event validation, "all" expansion, read-mode | tools/user.py, server.py |
| 5.2 | Fix `notifications.dispatch`: filter by ticket creator (not any user with matching config), fix webhook header name to `X-Webhook-Signature` | notifications.py |

### Phase 6: Drafts, Updates & Notification Wiring (4 steps)

| Step | What | Files |
|------|------|-------|
| 6.1 | Rewrite `draft_reply`: structured context with policy, history, agent | tools/domain.py |
| 6.2 | `update_ticket`: add `reply_body`, category enum, reopen clears | tools/domain.py, server.py |
| 6.3 | `reassign_ticket`: add `reason` param, `previous_agent` output | tools/domain.py, server.py |
| 6.4 | Wire `notifications.dispatch()` into update_ticket (fires only for ticket's `created_by` user) | tools/domain.py |

### Phase 7: Reports & Audit (3 steps)

| Step | What | Files |
|------|------|-------|
| 7.1 | `report_summary`: new period values, all output fields from spec | tools/domain.py |
| 7.2 | `agent_performance`: `period` param, csat/SLA/escalation fields | tools/domain.py, server.py |
| 7.3 | `get_audit_log`: add `total_matching`, `returned`, `id`; limit→500 | tools/domain.py |

### Phase 8: External Integrations (3 steps)

| Step | What | Files |
|------|------|-------|
| 8.1 | Rewrite `sync_to_freshdesk`: per-ticket, `action` param, real FD API with mappings | tools/domain.py, server.py |
| 8.2 | Fix `sync.py` background loop: filter open/in_progress, config store creds, ignore FD Status 2 | sync.py |
| 8.3 | `get_order`: Shopify fallback, `source` field, graceful error | tools/domain.py |

### Phase 9: Admin Config Tools (3 steps)

| Step | What | Files |
|------|------|-------|
| 9.1 | `set_rules`/`set_persona`: validation, output format | tools/config.py |
| 9.2 | `restore_version`: version_index=0 rejection, error messages | tools/config.py |
| 9.3 | `set_freshdesk_creds`/`set_shopify_creds`: actual config store, audit masking | tools/config.py |

### Phase 10: Catalog Fixes (2 steps)

| Step | What | Files |
|------|------|-------|
| 10.1 | `set_policy`/`set_order`: `embedding_regenerated` field, warning, validation | catalog.py |
| 10.2 | `list_all`: admin-only, pagination. `delete_item`: deleted_at, not-found | catalog.py, server.py |

### Phase 11: Infrastructure (2 steps)

| Step | What | Files |
|------|------|-------|
| 11.1 | Create `Dockerfile`, `fly.toml` | New files |
| 11.2 | Add `/health` endpoint, fix admin route path resolution | server.py |

### Phase 12: Final Verification (1 step)

| Step | What | Files |
|------|------|-------|
| 12.1 | Run tests. Verify tool listing. Clean commit. | tests/ |

---

## 5. Key Design Decisions

### 5.1 Config Versioning (spec contradiction resolved)

The `config_set_rules` section (line 868) says "NOT versioned / destructive" but `config_restore_version` and `config_history` depend on versioning. **Decision: Keep versioning.** The "not versioned" statement is outdated. Every `config_set_rules`/`config_set_persona` saves the previous value to `config_history` before overwriting.

### 5.2 R2 Presigned URL Generation

Use boto3's `generate_presigned_url` with `ClientMethod='get_object'`, `ExpiresIn=900` (15 min).
Credentials read from env vars: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT`, `R2_BUCKET`.
Endpoint URL format: `https://<accountid>.r2.cloudflarestorage.com`.

### 5.3 FastMCP tools/list Role Filtering

`tools/list` is an MCP protocol method, not a registered tool. FastMCP's
`add_tool_transformation()` runs at registration time — it cannot filter per-request.
Additionally, `tools/list` is called BEFORE `begin_session`, so there is no session token.

**Approach — Starlette middleware on `/mcp`:**

1. Mount a Starlette middleware or custom route handler wrapping the MCP app's mount
2. For `POST /mcp` with JSON-RPC body `{"method": "tools/list"}`:
   a. Extract the Descope JWT from the `Authorization` header (always sent by the client)
   b. Decode it to get the `role` claim (uses `get_access_token()` → `claims.role`)
   c. Call the original MCP handler to get the full tool list
   d. Filter: `role="admin"` → all tools; `role="staff"` → customer+agent; `role=null` → customer only
   e. Return the filtered list

**Fallback:** If middleware is too fragile, rely on backend role gating alone — every tool
already checks role on invocation and returns `"not found"` for unauthorized callers.
The tools/list filtering is defense-in-depth, not the sole access control mechanism.

### 5.4 Freshdesk Status Mapping (spec lines 1331–1347)

```
Local → Freshdesk (push):
  open/triaged   → 2 (Open)
  in_progress    → 3 (Pending)
  pending        → 3 (Pending)     [collapsed — no local equivalent in FD]
  resolved       → 4 (Resolved)
  closed         → 5 (Closed)

Freshdesk → Local (pull):
  2 (Open)       → IGNORED         [local authoritative]
  3 (Pending)    → pending
  4 (Resolved)   → resolved
  5 (Closed)     → closed
```

### 5.5 SLA Breach Definition (spec lines 753–758)

SLA breaches = count of tickets STILL OPEN at period end past their SLA target:
- critical > 1 hour
- high > 4 hours
- medium > 24 hours
- low > 72 hours

This is a **current-backlog metric**: tickets that breached SLA but were resolved before
period end are NOT counted.

---

## 6. Invariant Preservation

| # | Invariant | How preserved |
|---|-----------|---------------|
| 1 | One gateway | All tools on same FastMCP instance. No second server. |
| 2 | Tools only | No resources or prompts. Admin dashboard uses tools via fetch(). |
| 3 | Prove, don't trust | All tools use `sub` from session token. No `user_id` parameter. `tools/list` filters by role. |
| 4 | Fail closed | Every tool returns `_reminder`. Admin tools return "not found" for unauthorized callers. |

---

## 7. Files That Change (Summary)

| File | Change scope |
|------|-------------|
| `server.py` | Role-gating fixes for 3 tools, `tools/list` filtering, `/health` route, admin route path fix, customer attach_file access |
| `tools/domain.py` | 18 tool implementations — most need fixes per 3.3–3.21 above |
| `tools/user.py` | `configure_notifications` validation + read-mode |
| `tools/config.py` | validation, output format, actual credential storage |
| `catalog.py` | field names, validation, pagination, admin-gate |
| `notifications.py` | Fix webhook header name, creator-only filtering |
| `sync.py` | Fix query scope, config store creds, FD status handling |
| `role_gate.py` | Add `filter_tools_for_role()` function |
| `admin/index.html` | No changes (already correct) |
| `seed/tickets.json` | **New** — 5 sample tickets |
| `seed/attachments.json` | **New** — 2 attachment rows |
| `seed/notifications.json` | **New** — 1 notification config |
| `Dockerfile` | **New** |
| `fly.toml` | **New** |
| `tests/test_starter.py` | Fix for `require_session` return type (already done) |

---

## 8. Verification

After all phases:
- `uv run pytest -q` — all 8 tests pass
- `AUTH_DISABLED=1 uv run python -c "from connector_app.server import mcp..."` — all tools listed
- Spec acceptance criteria checked via manual curl/calls
- `git log` shows one commit per step for clean rollback
