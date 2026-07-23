# Support Desk — Behavioral Specification (v2 + v3)

**Extends v1.** v1 provided shared ticket lookup, order/policy search, ticket creation, cross-chat
state memory, and OAuth-gated identity. v2 deepens the support desk into a multi-agent system with
threading, satisfaction tracking, and analytics. v3 connects it to external platforms and hardens
multi-user isolation. v4 (autonomous agent loop) is out of scope here.

---

## Goal (the why)

**v2** turns the support desk from a single-customer lookup tool into a real multi-agent support
system. Human agents get assigned tickets, see their queue, draft AI-assisted replies, collect
post-resolution satisfaction ratings, and review audit logs. Customers attach files to tickets.
Managers see usage analytics.

**v3** connects the support desk to live external platforms (Freshdesk, Shopify) so
ticket data flows both ways and order data comes from the source of truth. Email and webhook
notifications let customers know when their ticket status changes. Multi-tenant hardening ensures
User B can never read User A's tickets — not even by guessing the ID — and private ticket content
becomes searchable (by its owner only).

No agent loop (that's v4). No web-based admin UI. Instead, admin tools within the MCP connector
(role-gated via Descope metadata) let business admins update rules, persona, policies, and catalog
items through the same AI chat interface — no SQL, no deploy, no developer needed. For bulk
editing and side-by-side review, a single-page admin dashboard served at `/admin` from the same
Fly.io application provides the same functionality with a web form interface, gated by the same
Descope sign-in and role check. No multi-language support. All existing v1 tools and invariants
remain untouched.

---

## User Scenarios

### v2 Scenario 1: Agent picks up a ticket and drafts a reply

> Ravi (human support agent) opens his AI assistant. He sees ticket tkt-004 assigned to him:
> "Damaged shoes — refund requested." He asks the AI: *"Draft a reply for ticket tkt-004."*

The AI calls `domain_get_ticket("tkt-004")` → sees the damage claim. Calls `domain_get_policy("pol-001")` →
learns the refund rule for defective items. Calls `domain_draft_reply("tkt-004")` → the service
returns structured context: ticket details, policy excerpt, customer history, and Ravi's name.
The AI composes a draft reply from this context: *"Hi Priya, I'm sorry about the damaged shoes.
Since they arrived defective, you're eligible for a full refund with no restocking fee. I've
authorized the return. You'll receive a prepaid return label within 2 hours. Your refund of $129
will process once we receive the shoes — typically 5-7 business days. — Ravi"* The AI shows Ravi
the draft. Ravi edits one line and calls `domain_update_ticket` with the `reply_body` to send.

**Visible failure if broken:** `domain_draft_reply` returns context that doesn't include the
ticket's actual content, policy, or customer name. The AI composes a draft that contradicts
policy (e.g., says "restocking fee applies" when the item is defective) because the tool
returned the wrong policy or no policy at all.

### v2 Scenario 2: Manager reviews weekly performance

> Sarah (support manager) asks her AI: *"How did the team do this week?"*

The AI calls `domain_report_summary("week")` → returns: tickets created (23), resolved (19),
avg resolution time (8.2h), top issue category ("billing disputes"), agents with most resolved.
The AI presents a clear summary. Sarah asks: *"How is agent Ravi performing?"* The AI calls
`domain_agent_performance("Ravi")` → returns Ravi's stats: 12 resolved, avg 6.1h, CSAT 4.6.

**Visible failure if broken:** `domain_report_summary` returns zeroes for a week that had
activity, or reports tickets for the wrong time period, or mixes data across different agents.

### v2 Scenario 3: Customer attaches a screenshot to a ticket

> Priya's damaged shoes ticket (tkt-004) is open. She opens her AI and says: *"I want to add
> photos of the damage to my ticket."*

The AI calls `domain_attach_file("tkt-004", <file_data>)` → the service stores the attachment
and links it to tkt-004. The AI confirms: *"Three photos attached to ticket tkt-004."* Later,
when Ravi looks at the ticket, the AI tells him there are attachments available.

**Visible failure if broken:** Attachment is stored but not linked to the ticket ID.
Subsequent `domain_get_ticket` calls show no indication that attachments exist. Or the
attachment is linked to the wrong ticket.

### v2 Scenario 4: Customer rates resolution, manager checks CSAT

> Ravi resolves Priya's ticket. Priya gets a prompt via her AI: *"Was your issue resolved?
> Rate 1-5."* She says: *"5 — great service."*

The AI calls `domain_submit_csat("tkt-004", 5)` → the service records the score against
the ticket. Later, Sarah checks the weekly report → CSAT average is now updated to include
this score.

**Visible failure if broken:** CSAT score is recorded but not reflected in
`domain_report_summary` or `domain_agent_performance`. Or CSAT scores from different tickets
are averaged incorrectly (e.g., counting closed tickets that were never rated as 0).

### v3 Scenario 5: Ticket syncs to Freshdesk

> Ravi's company uses Freshdesk as their primary helpdesk. A customer creates ticket tkt-008
> through the AI assistant. The AI assistant (connected to this gateway) calls
> `domain_sync_to_freshdesk("tkt-008")` → the ticket appears in Ravi's Freshdesk queue with
> the same subject, body, priority, and customer identity. When Ravi closes it in Freshdesk,
> the status syncs back: `domain_get_ticket("tkt-008")` now shows `status: "closed"`.

**Visible failure if broken:** Ticket appears in Freshdesk but the body is truncated or
priority is wrong. Status change in Freshdesk doesn't propagate back. Or the sync creates
a duplicate ticket on every call instead of updating the existing one.

### v3 Scenario 6: Customer gets notified on status change

> Julia filed ticket tkt-005 about being overcharged. She configured notifications via her AI:
> *"Let me know if anything changes on my ticket."*

The AI calls `user_configure_notifications(email="julia@example.com")` → the service records
her email for notifications. Later, when an agent updates the ticket status to "in_progress",
the service sends an email: *"Your ticket tkt-005 is now being reviewed by a billing specialist."*

**Visible failure if broken:** Notification is configured but never sent. Or notification is
sent to the wrong email address. Or notification fires for a different user's ticket.

### v3 Scenario 7: Multi-tenant isolation prevents cross-user access

> User A creates ticket tkt-010 about their account. User B (a different customer) guesses
> the ticket ID and asks their AI: *"Show me ticket tkt-010."*

The AI calls `domain_get_ticket("tkt-010")` → the service checks: `created_by` for tkt-010
is User A's identity. User B's identity doesn't match. The service returns `"not found"` —
same response as if the ticket didn't exist. User B learns nothing. User B tries
`domain_search("account")` with `include_my_tickets: true` → only User B's own tickets
appear in results. User A's ticket tkt-010 is never exposed.

**Visible failure if broken:** User B successfully reads User A's ticket by ID. Or
`domain_search` with `include_my_tickets: true` returns tickets that don't belong to the
caller. Or the error message distinguishes "not found" from "not your ticket" — leaking
that the ticket exists.

### v3 Scenario 8: Live order data from Shopify

> Customer asks: *"Where's my order ORD-9921?"* The order isn't in the seed catalog — it's
> a live order from the Shopify store.

The AI calls `domain_get_order("ORD-9921")` → the service checks the local catalog first
(seed data). Not found. Falls through to the Shopify API → finds the order: *"Wireless
Earbuds Pro, $89.99, shipped via USPS #9400..., estimated delivery tomorrow."* The AI
presents the live data. The customer sees accurate, real-time order status.

**Visible failure if broken:** Tool returns "not found" for an order that exists on Shopify.
Or returns stale seed data when the Shopify order is more recent. Or the Shopify API being
down causes `domain_get_order` to crash (it should fall back gracefully).

### v2 Scenario 9: Business admin updates policy without a developer

> The refund window changes from 30 to 60 days. Sarah (business admin) opens her AI assistant
> (same connector, same tools — but Sarah has `role: "admin"` in her Descope profile, set by
> the business owner in the Descope Dashboard). She says: *"Update our refund policy: change
> the return window from 30 days to 60 days. No restocking fee for any returns under $100. The
> rest stays the same."*

The AI calls `catalog_set_policy("pol-001", "Refund & Return Policy",
"Customers may return items within 60 days of delivery for a full refund...", "all physical products")`
→ the service upserts the policy content into the catalog, calls Mistral to generate a new
1024-dim embedding for semantic search, and confirms the update. Seconds later, any customer
who asks "what's your refund policy?" via `domain_search` or `domain_get_policy` sees the
60-day window. No developer deployed code. No SQL console. No Nebula UI.

**Visible failure if broken:** Policy text updates but embedding is stale — `domain_search("return
policy")` returns the old similarity score or fails to rank the updated policy. Or the tool
requires SQL knowledge from the business admin. Or a non-admin customer calls the same tool
and successfully modifies the catalog.

### v2 Scenario 10: Business admin adjusts the assistant's behavior

> Sarah notices the AI is being too formal with returning customers. She says: *"Make the
> persona more casual and friendly for returning customers — use their first name, skip the
> formal greeting after the first interaction."*

The AI calls `config_set_persona("PERSONA — SUPPORT DESK ASSISTANT\n...updated text...")` →
the service updates the persona in the config store. The next `begin_session` call by any
customer returns the updated persona. All customer interactions from that point use the new
voice. Sarah didn't touch a database, a config file, or a deployment — she described the change
in plain language and the AI's admin-gated tool applied it.

**Visible failure if broken:** Sarah gets "not found" when calling config_set_persona because
her admin role wasn't recognized from Descope. Or the update succeeds but subsequent
`begin_session` calls still return the old persona (caching bug).

### v2 Scenario 11: Admin uses dashboard for bulk policy updates

> Sarah needs to update 6 policies at once after a compliance review. The AI chat interface is
> great for one-off changes but slow for bulk work — updating 6 policies would take 6 separate
> chat exchanges. She opens her browser and navigates to `https://support-desk.fly.dev/admin`.
> The page shows a Descope sign-in prompt (same provider as the MCP connector). After sign-in,
> the dashboard recognizes Sarah's `role: "admin"` from her Descope profile and loads all
> policies in a table. Each row shows the policy ID, title, applies_to, and last-updated
> timestamp. Sarah clicks the first row — it expands into an inline editor with textareas for
> title, body, and applies_to. She pastes the updated compliance text, clicks Save, and sees a
> green "Saved" confirmation. She repeats for the remaining 5 policies — each save triggers
> `catalog_set_policy` automatically, regenerating the Mistral embedding in the background. She
> also scrolls up to the Rules editor, adds a new escalation trigger: "compliance violation
> suspected," and saves. The entire compliance update takes 4 minutes — no developer, no SQL, no
> deploy. The next customer who searches for a policy via `domain_search` gets the updated
> versions with fresh semantic embeddings.

**Visible failure if broken:** The page loads but the policy table is empty (failed to fetch
from DB). Save button does nothing (JS error). Non-admin accesses `/admin` and sees the policy
editor instead of "Access denied." Session expires mid-edit and Save silently fails without
prompting re-login. Dashboard loads stale data from browser cache instead of fresh DB state.

### v2 Scenario 12: Staff agent completes a full ticket lifecycle

> Julia (customer) opens her AI assistant and says: *"I was charged twice for my subscription —
> order ORD-8821, $49 each. Please help."* The AI calls `domain_create_ticket(subject="Double
> charge on subscription", body="Charged twice for order ORD-8821...", priority="high",
> category="billing")` → ticket tkt-012 is created with status "open". Ravi (staff agent) opens
> his AI assistant. He sees tkt-012 in the queue after calling `domain_get_ticket("tkt-012")`.
> He calls `domain_assign_ticket("tkt-012", "Ravi")` → status becomes "in_progress".
>
> Ravi asks his AI: *"Draft a reply for ticket tkt-012."* The AI calls `domain_draft_reply("tkt-012")`
> → returns structured context. The AI composes: *"Hi Julia, I've located your order ORD-8821 and
> I can confirm there was a duplicate charge of $49. I've initiated a refund of $49 which should
> appear on your card within 3-5 business days."* Ravi approves and says *"Send it."* The AI calls
> `domain_update_ticket("tkt-012", reply_body="Hi Julia, ...", status="resolved")` → the reply
> is sent and Julia receives an email notification (if she configured it).
>
> Julia opens her AI: *"Did my ticket get resolved?"* The AI calls `domain_get_ticket("tkt-012")` →
> shows status "resolved". Julia says: *"Rate it 5 stars."* The AI calls
> `domain_submit_csat("tkt-012", 5)` → score recorded. Ravi later asks: *"How's my performance?"*
> but his AI responds that `domain_agent_performance` is unavailable — it's admin-only. Only
> Sarah (admin) can see the team metrics.

**Visible failure if broken:** Any step in the chain fails silently — ticket doesn't transition
from open to in_progress on assignment, reply doesn't trigger notification, CSAT isn't linked
to the correct agent.

### v2 Scenario 13: Mistral embedding API is down during policy updates

> Sarah needs to update 3 policies (pol-001 through pol-003) from the dashboard after a compliance
> review. The Mistral embedding API is experiencing an outage. She opens the policy table, clicks
> pol-001, pastes the updated text, and clicks Save. `catalog_set_policy` saves the content to
> the database but Mistral is unreachable. The tool returns: `{"status": "updated",
> "embedding_regenerated": false, "warning": "Embedding unavailable. Policy saved but will not
> appear in semantic search results until re-indexed."}` The dashboard shows a yellow warning
> instead of the green "Saved" toast.
>
> Sarah continues and saves pol-002 and pol-003 with the same result. All three policies are
> saved and accessible by ID (`domain_get_policy("pol-001")` returns the updated text) but none
> appear in `domain_search` results. An hour later, Mistral recovers. Sarah re-opens each policy
> in the dashboard and clicks Save again (same text). This time `embedding_regenerated: true`
> returns for all three. Customers searching for policy keywords now find the updated versions.

**Visible failure if broken:** Dashboard crashes instead of showing the warning. Save fails
entirely instead of gracefully saving content without embeddings. Customer gets old policy
content via `domain_get_policy` after save.

### v2 Scenario 14: SendGrid rate limit hit during heavy notification day

> It's Monday morning and 20 customers have tickets resolved within the same hour. All have
> email notifications configured. The first 100 emails of the day send successfully via
> SendGrid (free tier: 100 emails/day). Ticket tkt-015 is the 101st resolution of the day.
>
> Ravi resolves tkt-015. The AI calls `domain_update_ticket("tkt-015", status="resolved",
> reply_body="Your refund has been processed...")`. The tool updates the ticket status
> successfully and attempts to send the notification email. SendGrid returns HTTP 429 (rate
> limit exceeded). The email delivery fails — logged as a warning with the correlation ID.
> The tool still returns: `{"ticket_id": "tkt-015", "status": "resolved", "reply_sent": true,
> "updated_at": "..."}`. Ravi sees the confirmation. Neither Ravi nor Julia know the email
> failed. The failure is in the application logs only.
>
> SendGrid's rate limit resets at midnight UTC. The next day, notifications resume normally.
> Julia can check her ticket status manually via `domain_get_ticket("tkt-015")` — the
> resolution is recorded even if the notification didn't fire.

**Visible failure if broken:** Rate limit causes the entire `domain_update_ticket` call to
fail (rejecting the status change because email failed). Or the rate limit error is surfaced
to the customer as a tool error message. Or emails silently drop without any logging.

---

## Access Control (Role Gating)

The support desk has three roles, all managed through Descope user metadata. The role is set as
a custom claim in the Descope JWT, verified by `auth.py` alongside `sub`, and embedded in the
session token by `begin_session`. The role claim is HMAC-signed — tampering invalidates the token.

```
Descope Dashboard → User → Metadata → { "role": "admin" | "staff" | <absent> }
                         │
                         ▼
Descope JWT claims: { "sub": "...", "role": "admin"|"staff", ... }
                         │
                         ▼
auth.py verifies JWT → exposes full claims dictionary
                         │
                         ▼
begin_session() copies role into session token
                         │
         ┌───────────────▼───────────────┐
         │ role == "admin"?  → All tools │
         │ role == "staff"?  → Staff set │
         │ role is null?     → Customer  │
         └───────────────────────────────┘
```

### Role Definitions

| Role | Descope Metadata | Description |
|------|-----------------|-------------|
| **Admin** | `{ "role": "admin" }` | Full access — all customer, agent, and admin tools. Manages rules, persona, policies, catalog items, reports, and platform credentials. |
| **Staff / Agent** | `{ "role": "staff" }` | Support agent — customer-facing tools + agent tools (assign, draft, reassign, audit log, attachment access). Cannot edit catalog, config, or platform credentials. Cannot see reports. |
| **Customer** | role absent / null | End user — creates and views own tickets, searches catalog, submits CSAT, attaches files, configures notifications. Cannot access agent or admin tools. |

### Tool Gating Matrix

| Tool | Customer | Staff | Admin |
|------|:---:|:---:|:---:|
| `begin_session` | ✓ | ✓ | ✓ |
| `domain_create_ticket` | ✓ | ✓ | ✓ |
| `domain_get_ticket` | ✓ (own only) | ✓ (own + assigned) | ✓ (own + assigned) |
| `domain_search` | ✓ | ✓ | ✓ |
| `domain_get_policy` | ✓ | ✓ | ✓ |
| `domain_get_order` | ✓ | ✓ | ✓ |
| `domain_submit_csat` | ✓ | ✓ | ✓ |
| `domain_attach_file` | ✓ (own tickets) | ✓ (own + assigned) | ✓ (own + assigned) |
| `domain_get_attachment` | ✓ (own only) | ✓ (own + assigned) | ✓ (own + assigned) |
| `domain_get_customer_profile` | ✓ | ✓ | ✓ |
| `user_save_state` | ✓ | ✓ | ✓ |
| `user_get_profile` | ✓ | ✓ | ✓ |
| `user_configure_notifications` | ✓ | ✓ | ✓ |
| `domain_draft_reply` | — | ✓ | ✓ |
| `domain_assign_ticket` | — | ✓ | ✓ |
| `domain_reassign_ticket` | — | ✓ | ✓ |
| `domain_update_ticket` | — | ✓ | ✓ |
| `domain_sync_to_freshdesk` | — | ✓ | ✓ |
| `domain_get_audit_log` | — | ✓ | ✓ |
| `domain_report_summary` | — | — | ✓ |
| `domain_agent_performance` | — | — | ✓ |
| `config_set_rules` | — | — | ✓ |
| `config_set_persona` | — | — | ✓ |
| `config_restore_version` | — | — | ✓ |
| `catalog_set_policy` | — | — | ✓ |
| `catalog_set_order` | — | — | ✓ |
| `catalog_delete_item` | — | — | ✓ |
| `catalog_list_all` | — | — | ✓ |
| `config_set_freshdesk_creds` | — | — | ✓ |
| `config_set_shopify_creds` | — | — | ✓ |

### Admin Tool Gating Rules

**Key rule:** A non-admin calling an admin-only tool receives the exact same response as calling a
non-existent tool: `"not found"`. The response must NOT distinguish "this tool exists but you're
not authorized" from "this tool doesn't exist." The tool's name, description, and existence are
invisible to non-admin callers. The AI model never sees admin tools in a non-admin's session —
they are excluded from tool discovery (the MCP `tools/list` response must omit admin tools for
non-admin sessions, and both admin and agent tools for customer sessions).

**Session token role caching:** The role is extracted from the Descope JWT on every `begin_session`
call, embedded in the session token, and cached for the session duration (30 min). This means:

- **Adding a role:** Go to Descope Dashboard → Users → select the user → User Metadata → set
  `{ "role": "admin" }` or `{ "role": "staff" }`. Next `begin_session` picks up the new role.
- **Removing a role:** Delete the `role` metadata field. Next `begin_session` → role is null →
  tool list shrinks to customer tier.
- **Role change delay:** Active sessions with the old role remain valid until their session token
  expires (30 min). Role changes are not real-time — they take effect on the next `begin_session`.
- **Session token tampering:** If the `role` claim in the session token is modified, the HMAC
  signature becomes invalid and `require_session` rejects the token.

### Setting Up Roles in Descope Dashboard

**Step-by-step:**
1. Log into [Descope Console](https://app.descope.com) → select your project.
2. Navigate to **Authorization** → **Users** → find the user in the list or search by email.
3. Click the user row to open their profile.
4. Scroll to **User Metadata** → click **Add**.
5. Enter key: `role`, value: `admin` (for full access) or `staff` (for agent access).
6. Click **Save**. No code change, no deploy, no database migration needed.
7. The user's next `begin_session` call picks up the new role.

**Removing a role:** Delete the `role` key from User Metadata, or set value to an empty string.
Next `begin_session` → `role: null` → customer-tier access.

**Setting up the custom claim in Descope (one-time):**
1. Navigate to **Authorization** → **JWT Templates** → select the access token template.
2. Under **Custom Claims**, add a claim with name `role`, source type **User Metadata**,
   metadata key `role`. The claim is now included in every access token issued by Descope.
3. If your Descope plan does not support custom claims, the connector must fall back to the
   Descope Management API: `begin_session` calls `GET /v1/mgmt/user/{sub}` with a Management
   API key (stored as Fly secret `DESCOPE_MANAGEMENT_API_KEY`) to fetch the user's metadata
   and extract `role`. This adds ~50ms latency to `begin_session`.

---

## Functional Requirements

### v1 Tools (Prerequisite Reference)

These tools exist from v1 and are assumed present. Their v2/v3 modifications are documented
in the respective modification sections below. This table defines their contract for context.

| Tool | Input | Output | Notes |
|------|-------|--------|-------|
| `health` | none | `{"status": "ok"}` | Gateway health check, no auth required |
| `begin_session` | none (reads OAuth token) | `{session_token, rules, persona, state, role}` | v3 adds `role` field |
| `domain_get_ticket` | `id` | `{id, subject, body, status, priority, category, created_by, ...}` | v2 adds `attachment_count/ids`; v3 adds identity hardening |
| `domain_create_ticket` | `subject, body, priority?, category?` | `{id, subject, status: "open", ...}` | Priority defaults to "medium"; category defaults to "other" |
| `domain_get_policy` | `id` | `{id, title, body, applies_to, ...}` | Reads from `support_embeddings` table |
| `domain_get_order` | `id` | `{id, items, tracking, ...}` | v3 adds Shopify live lookup with `source` field |
| `domain_search` | `query, include_my_tickets?` | `[{id, entity_type, content, similarity, status?, priority?}]` | v3 adds `include_my_tickets` for personal ticket search |
| `domain_get_customer_profile` | none (reads from session) | `{tickets_count, resolved_count, avg_csat, csat_trend, ...}` | v2 adds `csat_trend` field |
| `user_save_state` | `key, value` | `{key, status: "saved"}` | Cross-chat memory, keyed by `sub` |
| `user_get_profile` | none (reads from session) | `{state: {...}, tickets_summary: ...}` | Returns saved state + ticket overview |
| `user_configure_notifications` | `email?, webhook_url?, events?` | `{email, webhook_url, events, configured_at}` | v3 new tool; no params = read current config |
| `domain_sync_to_freshdesk` | `ticket_id, action?` | `{ticket_id, freshdesk_id, sync_status, synced_at}` | v3 new tool |
| `domain_get_attachment` | `ticket_id, attachment_id` | `{attachment_id, file_name, mime_type, presigned_url, url_expires_at}` | v2 new tool |
| `domain_get_audit_log` | `user_id?, tool_name?, since?, limit?` | `{entries: [...], total_matching, returned}` | v2 new tool, staff+ gated |

### New v2 Tools

#### `domain_assign_ticket`

**What it does:** Assigns a support ticket to a human agent. The agent name is recorded on the
ticket. If the ticket already has a different agent assigned, the assignment is updated (reassignment).
Returns the ticket's current state after assignment.

**Input:**
- `ticket_id` (string, required): The ticket to assign — e.g. "tkt-004".
- `agent` (string, required): The agent name or identifier — e.g. "Ravi" or "agent-ravi-01".

**Output:**
```json
{
  "ticket_id": "tkt-004",
  "assigned_to": "Ravi",
  "status": "in_progress",
  "assigned_at": "2026-07-24T09:15:00Z"
}
```

**Behavior:**
- Assigning a ticket automatically transitions its status from "open" to "in_progress" (unless
  already "in_progress" or further along). Status must never move backwards.
- If the ticket is already assigned to the same agent, return the current state — no change, no error.
  Agent name matching is case-insensitive and trimmed of whitespace (consistent with
  `domain_agent_performance`).
- If the ticket is assigned to a different agent, update `assigned_to` to the new agent. Status
  stays "in_progress" (or whatever it already is, as long as it's not "resolved" or "closed").
- If the ticket is "resolved" or "closed", reject with: "ticket is already resolved — cannot reassign."

**Validation:**
- Non-existent ticket → "not found"
- Empty agent name → "agent is required"
- Ticket resolved/closed → "ticket is already resolved — cannot reassign"

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `staff` or `admin` in session token.

---

#### `domain_reassign_ticket`

**What it does:** Explicitly transfers a ticket from one agent to another. Records the transfer
reason. Distinct from `domain_assign_ticket` to make intent clear in the audit trail.

**Input:**
- `ticket_id` (string, required)
- `new_agent` (string, required)
- `reason` (string, optional): Why the transfer — e.g. "vacation coverage", "escalation to
  specialist", "wrong department".

**Output:**
```json
{
  "ticket_id": "tkt-004",
  "assigned_to": "Priya",
  "previous_agent": "Ravi",
  "reason": "escalation to billing specialist",
  "reassigned_at": "2026-07-24T14:30:00Z"
}
```

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `staff` or `admin` in session token.

---

#### `domain_update_ticket`

**What it does:** Updates mutable fields on a support ticket — status, priority, category, and
reply body. Status changes follow the state machine (see Ticket Status State Machine below).
This is the only tool that can change ticket status directly (assignment tools call it internally).

**Input:**
- `ticket_id` (string, required): The ticket to update.
- `status` (string, optional): New status. Must be a valid transition from the current status.
  See status state machine for allowed transitions.
- `priority` (string, optional): One of `"critical"`, `"high"`, `"medium"`, `"low"`.
- `category` (string, optional): One of `"billing"`, `"returns"`, `"technical"`, `"account"`,
  `"shipping"`, `"other"`.
- `reply_body` (string, optional): Agent's reply text. Appended to ticket history as a note
  from the agent. Triggers synchronous notification dispatch to the ticket creator if they have
  notifications configured for the changed status's event type.

**Output:**
```json
{
  "ticket_id": "tkt-004",
  "status": "resolved",
  "priority": "high",
  "category": "returns",
  "reply_sent": true,
  "updated_at": "2026-07-24T15:00:00Z"
}
```

**Behavior:**
- All parameters are optional — only provided fields are updated. Calling with just `ticket_id`
  returns the current ticket state (no-op read).
- Status transitions are validated against the state machine. Invalid transition → rejected.
- Setting status to "resolved" automatically sets `resolved_at` to now.
- Setting status to "open" from "resolved" (reopen) clears `resolved_at` and `csat_score`.
- `reply_body` triggers synchronous notification dispatch to the ticket creator (if they have
  notifications configured). Email is sent via SendGrid API; webhook is POSTed with HMAC-SHA256
  signature. Notification failure does not block the update.
- Audit logged with summary of changed fields.
- Priority and category validated against fixed enums. Invalid value → rejected with a message
  listing valid options.

**Validation:**
- Non-existent ticket → `"not found"`
- Invalid status transition → `"cannot transition from {current} to {requested}"`
- Invalid priority → `"priority must be one of: critical, high, medium, low"`
- Invalid category → `"category must be one of: billing, returns, technical, account, shipping, other"`

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `staff` or `admin` in session token.

---

#### `domain_submit_csat`

**What it does:** Records a customer satisfaction score for a resolved ticket. A ticket can
be rated only once — second call on the same ticket returns the existing score without error.

**Input:**
- `ticket_id` (string, required)
- `score` (integer, required, 1–5): 1 = very dissatisfied, 5 = very satisfied.

**Output:**
```json
{
  "ticket_id": "tkt-004",
  "csat_score": 5,
  "submitted_at": "2026-07-24T16:00:00Z"
}
```

**Behavior:**
- Can only be submitted for tickets with status "resolved". Reject with
  "ticket must be resolved before rating" if the ticket is open, in_progress, triaged, or closed.
- If the ticket already has a CSAT score (re-submission), return the existing score:
  `{"ticket_id": "tkt-004", "csat_score": 5, "already_rated": true, "submitted_at": "<original timestamp>"}`.
  Do not error — returning the existing score is correct behavior.

**Validation:**
- Non-existent ticket → "not found"
- Score not in 1–5 range → "score must be between 1 and 5"
- Ticket not resolved → "ticket must be resolved before rating"

**Requires sign-in:** Yes.
**Requires session:** Yes.

---

#### `domain_attach_file`

**What it does:** Attaches a file (image, PDF, or text) to a support ticket. Multiple attachments
per ticket are allowed. Each attachment is stored with a sequential identifier.

**Input:**
- `ticket_id` (string, required)
- `file_data` (base64-encoded string, required): The file content, encoded as base64.
- `file_name` (string, required): Original filename — e.g. "damaged_sole.jpg".
- `mime_type` (string, required): MIME type — e.g. "image/jpeg", "application/pdf", "text/plain".

**Output:**
```json
{
  "attachment_id": "att-001",
  "ticket_id": "tkt-004",
  "file_name": "damaged_sole.jpg",
  "size_bytes": 245760,
  "attached_at": "2026-07-24T10:00:00Z"
}
```

**Behavior:**
- Maximum file size: 10MB. Larger → rejected: "file exceeds 10MB limit."
- Maximum attachments per ticket: 10. More → rejected: "ticket already has 10 attachments."
- Only these MIME types are accepted: image/jpeg, image/png, image/gif, application/pdf,
  text/plain, text/csv. Others → rejected: "unsupported file type: {mime_type}."
- When `domain_get_ticket` is called, its output includes `attachment_count` and
  `attachment_ids` so the AI knows attachments exist.

**Validation:**
- Non-existent ticket → "not found"
- Empty file_data → "file data is required"
- Empty file_name → "file name is required"
- Invalid base64 → "file data is not valid base64"

**Requires sign-in:** Yes.
**Requires session:** Yes.

---

#### `domain_get_attachment`

**What it does:** Returns a presigned URL for downloading a file attachment from Cloudflare R2.
The URL is valid for 15 minutes. The actual file content is never returned inline.

**Input:**
- `ticket_id` (string, required): The ticket the attachment belongs to.
- `attachment_id` (string, required): The attachment to retrieve — e.g. "att-001".

**Output:**
```json
{
  "attachment_id": "att-001",
  "ticket_id": "tkt-004",
  "file_name": "damaged_sole.jpg",
  "mime_type": "image/jpeg",
  "size_bytes": 245760,
  "presigned_url": "https://<bucket>.r2.cloudflarestorage.com/...?X-Amz-Expires=900...",
  "url_expires_at": "2026-07-24T10:15:00Z"
}
```

**Behavior:**
- The presigned URL is an S3-compatible presigned GET URL for the R2 bucket. No auth required
  to download — the signature in the URL grants temporary access.
- Ticket owner can access attachments on their own tickets (v3 hardening: `created_by` must
  match caller's `sub`).
- Staff+ (role admin or staff) can access attachments on tickets assigned to them.
- If the caller has no access → `"not found"` (identical to nonexistent attachment).
- If the R2 object is missing (deleted/expired) → `"attachment file not found"`.
- The calling AI model receives the presigned URL and can present it to the user as a clickable
  link or instruct the user to download it.

**Validation:**
- Non-existent ticket → `"not found"`
- Non-existent attachment → `"not found"`
- Attachment exists on a different ticket → `"not found"`

**Requires sign-in:** Yes.
**Requires session:** Yes.

**`domain_get_ticket` output change (v2):** The ticket output now includes:
```json
{
  "id": "tkt-004",
  "... all existing fields ...": "...",
  "attachment_count": 3,
  "attachment_ids": ["att-001", "att-002", "att-003"]
}
```

---

#### `domain_draft_reply`

**What it does:** Returns structured context for a human agent to compose a reply. This tool
gathers ticket details, relevant policies, customer profile, and the assigned agent's name —
but does NOT generate natural language. The calling AI model (Claude) composes the final draft
from the returned context. The server does deterministic work; the AI does generation.

**Input:**
- `ticket_id` (string, required)

**Output:**
```json
{
  "ticket_id": "tkt-004",
  "customer_name": "Priya",
  "ticket_subject": "Damaged item on delivery — order ORD-8821",
  "ticket_body": "I received my order today and the running shoes have a torn sole...",
  "ticket_status": "in_progress",
  "ticket_priority": "high",
  "policy_id": "pol-001",
  "policy_title": "Refund & Return Policy",
  "policy_excerpt": "Customers may return defective items within 30 days for a full refund with no restocking fee...",
  "customer_history": "2 previous tickets: both resolved, CSAT avg 4.5",
  "agent_name": "Ravi",
  "recommended_action": "Offer full refund with prepaid return label per pol-001"
}
```

**Behavior:**
- The tool queries the ticket, looks up the first relevant policy by matching keywords from the
  ticket body/subject against policy titles, and fetches the customer's ticket history.
- `policy_id` and `policy_excerpt` are null if no matching policy is found.
- `customer_history` is null if this is the customer's first ticket.
- If no agent is assigned, `agent_name` is `null` and `recommended_action` suggests
  "Assign an agent first before drafting a reply."
- This is a pure read tool — it never modifies any data. Each call is independent.
- **Fail-safe:** If the ticket body is empty or null, `ticket_body` is empty and all
  context fields are populated with what IS available. The `recommended_action` notes:
  "The ticket has no details yet — ask the customer to provide more information."

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `staff` or `admin` in session token.

---

#### `domain_report_summary`

**What it does:** Returns aggregate support desk metrics for a given time period. Counts, averages,
top categories, and SLA compliance. This is a snapshot — every call recomputes from live ticket data.

**Input:**
- `period` (string, required): One of "today", "yesterday", "week" (last 7 days), "month"
  (last 30 days), "quarter" (last 90 days).

**Output:**
```json
{
  "period": "week",
  "from": "2026-07-17T00:00:00Z",
  "to": "2026-07-24T00:00:00Z",
  "tickets_created": 23,
  "tickets_resolved": 19,
  "avg_resolution_time_hours": 8.2,
  "avg_csat_score": 4.3,
  "sla_breaches": 2,
  "top_categories": [
    {"category": "billing", "count": 8},
    {"category": "returns", "count": 6},
    {"category": "technical", "count": 4}
  ],
  "by_priority": {
    "critical": 1,
    "high": 7,
    "medium": 10,
    "low": 5
  }
}
```

**Behavior:**
- `tickets_created`: count of tickets with `created_at` within the period.
- `tickets_resolved`: count of tickets with `resolved_at` within the period.
- `avg_resolution_time_hours`: average of `(resolved_at - created_at)` in hours, for tickets
  resolved within the period. Null if no tickets were resolved.
- `avg_csat_score`: average of `csat_score` for tickets resolved within the period. Null if no
  ratings exist.
- `sla_breaches`: count of tickets still open at period end that exceeded their SLA target
  (critical > 1h, high > 4h, medium > 24h, low > 72h). This is a **current-backlog metric**:
  only tickets that are STILL open past their SLA at period-end count. A ticket that breached
  SLA at any time during the period but was resolved before period-end is NOT counted — it
  no longer needs attention. This is an explicit design decision: `sla_breaches` measures
  currently-burning fires, not historical breaches.
- `top_categories`: tickets grouped by the `category` field on the ticket. At most 5
  categories returned, ranked by count. If fewer than 5 categories are present in the
  period, return only those. Categories with zero tickets are omitted.
- All-zero response for a period with no activity is valid (not an error).

**Validation:**
- Invalid period → "period must be one of: today, yesterday, week, month, quarter"

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in session token.

---

#### `domain_agent_performance`

**What it does:** Returns performance metrics for a specific human agent across all time
(or the specified period). Used by managers reviewing team performance.

**Input:**
- `agent` (string, required): Agent name or identifier — e.g. "Ravi".
- `period` (string, optional): Same period values as `domain_report_summary`. Default: all time.

**Output:**
```json
{
  "agent": "Ravi",
  "period": "all_time",
  "tickets_assigned": 47,
  "tickets_resolved": 41,
  "avg_resolution_time_hours": 6.1,
  "avg_csat_score": 4.6,
  "sla_breaches": 1,
  "current_open_tickets": 3,
  "escalations_handled": 5
}
```

**Behavior:**
- `tickets_assigned`: count of tickets where `assigned_to` = this agent (ever).
- `tickets_resolved`: count of those tickets with status "resolved" or "closed".
- `avg_resolution_time_hours` and `avg_csat_score`: filtered to this agent's tickets only.
- `current_open_tickets`: tickets currently assigned to this agent with status NOT resolved/closed.
- `escalations_handled`: count of tickets assigned to this agent where the previous agent was
  different (reassignments with a reason containing "escalation").
- Agent name matching is case-insensitive and trimmed of whitespace.

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in session token.

---

#### `domain_get_audit_log`

**What it does:** Returns audit log entries filtered by optional criteria. This is the read-side
of the audit trail (write-side was added in v1 — every tool call already logs). Restricted to
authorized roles.

**Input:**
- `user_id` (string, optional): Filter to entries for a specific user.
- `tool_name` (string, optional): Filter to a specific tool — e.g. "domain_get_ticket".
- `since` (string, optional): ISO 8601 timestamp — only entries after this time.
- `limit` (integer, optional): Max entries to return. Default 50. Max 500.

**Output:**
```json
{
  "entries": [
    {
      "id": 1042,
      "user_id": "user_3Gtab...",
      "tool_name": "domain_get_ticket",
      "input_summary": "id=tkt-004",
      "output_summary": "found ticket tkt-004",
      "created_at": "2026-07-24T09:15:00Z"
    }
  ],
  "total_matching": 1042,
  "returned": 50
}
```

**Behavior:**
- Entries are returned newest-first.
- `total_matching` is the count of all entries matching the filters (before limit), so the
  caller knows if more entries exist.
- If no filters are provided, returns the most recent 50 entries across all users and tools.
- This tool is gated to staff+ (admin and staff roles). The data it returns is an audit
  trail of tool usage across the support desk. Staff see all entries; per-user filtering by
  `user_id` parameter provides narrower visibility when needed.

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `staff` or `admin` in session token.

---

### Admin Tools (v2, Role-Gated)

Admin tools require the signed-in user to have `role: "admin"` in their Descope user metadata.
Non-admin callers receive `"not found"` — identical to calling a non-existent tool. Admin tools
are excluded from MCP `tools/list` for non-admin sessions, so the AI model never sees them. The
admin role is extracted from the Descope JWT claims on every `begin_session`, cached for the
session duration, and re-verified when the session token expires and a new `begin_session` is called.

#### `config_set_rules`

**What it does:** Replaces the current behavioral rules text. Takes effect on the next
`begin_session` call by any user. The previous rules are NOT versioned — the update is
immediate and destructive (the old text is lost).

**Input:**
- `text` (string, required, max 10000 characters): The new rules text.

**Output:**
```json
{
  "status": "updated",
  "key": "rules",
  "updated_at": "2026-07-24T15:00:00Z"
}
```

**Behavior:**
- `UPDATE config SET value = text, updated_at = now() WHERE key = 'rules'`
- If the config row for 'rules' was deleted, creates it (UPSERT).
- The caller must have `role: "admin"`. Otherwise → `"not found"`.
- Audit logged: tool_name = "config_set_rules", input_summary = first 100 chars of text.
- Empty text → rejected: "rules text is required."

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `config_set_persona`

**What it does:** Same as `config_set_rules` but for the persona/voice definition.

**Input:**
- `text` (string, required, max 5000 characters): The new persona text.

**Output:**
```json
{
  "status": "updated",
  "key": "persona",
  "updated_at": "2026-07-24T15:05:00Z"
}
```

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `catalog_set_policy`

**What it does:** Creates or updates a policy in the support catalog. Automatically re-generates
the Mistral embedding so the policy remains searchable via `domain_search` with the new content.
The business admin provides plain text — the embedding pipeline is invisible to them.

**Input:**
- `id` (string, required): Policy ID — e.g. "pol-001" (update) or "pol-003" (new).
- `title` (string, required): The policy title — e.g. "Refund & Return Policy".
- `body` (string, required, max 5000 characters): The full policy text.
- `applies_to` (string, required): What the policy covers — e.g. "all physical products".

**Output:**
```json
{
  "id": "pol-001",
  "status": "updated",
  "entity_type": "policy",
  "embedding_regenerated": true,
  "updated_at": "2026-07-24T15:10:00Z"
}
```

**Behavior:**
- UPSERT into `support_embeddings` with `entity_type = 'policy'`, `content = {title, body, applies_to}`.
- Call Mistral API with the full body text to generate a new 1024-dim embedding.
- `UPDATE support_embeddings SET embedding = new_vector WHERE id = id`.
- If Mistral API is unreachable: the content is saved but embedding stays null. Returns
  `{"status": "updated", "embedding_regenerated": false, "warning": "Embedding unavailable.
  Policy saved but will not appear in semantic search results until re-indexed."}`.
  The policy is still accessible via `domain_get_policy(id)` — only semantic search is degraded.
- The caller must have `role: "admin"`. Otherwise → `"not found"`.
- Audit logged.

**Validation:**
- Empty title → "title is required"
- Empty body → "body is required"
- Empty applies_to → "applies_to is required"

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `catalog_set_order`

**What it does:** Creates or updates a seed order in the support catalog (before Shopify takes over
in v3). Same auto-embedding pipeline as `catalog_set_policy`.

**Input:**
- `id` (string, required): Order ID — e.g. "ord-001".
- `content` (object, required): The full order as a JSON object. Shape is flexible (e-commerce
  orders have items/tracking, SaaS orders have plan/seats) — the service accepts whatever the
  business admin provides.

**Output:**
```json
{
  "id": "ord-001",
  "status": "updated",
  "entity_type": "order",
  "embedding_regenerated": true,
  "updated_at": "2026-07-24T15:12:00Z"
}
```

**Validation:**
- Empty content → "content is required"
- Content not a valid JSON object → "content must be a JSON object"
- Content JSON stringified > 50KB → "content exceeds 50KB limit"

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `catalog_delete_item`

**What it does:** Removes an item (policy or order) from the support catalog. The item is
immediately excluded from `domain_search` results and returns `"not found"` via
`domain_get_policy`/`domain_get_order`.

**Input:**
- `id` (string, required): The catalog item ID — e.g. "pol-003" or "ord-099".

**Output:**
```json
{
  "id": "pol-003",
  "status": "deleted",
  "deleted_at": "2026-07-24T15:15:00Z"
}
```

**Behavior:**
- `DELETE FROM support_embeddings WHERE id = id`.
- If the item doesn't exist → `"not found"` (deletion is idempotent — it was already gone).
- Audit logged.
- The caller must have `role: "admin"`. Otherwise → `"not found"`.

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `catalog_list_all`

**What it does:** Returns all catalog items (policies and orders) for admin review in the
dashboard. Supports pagination and entity-type filtering.

**Input:**
- `entity_type` (string, optional): Filter by type — `"policy"`, `"order"`, or null/absent
  for all types.
- `limit` (integer, optional): Max items to return. Default 50, max 200.
- `offset` (integer, optional): Offset for pagination. Default 0.

**Output:**
```json
{
  "items": [
    {"id": "pol-001", "entity_type": "policy", "title": "Refund & Return Policy",
     "applies_to": "all physical products", "updated_at": "2026-07-24T15:10:00Z"},
    {"id": "ord-001", "entity_type": "order", "content": {...},
     "updated_at": "2026-07-23T10:00:00Z"}
  ],
  "total": 12,
  "returned": 2,
  "offset": 0
}
```

**Behavior:**
- Returns items newest-first by `updated_at`.
- `total` is the count of all items matching the entity_type filter (before limit/offset).
- If no items match → `{"items": [], "total": 0, "returned": 0, "offset": 0}` — not an error.
- The caller must have `role: "admin"`. Otherwise → `"not found"`.
- Not audit logged (read-only, high volume — would flood the audit trail).

**Validation:**
- Invalid entity_type → `"entity_type must be 'policy', 'order', or omitted"`
- limit > 200 → silently capped at 200

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `config_restore_version`

**What it does:** Restores a previous version of the rules or persona from the `config_history`
table. The restore is immediate — the current value is replaced and a new history entry is
created so the restore itself is versioned.

**Input:**
- `key` (string, required): `"rules"` or `"persona"`.
- `version_index` (integer, required): The version to restore. 1 = most recent previous version,
  2 = one before that, etc. (Index 0 is the current version — cannot restore to itself.)

**Output:**
```json
{
  "key": "rules",
  "restored_from_version": 3,
  "new_version": 5,
  "restored_at": "2026-07-24T16:00:00Z"
}
```

**Behavior:**
- Copies the value at `version_index` from `config_history` into the active config table
  (UPSERT). Creates a new `config_history` row for the restore action itself.
- The restored version takes effect on the next `begin_session` call by any user.
- Audit logged.

**Validation:**
- `version_index` is 0 → `"version_index 0 is the current version — cannot restore to itself"`
- `version_index` exceeds history length → `"version {N} not found for key '{key}' (latest
  previous version is {M})"`
- Key has never been edited → `"no previous versions available for key '{key}'"`
- Invalid key → `"key must be 'rules' or 'persona'"`

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `config_set_freshdesk_creds`

**What it does:** Sets or updates Freshdesk integration credentials at runtime. Overrides the
Fly secret defaults. The background sync task and `domain_sync_to_freshdesk` use these
credentials.

**Input:**
- `api_key` (string, required): Freshdesk API key.
- `domain` (string, required): Freshdesk domain — e.g. `"acmecorp.freshdesk.com"`.

**Output:**
```json
{
  "platform": "freshdesk",
  "status": "configured",
  "updated_at": "2026-07-24T15:00:00Z"
}
```

**Behavior:**
- UPSERTs into config store under `freshdesk_api_key` and `freshdesk_domain`.
- Takes effect immediately — next sync call (background or on-demand) uses the new credentials.
- Pass empty string to clear: `api_key=""` → removes the key (falls back to Fly secret).
- Audit logged (input_summary does NOT include the API key value — it logs first 4 chars only
  for audit purposes: `"key=abcd..."`).

**Validation:**
- Empty domain → `"domain is required"`
- Empty api_key → `"api_key is required"` (unless explicitly clearing)

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

#### `config_set_shopify_creds`

**What it does:** Sets or updates Shopify integration credentials at runtime. Overrides the
Fly secret defaults. `domain_get_order` uses these credentials for live order lookup.

**Input:**
- `access_token` (string, required): Shopify Admin API access token.
- `store_domain` (string, required): Shopify store domain — e.g. `"acmecorp.myshopify.com"`.

**Output:**
```json
{
  "platform": "shopify",
  "status": "configured",
  "updated_at": "2026-07-24T15:00:00Z"
}
```

**Behavior:**
- UPSERTs into config store under `shopify_access_token` and `shopify_store_domain`.
- Takes effect immediately — next `domain_get_order` call uses the new credentials.
- Pass empty string to clear: `access_token=""` → removes the token (falls back to Fly secret).
- If neither Fly secret nor runtime credentials exist, Shopify lookup is skipped entirely
  (local catalog only, no error).
- Audit logged (token value is never included in the log — logged as `"token=****"`).

**Validation:**
- Empty store_domain → `"store_domain is required"`
- Empty access_token → `"access_token is required"` (unless explicitly clearing)

**Requires sign-in:** Yes.
**Requires session:** Yes.
**Requires role:** `admin` in Descope user metadata.

---

## Admin Dashboard (Web Interface, v2)

The admin dashboard provides a web-form alternative to AI chat for bulk editing and side-by-side
review. It is a single static HTML page served from the same Starlette application at `/admin`,
gated by the same Descope sign-in and `role: "admin"` check. It calls the same admin MCP tools
(`config_set_*`, `catalog_set_*`, `catalog_delete_item`, `catalog_list_all`, `config_restore_version`)
via fetch(), so all business logic lives in the tools — the dashboard is a thin UI shell.

### Architecture

```
Browser ──GET /admin──▶ Starlette ──serve admin.html──▶ Dashboard loads
   │                                                        │
   │  1. JS calls Descope sign-in (same OAuth flow as MCP)  │
   │  2. JS calls begin_session → gets role + session_token │
   │  3. If role != "admin" → show "Access denied"          │
   │  4. If role == "admin" → render editors                │
   │                                                        │
   │  Edit → Save → JS calls catalog_set_policy(...)        │
   │          with session_token as parameter                │
   │          → tool updates DB + re-embeds                 │
   ▼                                                        ▼
Same FastMCP tools ──── Same Neon DB ──── Same Descope auth
```

### Sections

| Section | What admin can do | Backend tool called |
|---|---|---|
| **Rules editor** | Textarea pre-filled with current rules. Edit text → Save button. "History" button toggles a dropdown showing previous versions with timestamps — click a version to restore it (calls `config_restore_version`). | `config_set_rules(text)`, `config_restore_version(key, version_index)` |
| **Persona editor** | Same pattern — textarea, edit, save. History dropdown for previous versions with restore. | `config_set_persona(text)`, `config_restore_version(key, version_index)` |
| **Policy table** | Table: ID, Title, "applies_to", last updated. Click row → inline edit. Delete button per row with confirmation. "Add new policy" button at top. Rows fetched via `catalog_list_all`. | `catalog_set_policy(id, title, body, applies_to)`, `catalog_delete_item(id)`, `catalog_list_all(entity_type)` |
| **Order table (seed)** | Same CRUD pattern for seed orders. Collapsed by default, toggle to show | `catalog_set_order(id, content)`, `catalog_delete_item(id)` |
| **Sync status bar (v3)** | Read-only: "Last Freshdesk sync: 2 min ago. 3 tickets synced. 0 errors." | Reads sync status from server |
| **Sign out** | Clear session, return to login screen | No backend call — client-side only |

### Behavior

- **Load:** Dashboard JS calls `begin_session` via the MCP endpoint → extracts `role` and
  `session_token`. If role is not `"admin"`, displays "Access denied. Your account does not have
  admin permissions." and renders nothing else. If role is `"admin"`, fetches current rules,
  persona, and catalog items from the DB and populates each section.
- **Edit → Save:** JS calls the appropriate admin tool with the session token as a parameter.
  Each tool returns `{"status": "updated"}` on success. Dashboard displays a green confirmation
  toast for 3 seconds, then refreshes the relevant section from the DB. If the tool returns an
  error, dashboard displays the error message in red inline next to the field.
- **Delete:** Confirmation dialog ("Delete pol-003? This cannot be undone.") → on confirm,
  calls `catalog_delete_item` → removes the row from the table.
- **Add:** "Add new policy" button opens a blank inline form → fill ID, title, body, applies_to →
  Save → calls `catalog_set_policy` → new row appears in table, auto-re-embedded.
- **No caching:** Every page load fetches fresh state from the DB. No browser cache, no
  server-side cache.

### Error States

| Error | Behavior |
|---|---|
| Session token expired during edit | Save returns "invalid session" → JS redirects to Descope login. After re-auth, page reloads with fresh DB state. Unsaved edits are lost (acceptable — edits are small and quick; an auto-save draft would add complexity with no user benefit for a single-admin tool). |
| Save failed (DB error, Mistral down) | Inline error message: "Save failed: ...". The editor stays open with the user's edits preserved in the textarea so they can try again. |
| Dashboard JS fails to load (network error, 404) | User sees HTML fallback content served by the Starlette route: "Dashboard unavailable. Use AI chat to manage config." with a link to the connector in claude.ai. |
| Non-admin visits `/admin` | Descope sign-in works (any user can authenticate), but after sign-in the page checks `role` from the session token. If role is not `"admin"`, the page displays "Access denied. Your account does not have admin permissions." No dashboard content is visible. |
| Two admin browser tabs open | Last save wins. No conflict detection. This is a single-business-admin scenario — if there's one admin, there's no concurrent-edit race. If the business adds a second admin, the dashboard is still safe (last write wins, no corruption). |

### Technical Constraints

- **Single static HTML file.** No npm, no webpack, no build step, no JavaScript framework. HTML +
  inline CSS + inline JS. Served by Starlette's `StaticFiles` or a simple `FileResponse`.
- **File location:** `admin/index.html` in the project repository, copied into the Docker image.
- **No additional dependencies.** The dashboard calls the same MCP tools via HTTP POST to `/mcp`
  (JSON-RPC), using the session token obtained from `begin_session`. No new backend endpoints,
  no REST API layer, no GraphQL.
- **Load time:** Under 2 seconds on first visit (one HTML file, one sign-in redirect, one
  `begin_session` call, one catalog fetch).
- **Mobile:** Not optimized for mobile. The primary admin workflow is on a desktop browser.
  The dashboard is still functional on mobile (text areas scroll), but not designed for it.

### Comparison: AI Chat vs Dashboard

| Task | AI Chat | Dashboard |
|---|---|---|
| "Update refund window to 60 days" | Natural language, one chat exchange | Find pol-001 in table, click, edit, save |
| "Add 5 new policies from the ops doc" | 5 back-and-forth exchanges | Paste all 5, save each in succession |
| "What does the current escalation rule say?" | Ask and read the response | See it in a textarea, editable |
| "Delete old pol-003 and ord-099" | Two tool calls | Click delete twice |
| "Review all policies side-by-side" | Multiple tool calls, scrolling chat | Table view, scroll, compare rows |
| Correcting a typo in a policy body | Full sentence: "In pol-001, change 'retrun' to 'return'" | Click row, fix typo, save |
| Adding a new escalation trigger | "Add this escalation rule: ..." to rules text | Scroll to rules textarea, add line, save |

---

### v1 Tool Modifications for v2

#### `domain_get_ticket` (modified)

Returns two new fields:
```json
{
  "... all v1 fields ...": "...",
  "attachment_count": 3,
  "attachment_ids": ["att-001", "att-002", "att-003"]
}
```
When no attachments exist, `attachment_count` is 0 and `attachment_ids` is `[]`.
These fields are always present — never omitted.

#### `domain_get_customer_profile` (modified)

Returns one new field:
```json
{
  "... all v1 fields ...": "...",
  "csat_trend": "improving"
}
```
`csat_trend` is one of: "improving" (last 5 rated tickets show upward trend), "declining"
(downward), "stable" (flat or < 3 rated tickets), or `null` (no rated tickets at all).
Computed live from the CSAT scores on the user's resolved tickets, newest first.

---

### New v3 Tools

#### `domain_sync_to_freshdesk`

**What it does:** Pushes a ticket from the support desk to an external Freshdesk instance.
If the ticket was already synced, updates the existing Freshdesk ticket instead of creating
a duplicate. Requires Freshdesk integration credentials to be configured (read from the config
store, not hardcoded).

**Input:**
- `ticket_id` (string, required)
- `action` (string, optional): "push" (default), "pull", or "sync_bi". "push" sends local state
  to Freshdesk. "pull" fetches Freshdesk state and updates the local ticket. "sync_bi"
  synchronizes both directions (latest-wins on status, local-wins on body).

**Output:**
```json
{
  "ticket_id": "tkt-008",
  "freshdesk_id": "FD-8821",
  "sync_status": "pushed",
  "synced_at": "2026-07-24T11:00:00Z"
}
```

**Behavior:**
- On first sync ("push"): creates a new ticket in Freshdesk with subject, body, priority from
  the local ticket. Records the Freshdesk ID locally.

**Freshdesk field mapping (local → Freshdesk):**

| Local Field | Freshdesk Field | Notes |
|---|---|---|
| `subject` | `subject` | Prefixed with local ticket ID: `"[tkt-008] Double charge on subscription"` |
| `body` | `description` | Full body text |
| `status` | `status` | Mapped: open→2, triaged→2, in_progress→3, pending→3, resolved→4, closed→5 |
| `priority` | `priority` | Mapped: critical→4, high→3, medium→2, low→1 |
| `created_by` | `email` | Looked up from the user's Descope profile OR a `guest_email` field on the ticket. If unavailable, defaults to a configurable fallback email |

**Freshdesk field mapping (Freshdesk → local, on pull/sync_bi):**

| Freshdesk Field | Local Field | Notes |
|---|---|---|
| `status` | `status` | 3→in_progress, 4→resolved, 5→closed. Status 2 (Open) is **always ignored on pull** — the local system is authoritative for open/triaged status. Freshdesk cannot reopen a locally closed ticket or change a local status to "open" or "triaged." |
| `priority` | `priority` | Reverse mapping: 4→critical, 3→high, 2→medium, 1→low |
| `id` | `freshdesk_id` | Stored locally for tracking |

This means two local states (open, triaged) collapse into one Freshdesk code on push, and
neither can be restored on pull. If a ticket is closed in Freshdesk, the pull sets local
status to "closed" and `closed_at` to now. If a ticket is resolved in Freshdesk (status 4),
the pull sets local status to "resolved" and `resolved_at` to now.

- On subsequent sync: updates the existing Freshdesk ticket.
- On "pull": fetches Freshdesk ticket status and updates the local ticket per the mapping
  above. Freshdesk Status 2 is no-oped — local status is NOT changed to "open" or "in_progress"
  from a Freshdesk pull. The local ticket's status is authoritative for the open/triaged/in_progress
  distinction. Only resolved (4) and closed (5) propagate from Freshdesk to local.
- On "sync_bi": pushes local body/priority changes to Freshdesk, pulls Freshdesk status to local
  using the same resolution rules as pull above (Freshdesk Status 2 ignored, local body wins,
  Freshdesk status 4 or 5 wins for resolved/closed).
- If Freshdesk API is unreachable (timeout or non-200), return: `{"error": "Freshdesk sync
  unavailable. The ticket was not synced. Try again later."}` — fail gracefully, do not crash.

**Validation:**
- Non-existent ticket → "not found"
- Invalid action → "action must be one of: push, pull, sync_bi"

**Requires sign-in:** Yes.
**Requires session:** Yes.

---

#### `user_configure_notifications`

**What it does:** Configures how the signed-in user wants to be notified when their ticket
status changes. Stores email address and/or webhook URL. Call with no parameters to read
current config.

**Input:**
- `email` (string, optional): Email address for notifications. Pass an empty string to clear.
- `webhook_url` (string, optional): HTTPS URL to POST status-change events to. Pass an empty
  string to clear.
- `events` (array of strings, optional): Which events trigger notifications. Options:
  "status_changed", "agent_assigned", "resolution", "all". Default: ["status_changed"].

**Output (write mode):**
```json
{
  "email": "julia@example.com",
  "webhook_url": null,
  "events": ["status_changed", "agent_assigned"],
  "configured_at": "2026-07-24T12:00:00Z"
}
```

**Behavior:**
- When a ticket's status changes and the ticket creator has notifications configured, the
  service sends an email (SMTP) and/or POSTs to the webhook URL with:
  `{"event": "status_changed", "ticket_id": "tkt-005", "old_status": "open", "new_status":
  "in_progress", "timestamp": "..."}`.
- Webhook delivery is fire-and-forget: a failed webhook POST is logged but not retried.
- Email delivery failure is logged but does not affect the ticket status change.
- Notification config is per-user (keyed to the signed-in identity), not per-ticket.
- Calling with no parameters reads and returns the current config without changing it.

**Validation:**
- Invalid email format → "email is not a valid email address"
- webhook_url not starting with "https://" → "webhook URL must start with https://"
- Invalid event name → "unknown event: {name}. Valid events: status_changed, agent_assigned,
  resolution, all"

**Requires sign-in:** Yes.
**Requires session:** Yes.

---

### v3 Tool Modifications

#### `begin_session` (v3 — role extraction)

`begin_session` now extracts the caller's role from the Descope JWT claims (via `auth.py`
returning the full verified claims dictionary, not just `sub`). The role is read from the
JWT claim `role` (set via Descope Dashboard → User Metadata → `{ "role": "admin" }` or
`{ "role": "staff" }`). Customers have no `role` claim — the field is null.

**Output change:** A new field `role` is added to the `begin_session` return:
```json
{
  "... all v1/v2 fields ...": "...",
  "role": "admin"
}
```
For staff users, `role` is `"staff"`. For customers, `role` is `null`. The field is always
present — never omitted.

**Internal session token:** The role is embedded in the signed session token as a claim:
```
{
  "sub": "<OAuth sub>",
  "role": "admin",       // "staff" or null for non-admin/non-staff
  "iat": ...,
  "exp": ...,
  "scope": "session"
}
```
Every gated tool reads `role` from the session token:
- Admin tools (`config_set_*`, `catalog_*`, `config_restore_version`, `catalog_list_all`,
  `config_set_freshdesk_creds`, `config_set_shopify_creds`) require `role == "admin"`.
  Non-admin → `"not found"`.
- Agent tools (`domain_draft_reply`, `domain_assign_ticket`, `domain_reassign_ticket`,
  `domain_update_ticket`, `domain_get_audit_log`, `domain_sync_to_freshdesk`) require
  `role in ("admin", "staff")`. Customer → `"not found"`.
- Report tools (`domain_report_summary`, `domain_agent_performance`) require `role == "admin"`.
  Staff → `"not found"`.

**`tools/list` filtering:** The MCP `tools/list` response excludes tools based on role:
- Customer sessions: only customer-level tools are listed (~12 tools).
- Staff sessions: customer + agent tools are listed (~18 tools).
- Admin sessions: all tools are listed (~28 tools).
The AI model never learns about tools it cannot call — it cannot hallucinate an out-of-role
tool call.

#### `domain_get_ticket` (v3 hardening)

In v3, `domain_get_ticket` filters by the caller's identity. The behavior is:
- **Customers (no role):** If `created_by` on the ticket matches the signed-in user's `sub` →
  return the ticket. If not → return `"not found"`.
- **Staff and admins:** If `created_by` matches OR the ticket is `assigned_to` this agent →
  return the ticket. If neither → return `"not found"`.
- The "not found" response is identical for nonexistent tickets and unauthorized tickets.
- There is no role-based override that lets any user see ALL tickets. Staff see their
  assigned tickets + their own created tickets. Admins see all tickets that match either
  `created_by` or `assigned_to` for their identity (admins don't get unrestricted global
  visibility — reporting tools serve aggregate data for that purpose).
- The audit log records every `domain_get_ticket` call including the `id` requested, whether
  found or not found (with `sub` of the caller). This means the audit log can reveal that
  User B attempted to access User A's ticket — an accountability feature.

**Visible change from v1/v2:** A ticket created by User A that was previously readable by User B
via ID lookup is now hidden from User B (unless User B is the assigned agent). This is a
breaking access-control change justified by multi-tenant hardening.

#### `domain_get_order` (v3 live lookup)

- First checks the local catalog (seed data in `support_embeddings`).
- If not found locally, queries the configured Shopify API for the order ID.
  **Endpoint:** `GET https://{store_domain}/admin/api/2024-07/orders/{order_id}.json`
  with header `X-Shopify-Access-Token: {access_token}`. Response parsed for order status,
  line items, fulfillment status, and tracking information.
- If found on Shopify, returns the live order data in the same output shape as seed orders.
- If not found on Shopify either, returns `"not found"`.
- If the Shopify API is unreachable, returns: `{"error": "Live order lookup temporarily
  unavailable. Local catalog returned: not found.", "source": "catalog_only"}` — does NOT crash.
- A `source` field is added to the output: `"catalog"` for seed data, `"shopify"` for live data.

#### `domain_search` (v3 ticket inclusion)

- A new optional parameter `include_my_tickets` (boolean, default false) is added.
- When `true`: the search scope expands to include the *calling user's own tickets* in addition
  to the shared order/policy catalog.
- Ticket results include `"id"`, `"entity_type": "ticket"`, `"content"` (first 200 chars of body),
  `"similarity"`, `"status"`, and `"priority"`.
- The search never includes tickets belonging to OTHER users — even with `include_my_tickets: true`,
  only the caller's tickets are searched.
- Tickets without embeddings are excluded from search results (they can't be ranked). Only
  tickets that have been embedded (via the same Mistral pipeline used for catalog items) appear.

---

## Edge Cases & Rules

### Complete Ticket Schema

All tickets have the following fields:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique ticket ID — e.g. "tkt-001" |
| `subject` | string | Short summary — e.g. "Damaged item on delivery" |
| `body` | string | Full description from the customer |
| `status` | string | One of: open, triaged, in_progress, pending, resolved, closed |
| `priority` | string | One of: critical, high, medium, low |
| `category` | string | One of: billing, returns, technical, account, shipping, other |
| `created_by` | string | The OAuth `sub` of the ticket creator |
| `created_at` | datetime | When the ticket was created (UTC) |
| `assigned_to` | string | Agent name — null if unassigned |
| `assigned_at` | datetime | When the agent was assigned — null if unassigned |
| `resolved_at` | datetime | When status became "resolved" — null if not resolved |
| `closed_at` | datetime | When status became "closed" — null if not closed |
| `freshdesk_id` | string | External Freshdesk ticket ID — null if not synced |
| `freshdesk_synced_at` | datetime | Last sync timestamp — null if never synced |
| `attachment_count` | integer | Number of attached files (always present, 0 if none) |
| `attachment_ids` | array | List of attachment IDs — e.g. ["att-001"] (always present) |
| `csat_score` | integer | 1-5 satisfaction rating — null if not yet rated |
| `csat_submitted_at` | datetime | When the CSAT was submitted — null if not rated |
| `tags` | array of strings | Flexible tags — e.g. ["urgent", "vip"] (always present, [] if none) |
| `updated_at` | datetime | Last modification timestamp (UTC) |
| `last_activity_at` | datetime | Last human or agent action timestamp (UTC) |
| `source` | string | Origin of the ticket: "mcp" or "freshdesk" |

### Ticket Status State Machine

```
                  ┌─────────┐
                  │  open   │
                  └────┬────┘
                       │ (triage)
                  ┌────▼────┐
                  │ triaged │◄──────────┐
                  └────┬────┘           │
                       │ (assign)      │
                  ┌────▼────┐          │
                  │in_progress│        │
                  └────┬────┘          │
                       │              │
          ┌────────────┼──────────────┤
          ▼            ▼              ▼
    ┌─────────┐  ┌─────────┐    (reopen from
    │ pending │  │resolved │     resolved only)
    └────┬────┘  └────┬────┘
         │            │
         ▼            ▼
    ┌─────────┐  ┌─────────┐
    │resolved │  │ closed  │ (terminal)
    └─────────┘  └─────────┘
```

**Allowed transitions:**
- `open` → `triaged` (triage step — categorize and prioritize)
- `open` ↔ `triaged` (bi-directional: re-triage if categorization was wrong)
- `triaged` → `in_progress` (assignment: `domain_assign_ticket` triggers this)
- `in_progress` ↔ `pending` (bi-directional: pause/resume work)
- `pending` → `resolved` (work completed)
- `in_progress` → `resolved` (direct resolution, skip pending)
- `resolved` → `closed` (terminal — irreversible)
- `resolved` → `open` (reopen: `domain_update_ticket` with `status: "open"`)
- Reopen clears `resolved_at` and `csat_score` (the ticket can be rated again after second resolution).
  Reopen also clears `freshdesk_synced_at` — the next background sync cycle will see the ticket
  as needing a fresh push if it was previously synced, or the agent must manually call
  `domain_sync_to_freshdesk` to push the reopened state.
- **`pending` state explained:** The ticket is waiting for external input — a customer response,
  a third-party vendor, or an internal escalation review. SLA clock does not count time in
  `pending` (future v4 feature; v2/v3 SLA calculation treats `pending` the same as `in_progress`).
  Agents move the ticket to `in_progress` when work resumes or directly to `resolved` when
  the pending input arrives and work is complete.

**Invalid transitions (rejected):**
- Any transition FROM `closed` — it is terminal
- `open` → `in_progress` (must triage first via domain_assign_ticket)
- `triaged` → `resolved` (must go through in_progress/pending)
- `in_progress` → `triaged` (backwards — use reopen if needed)
- Any transition not listed above

### Priority Values

Fixed enum, not extensible in v2/v3:

| Value | SLA Target |
|-------|-----------|
| `critical` | 1 hour |
| `high` | 4 hours |
| `medium` | 24 hours |
| `low` | 72 hours |

### Category Values

Fixed enum, not extensible in v2/v3:

| Value | Description |
|-------|-------------|
| `billing` | Charges, invoices, refunds, payment issues |
| `returns` | Product returns, exchanges, RMA |
| `technical` | Bugs, errors, platform issues |
| `account` | Login, profile, permissions, subscription |
| `shipping` | Delivery, tracking, lost packages |
| `other` | Catch-all for uncategorized tickets |

Set at ticket creation (via `domain_create_ticket`) or updated via `domain_update_ticket`.
`domain_report_summary` groups tickets by the `category` field for the `top_categories` output.
Category is set at ticket creation and can be updated via `domain_update_ticket`. Only tickets
with a non-null category are included in top_categories; tickets without a category are counted
in totals but excluded from the top-5 ranking.

### Notification Details

**Email (SendGrid):** Emails are sent via the SendGrid API (free tier: 100 emails/day).
The SendGrid API key is stored as a Fly secret (`SENDGRID_API_KEY`). Email sending is
synchronous within the tool call that triggers it. On failure (SendGrid down, rate limit,
invalid email), the failure is logged but does NOT block the ticket status change. The
tool returns normally — notification delivery is best-effort.

**Webhook:** Webhook notifications POST to the configured HTTPS URL with:
```json
{
  "event": "status_changed",
  "ticket_id": "tkt-005",
  "old_status": "open",
  "new_status": "in_progress",
  "timestamp": "2026-07-24T15:00:00Z"
}
```
The POST includes an `X-Webhook-Signature` header: `sha256=<hex HMAC-SHA256 of the JSON body
using WEBHOOK_SECRET as the key>`. The consumer verifies the signature with the same secret.
Webhook delivery is fire-and-forget — a failed POST is logged but not retried. The ticket
status change proceeds regardless.

**WEBHOOK_SECRET** is stored as a Fly secret.

### Freshdesk Sync Bootstrap

The background sync task (v3) queries for tickets with a `freshdesk_id`. On first deploy,
no tickets have one. The bootstrap path is:
1. An admin or staff member manually calls `domain_sync_to_freshdesk("tkt-XXX", "push")`
   which creates the Freshdesk ticket and records the `freshdesk_id` on the local ticket.
2. From that point forward, the background sync task can pull status updates for that ticket.
3. Each new ticket that needs Freshdesk sync must be manually pushed once via
   `domain_sync_to_freshdesk`. The on-demand push is the only bootstrap path.

### Attachment Storage (Cloudflare R2)

Attachments are stored in a Cloudflare R2 bucket (free tier: 10 GB, zero egress, S3-compatible
API). The database stores metadata; the actual file binary lives in R2. `domain_get_attachment`
generates a presigned S3-compatible GET URL valid for 15 minutes for download. Files are never
returned inline as base64 in tool responses.

**`attachments` table schema:**

```
attachments:
  id            text primary key    — e.g. "att-001"
  ticket_id     text not null       — FK to tickets table
  file_name     text not null       — original filename
  mime_type     text not null       — e.g. "image/jpeg"
  size_bytes    integer not null    — file size in bytes
  r2_key        text not null       — R2 object key (path in bucket)
  uploaded_by   text not null       — sub of the uploader
  uploaded_at   timestamptz not null
```

**R2 upload failure:** If the DB insert succeeds but the R2 upload fails (network error,
credentials invalid, bucket missing), the DB row is deleted and the tool returns an error.
DB and R2 must remain consistent — no orphan attachment rows referencing missing R2 objects.
If the DB insert fails but R2 upload already succeeded, an orphan R2 object may exist.
This is accepted as a rare edge case (the R2 object is inaccessible without a DB row).

**R2 lifecycle policy:** No auto-expiry in v2/v3. Attachments persist indefinitely. A future
admin tool (v4) may add manual cleanup. The 10 GB free tier is the implicit storage limit.
When the bucket approaches 10 GB, the admin must manually clean up old attachments or upgrade
the R2 plan.

**Content security:** Attachment safety relies on MIME-type allowlisting only (image, PDF,
text, CSV). No malware scanning, antivirus, or content inspection is performed in v2/v3.
Executable files, scripts, and archives are rejected by the MIME-type check. This is a
conscious scope decision — R2 objects are served via presigned URLs only and are never
executed server-side.

### Notification Config Table

**`notification_config` table schema:**

```
notification_config:
  user_sub      text primary key    — the OAuth sub of the user
  email         text                — notification email address, null if not set
  webhook_url   text                — HTTPS webhook URL, null if not set
  events        text[]              — Postgres array: e.g. {"status_changed","resolution"}
  created_at    timestamptz not null
  updated_at    timestamptz not null
```

One row per user (upserted by `user_configure_notifications`). If a user has no row, they
have no notifications configured — all notification checks skip silently. The `events` array
uses Postgres native array type. If a user passes `"all"` as an event, it is expanded to
`["status_changed", "agent_assigned", "resolution"]` before storage.

### Ticket Notes Table

**`ticket_notes` table schema:**

```
ticket_notes:
  id            serial primary key
  ticket_id     text not null       — FK to tickets table
  author_sub    text not null       — who wrote this note
  author_role   text not null       — "customer", "staff", "admin", or "system"
  body          text not null       — the note/reply content
  note_type     text not null       — "reply", "internal_note", "system_event"
  created_at    timestamptz not null
```

Used by `domain_update_ticket` when `reply_body` is provided — creates a note with
`note_type: "reply"`. Also used by `domain_assign_ticket` and `domain_reassign_ticket`
for automatic audit notes (`note_type: "system_event"`). System-generated notes have
`author_role: "system"`. Notes are append-only — never modified or deleted.

### Config Version History

Every `config_set_rules` and `config_set_persona` call creates a row in `config_history`
before overwriting the active config. The history table schema:

```
config_history:
  id            serial primary key
  key           text    — "rules" or "persona"
  value         text    — the full text at that point in time
  version_index integer — auto-incrementing per key (1, 2, 3, ...)
  updated_by    text    — the sub of the admin who made the change
  updated_at    timestamptz
```

`config_restore_version` reads from this table and writes the restored value back to the
active config, creating a new history row for the restore itself.

### Notification Config Details

**Per-user isolation:** Notification config is keyed to the signed-in user's `sub`. User A's
notification events never fire for User B's tickets. When a ticket status changes:
1. The tool reads the ticket's `created_by` (the affected customer).
2. Looks up that user's notification config by `sub`.
3. If config exists and the event type matches → dispatch email/webhook.
4. If no config → no notification (silent — not an error).

### Config Restore Edge Cases

- `version_index=0` → rejected: "version_index 0 is the current version — cannot restore to itself"
- `version_index > history length` → rejected with the latest available version number
- Key has no history (never edited, or all history rows deleted) → "no previous versions available"
- Restoring to a version that deleted the key entirely is not possible (config_history only
  tracks overwrites, not deletes — there is no config delete tool in v2/v3)
- A single ticket with 10 attachments → `domain_get_ticket` returns all 10 IDs in `attachment_ids`.
  No truncation.
- An attachment stored then immediately retrieved → `domain_get_ticket` reflects the updated count.
- Attachments persist across ticket status changes (they're not deleted when a ticket is closed).
- Base64 decoding failure → rejected before any storage attempt.

### CSAT
- A ticket resolved 6 months ago and rated today → accepted. No time restriction on rating.
- A ticket that was re-opened after being resolved → CSAT score remains (it was rated for the
  previous resolution). A second resolution enables a second rating (overwrites the first).
- `domain_report_summary` and `domain_agent_performance` must agree on CSAT averages for the
  same period — compute from the same query path.

### Notifications
- Notification config is per-user, not global. User A's notification email never receives
  events about User B's tickets.
- A user configures notifications, then deletes their email → next status change fails email
  delivery silently (logged, not surfaced to the user via tool error).
- Webhook URL returns 500 on POST → logged, event proceeds, ticket status change is unaffected.
- **Webhook timeout:** POST to webhook URL has a 5-second timeout. After 5 seconds, the
  connection is dropped and delivery is considered failed. Logged and never retried. The
  ticket update proceeds regardless.
- A user configures notifications for "all" events → every status change, assignment, and
  resolution triggers a notification. This is a valid preference.

### Ticket assignment
- Assigning a ticket changes status from "open" to "in_progress" automatically. Assigning an
  already "in_progress" ticket to the same agent does nothing.
- Reassigning a "resolved" or "closed" ticket must be rejected. A resolved ticket cannot be
  reopened via reassignment — there must be a separate `domain_update_ticket` call.
- An agent name is a free-text string — no agent roster validation. "Ravi" and "ravi" are
  treated as the same agent (case-insensitive match in `domain_agent_performance`).
- **Concurrent assignment:** If two staff members call `domain_assign_ticket` simultaneously
  for the same unassigned ticket, both see the ticket as assignable before either transaction
  commits. Use `SELECT ... FOR UPDATE` on the ticket row to serialize the two transactions.
  The first caller's assignment commits; the second caller's transaction reads the committed
  state and sees `assigned_to` already set by the first caller. The second caller receives
  the current ticket state reflecting the first caller's assignment — this is a successful
  response, not an error. The second caller learns who got the ticket and can move on.

### Report period boundaries
- "today" = from midnight UTC of the current day to now.
- "yesterday" = the full 24 hours of the previous UTC day.
- "week" = the 7 full UTC days ending at midnight of the current day (current day excluded,
  7 complete days).
- "month" = 30 full UTC days ending at midnight of the current day.
- "quarter" = 90 full UTC days ending at midnight of the current day.
- This definition is consistent across `domain_report_summary` and `domain_agent_performance`.

### Draft replies
- `domain_draft_reply` does not modify any ticket. It is a pure read-and-generate tool.
- Calling it twice on the same ticket produces two independent drafts — it does not cache
  or remember the previous draft.
- If the ticket has no `assigned_to`, the draft still generates but with a generic sign-off
  and `agent_name: null`. The AI should not present this draft as if an agent wrote it.
- If the persona config changes mid-session, the next `domain_draft_reply` reflects the
  new persona. No session restart required.

### Audit log reading
- `domain_get_audit_log` with `limit=500` returns at most 500 entries.
- If `total_matching` > `returned`, the caller knows to paginate with `since` + `limit`.
- Audit log entries are immutable — no tool modifies or deletes them.
- A tool call that failed (returned error) is still logged in the audit trail — `output_summary`
  contains the error message.

### Platform sync (v3)
- Sync failure (Freshdesk down, Shopify down) must not prevent local tools from working.
  `domain_get_ticket`, `domain_create_ticket`, etc. remain fully functional regardless
  of external platform state.
- All external API calls (Freshdesk, Shopify) have a **10-second timeout**. If the request
  does not complete within 10 seconds, the connection is dropped and the call is treated as
  unreachable. The tool returns the graceful error response without crashing.
- A sync conflict (both local and Freshdesk modified the same ticket since last sync)
  resolves per the `action` parameter — "sync_bi" has explicit resolution rules.
- Shopify integration is optional — if no Shopify credentials are configured in the config
  store, `domain_get_order` falls through to local catalog only.

### Multi-tenant hardening (v3)
- The identity check on `domain_get_ticket` (`created_by` must match caller's `sub`) is
  structural — it cannot be bypassed by any parameter or role. There is no admin bypass.
- `domain_search` with `include_my_tickets: true` applies the same identity filter — the
  search query's embedding computation happens, but results are filtered to the caller's
  tickets before ranking.
- "Not found" vs "access denied" must produce identical tool responses. The caller must
  not be able to distinguish "this ticket doesn't exist" from "this ticket exists but isn't
  yours."

### All v1 invariants still hold
- Identity from token's `sub` only. No tool accepts a user identifier parameter (audit log
  filter by `user_id` is the exception — it reads from a parameter but doesn't impersonate).
- Every gated tool requires a valid session token.
- Fail-closed: any tool returning an error causes the AI to refuse, not improvise.
- Per-tool reminder appended to every v2/v3 tool return, unchanged from v1.

### Admin access control
- Admin tools (`config_set_*`, `catalog_set_*`, `catalog_delete_*`) return `"not found"` to
  non-admin callers — identical to calling a tool that doesn't exist.
- Admin tools are excluded from MCP `tools/list` for non-admin sessions. The AI model cannot
  discover them, so it cannot hallucinate a call to an admin-only tool for a non-admin user.
- `begin_session` extracts the role from the Descope JWT claim `role`. If the Descope user
  has no `role` metadata, `role` is `null` in the session token — every admin tool rejects with
  `"not found"`.
- Changing a user's role in Descope Dashboard takes effect on their next `begin_session` call.
  Active sessions with the old role remain valid until their session token expires (30 min).
- Session token tampering: if a session token's `role` claim is modified, the HMAC signature
  becomes invalid and `require_session` rejects the token — the token cannot pass as admin.
- A session token minted for an admin user is valid for 30 minutes. If the admin's role is
  revoked in Descope during that window, the existing session token continues to grant admin
  access until expiry. This is an accepted trade-off: role changes are not real-time, they take
  effect on the next `begin_session`.

### Catalog and embedding pipeline
- `catalog_set_policy` and `catalog_set_order` call Mistral API synchronously. If Mistral is
  unreachable, the content is saved but `embedding_regenerated` is `false` and a warning is
  returned. The item is accessible by ID (`domain_get_policy`/`domain_get_order`) but excluded
  from semantic search results until re-indexed.
- **Re-indexing:** When Mistral recovers, the admin re-indexes an item by calling the same
  tool again with the same content (`catalog_set_policy` or `catalog_set_order`). The tool
  detects the content hasn't changed but embedding is missing → regenerates the embedding.
  There is no separate "re-index" tool — re-saving is the re-index mechanism.
- Catalog updates take effect immediately: `domain_search`, `domain_get_policy`, and
  `domain_get_order` read directly from the database — no cache, no lag.
- `catalog_delete_item` is idempotent: deleting a non-existent item returns `"not found"` —
  the item was already gone, which is the desired state.
- Po-001's refund window was 30 days, now 60. An existing customer chat that called
  `domain_get_policy("pol-001")` 5 minutes ago saw 30 days. The same chat calling it again
  now sees 60 days. No session restart required.
- Embedding regeneration for a policy takes < 2 seconds (Mistral API latency). The tool
  response includes `embedding_regenerated: true` to confirm the pipeline completed.

### Background Freshdesk sync (v3, free tier)
- On gateway startup, a background async task begins polling every 15 minutes (configurable).
- The task queries all local tickets with status "open" or "in_progress" that have a
  `freshdesk_id` (previously synced). For each, calls `pull` action to fetch the latest
  Freshdesk status and update the local ticket.
- The sync task runs in the same Python process as the MCP server — no separate service,
  no cron job, no additional cost.
- If Freshdesk credentials are missing from the config store, the sync loop is idempotent:
  it sleeps without querying — no errors, no crash.
- A sync failure for one ticket does not block sync for other tickets. Each ticket is synced
  independently.
- Sync failures are logged. No alerts. The next cycle retries — this is best-effort, not
  guaranteed delivery.
- Sync interval is 15 minutes. Between syncs, tickets can drift. The `domain_sync_to_freshdesk`
  tool provides on-demand sync for immediate needs.
- The sync task does NOT interfere with the MCP server's request handling — it runs in an
  asyncio background task that yields to incoming requests.

### Admin dashboard edges
- **Session expiry during edit:** Session token is valid 30 minutes. If it expires while the
  admin is editing, the next Save call returns "invalid session." The dashboard JS detects this,
  shows "Your session expired. Please sign in again.", and redirects to Descope login. After
  re-auth, the page loads fresh DB state — unsaved edits are lost. Edits are typically small
  (a few lines of text), so re-creating them is trivial.
- **Two browser tabs:** Both tabs have independent session tokens (each tab called
  `begin_session` separately). Both tabs can save. Last save wins. No conflict detection is
  needed — there's one business admin, not a team of concurrent editors.
- **Browser back/forward:** Navigating away from the dashboard and returning reloads the page
  and fetches fresh DB state. No stale cache.
- **Save → immediate search:** After `catalog_set_policy` saves and re-embeds, the dashboard
  shows `"embedding regenerated: true"`. The admin can immediately open claude.ai and search for
  the updated policy — the embedding is live within 2 seconds.
- **Dashboard JS load failure:** If the HTML file loads but the inline JS fails (browser
  compatibility, script error), the user sees the HTML fallback: a static message with
  instructions to use AI chat as the alternative. The fallback is plain HTML — no JS required.
- **`/admin` route discovered by a non-admin:** Any signed-in user can visit `/admin`. The
  dashboard JS calls `begin_session`, checks the role, and shows "Access denied" for non-admins.
  The admin tools are never called — the gate is in the dashboard JS AND in the backend tools
  (defense in depth). If the dashboard JS is bypassed (e.g., direct API call), the backend
  tools still reject non-admin callers with `"not found"`.
- **Dashboard on mobile:** The HTML is responsive enough to scroll and tap, but not optimized
  for mobile screens. Textareas and tables overflow horizontally on narrow viewports. The admin
  is expected to use a desktop browser for bulk editing. AI chat is the recommended mobile
  admin interface.
- **Mistral API down during dashboard save:** `catalog_set_policy` saves the content but returns
  `"embedding_regenerated": false, "warning": "Embedding unavailable..."`. The dashboard
  displays a yellow warning: "Policy saved but not searchable. It will be re-indexed when the
  embedding service recovers." The dashboard does not retry — the admin can re-save later to
  trigger re-embedding.

---

## Out of Scope (v2 + v3)

| Item | Why |
|---|---|
| Proactive alerts (auto-escalate on SLA breach) | v4 — requires agent loop |
| Auto-resolution of common patterns | v4 — requires agent loop |
| Agent loop (server watches, decides, acts) | v4 — architectural change |
| Multi-language support | Future |
| Freshdesk webhook inbound (Freshdesk pushing to us) | Future — v3 is push from our side only |
| Zendesk integration | v3 mentions it; initial implementation targets Freshdesk + Shopify |
| Ticket merging (link two tickets as duplicates) | Future |
| SLA pause/resume (stop the clock on weekends) | Future |
| Customer-facing ticket portal (non-AI interface) | Out of scope — this is an MCP server, not a web app |
| Batch operations (assign multiple tickets at once) | Future — tools are single-ticket by design |
| Notification templates (custom email body) | Future — v3 sends structured JSON events only |

---

## Acceptance Criteria

### v2 — Assignment & Routing
- [ ] `domain_assign_ticket("tkt-001", "Ravi")` → status becomes "in_progress", `assigned_to` is "Ravi"
- [ ] `domain_assign_ticket("tkt-001", "Ravi")` again (same agent) → no change, no error, status stays "in_progress"
- [ ] `domain_assign_ticket("tkt-001", "Priya")` (different agent) → `assigned_to` updates to "Priya"
- [ ] `domain_assign_ticket("tkt-003", "Ravi")` where tkt-003 status is "triaged" → status becomes "in_progress"
- [ ] `domain_assign_ticket("tkt-007", "Ravi")` where tkt-007 status is "resolved" → rejected: "ticket is already resolved"
- [ ] `domain_reassign_ticket("tkt-001", "Priya", "wrong department")` → returns `previous_agent`, `reason` set correctly
- [ ] Assign a ticket → `domain_get_ticket` shows `assigned_to` is updated immediately

### v2 — CSAT
- [ ] `domain_submit_csat("tkt-004", 5)` on a resolved ticket → score recorded, returned correctly
- [ ] `domain_submit_csat("tkt-004", 3)` again on the same ticket → returns existing score with `already_rated: true`
- [ ] `domain_submit_csat("tkt-001", 4)` where tkt-001 is open → rejected: "ticket must be resolved before rating"
- [ ] `domain_submit_csat("tkt-004", 0)` → rejected: "score must be between 1 and 5"
- [ ] `domain_submit_csat("tkt-004", 6)` → rejected: "score must be between 1 and 5"
- [ ] `domain_get_customer_profile` now returns `csat_trend` — not null for users with rated tickets

### v2 — Attachments
- [ ] `domain_attach_file("tkt-004", base64data, "photo.jpg", "image/jpeg")` → returns `attachment_id`
- [ ] `domain_get_ticket("tkt-004")` → includes `attachment_count: 1`, `attachment_ids: ["att-..."]`
- [ ] Attach 10 files to same ticket → all succeed. Attach an 11th → rejected: "ticket already has 10 attachments"
- [ ] Attach file > 10MB → rejected: "file exceeds 10MB limit"
- [ ] Attach file with MIME type "application/exe" → rejected: "unsupported file type: application/exe"
- [ ] Attach to non-existent ticket → "not found"
- [ ] Invalid base64 in file_data → rejected: "file data is not valid base64"
- [ ] `domain_get_attachment` returns presigned URL → wait 16 minutes → URL returns 403/expired from R2 (verified via curl)

### v2 — Draft Replies
- [ ] `domain_draft_reply("tkt-004")` → returns structured context with customer name, ticket details, policy excerpt, and agent name
- [ ] Draft for unassigned ticket → `agent_name: null`, `recommended_action` suggests assignment first
- [ ] Draft for ticket with empty body → context fields are populated with available data, `recommended_action` notes missing details
- [ ] Two consecutive calls → two independent responses (not cached)
- [ ] `domain_draft_reply("nonexistent")` → "not found"
- [ ] Staff user can call `domain_draft_reply` → returns context normally
- [ ] Customer cannot call `domain_draft_reply` → `"not found"`

### v2 — Reporting
- [ ] `domain_report_summary("week")` → all fields present, counts match actual data
- [ ] `domain_report_summary("today")` → returns data for today only (UTC boundaries)
- [ ] `domain_report_summary("invalid")` → rejected: "period must be one of: today, yesterday, week, month, quarter"
- [ ] `domain_agent_performance("Ravi")` → all fields present, `tickets_assigned` ≥ `tickets_resolved`
- [ ] `domain_agent_performance("Ravi", "week")` → filtered to the period, values ≤ all-time values
- [ ] `domain_report_summary` and `domain_agent_performance` agree on numbers for the same period
- [ ] Period with zero activity → returns zeroes (not nulls, not errors), avg fields are null

### v2 — Audit Log
- [ ] `domain_get_audit_log()` → returns most recent 50 entries
- [ ] `domain_get_audit_log(user_id="user_abc")` → only entries for that user
- [ ] `domain_get_audit_log(tool_name="domain_get_ticket", limit=10)` → at most 10 entries, all for that tool
- [ ] `domain_get_audit_log(since="2026-07-24T00:00:00Z")` → only entries after that timestamp
- [ ] `total_matching` > `returned` when more entries exist than limit
- [ ] `limit=500` → returns at most 500; `limit=501` → treated as 500 (max enforced silently, no error)

### v3 — Platform Sync
- [ ] `domain_sync_to_freshdesk("tkt-008")` → returns `freshdesk_id` (new ticket created)
- [ ] Same call again → updates existing Freshdesk ticket (idempotent, no duplicate)
- [ ] `domain_sync_to_freshdesk("tkt-008", "pull")` → local status updated from Freshdesk
- [ ] Freshdesk API unreachable → returns graceful error, local tools unaffected
- [ ] `domain_get_order("live-order-id")` → returns Shopify data when not in local catalog
- [ ] Shopify API unreachable → returns local catalog only with `source: "catalog_only"` and a note
- [ ] `domain_get_order` output includes `source` field (always present)

### v3 — Notifications
- [ ] `user_configure_notifications(email="user@test.com")` → config saved, returned on read
- [ ] `user_configure_notifications()` with no params → returns current config without changing it
- [ ] Invalid email → rejected: "email is not a valid email address"
- [ ] Webhook URL not https → rejected: "webhook URL must start with https://"
- [ ] Ticket status changes → email/webhook fires if creator has config matching the event type
- [ ] Notification fires only for the ticket creator's events, never for another user's ticket
- [ ] Failed webhook delivery does not block the status change
- [ ] Email delivery E2E: configure notification with valid email → update ticket status → verify SendGrid API was called (via mock or API activity log)
- [ ] SendGrid rate limit (100/day free tier): 101st email in a day → logged as warning, ticket update still succeeds, no error surfaced to caller

### v3 — Multi-Tenant Hardening
- [ ] User B calls `domain_get_ticket` for User A's ticket → "not found" (identical to nonexistent ticket)
- [ ] User A calls `domain_get_ticket` for their own ticket → returns ticket normally
- [ ] `domain_search("billing", include_my_tickets: true)` as User A → only User A's tickets in results
- [ ] `domain_search("billing", include_my_tickets: true)` as User B → only User B's tickets in results
- [ ] Same ticket ID: "not found" for wrong user vs "not found" for nonexistent ID → identical responses
- [ ] Audit log shows User B's attempt to access User A's ticket (accountability preserved)

### Cross-Version Compatibility
- [ ] All v1 tools work unchanged (except `domain_get_ticket` output gains `attachment_count/ids`)
- [ ] All v1 acceptance criteria still pass with v2+v3 tools present
- [ ] `begin_session` contract unchanged — same fields, same behavior (plus `role` field in v3)
- [ ] Session tokens work identically for v1 and v2/v3 tools
- [ ] Config store (rules, persona) unchanged — v2/v3 don't require new config keys
- [ ] Four invariants hold: one gateway, tools only, identity from sub, fail closed
- [ ] Per-tool reminder line appears on every v2/v3 tool return, unchanged from v1

### Admin Tools & Role Gating

#### Role Gating (3 Tiers)
- [ ] Customer (no role) → `tools/list` shows only customer-level tools (~12 tools)
- [ ] Staff (role `"staff"`) → `tools/list` shows customer + agent tools (~18 tools), no admin tools
- [ ] Admin (role `"admin"`) → `tools/list` shows all tools (~28 tools)
- [ ] Customer calls `domain_assign_ticket` → `"not found"`
- [ ] Customer calls `domain_draft_reply` → `"not found"`
- [ ] Customer calls `domain_report_summary` → `"not found"`
- [ ] Staff calls `domain_agent_performance` → `"not found"` (admin only)
- [ ] Staff calls `domain_report_summary` → `"not found"` (admin only)
- [ ] Staff calls `catalog_set_policy` → `"not found"`
- [ ] Revoke staff role in Descope → next `begin_session` returns `role: null` → agent tools return `"not found"`

#### Admin Tools (Existing)
- [ ] Non-admin calls `config_set_rules("text")` → `"not found"` (same as nonexistent tool)
- [ ] Non-admin calls `catalog_set_policy(...)` → `"not found"`
- [ ] Non-admin calls `catalog_delete_item("pol-001")` → `"not found"`
- [ ] Admin user (metadata `{"role": "admin"}` in Descope) calls `config_set_rules("new text")` → `{"status": "updated"}`
- [ ] After `config_set_rules`, next `begin_session` by any user returns the new rules
- [ ] After `config_set_persona`, next `begin_session` by any user returns the new persona
- [ ] `catalog_set_policy("pol-003", "New Policy", "body text", "all")` → new policy accessible via `domain_get_policy("pol-003")`
- [ ] `catalog_set_policy("pol-001", ..., "updated body", ...)` → `domain_search("updated body keywords")` finds pol-001 with correct similarity
- [ ] `catalog_set_order("ord-003", {...})` → `domain_get_order("ord-003")` returns the order
- [ ] `catalog_delete_item("pol-003")` → `domain_get_policy("pol-003")` returns `"not found"`
- [ ] `catalog_delete_item("pol-003")` again → `"not found"` (idempotent)
- [ ] `catalog_set_policy` when Mistral API is down → content saved, embedding not regenerated, warning returned, policy accessible by ID
- [ ] Revoke admin role in Descope → next `begin_session` returns `role: null` → admin tools return `"not found"`
- [ ] Session token with tampered `role` claim → rejected as invalid signature

#### New Admin Tools (v2)
- [ ] `catalog_list_all()` → returns all policies and orders
- [ ] `catalog_list_all(entity_type="policy", limit=10)` → returns at most 10 policies
- [ ] `catalog_list_all(offset=10)` → returns items starting from offset 10
- [ ] Non-admin calls `catalog_list_all` → `"not found"`
- [ ] `config_restore_version("rules", 1)` → restores most recent previous version, config updated, new history row created
- [ ] `config_restore_version("persona", 5)` where only 3 versions exist → rejected with clear error
- [ ] `config_restore_version("rules", 0)` → rejected: cannot restore to current version
- [ ] Key never edited → `config_restore_version` → rejected: no previous versions available
- [ ] Non-admin calls `config_restore_version` → `"not found"`
- [ ] `config_set_freshdesk_creds(api_key, domain)` → creds stored, background sync picks them up
- [ ] `config_set_shopify_creds(access_token, store_domain)` → `domain_get_order` uses new creds
- [ ] Freshdesk/Shopify creds missing both Fly secret and runtime config → sync/order lookup gracefully disabled (no crash)

#### New Tools (v2)
- [ ] `domain_get_attachment("tkt-004", "att-001")` → returns presigned R2 URL with 15min expiry
- [ ] User B calls `domain_get_attachment` for User A's ticket → `"not found"`
- [ ] Staff calls `domain_get_attachment` for ticket assigned to them → returns presigned URL
- [ ] Non-existent attachment → `"not found"`
- [ ] `domain_update_ticket("tkt-004", status="resolved")` → status changed, `resolved_at` set
- [ ] `domain_update_ticket("tkt-004", status="open")` from resolved → reopened, `resolved_at` cleared, `csat_score` cleared
- [ ] `domain_update_ticket("tkt-004", status="closed")` from resolved → closed, `closed_at` set (terminal)
- [ ] `domain_update_ticket("tkt-004", status="open")` from closed → rejected (terminal state)
- [ ] `domain_update_ticket("tkt-004", priority="critical")` → priority updated
- [ ] `domain_update_ticket("tkt-004", category="billing")` → category updated
- [ ] `domain_update_ticket("tkt-004", reply_body="Hi...")` → reply appended, notification dispatched to ticket creator

#### Status State Machine
- [ ] `open` → `triaged` → valid
- [ ] `triaged` → `open` → valid (re-triage)
- [ ] `triaged` → `in_progress` → valid (via `domain_assign_ticket`)
- [ ] `in_progress` → `pending` → valid
- [ ] `pending` → `resolved` → valid
- [ ] `in_progress` → `resolved` → valid (skip pending)
- [ ] `resolved` → `closed` → valid (terminal)
- [ ] `resolved` → `open` → valid (reopen, `resolved_at` and `csat_score` cleared)
- [ ] `closed` → any → rejected (all transitions from closed are invalid)
- [ ] `open` → `in_progress` directly → rejected (must be assigned/triaged first)
- [ ] `triaged` → `resolved` directly → rejected
- [ ] `in_progress` → `triaged` → rejected (use reopen flow)

### Admin Dashboard
- [ ] Admin visits `/admin` → Descope login prompt → after sign-in → dashboard shows rules, persona, policy table
- [ ] Non-admin visits `/admin` → Descope login prompt → after sign-in → "Access denied. Your account does not have admin permissions." shown
- [ ] Staff (role `"staff"`) visits `/admin` → Descope login → "Access denied. Your account does not have admin permissions." — no dashboard content rendered
- [ ] Rules textarea is pre-filled with current rules from DB (not empty, not stale)
- [ ] Admin edits rules in textarea → clicks Save → green "Saved" toast → next `begin_session` returns updated rules
- [ ] Persona textarea same flow: edit → Save → confirmation → next `begin_session` updated
- [ ] Policy table lists all policies with ID, title, applies_to columns
- [ ] Click policy row → row expands with inline editor showing title, body, applies_to in textareas
- [ ] Edit policy body → Save → `catalog_set_policy` called → policy updated + re-embedded → row refreshes
- [ ] Delete button on a policy → confirmation dialog ("Delete pol-003? This cannot be undone.") → on confirm → policy removed from table → `domain_get_policy("pol-003")` returns "not found"
- [ ] "Add new policy" button → blank inline form → fill ID, title, body, applies_to → Save → new row appears in table
- [ ] Order table toggle → collapsed by default → click to show → seed orders displayed with same CRUD
- [ ] Session expires mid-edit → Save returns error → "Your session expired. Please sign in again." → redirects to Descope login
- [ ] Save fails (DB error) → inline error message shown → editor stays open with edits preserved so admin can retry
- [ ] Refresh browser → dashboard loads fresh DB state (not stale cache — verified by editing a policy via AI chat, then refreshing dashboard)
- [ ] `/admin` served at correct URL on Fly.io (`https://support-desk.fly.dev/admin`)
- [ ] Dashboard JS load failure → HTML fallback visible: "Dashboard unavailable. Use AI chat to manage config."
- [ ] Dashboard load time < 2 seconds on first visit (Descope sign-in time excluded)
- [ ] Two admin tabs open → both can save → last save wins → no corruption, no crash

### Background Sync (v3)
- [ ] Gateway starts → background sync task begins without blocking server
- [ ] Sync runs every 15 minutes (verify via logs or audit trail entries)
- [ ] Open ticket synced to Freshdesk → Freshdesk status change → next sync cycle updates local ticket
- [ ] Freshdesk credentials missing from config → sync task sleeps with no errors
- [ ] One ticket sync fails (e.g., Freshdesk timeout) → other tickets still sync
- [ ] Sync failure is logged, no crash, no impact on MCP tool calls
- [ ] `domain_sync_to_freshdesk` on-demand call still works independently of background sync
- [ ] Server restart → sync task restarts from scratch (no state remembered between restarts)



---

## Operational & Cross-Cutting Concerns

### Logging Strategy

All errors and warnings are logged to stdout (captured by Fly.io and viewable via `fly logs`).
The audit trail (database `audit_log` table) captures every tool call — successful or failed.
Application-level errors (DB connection failures, R2 timeouts, Mistral API errors, SendGrid
failures) are logged to stdout with timestamp, severity level, and a correlation ID from the
request context. No personally identifiable information (PII) is written to stdout logs —
customer names, email addresses, and ticket bodies are only stored in the database. The audit
log input/output summaries truncate at 200 characters to limit log size.

### Rate Limiting

No rate limiting is implemented in v2/v3. The MCP server is invitation-only — a single
connector URL that the user adds to their AI assistant. Each signed-in user represents a
real human behind a Descope-authenticated session. Abuse risk is low (an attacker would
need to create multiple Descope accounts). If abuse becomes a concern in production, v4
should add a Redis-backed token-bucket rate limiter per `sub` with configurable thresholds.

### Input Sanitization

All user-supplied string inputs (ticket subject, body, agent name, category, policy body,
notification email, webhook URL) are sanitized before storage:
- Stripped of NULL bytes (`\x00`).
- Trimmed of leading and trailing whitespace.
- Validated against maximum length limits (documented per-tool).
SQL injection is prevented by using parameterized queries exclusively (psycopg2/asyncpg with
`%s` placeholders, never f-string or string concatenation). No HTML rendering occurs in the
MCP tool path (JSON-RPC responses only) — XSS is not applicable. The admin dashboard renders
user-edited policy text in textareas (not innerHTML), preventing DOM injection.

### Data Retention

No automatic data deletion in v2/v3. All tickets, attachments, audit logs, config history,
and notification configs persist indefinitely. Storage limits are:
- PostgreSQL: Neon free tier (3 GB project storage).
- Attachments: Cloudflare R2 free tier (10 GB).
When limits are approached, the admin must manually clean up old data or upgrade the plan.
GDPR compliance (right to erasure, data portability) is out of scope for v2/v3 and will be
addressed via admin tools in a future version. Tickets contain no healthcare, financial
account numbers, or government ID data — only support-related content.

---

## Deployment to Fly.io (Cloud, Free Tier)

The gateway currently runs on your machine behind a Cloudflare tunnel. Fly.io moves the compute
to a free-tier cloud VM with a fixed HTTPS URL — no tunnel, no laptop dependency, no URL changes
on restart. Neon and Descope remain in their respective clouds with zero changes.

### Architecture After Deployment

```
                       ┌──────────────────────────────┐
                       │   Descope (cloud)             │
                       │   OAuth 2.1 + DCR + PKCE      │
                       └──────────┬───────────────────┘
                                  │
                       ┌──────────▼───────────────────┐
  claude.ai ──────────▶│   Fly.io (cloud)              │
                       │   Docker container            │
                       │   FastMCP + Starlette         │
                       │   https://support-desk.fly.dev│
                       └──────────┬───────────────────┘
                                  │
                       ┌──────────▼───────────────────┐
                       │   Neon (cloud)                │
                       │   PostgreSQL + pgvector       │
                       └──────────────────────────────┘
```

Key differences from tunnel deployment:
- Fixed URL — no `trycloudflare.com` hostname changes, no re-adding connector in claude.ai
- No `cloudflared` process on your machine
- Gateway runs in Docker on Fly.io's infrastructure, not your laptop
- Stays alive even when your machine is off
- Free tier: 3 shared VMs (256MB each), $5/mo credit covers hobby usage

### Files to Create

#### `Dockerfile` (project root)

```dockerfile
FROM python:3.14-slim

WORKDIR /app

# Install uv for dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Install deps first (layer caching)
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --frozen

# Copy application code
COPY src/ ./src/
COPY seed/ ./seed/
COPY admin/ ./admin/

# Fly.io health check reads port from env
EXPOSE 8080

CMD ["uv", "run", "python", "-m", "connector_app.server"]
```

#### `fly.toml` (project root)

```toml
app = "support-desk"
primary_region = "iad"

[build]
  dockerfile = "Dockerfile"

[env]
  PORT = "8080"

[http_service]
  internal_port = 8080
  force_https = true
  auto_stop_machines = false
  auto_start_machines = true
  min_machines_running = 1

  [[http_service.checks]]
    interval = "15s"
    timeout = "5s"
    method = "GET"
    path = "/health"

[[vm]]
  memory = "256mb"
  cpu_kind = "shared"
  cpus = 1
```

### Code Change Required

`server.py` currently hardcodes `host="127.0.0.1", port=8000`. For Fly.io, the server must bind
`0.0.0.0` and read the port from the `PORT` environment variable (Fly.io sets this automatically).

Change the last line of `server.py` from:

```python
uvicorn.run(app, host="127.0.0.1", port=8000)
```

to:

```python
uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
```

This is the only runtime code change needed for deployment. Local dev still works: when `PORT`
is not set, it defaults to 8000. On Fly.io, `PORT=8080` is set automatically. The `0.0.0.0`
binding lets Fly.io route traffic to the container.

**Admin dashboard route:** Add one Starlette route to serve the static admin page:

```python
from pathlib import Path
from starlette.responses import FileResponse

async def serve_admin(request):
    admin_html = Path(__file__).parent.parent.parent / "admin" / "index.html"
    return FileResponse(admin_html)

# In routes list, alongside Mount("/", app=mcp_app):
Route("/admin", serve_admin, methods=["GET"])
```

The admin page (`admin/index.html`) is a single static HTML file with inline CSS and JS. No npm,
no webpack, no framework. The Dockerfile must copy it:

```dockerfile
COPY admin/ ./admin/
```

**Health endpoint:** Add a dedicated health check route that does not require auth:

```python
async def health_endpoint(request):
    return JSONResponse({"status": "ok"})

# In routes:
Route("/health", health_endpoint, methods=["GET"])
```

The `/health` endpoint returns `200 OK {"status": "ok"}`. Used by Fly.io health checks instead
of `/mcp` (which returns 401 without auth and can trigger false negatives). Update fly.toml:

```toml
[[http_service.checks]]
  interval = "15s"
  timeout = "5s"
  method = "GET"
  path = "/health"
```

**Database migration strategy:** No migration framework is used. The coding agent manages the
Neon database schema via MCP tools. The agent compares the schema expectations from AGENTS.md
against the live database and creates or alters tables as needed. This is the Manufacturing-track
approach — the agent handles DDL, you review. Tables in scope: `tickets` (v1), `users` + `user_state`
(v1), `support_embeddings` (v1), `audit_log` (v1), `config_history` (v2), `attachments` (v2),
`notification_config` (v3), `ticket_notes` (v2). The `config_history` table must be seeded with
the current rules and persona values on first creation (one row per key, version_index=0).

**Seed data for v2/v3:** Add to the project repository:
- `seed/tickets.json` — 5 sample tickets with various statuses (open, triaged, in_progress,
  pending, resolved), priorities, and categories. At least 1 with `created_by` set to the
  developer's test user sub, 1 with `assigned_to` set, 1 with `csat_score`, 1 with `freshdesk_id`.
- `seed/attachments.json` — 2 sample attachment metadata rows linked to seed tickets. The
  actual R2 files are optional for local dev (presigned URLs will 404 if R2 isn't configured,
  which is acceptable for tests).
- `seed/notifications.json` — 1 sample notification config row for the test user.
- Existing `seed/articles.json` and `seed/orders.json` from v1 remain unchanged.

### Deploy Steps

```bash
# 1. Install flyctl (one-time)
curl -L https://fly.io/install.sh | sh

# 2. Sign up / sign in (one-time, uses email or GitHub)
fly auth signup

# 3. Initialize (creates fly.toml automatically if not already present)
fly launch --name support-desk --region iad
# When prompted: "Would you like to deploy now?" → No (secrets not set yet)

# 4. Set secrets (never echoed — fly encrypts them)
fly secrets set DATABASE_URL="postgresql://..."
fly secrets set DESCOPE_CONFIG_URL="https://api.descope.com/v1/apps/agentic/P.../RS.../.well-known/openid-configuration"

# Optional: Only needed if Descope plan doesn't support custom JWT claims
# Used as fallback for fetching user role via Management API
fly secrets set DESCOPE_MANAGEMENT_API_KEY="..."

fly secrets set BASE_URL="https://support-desk.fly.dev"
fly secrets set SESSION_SIGNING_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
fly secrets set MISTRAL_API_KEY="..."
fly secrets set DEV_SUB="dev-user-001"

# v2 — Email notifications (SendGrid free tier: 100 emails/day)
fly secrets set SENDGRID_API_KEY="..."

# v2 — Attachment storage (Cloudflare R2 free tier: 10 GB, zero egress)
fly secrets set R2_ACCESS_KEY_ID="..."
fly secrets set R2_SECRET_ACCESS_KEY="..."
fly secrets set R2_ENDPOINT="https://<accountid>.r2.cloudflarestorage.com"
fly secrets set R2_BUCKET="support-desk-attachments"

# v3 — External platforms (set to "" if not using)
fly secrets set FRESHDESK_API_KEY="..."
fly secrets set FRESHDESK_DOMAIN="acmecorp.freshdesk.com"
fly secrets set SHOPIFY_ACCESS_TOKEN="..."
fly secrets set SHOPIFY_STORE_DOMAIN="acmecorp.myshopify.com"

# v3 — Webhook notifications
fly secrets set WEBHOOK_SECRET="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"

# 5. Deploy
fly deploy

# 6. Confirm health
curl https://support-desk.fly.dev/mcp -X POST \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"health","arguments":{}}}'
```

### Post-Deploy Configuration (Descope Dashboard)

After deployment, update the Descope MCP Server configuration to point to the Fly.io URL:

| Setting | Old Value | New Value |
|---|---|---|
| MCP Server URL | `https://xxxx.trycloudflare.com/mcp` | `https://support-desk.fly.dev/mcp` |
| App URL (project settings) | `https://xxxx.trycloudflare.com` | `https://support-desk.fly.dev` |
| Approved Domains | `trycloudflare.com` | add `fly.dev` |

Also update the local `.env` file for when you run the gateway locally (the Fly.io instance doesn't
read `.env` — it uses `fly secrets`):

```env
RESOURCE_URL=https://support-desk.fly.dev
BASE_URL=https://support-desk.fly.dev
```

### Operational Notes

```bash
# View logs
fly logs

# Restart after crash
fly apps restart support-desk

# Scale to 0 (stop entirely, no cost)
fly scale count 0

# Scale back to 1 (start)
fly scale count 1

# Update code
git push                           # push your changes
fly deploy                         # rebuild + ship

# Set a new secret
fly secrets set KEY=VALUE
fly deploy                         # restart with new secret

# Check running instances
fly status

# SSH into the machine (debugging)
fly ssh console
```

### Acceptance Criteria (Deployment)

- [ ] `curl https://support-desk.fly.dev/mcp` returns a valid MCP endpoint (200 or 401, not 000)
- [ ] `fly status` shows 1 machine running, state "started"
- [ ] No token → 401 via Fly.io URL with correct `WWW-Authenticate` header
- [ ] Well-known discovery returns Fly.io URL as `resource` and Descope as `authorization_servers`
- [ ] Valid Descope JWT → `begin_session` returns session token, rules, persona, state
- [ ] `domain_get_ticket("tkt-001")` returns the seed billing dispute ticket
- [ ] `user_save_state` + new chat `user_get_profile` round-trips (cross-chat memory works on cloud)
- [ ] Service survives a `fly apps restart` — health check passes within 5 seconds
- [ ] Logs visible via `fly logs` streaming
- [ ] All 5 offline security tests still pass (they test `auth.py` + `session.py` directly, no Fly.io dependency)

---

*End of behavioral specification (v2 + v3).*
