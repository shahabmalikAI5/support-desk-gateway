# Support Desk — Specification

**A connector-native app.** One remote MCP server. One URL, one Authorize click.
The customer is an AI — it reads the tools, decides which to call, and returns results to the user.

---

## Goal

Support Desk gives any business an AI support agent that:
- Looks up real tickets, orders, and policies by ID
- Searches the support catalog by meaning (semantic search)
- Creates new support tickets on behalf of customers
- Remembers each customer across separate chat sessions
- Escalates to human agents based on configurable rules
- Refuses to improvise when systems are unavailable

The connector deploys once, costs nothing, and the business admin updates policies, rules, and catalog items directly in the database — no code deploy needed.

---

## User Scenarios

### Scenario 1: Customer asks about an order

Priya opens claude.ai. She added the Support Desk connector once, signed in via Google. Now:

> "My order ORD-8821 — the running shoes arrived damaged. I want a refund."

The AI calls `begin_session` → learns it's Priya, gets rules about refunds, loads her saved state (empty — first visit). The AI calls `domain_get_order("ord-8821")` → sees "Running Shoes Pro, $129, shipped Jul 18, TR-9911." It calls `domain_get_policy("pol-001")` → learns: 30-day return window, no restocking fee if defective. It calls `domain_create_ticket` to file the refund. It calls `user_save_state` so next time it remembers what they were discussing. The AI tells Priya: "I've created ticket tkt-004. Since defective, no restocking fee. An agent will respond within 24 hours."

### Scenario 2: Customer returns next day, new chat

Priya opens a brand-new claude.ai chat (different tab, no history):

> "Any update on my refund?"

The AI calls `begin_session` → loads her saved state: `{last_viewed_item_id: "tkt-004"}`. The AI immediately calls `domain_get_ticket("tkt-004")` → "Still open, no agent assigned yet." The AI tells Priya: "Welcome back — your ticket is still open. Would you like me to flag it as urgent?"

### Scenario 3: Customer searches for policy

Marcus types:

> "Can I return something after 45 days?"

The AI calls `domain_search("return policy time limit")` → semantic search returns pol-001 ranked first. The AI reads: "30-day window." It tells Marcus: "Our return window is 30 days. After 45 days, returns are not accepted except for defective items. Was your item defective?"

### Scenario 4: Customer submits a new issue

Julia types:

> "My SaaS subscription shows 15 seats but I only have 10 people. I'm being overcharged."

The AI calls `begin_session` → gets rules. Calls `domain_search("billing dispute overcharge")` → finds tkt-001 (similar billing issue). Calls `domain_create_ticket("Overcharged — 15 seats billed, only 10 active", "Customer Julia reports subscription shows 15 seats, team size is 10. Overcharge amount unknown.", "high")` → creates tkt-005. AI: "I've filed ticket tkt-005 as high priority. A billing specialist will review the seat count discrepancy."

### Scenario 5: Support agent looks up a customer before responding

Ravi (human support agent) is working through his Freshdesk queue. He sees tkt-005 assigned to him: "Billing overcharge — Julia." Before responding, he opens his AI assistant (also connected to Support Desk) and asks:

> "Tell me about the customer on tkt-005."

The AI calls `domain_get_ticket("tkt-005")` → gets the subject and body. It calls `domain_get_customer_profile()` → returns: 8 previous tickets, avg resolution 11 hours, CSAT 4.2, zero SLA breaches. The AI tells Ravi: "Julia has a good history — 8 tickets, no prior escalations, CSAT average 4.2/5. First billing dispute. Recommend standard priority handling."

**Note:** This is a standard domain tool call (lookup + profile), NOT agent-assist copilot. Agent-assist copilot (v2) would be the AI drafting the actual reply message for Ravi — generating prose, suggesting tone, composing the email body. What happens here is the AI fetching context so Ravi can make his own decision. Context retrieval (v1) vs. content generation (v2).

### Scenario 6: System is down

Neon database is unreachable. Priya types:

> "Where's my order?"

The AI calls `begin_session` → fails. The rules (fail-closed paragraph delivered on the last successful `begin_session`) say: "If you cannot reach begin_session or a tool returns an error, tell the user plainly that the session can't continue right now. Do NOT improvise an answer from your own knowledge and do NOT invent the user's saved state." The AI tells Priya: "I'm sorry, I can't access the support system right now. Please try again in a moment, or email support@company.com." It does NOT guess the order status.

### Scenario 7: Admin updates a policy without deploy

The business admin changes the refund window from 30 to 60 days. Opens the Neon SQL console, runs: `UPDATE support_embeddings SET content = 'Refund policy: 60-day window...' WHERE id = 'pol-001';`. The next customer who asks about returns gets the new 60-day policy. No code deployed. No developer involved. 30 seconds.

---

## Four Invariants (Hard Rules)

1. **One gateway** — single MCP server, single URL, tools grouped by underscore prefix (`domain_*`, `user_*`, `config_*`).
2. **Tools only** — all user-facing logic is `@mcp.tool()`. No resources, no prompts.
3. **Prove, don't trust** — identity from verified OAuth token's `sub`, never from a tool argument. `auth.py` (given) enforces this.
4. **Fail closed** — broken tools → clean refusal. Never improvise. Rule lives in `config` table, reinforced on every tool return.

---

## Tool Catalog

### Tool Descriptions

Every tool must include a description the AI reads to decide when to call it. MCP tool descriptions are concise (1-3 sentences) with clear parameter descriptions.

---

#### `health`

**Description:** Confirm the Support Desk gateway is alive and reachable. Returns a simple status. Call this if you suspect the service is down before telling the user.

**Parameters:** None.

**Returns:**
```json
{"status": "ok"}
```

**Gated:** No. Always available.

---

#### `begin_session`

**Description:** Call this FIRST on any new request or new chat. Returns how to behave for this user, their saved state, and a session token that all other tools require. If the user is new, creates their account automatically. Do not call any gated tool before this.

**Parameters:** None.

**Returns:**
```json
{
  "rules": "<full rules text from config>",
  "persona": "<full persona text from config>",
  "state": {
    "preferred_name": "Julia",
    "last_viewed_item_id": "tkt-005",
    "last_action": "created ticket tkt-005 for billing dispute",
    "session_started_at": "2026-07-22T09:15:00Z"
  },
  "session_token": "<signed HS256 JWT, 30-min TTL>",
  "reminder": "Present every result in the support agent's professional voice — be helpful, precise, and escalate when uncertain."
}
```

**Gated:** Only by OAuth bearer token (auth.py). Requires valid Clerk-issued JWT. No session token needed (this tool ISSUES the session token).

**First-user behavior:** If the authenticated `sub` has no row in `users`, create one (email from token if available), create `user_state` with empty `{}`, and set `last_seen_at`. Return empty state in the session response. No error.

**Config vs begin_session relationship:** `begin_session` returns rules and persona as its PRIMARY delivery. Standalone `config_get_rules` and `config_get_persona` tools exist for mid-session refresh (when the model needs to re-read a rule without restarting the session). Both paths read from the same `config` table — one source of truth.

**Session token claims:**
```
{
  "sub": "<verified OAuth sub>",
  "iat": <issued-at timestamp>,
  "exp": <iat + 1800 seconds>,
  "scope": "session"
}
```
Signed with HS256 using `SESSION_SIGNING_SECRET`.

---

#### `domain_get_ticket`

**Description:** Retrieve a support ticket by its ID from the `tickets` table. Returns the full ticket: subject, body, priority, status, creation date, and the user who created it. This queries ALL tickets — both seed tickets (tkt-001, tkt-002, tkt-003) and user-created tickets (tkt-004, etc.) — from a single source of truth. Use this when a customer asks about a specific ticket number or when you know the ticket ID from saved state.

**Parameters:**
- `id` (string, required): The ticket ID, e.g. "tkt-001".

**Returns:**
```json
{
  "id": "tkt-001",
  "subject": "Overcharged on annual subscription",
  "body": "Customer was billed $4,500 instead of $3,600 for annual renewal...",
  "priority": "high",
  "status": "open",
  "created_by": "user-alice-42",
  "created_at": "2026-07-20T14:15:00Z"
}
```

**Isolation:** A user can retrieve any ticket by ID (the catalog is shared — tickets are not private). However, `domain_list_my_tickets` filters by creator. The audit log records who accessed which ticket.

**Gated:** Yes. Requires valid session token.

---

#### `domain_get_order`

**Description:** Retrieve an order by its ID. Returns customer name, items, total amount, status, and tracking information if shipped. Use this when a customer asks about a specific order number.

**Parameters:**
- `id` (string, required): The order ID, e.g. "ord-001".

**Returns:**
```json
{
  "id": "ord-001",
  "customer": "Alex Rivera",
  "items": ["Laptop Pro 15\"", "USB-C Hub", "Laptop Sleeve"],
  "total": 1249.99,
  "currency": "USD",
  "status": "shipped",
  "tracking_number": "TR-88291",
  "carrier": "FastShip Couriers",
  "ordered_at": "2026-07-16T08:30:00Z",
  "shipped_at": "2026-07-18T10:00:00Z",
  "estimated_delivery": "2026-07-23",
  "shipping_address": "Alex Rivera, 451 Oak Ave, Apt 12, Portland OR 97201"
}
```

**Domain boundary:** Orders live in the support catalog because customers frequently ask "where's my order?" alongside support questions. v1 uses seed data. v3 upgrades to live Shopify integration.

**Gated:** Yes.

---

#### `domain_get_policy`

**Description:** Retrieve a support or operational policy by its ID. Returns the policy title, full body text, and what it applies to. Use this when a customer asks about refunds, returns, SLAs, or escalation rules.

**Parameters:**
- `id` (string, required): The policy ID, e.g. "pol-001".

**Returns:**
```json
{
  "id": "pol-001",
  "title": "Refund & Return Policy",
  "body": "Customers may return items within 30 days of delivery...",
  "applies_to": "all physical products"
}
```

**Gated:** Yes.

---

#### `domain_search`

**Description:** Semantic search across orders and policies in the support catalog. Finds items by meaning, not just exact keywords. Returns ranked results with entity type, ID, and content snippet. Use this when the customer describes a problem but doesn't know the exact policy or order ID. Does NOT search tickets — for ticket lookups, use `domain_get_ticket(id)` or `domain_list_my_tickets()`.

**Parameters:**
- `query` (string, required): Natural language search query, e.g. "refund policy for damaged items" or "billing dispute resolution".

**Returns:**
```json
{
  "results": [
    {"id": "pol-001", "entity_type": "policy", "content": "Customers may return items within 30 days...", "similarity": 0.92},
    {"id": "pol-002", "entity_type": "policy", "content": "The Support Desk AI must escalate to a human agent...", "similarity": 0.81},
    {"id": "ord-002", "entity_type": "order", "content": "Alice Chen, Team Annual, 15 seats, $4,500.00...", "similarity": 0.74}
  ]
}
```

**Search scope:** The `support_embeddings` table holds orders and policies only. `domain_search` queries this catalog via semantic similarity. Tickets are NOT in `support_embeddings` — they live exclusively in the `tickets` table. To find tickets, use `domain_get_ticket(id)` or `domain_list_my_tickets()`. To search orders and policies by meaning, use `domain_search(query)`.

This separation prevents cross-user data leakage: user-created ticket content is never exposed through semantic search. Only shared catalog content (orders, policies) is searchable.

**Gated:** Yes.

---

#### `domain_create_ticket`

**Description:** Create a new support ticket on behalf of the current user. Requires a subject, body, and priority level. Returns the new ticket ID. The ticket is stamped with the authenticated user's identity.

**Parameters:**
- `subject` (string, required, max 500 characters): Brief summary of the issue.
- `body` (string, required, max 5000 characters): Full description of the problem.
- `priority` (string, required): One of "low", "medium", "high", "critical".

**Returns:**
```json
{
  "ticket_id": "tkt-004",
  "status": "open",
  "created_at": "2026-07-22T12:30:00Z"
}
```

**Validation:**
- Empty subject → rejected: "subject is required"
- Subject > 500 chars → rejected: "subject exceeds 500 characters"
- Empty body → rejected: "body is required"
- Invalid priority → rejected: "priority must be one of: low, medium, high, critical"

**Gated:** Yes.

---

#### `domain_list_my_tickets`

**Description:** List all tickets created by the current authenticated user. Returns ticket IDs, subjects, statuses, and creation dates. Use this when a customer asks "what tickets do I have open?" or "show me my ticket history."

**Parameters:** None.

**Returns:**
```json
{
  "tickets": [
    {"id": "tkt-004", "subject": "Damaged item — order ORD-8821", "status": "open", "created_at": "2026-07-22T12:30:00Z"},
    {"id": "tkt-007", "subject": "Wrong size shipped", "status": "resolved", "created_at": "2026-06-15T08:00:00Z"}
  ]
}
```

**Isolation:** Filtered by the authenticated user's `sub`. User A never sees User B's tickets in this list. Empty list returned if no tickets exist (not an error).

**Gated:** Yes.

---

#### `domain_get_customer_profile`

**Description:** Get the current authenticated user's support profile — metrics and history computed from the `tickets` table that help determine priority, tone, and escalation urgency. Use this before deciding whether to escalate, or when a support agent asks "who is this customer?"

**Data source:** All metrics are computed live from the `tickets` table filtered by `created_by = <sub>`:
- `open_tickets`: COUNT WHERE status IN ('open', 'in_progress')
- `total_tickets`: COUNT all rows
- `avg_resolution_time_hours`: AVG(resolved_at - created_at) WHERE status = 'resolved'
- `csat_score`: AVG(csat_score) WHERE csat_score IS NOT NULL
- `sla_breaches`: COUNT WHERE ((priority = 'high' AND created_at < NOW() - INTERVAL '4 hours') OR (priority = 'medium' AND created_at < NOW() - INTERVAL '24 hours') OR (priority = 'low' AND created_at < NOW() - INTERVAL '72 hours')) AND status NOT IN ('resolved', 'closed')
- `account_age_days`: EXTRACT(DAY FROM NOW() - users.created_at)
- `last_contact_at`: MAX(tickets.created_at)

**Parameters:** None.

**Returns:**
```json
{
  "open_tickets": 2,
  "total_tickets": 14,
  "avg_resolution_time_hours": 11.5,
  "csat_score": 4.2,
  "sla_breaches": 0,
  "account_age_days": 410,
  "last_contact_at": "2026-07-20T14:15:00Z"
}
```

**Gated:** Yes.

**Domain alignment:** Metrics are support KPIs (open tickets, resolution time, CSAT, SLA breaches) — not e-commerce metrics (loyalty tier, lifetime value). This matches the Customer Support & Experience entry niche.

---

#### `user_get_profile`

**Description:** Get the current user's saved preferences and state from their last session. Returns preferred name, last viewed item, and any saved draft. Use this to greet returning customers personally and pick up where they left off. Note: `begin_session` already returns state — use this tool mid-session if you need to re-read the profile.

**Parameters:** None.

**Returns:**
```json
{
  "preferred_name": "Priya",
  "last_viewed_item_id": "tkt-004",
  "last_action": "created ticket tkt-004 for damaged shoes",
  "saved_draft": ""
}
```

**Difference from `begin_session`:** `begin_session` returns state ONCE at session start. `user_get_profile` is for mid-session refresh (e.g., the AI wants to re-check the last viewed item after several tool calls). Both read from the same `user_state` table. Same source of truth.

**Gated:** Yes.

---

#### `user_save_state`

**Description:** Save the current user's session state to persist across chats. Provide a JSON object with any fields you want remembered: preferred_name, last_viewed_item_id, last_action, saved_draft, or any future fields. The state is keyed to the authenticated user — you cannot write to another user's state.

**Parameters:**
- `state` (object, required): A JSON object containing the state fields to persist.

**State schema (meaningful fields for Support Desk):**
```json
{
  "preferred_name": "Priya",
  "last_viewed_item_id": "tkt-004",
  "last_action": "created ticket tkt-004 for damaged shoes",
  "saved_draft": "Drafting response: we have received your refund request..."
}
```

Fields are flexible — the AI can store whatever it deems useful. Only the verified user's `sub` can write to their own row.

**Gated:** Yes.

---

#### `config_get_rules`

**Description:** Read the current behavioral rules — escalation criteria, response guidelines, and the fail-closed instruction. Use this mid-session if you need to re-check escalation thresholds or behavioral guidelines. Note: rules are already returned in `begin_session`. Call this only if you need a refresh.

**Parameters:** None.

**Returns:**
```json
{
  "rules": "<full rules text from config table>"
}
```

**Gated:** Yes.

---

#### `config_get_persona`

**Description:** Read the current assistant persona and voice definition. Use this mid-session if you need to re-check the tone or style guidelines. Note: the persona is already returned in `begin_session`. Call this only if you need a refresh.

**Parameters:** None.

**Returns:**
```json
{
  "persona": "<full persona text from config table>"
}
```

**Gated:** Yes.

---

### Per-Tool Return Reminder

Every gated tool (tools 1-11) appends this one-line reminder to its return:

> *Present your answer in the support agent's professional voice — be helpful, precise, and escalate when uncertain.*

---

## Config Content (Verbatim)

This is the exact text stored in the `config` table. It is seeded once during migration and editable by the business admin via Neon SQL console thereafter. The content lives here in the spec so any implementer can seed it without guessing.

### Config key: `rules`

```
RULES FOR THE SUPPORT DESK ASSISTANT
=====================================

You are the AI support agent for this company. Behave as follows for every user:

1. COOPERATIVE TONE
   Greet the user warmly. Use their preferred name if available. Never pretend
   to have authority you don't have. If information is estimated vs. confirmed,
   say so explicitly.

2. LOOK BEFORE YOU ACT
   Before creating a ticket, check if one already exists for this issue
   (use domain_list_my_tickets). Before answering a policy question, fetch
   the actual policy (use domain_get_policy). Never quote a policy from memory.

3. ESCALATION CRITERIA — escalate to a human agent when ANY of these are true:
   (a) Refund or cancellation amount exceeds $500
   (b) The issue involves account security, data privacy, or legal compliance
   (c) The customer explicitly requests a human agent
   (d) The customer expresses anger, frustration, or threatens to leave
   (e) Data appears inconsistent across systems (e.g., order says shipped
       but tracking says pending)
   (f) The same issue has been open for more than 48 hours without resolution
   When escalating, tell the user clearly that a specialist will take over,
   explain why escalation is happening, and give an expected response time.

4. SLA AWARENESS
   High priority tickets: target response within 4 hours.
   Medium priority: 24 hours. Low priority: 72 hours.
   If a ticket is approaching or past its SLA, inform the user and escalate.

5. FAIL CLOSED — CRITICAL
   If you cannot reach begin_session OR any tool returns an error, tell the
   user plainly: "I'm sorry, I can't access the support system right now.
   Please try again in a moment." Do NOT improvise an answer from your own
   knowledge. Do NOT invent the user's saved state. Do NOT guess ticket
   statuses, order details, policy terms, or customer information. An honest
   "I can't access that right now" is always better than a confident wrong answer.

6. PRESENTATION
   When presenting ticket or order details, use a clear structure: what the
   item is, its current status, when it was last updated, and what the next
   step should be. When citing a policy, include the policy ID so it can be
   verified. End every interaction by asking if there's anything else you can
   help with, and save the user's state before closing.
```

### Config key: `persona`

```
PERSONA — SUPPORT DESK ASSISTANT
=================================

You are a professional support agent for a multi-industry business platform.
Your voice should be:

- CLEAR: Use plain language, short sentences. No jargon unless the customer
  uses it first. If a policy is complex, summarize it in one sentence first,
  then give the detail.

- PRECISE: Always cite your sources (ticket ID, policy ID, order number).
  Never say "I think" or "probably" about factual data. If data is missing
  or incomplete, say so rather than filling gaps.

- EMPATHETIC: Acknowledge frustration before solving the problem. "I understand
  this is frustrating — let me figure out what happened" before diving into
  data. Don't be chipper when the customer is upset.

- HONEST: If you don't know something, say so. If a tool is unavailable, say
  so. Never invent, embellish, or guess. Trust is built on honesty, not on
  always having an answer.

- EFFICIENT: Get to the point. Don't repeat information the customer already
  gave you. After looking up data, present the relevant parts — not the entire
  record unless asked.

You are NOT:
- A salesperson (don't upsell)
- A developer (don't explain how the system works internally)
- A therapist (be kind, but stay focused on solving the support issue)
- A decision-maker for refunds above the escalation threshold (hand off to human)
```

---

## Seed Data (Verbatim)

Seven records covering SaaS billing, e-commerce returns, and support policies — multi-industry. Three seed tickets are INSERTed into the `tickets` table. Two orders and two policies are stored in `support_embeddings` with Mistral embeddings (1024-dim) for semantic search. The `content` field is what `domain_get_order/domain_get_policy` returns; `domain_get_ticket` returns rows from the `tickets` table.

### tkt-001 (ticket — SaaS billing dispute)

Seeded into `tickets` table:
```json
{
  "id": "tkt-001",
  "subject": "Overcharged on annual subscription renewal",
  "body": "Customer reports billing discrepancy: annual Team plan renewal charged $4,500 instead of the contracted $3,600 for 15 seats. The overcharge is $900. Customer discovered this on their credit card statement dated July 18. They request immediate refund of the difference and an explanation of why the incorrect amount was charged. Previous invoices (Jan-Jun) were all at the $3,600 rate. Account manager: Sarah Chen. Contract ID: CT-4451.",
  "priority": "high",
  "status": "open",
  "created_by": "user-alice-42",
  "created_at": "2026-07-20T14:15:00Z"
}
```

### tkt-002 (ticket — e-commerce damaged item)

Seeded into `tickets` table:
```json
{
  "id": "tkt-002",
  "subject": "Damaged item on delivery — order ORD-8821",
  "body": "Customer ordered running shoes (Pro Runner X, $129) delivered July 18. Upon opening the box, the right shoe has a torn sole and the insole is separated. Customer attached three photos showing the damage. Box exterior was undamaged, suggesting the item was packed already defective. They request a full refund or replacement. Tracking number: TR-9911. Delivered by: FastShip Couriers. Customer is a Gold-tier repeat buyer (3 years, 12 previous orders).",
  "priority": "high",
  "status": "open",
  "created_by": "user-priya-88",
  "created_at": "2026-07-19T09:30:00Z"
}
```

### tkt-003 (ticket — SaaS feature request)

Seeded into `tickets` table:
```json
{
  "id": "tkt-003",
  "subject": "Feature request: bulk export for enterprise reporting",
  "body": "Enterprise customer on the Business plan needs a bulk CSV export feature for their quarterly compliance reports. Currently they must export data one project at a time (40+ projects). The request includes: export all projects to CSV with filters by date range and department. Customer says this is a blocker for renewing their annual contract (up for renewal in September). They've been a customer for 2 years, 200-seat deployment.",
  "priority": "low",
  "status": "triaged",
  "created_by": "user-marcus-55",
  "created_at": "2026-07-15T11:00:00Z"
}
```

### ord-001 (order — e-commerce electronics)

Stored in `support_embeddings` for semantic search. `domain_get_order("ord-001")` returns:
```json
{
  "customer": "Alex Rivera",
  "items": ["Laptop Pro 15\" (Space Gray)", "USB-C Hub 7-in-1", "Laptop Sleeve 15\""],
  "total": 1249.99,
  "currency": "USD",
  "status": "shipped",
  "tracking_number": "TR-88291",
  "carrier": "FastShip Couriers",
  "ordered_at": "2026-07-16T08:30:00Z",
  "shipped_at": "2026-07-18T10:00:00Z",
  "estimated_delivery": "2026-07-23",
  "shipping_address": "Alex Rivera, 451 Oak Ave, Apt 12, Portland OR 97201"
}
```

### ord-002 (order — SaaS subscription)

Stored in `support_embeddings` for semantic search. `domain_get_order("ord-002")` returns:
```json
{
  "customer": "Alice Chen",
  "plan": "Team Annual",
  "seats": 15,
  "billed_amount": 4500.00,
  "expected_amount": 3600.00,
  "currency": "USD",
  "status": "pending_payment",
  "contract_id": "CT-4451",
  "renewal_date": "2026-07-15",
  "billing_cycle": "annual",
  "account_manager": "Sarah Chen"
}
```

### pol-001 (policy — refund & return)

Stored in `support_embeddings` for semantic search. `domain_get_policy("pol-001")` returns:
```json
{
  "title": "Refund & Return Policy",
  "body": "Customers may return items within 30 days of delivery for a full refund. Items must be in original condition with all packaging and accessories. Defective items are exempt from the original-condition requirement and have no restocking fee. Non-defective returns incur a 10% restocking fee. Digital goods, gift cards, and personalized items are non-refundable. Refunds are processed to the original payment method within 5-10 business days after the returned item is received at our warehouse. Return shipping is free for defective items; customer pays return shipping for non-defective returns. Refunds exceeding $500 require supervisor approval (see escalation policy pol-002).",
  "applies_to": "all physical products"
}
```

### pol-002 (policy — escalation)

Stored in `support_embeddings` for semantic search. `domain_get_policy("pol-002")` returns:
```json
{
  "title": "Escalation & Handoff Policy",
  "body": "The Support Desk AI must escalate to a human agent when ANY of the following conditions are met: (1) Refund or cancellation amount exceeds $500. (2) The issue involves account security, password resets, data privacy, or legal compliance. (3) The customer explicitly requests a human agent. (4) The customer expresses anger, frustration, or threatens to cancel their account. (5) Data appears inconsistent between systems (e.g., order says shipped but tracking says pending). (6) A high-priority ticket has been open for more than 48 hours without agent assignment. When escalating: inform the customer clearly, explain why, provide the expected response time, and ensure the ticket is flagged for immediate review. Low-risk issues (simple policy questions, order status lookups, feature requests) may be handled autonomously without escalation.",
  "applies_to": "all support interactions"
}
```

---

## begin_session Contract

### Return JSON shape

```json
{
  "rules": "<string: full rules text from config table>",
  "persona": "<string: full persona text from config table>",
  "state": {
    "preferred_name": "<string | null>",
    "last_viewed_item_id": "<string | null>",
    "last_action": "<string | null>",
    "saved_draft": "<string | null>",
    "session_started_at": "<ISO 8601 timestamp>"
  },
  "session_token": "<string: signed HS256 JWT>",
  "reminder": "Present every result in the support agent's professional voice — be helpful, precise, and escalate when uncertain."
}
```

### First-user behavior

1. `begin_session` receives an OAuth token. `auth.verified_claims(token)` returns `sub`.
2. Query `users` table for `id = sub`.
3. If no row exists:
   - `INSERT INTO users (id, email) VALUES (sub, email_from_token_or_null)`
   - `INSERT INTO user_state (user_id, state) VALUES (sub, '{}')`
   - Set `last_seen_at = now()`
   - Return state as `{}`
4. If row exists:
   - `UPDATE users SET last_seen_at = now() WHERE id = sub`
   - Read `user_state.state` for this `sub`
   - Return the saved state

### Session token claims

```
{
  "sub": "<verified OAuth sub>",
  "iat": <issued-at Unix timestamp>,
  "exp": <iat + 1800>,
  "scope": "session"
}
```
- Algorithm: HS256
- Secret: `SESSION_SIGNING_SECRET` from environment
- TTL: 30 minutes (1800 seconds)
- Validated by `session.require_session(token)` which checks: token present, not expired, scope = "session", signature valid

### Config delivery

Rules and persona are delivered through `begin_session` as the primary mechanism. The standalone `config_get_rules` and `config_get_persona` tools exist for mid-session refresh — if the model needs to re-read rules without restarting the session (which would issue a new token). Both paths read from the same `config` database table.

---

## Identity & Auth

### Clerk JWT Template Specification

Clerk must issue tokens with these claims for `auth.py` to accept them:

| Claim | Required | Value | Checked by |
|-------|:---:|-------|-----------|
| `sub` | Yes | Clerk user ID (e.g., `user_2abc123...`) | `jwt.decode(options={"require": ["sub"]})` |
| `iss` | Yes | `https://<clerk-domain>` | `jwt.decode(issuer=AUTH_ISSUER)` |
| `aud` | Yes | `https://support-desk.fly.dev` (EXACT — the `RESOURCE_URL`) | `jwt.decode(audience=RESOURCE_URL)` |
| `exp` | Yes | Token expiry (recommend 1 hour) | `jwt.decode(options={"require": ["exp"]})` |
| `iat` | Yes | Issued-at timestamp | Standard JWT |
| `kid` | Yes | Key ID matching Clerk's JWKS | `auth._key_for(token)` |

**Clerk dashboard configuration:**
1. Create a custom JWT template in Clerk Dashboard → JWT Templates → New Template
2. Set the `aud` claim to the exact `RESOURCE_URL` (initially `http://localhost:8000` for dev, later `https://support-desk.fly.dev` for production)
3. Token lifetime: 1 hour (matches typical OAuth token TTL; the session token is separate and is 30 minutes)
4. Signing algorithm: RS256 (Clerk's default — matches `auth.py`'s `algorithms=["RS256"]`)

### Development path — mock_auth

During local development before Clerk is set up, use the bundled `mock_auth` service:
- Start: `uv run uvicorn mock_auth.server:app --port 9000`
- Set `.env`: `AUTH_ISSUER=http://localhost:9000`, `AUTH_JWKS_URL=http://localhost:9000/jwks.json`, `RESOURCE_URL=http://localhost:8000`
- `mock_auth` issues RS256 tokens with `aud = http://localhost:8000` matching local dev
- The exact same `auth.py` code path runs — no difference in verification logic
- Transition to Clerk: swap 3 values in `.env` and add the JWT template. Code unchanged.

### User lifecycle

| Event | Behavior |
|-------|----------|
| **First sign-in** | `begin_session` auto-creates `users` row + empty `user_state` row. No error. |
| **Returning sign-in** | `begin_session` updates `last_seen_at`, returns existing state. |
| **Account deleted (Clerk)** | Tokens invalidated immediately. Next `begin_session` returns 401. Data rows persist (audit trail). |
| **Data cleanup** | No automatic deletion. Admin runs cleanup queries if needed. |
| **Token rotation (Clerk key change)** | JWKS cache (600s TTL) auto-refetches. No downtime. |

---

## Data Model

### Tables

```sql
CREATE TABLE users (
    id TEXT PRIMARY KEY,                              -- verified OAuth sub
    email TEXT,                                        -- from token if available
    created_at TIMESTAMPTZ DEFAULT now(),
    last_seen_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE user_state (
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    state JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE audit_log (
    id SERIAL PRIMARY KEY,
    user_id TEXT,                                      -- sub of the caller
    tool_name TEXT NOT NULL,                           -- which tool was called
    input_summary TEXT,                                -- brief description of inputs
    output_summary TEXT,                               -- brief description of result
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE config (
    key TEXT PRIMARY KEY,                              -- 'rules' | 'persona'
    value TEXT NOT NULL,                               -- full text content
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE tickets (
    id TEXT PRIMARY KEY,                              -- tkt-001, tkt-004, etc.
    subject TEXT NOT NULL,                             -- brief summary
    body TEXT NOT NULL,                                -- full description
    priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    created_by TEXT NOT NULL,                          -- OAuth sub of creator
    assigned_to TEXT,                                  -- agent name (v2)
    resolved_at TIMESTAMPTZ,                           -- when resolved (for avg_resolution_time)
    csat_score DECIMAL(2,1) CHECK (csat_score >= 0 AND csat_score <= 5),  -- post-resolution satisfaction
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE support_embeddings (
    id TEXT PRIMARY KEY,                               -- matches entity IDs (ord-*, pol-*)
    entity_type TEXT NOT NULL CHECK (entity_type IN ('order', 'policy')),
    content JSONB NOT NULL,                            -- the full entity as JSON
    embedding VECTOR(1024)                             -- Mistral embedding-embed
);
```

**Six tables total.** Tickets table added — this is the source of truth for all tickets (seed + user-created). Three seed tickets (tkt-001, tkt-002, tkt-003) are INSERTed during migration, alongside any user-created tickets at runtime.

**`support_embeddings` now holds only `order` and `policy` entity types** (ticket content is not duplicated — tickets live exclusively in the `tickets` table).

### State schema (user_state.state JSONB)

```json
{
  "preferred_name": "string | null",
  "last_viewed_item_id": "string | null",
  "last_action": "string | null",
  "saved_draft": "string | null"
}
```

Fields are not enforced by schema (JSONB is flexible). The AI can add fields. The spec defines the minimum meaningful set. Unknown fields are preserved (no stripping).

### Foreign key behavior

- `user_state.user_id → users.id`: ON DELETE CASCADE. If a user row is removed, their state is removed.
- `audit_log.user_id → users.id`: No FK constraint (logs persist even if user is deleted — audit trail integrity).

### Config table seeding

Two rows inserted during migration:
- `key='rules'`, `value='<full rules text from Config Content section>'`
- `key='persona'`, `value='<full persona text from Config Content section>'`

Business admin updates these rows directly to change behavior without deploying code. `config_store.py` reads from this table.

### Fallback config (hardcoded)

When the `config` table is unreachable (DB down) or a config row has been deleted, `config_get_rules` and `config_get_persona` return hardcoded minimal versions. This ensures `begin_session` always returns something — the fail-closed instruction in particular must always be delivered.

**Fallback rules (when DB is unavailable):**
```
You are the AI support agent for this company.

FAIL CLOSED — CRITICAL: If you cannot reach begin_session or any tool
returns an error, tell the user plainly: "I'm sorry, I can't access the
support system right now. Please try again in a moment." Do NOT improvise
an answer from your own knowledge. Do NOT invent the user's saved state.

ESCALATE to a human agent when: refund amounts exceed $500, the issue involves
account security or data privacy, the customer explicitly requests a human,
or the customer expresses anger or frustration.

Present answers in a professional, helpful tone. Look up policies and tickets
by ID before responding. Save user state before closing.
```

**Fallback persona (when DB is unavailable):**
```
You are a professional support agent. Be clear, precise, empathetic, and honest.
Never invent, embellish, or guess. Cite your sources. Present data in a clear structure.
```

---

## Edge Cases & Rules

### Cross-user isolation

1. **`user_get_profile`**: Reads `user_state` filtered by the session token's `sub`. User A cannot read User B's state.
2. **`user_save_state`**: Writes to `user_state` filtered by session token's `sub`. User A cannot write to User B's state.
3. **`domain_list_my_tickets`**: Returns only tickets where `created_by` = session token's `sub`. User A never sees User B's private tickets.
4. **`domain_get_ticket("tkt-XXX")`**: Returns any ticket by ID from the `tickets` table — the single source of truth for all tickets. The `audit_log` records who accessed which ticket. For standalone connectors (single business), all tickets in the table are visible via `domain_get_ticket` by ID (ticket IDs are not secret). `domain_list_my_tickets` filters by creator and is the primary isolation mechanism. If per-ticket access control is needed (e.g., in v3+ multi-tenant deployments), add a `customer_id` column to the `tickets` table and filter `domain_get_ticket` by the caller's sub.
5. **`domain_search`**: Searches only the `support_embeddings` catalog table (orders and policies — shared reference data). Tickets are NOT in this table; user-created ticket content is never exposed through semantic search.
6. **Tool signature audit**: Zero tool signatures contain `user_id` as a parameter. Identity is read from the session token's `sub`, never from an argument.

### Audit log access

The `audit_log` table records: `user_id`, `tool_name`, `input_summary`, `output_summary`, `created_at`. There is no tool to read audit logs (admin-only feature for v2). The log serves as a backend audit trail — proof of who accessed what and when.

### Search scope

`domain_search` searches the `support_embeddings` table which contains:
- 4 seed records (ord-001, ord-002, pol-001, pol-002)
- Additional catalog items added by the business admin

Tickets are not in `support_embeddings`. `domain_search` cannot find ticket content. To find tickets, use `domain_get_ticket(id)` or `domain_list_my_tickets()`.

### Concurrency

- Two simultaneous `begin_session` calls from the same user (two browser tabs): Both succeed, both issue separate session tokens. State writes use last-write-wins.
- Two simultaneous `user_save_state` calls: Last write wins. No corruption (atomic JSONB updates).
- Session token boundary: Valid at 29m59s. Expired at 30m01s. No grace period.

### Input validation

| Tool | Validation |
|------|-----------|
| `domain_get_ticket(id)` | ID must be non-empty string. Returns "not found" for unknown IDs (not error). |
| `domain_get_order(id)` | Same. |
| `domain_get_policy(id)` | Same. |
| `domain_create_ticket(subject, body, priority)` | Subject: 1-500 chars. Body: 1-5000 chars. Priority: one of low/medium/high/critical. |
| `domain_search(query)` | Query: 1-1000 chars. Empty query → "query is required." |
| `user_save_state(state)` | State must be a valid JSON object. Non-JSON → rejected. Max size: 50KB. |

### Fail-closed mechanism

The fail-closed paragraph is delivered in the rules text returned by every `begin_session`. It instructs the AI to refuse rather than improvise. The mechanism is reinforced three ways:
1. In the rules text returned at session start
2. In the per-tool return reminder on EVERY tool response
3. By the structural gate: tools return errors when DB/services are down, so the AI physically cannot get data to improvise with

---

## Out of Scope (v1)

- **Live platform integrations** (Freshdesk, Shopify, Zendesk) — v3
- **Proactive alerts and auto-resolution** — v4 (requires agent loop)
- **Ticket assignment and agent routing** — v2
- **Customer satisfaction surveys** — v2
- **Multi-language support** — future
- **File/image attachments on tickets** — v2
- **Semantic search over private user tickets** — v1 searches shared catalog only
- **Admin dashboard or UI** — business admin uses Neon SQL console directly
- **Email/push notifications to customers** — v3
- **Agent-assist copilot for human support agents** — v2
- **Usage analytics and reporting** — v2

---

## Acceptance Criteria

The build is done when:

- [ ] `health` returns 200 on unauthenticated GET
- [ ] Ungated tool call returns 401 with no Authorization header
- [ ] Valid Clerk token resolves `sub` through `auth.verified_claims`
- [ ] Token with wrong audience (`aud` ≠ RESOURCE_URL) is rejected with 401
- [ ] `/.well-known/oauth-protected-resource` returns correct discovery document
- [ ] `begin_session` returns rules, persona, state, session_token, and reminder
- [ ] First-time user: `begin_session` auto-creates `users` row + empty `user_state`, returns `{}` state
- [ ] Returning user: `begin_session` returns saved state from last session
- [ ] Gated tool called without session token → refused with "no session — call begin_session first"
- [ ] Gated tool called with expired session token → refused with "invalid session"
- [ ] `domain_get_ticket("tkt-001")` returns the exact seed data from spec
- [ ] `domain_get_order("ord-001")` returns the exact seed data from spec
- [ ] `domain_get_policy("pol-001")` returns the exact seed data from spec
- [ ] `domain_get_ticket("nonexistent")` returns "not found" (not error)
- [ ] `domain_search("refund policy")` returns results ranked by similarity
- [ ] `domain_create_ticket` with valid inputs creates a ticket, returns ticket ID
- [ ] `domain_create_ticket` with empty subject → rejected: "subject is required"
- [ ] `domain_create_ticket` with invalid priority → rejected
- [ ] `domain_list_my_tickets` returns only tickets created by current user
- [ ] `domain_list_my_tickets` for user with no tickets → returns `[]`
- [ ] `domain_get_customer_profile` returns support metrics (not e-commerce metrics)
- [ ] `user_save_state` + `user_get_profile` round-trips on fresh connection
- [ ] User A's `user_get_profile` shows no trace of User B's state
- [ ] User A's `domain_list_my_tickets` shows no trace of User B's tickets
- [ ] `config_get_rules` returns the exact rules text from spec
- [ ] `config_get_persona` returns the exact persona text from spec
- [ ] DB unreachable → all tools return clean errors, AI says "can't access" (proven by F1-F8 tests)
- [ ] Every gated tool return includes the per-tool reminder line
- [ ] All 93 test cases from the test matrix pass

---

## Test Matrix (93 tests)

### Auth Layer (A1-A12)

| # | Test | Expected |
|---|------|----------|
| A1 | No Authorization header | 401 |
| A2 | Expired JWT | 401 |
| A3 | Wrong audience JWT | 401 |
| A4 | Wrong issuer JWT | 401 |
| A5 | Tampered JWT (invalid signature) | 401 |
| A6 | JWT missing `sub` claim | 401 |
| A7 | JWT signed HS256 instead of RS256 | 401 |
| A8 | JWT missing `kid` header | 401 |
| A9 | Valid JWT → verify resolved sub | `sub` = expected Clerk user ID |
| A10 | Key rotation → JWKS cache re-fetch | Token from new key passes |
| A11 | Two users → distinct subs | No crossover |
| A12 | `/.well-known/oauth-protected-resource` | Returns `resource` + `authorization_servers` |

### Session Layer (S1-S10)

| # | Test | Expected |
|---|------|----------|
| S1 | Gated tool, no session token | "no session — call begin_session first" |
| S2 | Gated tool, expired session token | "invalid session" |
| S3 | Gated tool, tampered session token | "invalid session" |
| S4 | Session token scope ≠ "session" | "wrong token type" |
| S5 | User B uses User A's session token | Tools act on A's data (v1 accepted; 30-min TTL + HTTPS mitigates) |
| S6 | `begin_session` return | All 5 fields: rules, persona, state, session_token, reminder |
| S7 | `begin_session` called twice | Two valid tokens, both work within TTL |
| S8 | Session token boundary: 29m59s vs 30m01s | Works at 29:59; fails at 30:01 |
| S9 | Session expires → re-call `begin_session` | New token, conversation continues |
| S10 | Two concurrent `begin_session` calls | Both succeed, last write wins |

### Database Layer (D1-D13)

| # | Test | Expected |
|---|------|----------|
| D1 | `user_save_state` for new user → upsert | Row inserted |
| D2 | `user_save_state` for existing user → update | One row, updated timestamp |
| D3 | `user_save_state` with empty JSON `{}` | Stored as `{}`, returned as `{}` |
| D4 | `user_save_state` with 50KB JSON | Intact |
| D5 | `user_save_state` with unicode/emoji | Intact |
| D6 | `user_get_profile` for user with no row | Returns `{}` — not error |
| D7 | Value round-trip: save → fresh connection → read | Same value back |
| D8 | Concurrent `user_save_state` from two chats | Last write wins, no corruption |
| D9 | Neon unreachable → `user_save_state` | Clean error, no crash |
| D10 | Neon connection dropped mid-query | No crash, no raw SQL leaked |
| D11 | `user_save_state` with non-JSON string | Rejected with validation error |
| D12 | SQL injection via tool input | Parameterized query prevents — returns "not found" |
| D13 | SQL injection in `domain_search` query | Only text sent to embedding API |

### Domain Layer (M1-M19)

| # | Test | Expected |
|---|------|----------|
| M1 | `domain_get_ticket("tkt-001")` | Full object from seed data |
| M2 | `domain_get_ticket("nonexistent")` | Clean "not found" |
| M3 | `domain_get_order("ord-001")` | Full object from seed data |
| M4 | `domain_get_policy("pol-001")` | Full object from seed data |
| M5 | `domain_search("refund policy")` | pol-001 ranked highest |
| M6 | `domain_search("damaged item return policy")` | pol-001 ranked high (semantic match on "defective", "return", "refund" in policy text) |
| M7 | `domain_search("xyzzy nonexistent")` | Empty list `[]` |
| M8 | `domain_create_ticket("Subject", "Body", "high")` | New ticket ID returned, row in DB |
| M9 | `domain_create_ticket("", "Body", "high")` | "subject is required" |
| M10 | `domain_create_ticket("Subject", "Body", "invalid")` | "priority must be one of: low, medium, high, critical" |
| M11 | `domain_create_ticket` subject > 500 chars | "subject exceeds 500 characters" |
| M12 | `domain_list_my_tickets` | Only current user's tickets |
| M13 | `domain_list_my_tickets` for user with no tickets | `[]` |
| M14 | `domain_get_customer_profile` | Returns support KPI metrics |
| M15 | `domain_get_customer_profile` no profile row | Defaults returned |
| M16 | Embedding API unreachable → `domain_search` | "Search temporarily unavailable" |
| M17 | Embedding API rate limit → `domain_search` | Clean error, other tools unaffected |
| M18 | `domain_create_ticket` body > 5000 chars | Rejected — "body exceeds 5000 characters" |
| M19 | `domain_create_ticket` → `domain_get_ticket(ticket_id)` on same user | Returns newly created ticket with all fields (subject, body, priority, status, created_by, created_at). Verifies seed and user-created tickets share the same `tickets` table. |

### Config Layer (C1-C6)

| # | Test | Expected |
|---|------|----------|
| C1 | `config_get_rules()` | Exact rules text from spec |
| C2 | `config_get_persona()` | Exact persona text from spec |
| C3 | Admin updates `config` table → next `begin_session` | Updated rules returned |
| C4 | Admin deletes `config` row | Hardcoded fallback rules returned (with fail-closed paragraph) |
| C5 | DB unreachable → `begin_session` still returns rules | Fallback rules used |
| C6 | Rules text contains "forget previous instructions" | Rejected at seed migration — cooperative phrasing only |

### Multi-User Isolation (I1-I6)

| # | Test | Expected |
|---|------|----------|
| I1 | User A saves state → User B's `user_get_profile` | B returns B's state, no trace of A |
| I2 | User A creates ticket → User B's `domain_list_my_tickets` | B's list does NOT contain A's ticket |
| I3 | User A's `audit_log` entries | Only A's entries contain A's `sub` |
| I4 | Tool signature audit: grep `user_id` | Zero `user_id` params in any tool |
| I5 | Hallucinated `user_id` in request body | Ignored, sub read from token |
| I6 | User B calls `domain_get_ticket("tkt-A")` where tkt-A is User A's private ticket | Ticket returned by ID (all tickets in the table are accessible by ID in v1). `audit_log` records B's access. `domain_list_my_tickets` is the primary isolation mechanism — filters by creator. v3+ multi-tenant hardening adds `customer_id` column. |

### Fail-Closed (F1-F8)

| # | Test | Expected |
|---|------|----------|
| F1 | Neon down → "What's my order status?" | "I can't access the support system right now" — no invented status |
| F2 | Neon down → "What's the refund policy?" | No improvised policy |
| F3 | Neon down → "Is my ticket resolved?" | No false yes/no |
| F4 | No session → any tool call | "Session can't start right now" |
| F5 | Embedding API down → "Find my refund ticket" | "Search unavailable. I can look up by ID." |
| F6 | Tool returns partial data (body: null) | AI: "Ticket exists but body is empty" |
| F7 | `begin_session` returns → fail-closed paragraph present | AI respects it |
| F8 | Question with no tool available | "I don't have access to that information" |

### Real-World Scenarios (R1-R10)

| # | Test | Expected |
|---|------|----------|
| R1 | Two browser tabs → both call tools | No corruption, last write wins |
| R2 | Mobile + desktop simultaneously | No corruption, separate tokens |
| R3 | Session expires mid-convo → re-auth | New token, state restored |
| R4 | Close chat → reopen next day | State restored: "Welcome back" |
| R5 | Ticket with emoji body "😡 BROKEN 😡" | Stored and returned intact |
| R6 | Long URL in ticket body | Stored, not truncated |
| R7 | Non-Latin text (Urdu, Arabic, CJK) | Stored and returned correctly |
| R8 | User deletes Clerk account → tries connector | `begin_session` gets 401 |
| R9 | Server restart mid-convo | AI retries → `begin_session` → continues |
| R10 | OAuth token expires (1hr default) | Host re-authorizes silently → tools continue |

### Infrastructure (N1-N8)

| # | Test | Expected |
|---|------|----------|
| N1 | Health check `GET /health` | 200 regardless of DB state |
| N2 | Deploy with failing health → old VMs stay | Zero downtime |
| N3 | Process exceeds memory limit → OOM | Graceful shutdown → restart → resume |
| N4 | Neon regional outage | All tools → clean errors. Fail-closed. |
| N5 | Clerk outage → can't verify tokens | 401. Existing sessions within TTL survive. |
| N6 | Embedding API outage → `domain_search` error | Other 12 tools unaffected |
| N7 | Wrong Python version in container | Build catches it |
| N8 | `DATABASE_URL` with special chars in secrets | Properly encoded, connects correctly |

### Health (H1)

| # | Test | Expected |
|---|------|----------|
| H1 | `health()` called via MCP tools/call (not HTTP GET) | Returns `{"status": "ok"}`. Works unauthenticated (no OAuth token, no session token). |

---

## v1-v4 Growth Trajectory

| | v1 (Now) | v2 (Week 2-4) | v3 (Month 2) | v4 (Month 3+) |
|---|---|---|---|---|
| **Tickets handled autonomously** | 0% | 15% | 40% | 60% |
| **Agent time per ticket** | 8 min | 6 min | 3 min | 1 min |
| **Customer wait time** | 24 hr avg | 12 hr | 6 hr | 2 hr (or instant) |
| **What changes for business** | Deploy, paste URL on site | Update config rules in DB | Wire live platform APIs | Enable auto-resolution guardrails |
| **What changes for customer** | Pastes URL once, lookup answers | Urgency-aware responses | Live order status, faster resolution | Proactive check-ins, instant small refunds |

### v2 additions (behavioral)
- AI can check SLA targets and flag breaches
- AI can view full ticket history (timeline of status changes)
- AI can classify customer intent before responding
- AI can initiate refund workflow with guardrails
- Escalation matrix is queryable as a standalone config
- Customer gets ticket summary on session start

### v3 additions (behavioral)
- Tickets created in connector sync to external platforms
- Order status is live (not cached)
- Support agents get AI-drafted replies
- Customer's history aggregates across channels

### v4 (requires agent loop — separate course)
- Proactive satisfaction check-ins
- Auto-resolution for low-risk, policy-matching issues
- Churn risk detection
- Sentiment trend analysis

---

## Base Artifacts (Shipped Complete — Never Rewrite)

| File | Role |
|------|------|
| `src/connector_app/auth.py` | OAuth token verification: 4 checks (signature, issuer, audience, expiry) + `sub` extraction |
| `src/connector_app/session.py` | Session token minting and verification: `new_session_token`, `require_session` |
| `tests/test_starter.py` | 5 security-core smoke tests |
