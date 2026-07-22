# Support Desk — Behavioral Specification (v1)

**A single remote AI-support-desk service.** One endpoint, one sign-in. An AI model calls its tools to look up orders, policies, and tickets; create new tickets; search by meaning; and remember customers across sessions. No agent loop lives here — the model brings that.

---

## Goal (the why)

Give any business an AI support agent that:
- Looks up real tickets, orders, and policies by ID
- Searches the support catalog by meaning (semantic search)
- Creates new support tickets on behalf of signed-in customers
- Remembers each customer's conversation state across separate chat sessions
- Escalates to human agents based on configurable rules
- Refuses to improvise when its backing systems are unavailable

A business admin changes policies and rules directly in the live data store — no code deploy, no developer needed. The effect is immediate on the next customer interaction.

---

## User Scenarios

### Scenario 1: Customer asks about an order

Priya opens her AI chat app. She added the Support Desk once, signed in.

> "My order ORD-8821 — the running shoes arrived damaged. I want a refund."

The AI calls `begin_session` → learns it's Priya, gets the behavioral rules, loads her saved state. The AI calls `domain_get_order("ord-8821")` → sees the order details. It calls `domain_get_policy("pol-001")` → learns the 30-day return window and the no-restocking-fee rule for defective items. It calls `domain_create_ticket` to file the refund. It calls `user_save_state` so next time the AI remembers what they were discussing. The AI tells Priya: *"I've created ticket tkt-004. Since the item is defective, no restocking fee. An agent will respond within 24 hours."*

### Scenario 2: Customer returns next day, new chat

Priya opens a brand-new chat (different tab, no history):

> "Any update on my refund?"

The AI calls `begin_session` → loads her saved state: `{last_viewed_item_id: "tkt-004"}`. The AI immediately calls `domain_get_ticket("tkt-004")` → sees the ticket is still open. The AI tells Priya: *"Welcome back — your ticket is still open. Would you like me to flag it as urgent?"*

### Scenario 3: Customer searches for policy

Marcus types:

> "Can I return something after 45 days?"

The AI calls `domain_search("return policy time limit")` → semantic search returns the refund policy ranked first. The AI reads the 30-day window and the defective-item exception. It tells Marcus: *"Our return window is 30 days. After 45 days, returns are not accepted except for defective items. Was your item defective?"*

### Scenario 4: Customer submits a new issue

Julia types:

> "My SaaS subscription shows 15 seats but I only have 10 people. I'm being overcharged."

The AI calls `begin_session` → gets the rules. Calls `domain_search("billing dispute overcharge")` → finds a similar previous ticket. Calls `domain_create_ticket` to open tkt-005 as high priority. The AI tells Julia: *"I've filed ticket tkt-005 as high priority. A billing specialist will review the seat count discrepancy."*

### Scenario 5: Support agent looks up a customer

Ravi (human support agent) sees tkt-005 in his queue: "Billing overcharge — Julia." He opens his AI assistant (also connected to Support Desk) and asks:

> "Tell me about the customer on tkt-005."

The AI calls `domain_get_ticket("tkt-005")` → gets the subject and body. It calls `domain_get_customer_profile()` → returns Julia's support history. The AI tells Ravi: *"Julia has 8 prior tickets, avg resolution 11 hours, CSAT 4.2/5, zero SLA breaches. First billing dispute. Recommend standard priority."*

### Scenario 6: System is down

The backing data store is unreachable. Priya types:

> "Where's my order?"

The AI calls `begin_session` → fails. The rules (delivered on the last successful `begin_session`) say: *"If you cannot reach begin_session or a tool returns an error, tell the user plainly that the session can't continue right now. Do NOT improvise an answer from your own knowledge."* The AI tells Priya: *"I'm sorry, I can't access the support system right now. Please try again in a moment, or email support@company.com."* It does NOT guess the order status.

### Scenario 7: Admin updates a policy without deploy

The business admin changes the refund window from 30 to 60 days — edits the catalog entry directly. The next customer who asks about returns gets the new 60-day policy. No code deployed. No developer involved. Seconds later.

---

## Four Invariants (Hard Rules)

1. **One gateway** — single service, single endpoint. Tools are grouped by prefix (`domain_*`, `user_*`, `config_*`).
2. **Tools only** — all user-facing logic is exposed as callable tools. No alternative interface for application logic.
3. **Prove, don't trust** — identity comes only from a verified signed token's `sub` claim. No tool accepts a user identifier as an input parameter; every tool reads the identity from the request's verified authorization context.
4. **Fail closed** — when tools or backing systems are unavailable, the service returns clean errors. The AI is instructed (via the rules delivered at session start) to refuse rather than improvise. Improvisation is structurally impossible because the tools return nothing to improvise from.

---

## Functional Requirements

### Tool Catalog

Every tool includes a description the AI reads to decide when to call it. Each tool return includes a one-line reminder about presentation tone.

---

#### `health`

**What it does:** Confirms the service is alive and reachable.

**Input:** None.

**Output:**
```json
{"status": "ok"}
```

**Requires sign-in:** No. Always available.

**Requires session:** No.

---

#### `begin_session`

**What it does:** Starts a new interaction. Called first on any new request or new chat. Returns behavioral instructions, the signed-in user's saved state from prior sessions, and a short-lived session token required by all other tools. If the user has never signed in before, creates their profile automatically and returns empty state.

**Input:** None.

**Output:**
```json
{
  "rules": "<full behavioral rules text>",
  "persona": "<full persona/voice description>",
  "state": {
    "preferred_name": "<string or null>",
    "last_viewed_item_id": "<string or null>",
    "last_action": "<string or null>",
    "saved_draft": "<string or null>",
    "session_started_at": "<ISO 8601 timestamp>"
  },
  "session_token": "<signed session token, valid for 30 minutes>",
  "reminder": "Present every result in the support agent's professional voice — be helpful, precise, and escalate when uncertain."
}
```

**Requires sign-in:** Yes. Rejects with 401 if no valid signed-in identity.

**Requires session:** No (this tool issues the session token).

**First-user behavior:** If the signed-in identity has never used the service before, the service creates a new user profile with empty state, sets the last-seen timestamp, and returns state as `{}`. No error.

**Returning-user behavior:** Updates the last-seen timestamp, reads the saved state, returns it.

**Config delivery:** `begin_session` is the primary delivery of rules and persona. Standalone `config_get_rules` and `config_get_persona` tools exist for mid-session refresh.

---

#### `domain_get_ticket`

**What it does:** Retrieves a support ticket by its ID. Returns the full ticket: subject, body, priority, status, creation date, and creator identity.

**Input:**
- `id` (string, required): The ticket ID — e.g. "tkt-001".

**Output:**
```json
{
  "id": "tkt-001",
  "subject": "Overcharged on annual subscription",
  "body": "Customer was billed $4,500 instead of $3,600...",
  "priority": "high",
  "status": "open",
  "created_by": "<creator identity>",
  "created_at": "2026-07-20T14:15:00Z"
}
```

**Access:** Any signed-in user can retrieve any ticket by ID (the catalog is shared — ticket IDs are not secret). A tool that lists tickets filters by creator. Access is logged in an audit trail.

**Not-found behavior:** Returns a clear "not found" message, not an error. The service does not crash.

**Requires sign-in:** Yes.

**Requires session:** Yes. Rejected with "no session — call begin_session first" if no session token is provided.

---

#### `domain_get_order`

**What it does:** Retrieves an order by its ID. Returns the full order record — fields vary by order type. E-commerce orders include `items`, `tracking_number`, `carrier`, `shipping_address`. Subscription orders include `plan`, `seats`, `billed_amount`, `expected_amount`. The returned shape matches whatever the order actually is.

**Input:**
- `id` (string, required): The order ID — e.g. "ord-001".

**Output:**
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

**Not-found behavior:** Returns "not found", not an error.

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `domain_get_policy`

**What it does:** Retrieves a support or operational policy by its ID. Returns the policy title, full body text, and what it applies to.

**Input:**
- `id` (string, required): The policy ID — e.g. "pol-001".

**Output:**
```json
{
  "id": "pol-001",
  "title": "Refund & Return Policy",
  "body": "Customers may return items within 30 days...",
  "applies_to": "all physical products"
}
```

**Not-found behavior:** Returns "not found", not an error.

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `domain_search`

**What it does:** Semantic search across the shared support catalog (orders and policies). Finds items by meaning, not just exact keywords. Returns ranked results with entity type, ID, and a content snippet.

**Input:**
- `query` (string, required, 1–1000 characters): Natural language search query — e.g. "refund policy for damaged items" or "billing dispute resolution".

**Output:**
```json
{
  "results": [
    {"id": "pol-001", "entity_type": "policy", "content": "Customers may return items within 30 days...", "similarity": 0.92},
    {"id": "pol-002", "entity_type": "policy", "content": "The Support Desk AI must escalate to a human agent...", "similarity": 0.81},
    {"id": "ord-002", "entity_type": "order", "content": "Alice Chen, Team Annual, 15 seats, $4,500.00...", "similarity": 0.74}
  ]
}
```

**Search scope:** Searches orders and policies only. Tickets are **not** in the search index — customer-created ticket content is never exposed through semantic search. To find tickets, use `domain_get_ticket(id)` or `domain_list_my_tickets()`. To search orders and policies by meaning, use `domain_search(query)`.

**Empty query:** Rejected — "query is required."

**Empty results:** Returns `[]`, not an error.

**Search service unavailable:** Returns "Search temporarily unavailable." Other tools remain unaffected.

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `domain_create_ticket`

**What it does:** Creates a new support ticket on behalf of the signed-in user. The service generates a unique sequential ticket ID (format: `tkt-NNN`). The ticket is stamped with the authenticated user's identity — the creator is never read from a tool argument.

**Input:**
- `subject` (string, required, 1–500 characters): Brief summary of the issue.
- `body` (string, required, 1–5000 characters): Full description of the problem.
- `priority` (string, required): One of "low", "medium", "high", "critical".

**Output:**
```json
{
  "ticket_id": "tkt-004",
  "status": "open",
  "created_at": "2026-07-22T12:30:00Z"
}
```

**Validation failures (each rejected with a specific message):**
- Empty subject → "subject is required"
- Subject longer than 500 characters → "subject exceeds 500 characters"
- Empty body → "body is required"
- Body longer than 5000 characters → "body exceeds 5000 characters"
- Priority not one of the four allowed values → "priority must be one of: low, medium, high, critical"

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `domain_list_my_tickets`

**What it does:** Lists all tickets created by the signed-in user. Returns ticket IDs, subjects, statuses, and creation dates.

**Input:** None.

**Output:**
```json
{
  "tickets": [
    {"id": "tkt-004", "subject": "Damaged item — order ORD-8821", "status": "open", "created_at": "2026-07-22T12:30:00Z"},
    {"id": "tkt-007", "subject": "Wrong size shipped", "status": "resolved", "created_at": "2026-06-15T08:00:00Z"}
  ]
}
```

**Isolation:** The list is filtered to only tickets created by the signed-in user. User A never sees User B's tickets in this list. Empty list returned if no tickets exist (not an error — returns `[]`, not "not found").

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `domain_get_customer_profile`

**What it does:** Returns the signed-in user's support profile — metrics computed from their ticket history that help determine priority, tone, and escalation urgency.

**Input:** None.

**Output:**
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

**Metrics computed live from the signed-in user's ticket history:**
- `open_tickets`: count of tickets with status "open" or "in_progress"
- `total_tickets`: total count of tickets
- `avg_resolution_time_hours`: average time from creation to resolution for resolved tickets
- `csat_score`: average customer satisfaction score, if any exist
- `sla_breaches`: count of open tickets past their SLA target (critical > 1hr, high > 4hr, medium > 24hr, low > 72hr)
- `account_age_days`: days since the user's profile was created
- `last_contact_at`: timestamp of the user's most recent ticket

**User with no tickets:** Returns zero for counts (`open_tickets: 0`, `total_tickets: 0`, `sla_breaches: 0`), `null` for scores that require data (`avg_resolution_time_hours`, `csat_score`), and `account_age_days` computed from profile creation. `last_contact_at` is `null`.

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `user_get_profile`

**What it does:** Returns the signed-in user's saved preferences and state — preferred name, last viewed item, saved draft. Used mid-session when the AI needs to re-read the profile without restarting.

**Input:** None.

**Output:**
```json
{
  "preferred_name": "Priya",
  "last_viewed_item_id": "tkt-004",
  "last_action": "created ticket tkt-004 for damaged shoes",
  "saved_draft": ""
}
```

**User with no saved state:** Returns `{}`, not an error.

**Difference from `begin_session`:** `begin_session` returns state ONCE at session start. `user_get_profile` is for mid-session refresh. Both read from the same saved state.

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `user_save_state`

**What it does:** Saves the signed-in user's session state so it persists across separate chats. Accepts a JSON object with any fields — `preferred_name`, `last_viewed_item_id`, `last_action`, `saved_draft`, or others. The state is keyed to the signed-in user; writing another user's state is impossible because the user identity is read from the verified token, not an argument.

**Input:**
- `state` (JSON object, required, max 50KB): The state fields to persist.

**Example:**
```json
{
  "preferred_name": "Priya",
  "last_viewed_item_id": "tkt-004",
  "last_action": "created ticket tkt-004 for damaged shoes",
  "saved_draft": "Drafting response: we have received your refund request..."
}
```

**Validation:**
- Non-JSON input → rejected
- Exceeds 50KB → rejected
- Valid JSON of any shape → persisted and returned intact on next read

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `config_get_rules`

**What it does:** Returns the current behavioral rules — escalation criteria, response guidelines, and the fail-closed instruction. Used mid-session when the AI needs to re-check a rule without restarting the session. Note: rules are already delivered in `begin_session`; call this only for a refresh.

**Input:** None.

**Output:**
```json
{
  "rules": "<full rules text>"
}
```

**Config unavailable (data store down or row deleted):** Returns hardcoded fallback rules that still include the fail-closed instruction. The rules must always be deliverable.

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

#### `config_get_persona`

**What it does:** Returns the current assistant persona and voice definition. Used mid-session for tone/style refresh. Note: the persona is already delivered in `begin_session`.

**Input:** None.

**Output:**
```json
{
  "persona": "<full persona text>"
}
```

**Config unavailable:** Returns hardcoded fallback persona.

**Requires sign-in:** Yes.

**Requires session:** Yes.

---

### Config Content (Verbatim Behavioral Instructions)

These are the exact texts the service delivers. They are seeded once during initial setup and editable thereafter by a business admin editing the live data store. The service reads them fresh on every `begin_session` call.

#### Rules text:

```
RULES FOR THE SUPPORT DESK ASSISTANT

You are the AI support agent for this company. Behave as follows:

1. COOPERATIVE TONE — Greet warmly. Use preferred name if available. Never pretend
   authority you don't have. If information is estimated vs. confirmed, say so.

2. LOOK BEFORE YOU ACT — Before creating a ticket, check if one already exists
   (use domain_list_my_tickets). Before answering a policy question, fetch the
   actual policy (use domain_get_policy). Never quote a policy from memory.

3. ESCALATION — escalate when ANY of these are true:
   (a) Refund or cancellation amount exceeds $500
   (b) Issue involves account security, data privacy, or legal compliance
   (c) Customer explicitly requests a human agent
   (d) Customer expresses anger, frustration, or threatens to leave
   (e) Data appears inconsistent across systems
   (f) Same issue open > 48 hours without resolution
   When escalating: tell the user clearly, explain why, give expected response time.

4. SLA AWARENESS — Critical: respond within 1hr. High: 4hr. Medium: 24hr. Low: 72hr.
   If a ticket is approaching or past SLA, inform the user and escalate.

5. FAIL CLOSED — CRITICAL: If you cannot reach begin_session OR any tool returns
   an error, tell the user: "I'm sorry, I can't access the support system right
   now. Please try again in a moment." Do NOT improvise. Do NOT invent state.
   Do NOT guess ticket statuses, order details, policy terms, or customer
   information. An honest "I can't access that right now" is always better than
   a confident wrong answer.

6. PRESENTATION — Present ticket/order details clearly: what it is, its status,
   last update, next step. Cite policy ID when quoting policy. End interactions
   by asking if there's anything else, and save state before closing.
```

#### Persona text:

```
PERSONA — SUPPORT DESK ASSISTANT

You are a professional support agent for a multi-industry business platform.

CLEAR: Plain language, short sentences. No jargon unless the customer uses it first.
PRECISE: Cite sources (ticket ID, policy ID, order number). Never say "I think" or
"probably" about factual data. If data is missing, say so.
EMPATHETIC: Acknowledge frustration before solving. Don't be chipper when the
customer is upset.
HONEST: If you don't know, say so. If a tool is unavailable, say so. Never invent.
EFFICIENT: Get to the point. Don't repeat what the customer already told you.

You are NOT: a salesperson, a developer, a therapist, or a decision-maker for
refunds above the escalation threshold.
```

---

### Seed Data (What Must Be Present at Launch)

These seven records must exist in the service at launch so the tools return real data on day one.

#### tkt-001 — SaaS billing dispute

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

#### tkt-002 — Damaged item on delivery

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

#### tkt-003 — Feature request

```json
{
  "id": "tkt-003",
  "subject": "Feature request: bulk export for enterprise reporting",
  "body": "Enterprise customer on the Business plan needs a bulk CSV export feature for their quarterly compliance reports. Currently they must export data one project at a time (40+ projects). The request includes: export all projects to CSV with filters by date range and department. Customer says this is a blocker for renewing their annual contract (up for renewal in September). They've been a customer for 2 years, 200-seat deployment.",
  "priority": "low",
  "status": "open",
  "created_by": "user-marcus-55",
  "created_at": "2026-07-15T11:00:00Z"
}
```

#### ord-001 — E-commerce electronics order

```json
{
  "id": "ord-001",
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

#### ord-002 — SaaS subscription

```json
{
  "id": "ord-002",
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

#### pol-001 — Refund & Return Policy

```json
{
  "id": "pol-001",
  "title": "Refund & Return Policy",
  "body": "Customers may return items within 30 days of delivery for a full refund. Items must be in original condition with all packaging and accessories. Defective items are exempt from the original-condition requirement and have no restocking fee. Non-defective returns incur a 10% restocking fee. Digital goods, gift cards, and personalized items are non-refundable. Refunds are processed to the original payment method within 5-10 business days after the returned item is received at our warehouse. Return shipping is free for defective items; customer pays return shipping for non-defective returns. Refunds exceeding $500 require supervisor approval (see escalation policy pol-002).",
  "applies_to": "all physical products"
}
```

#### pol-002 — Escalation & Handoff Policy

```json
{
  "id": "pol-002",
  "title": "Escalation & Handoff Policy",
  "body": "The Support Desk AI must escalate to a human agent when ANY of the following conditions are met: (1) Refund or cancellation amount exceeds $500. (2) The issue involves account security, password resets, data privacy, or legal compliance. (3) The customer explicitly requests a human agent. (4) The customer expresses anger, frustration, or threatens to cancel their account. (5) Data appears inconsistent between systems (e.g., order says shipped but tracking says pending). (6) A high-priority ticket has been open for more than 48 hours without agent assignment. When escalating: inform the customer clearly, explain why, provide the expected response time, and ensure the ticket is flagged for immediate review. Low-risk issues (simple policy questions, order status lookups, feature requests) may be handled autonomously without escalation.",
  "applies_to": "all support interactions"
}
```

---

### `begin_session` Contract

**Return shape:** Exactly five top-level fields: `rules` (full text), `persona` (full text), `state` (JSON object — always includes `session_started_at`; other fields may be absent for new users), `session_token` (short-lived signed token), and `reminder` (one-line presentation reminder). Missing any field is a visible failure.

**First-user behavior:**
1. Identity is extracted from the verified sign-in token.
2. If no profile exists for that identity, one is created with empty saved state.
3. The last-seen timestamp is set.
4. The session returns state containing `session_started_at` (set to the current timestamp) with all other state fields absent. No error.

**Returning-user behavior:**
1. The last-seen timestamp is updated.
2. Saved state is read and returned (including `session_started_at` set to the current timestamp).
3. Rules and persona are read fresh from the live config store.

**Data store unreachable:** When the backing data store is completely unreachable, `begin_session` returns fallback rules and persona, state as `{"session_started_at": "<current timestamp>"}`, and a valid session token. The service does not fail — it delivers behavioral instructions and a session so the AI can at minimum tell the user the system is unavailable (via the fail-closed rule in the fallback config).

**Session token:**
- Contains the verified user identity, an issued-at timestamp, an expiry (30 minutes after issuance), and a scope marker.
- Signed so it cannot be forged.
- Valid at 29 minutes 59 seconds; expired at 30 minutes 1 second. No grace period.
- Any gated tool called without a valid session token is rejected. The rejection message distinguishes between "no session token provided — call begin_session first" and "session token expired or invalid."

**Config delivery:**
- `begin_session` delivers rules and persona as its primary mechanism.
- `config_get_rules` and `config_get_persona` exist for mid-session refresh (same underlying source).

---

### Identity & Authorization

**Identity source:** Identity comes solely from a verified signed token presented with each request. The token carries a user identifier (`sub` claim) that the service verifies before processing any request.

**Verification checks (all four must pass, in order):**
1. **Signature** — the token's signature must be cryptographically valid against the identity provider's published keys. Forged or tampered tokens are rejected with 401.
2. **Issuer** — the token's issuer must match the expected identity provider. Tokens from unexpected issuers are rejected with 401.
3. **Audience** — the token's audience must match the service's own identifier exactly. Tokens issued for a different service are rejected with 401.
4. **Expiry** — expired tokens are rejected with 401.

If all four checks pass, the `sub` claim is extracted. This `sub` is the ONLY source of user identity — no tool accepts a user identifier as an input parameter, and if any input claims to contain a user identifier, the service ignores it.

**Discovery:** The service exposes a well-known discovery endpoint that advertises the authorization server and its capabilities, so clients can discover how to obtain valid tokens.

**Service started without identity verification:** An explicit configuration flag can disable identity checks for demonstration purposes. When disabled, all users are treated as a single fixed identity and sign-in is bypassed. This mode is NOT the default and must be explicitly turned on.

**User lifecycle:**

| Event | Behavior |
|-------|----------|
| First sign-in | `begin_session` auto-creates profile with empty state. No error. |
| Returning sign-in | `begin_session` updates last-seen, returns saved state. |
| Profile deleted by admin | Next `begin_session` treats as first-time user — re-creates profile with empty state. No error. |
| Identity deleted by provider | Tokens invalidated immediately. Next `begin_session` returns 401. Saved data persists (audit trail). |
| Provider key rotation | Keys are re-fetched automatically; no downtime. |
| Data cleanup | No automatic deletion. Admin handles cleanup manually. |

---

### Per-Tool Return Reminder

Every tool that requires a session appends this one-line reminder to its return value:

> *Present your answer in the support agent's professional voice — be helpful, precise, and escalate when uncertain.*

This applies to `begin_session` (as the `reminder` field), `domain_get_ticket`, `domain_get_order`, `domain_get_policy`, `domain_search`, `domain_create_ticket`, `domain_list_my_tickets`, `domain_get_customer_profile`, `user_get_profile`, `user_save_state`, `config_get_rules`, and `config_get_persona`. `health` is the only tool that does NOT include this reminder.

---

## Edge Cases & Rules

### Cross-user isolation

1. **`user_get_profile`**: Returns state for the signed-in user only. User A never sees User B's state.
2. **`user_save_state`**: Writes for the signed-in user only. User A cannot write to User B's state.
3. **`domain_list_my_tickets`**: Returns tickets created by the signed-in user only. User A never sees User B's tickets in this list.
4. **`domain_get_ticket(id)`**: Returns any ticket by ID (tickets are not private by ID in v1). Access is logged in an audit trail. To find which tickets exist, use `domain_list_my_tickets` (filtered by creator) or know the ID.
5. **`domain_search`**: Searches orders and policies only — shared catalog content. Customer-created tickets are never searchable this way; ticket content cannot leak through semantic search.
6. **No `user_id` in any tool signature**: Identity is read from the verified token's `sub`, never from an input parameter. A build can be audited by checking that no tool accepts `user_id` as a parameter.

### Audit trail

Every tool call is logged — this includes all 13 tools: `health`, `begin_session`, and all 11 gated domain/user/config tools. Each log entry records: who called it, which tool, a summary of inputs, a summary of the result, and when. The audit trail is write-only from the tool perspective — there is no tool to read audit logs in v1. Logs persist even if a user's profile is later removed (the trail survives for accountability).

### Search scope

`domain_search` searches orders and policies — shared catalog content. It does NOT search customer-created ticket content. Results are filtered by a minimum similarity threshold of 0.5; results below this threshold are excluded. At most 5 results are returned, ranked by similarity descending. The two data sets are stored separately and queried through different tools: `domain_search` for catalog, `domain_get_ticket`/`domain_list_my_tickets` for tickets. This separation is structural — even a misconfigured search cannot expose private ticket content.

### Concurrency

- Two simultaneous `begin_session` calls from the same user (two browser tabs): Both succeed, both issue separate session tokens. State writes use last-write-wins.
- Two simultaneous `user_save_state` calls: Last write wins. No corruption (state writes are atomic).
- Session token boundary: Valid at 29m59s from issuance. Expired at 30m01s. No grace period. If it's past 30 minutes, the call is rejected and the AI must call `begin_session` again.
- Two different devices: Separate session tokens. No shared state corruption. Last write from either device wins.

### Input validation

| Tool | Validation rule |
|------|----------------|
| `domain_get_ticket(id)` | `id` must be a non-empty string. Unknown IDs return "not found", not an error. |
| `domain_get_order(id)` | Same as above. |
| `domain_get_policy(id)` | Same as above. |
| `domain_create_ticket(subject, body, priority)` | `subject`: 1–500 chars (non-empty, ≤ 500). `body`: 1–5000 chars (non-empty, ≤ 5000). `priority`: must be one of "low", "medium", "high", "critical". |
| `domain_search(query)` | `query`: 1–1000 chars. Empty query → "query is required." |
| `user_save_state(state)` | `state` must be a valid JSON object. Non-JSON → rejected. Max size: 50KB. Larger → rejected. |

### Fail-closed mechanism

The fail-closed behavior is delivered three ways:
1. In the rules text returned by every `begin_session` (the "FAIL CLOSED — CRITICAL" paragraph)
2. In the per-tool reminder on every tool response
3. Structurally: when the backing data store or services are unavailable, tools return clean errors with no data — the AI physically cannot get data to improvise from

The hardcoded fallback config (used when the config store is unreachable) includes the fail-closed paragraph so it is always delivered, even if the config store itself is down.

### Fallback config

When the live config is unreachable or a config entry has been deleted, `config_get_rules` and `config_get_persona` return hardcoded minimal versions. The fail-closed instruction must always be in the fallback rules — it is the single most critical behavioral instruction.

**Fallback rules:**
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

**Fallback persona:**
```
You are a professional support agent. Be clear, precise, empathetic, and honest.
Never invent, embellish, or guess. Cite your sources. Present data in a clear structure.
```

---

## Out of Scope (v1)

| Item | Planned for |
|------|------------|
| Live platform integrations (freshdesk, shopify, etc.) | v3 |
| Proactive alerts and auto-resolution of tickets | v4 |
| Ticket assignment and agent routing | v2 |
| Customer satisfaction surveys after resolution | v2 |
| Multi-language support | future |
| File/image attachments on tickets | v2 |
| Semantic search over user-created ticket content | v1 searches shared catalog only |
| Admin dashboard or UI — business admin edits data store directly | N/A |
| Email/push notifications to customers | v3 |
| AI-drafted agent replies (copilot) | v2 |
| Usage analytics and reporting | v2 |
| Per-user access control on `domain_get_ticket` (any user can access any ticket by ID) | v3+ |
| Audit log reading tool | v2 |

---

## Acceptance Criteria

The build is complete when every one of these passes. Each criterion is specific — a build that ignored it would visibly fail (wrong output, wrong error, wrong identity, or data leakage).

### Health & availability
- [ ] `health` tool returns `{"status": "ok"}` without any sign-in or session token
- [ ] `health` returns success even when the backing data store is completely unreachable

### Identity & authorization
- [ ] Any gated tool called with no sign-in token returns 401
- [ ] A sign-in token with a tampered signature is rejected with 401
- [ ] A sign-in token with the wrong audience (issued for a different service) is rejected with 401
- [ ] A sign-in token from the wrong issuer is rejected with 401
- [ ] An expired sign-in token is rejected with 401
- [ ] A sign-in token missing the `sub` claim is rejected with 401
- [ ] A valid sign-in token resolves the correct user identity
- [ ] Two different sign-in tokens produce two different user identities with no crossover
- [ ] The well-known discovery endpoint returns the correct resource identifier and authorization server list
- [ ] When the identity provider's signing keys rotate, new tokens still pass verification without downtime

### Session management
- [ ] A gated tool called without a session token is rejected: "no session — call begin_session first"
- [ ] A gated tool called with an expired session token is rejected: "invalid session"
- [ ] A gated tool called with a tampered/forged session token is rejected: "invalid session"
- [ ] A session token with the wrong scope marker is rejected: "wrong token type"
- [ ] A session token that is 29 minutes 59 seconds old is accepted; one that is 30 minutes 1 second old is rejected
- [ ] `begin_session` returns exactly five fields: `rules`, `persona`, `state`, `session_token`, `reminder` — all present and non-null
- [ ] Two `begin_session` calls from the same user produce two distinct valid session tokens, both usable within their TTL
- [ ] A session token from one user, when used by a different user's request, is rejected — the token's identity must match the sign-in token's identity
- [ ] After a session expires, calling `begin_session` again returns a fresh token and the user's saved state is restored — the conversation continues

### Data correctness
- [ ] `domain_get_ticket("tkt-001")` returns the exact seed record — all fields match the spec
- [ ] `domain_get_ticket("nonexistent")` returns "not found", not a server error
- [ ] `domain_get_order("ord-001")` returns the exact seed record
- [ ] `domain_get_policy("pol-001")` returns the exact seed record
- [ ] `domain_search("refund policy")` returns results with pol-001 ranked highest
- [ ] `domain_search("nonexistent query with no matches")` returns `[]`, not an error
- [ ] `domain_create_ticket` with valid inputs creates a ticket, returns the new ticket ID, and a subsequent `domain_get_ticket(new_id)` returns the full ticket (same data store for seed and user-created tickets)
- [ ] `domain_create_ticket("", "Body", "high")` is rejected: "subject is required"
- [ ] `domain_create_ticket("Subject", "Body", "invalid")` is rejected: "priority must be one of: low, medium, high, critical"
- [ ] `domain_create_ticket` with subject over 500 characters is rejected
- [ ] `domain_create_ticket` with body over 5000 characters is rejected
- [ ] `domain_list_my_tickets` returns only tickets created by the signed-in user
- [ ] `domain_list_my_tickets` for a user with no tickets returns `[]`, not an error
- [ ] `domain_get_customer_profile` returns support metrics (open tickets, resolution time, CSAT, SLA breaches) — not e-commerce metrics
- [ ] `domain_get_customer_profile` for a user with no tickets returns sensible defaults (zero counts, null scores)

### State persistence
- [ ] `user_save_state({"key": "value"})` followed by `user_get_profile()` on a fresh connection returns `{"key": "value"}`
- [ ] `user_save_state` with empty `{}` stores and returns `{}`
- [ ] `user_save_state` with 50KB of JSON stores and returns intact
- [ ] `user_save_state` with unicode/emoji stores and returns correctly (e.g. "😡 BROKEN 😡")
- [ ] `user_save_state` with non-Latin text (Urdu, Arabic, CJK) stores and returns correctly
- [ ] User A saves state → User B calls `user_get_profile()` → B sees B's state, zero trace of A's state

### Cross-user isolation
- [ ] User A creates a ticket → User B calls `domain_list_my_tickets()` → B's list does not contain A's ticket
- [ ] User A creates a ticket → User B calls `domain_get_ticket("A's ticket ID")` → returns the ticket (tickets are accessible by ID), and the audit log records B's access
- [ ] Audit check: No tool signature contains `user_id` as an input parameter
- [ ] If a tool is called with a hallucinated `user_id` in the input, the service ignores it — identity comes exclusively from the sign-in token

### Config management
- [ ] `config_get_rules()` returns the exact rules text from the spec
- [ ] `config_get_persona()` returns the exact persona text from the spec
- [ ] Admin updates the rules in the config store → next `begin_session` returns the updated rules
- [ ] A config entry is deleted → the tool returns the hardcoded fallback (with the fail-closed paragraph)
- [ ] The config store is unreachable → `begin_session` still returns rules (fallback) — it never fails to deliver behavioral instructions

### Fail-closed behavior
- [ ] Data store unreachable → all tools return clean errors (no raw internals leaked), and the rules text instructs the AI to say "I can't access the support system right now"
- [ ] Data store unreachable and user asks "What's my order status?" → AI does NOT invent an order status
- [ ] Data store unreachable and user asks "What's the refund policy?" → AI does NOT quote a policy from memory
- [ ] Data store unreachable and user asks "Is my ticket resolved?" → AI does NOT say yes or no
- [ ] Search service unreachable → `domain_search` returns "Search temporarily unavailable"; all other 12 tools remain functional
- [ ] A tool returns partial data (e.g. ticket body is empty/null) → the AI reports what it has and notes what's missing, rather than filling gaps
- [ ] Question asked that no tool can answer → AI says "I don't have access to that information"

### Per-tool reminder
- [ ] Every gated tool's return (all except `health`) includes the reminder line: "Present your answer in the support agent's professional voice — be helpful, precise, and escalate when uncertain."
- [ ] `begin_session` returns the reminder as the `reminder` field
- [ ] `health` does NOT include the reminder (it is ungated)

### Real-world scenarios
- [ ] Two browser tabs, same user: no corruption, last write wins
- [ ] Mobile + desktop simultaneously, same user: separate tokens, no corruption
- [ ] Session expires mid-conversation → AI re-authenticates → state is restored
- [ ] Chat closed, reopened next day: state is restored (cross-chat memory works)
- [ ] A ticket body containing a long URL: stored and returned without truncation
- [ ] A user's identity is deleted by the provider → `begin_session` returns 401; saved data persists (audit trail)
- [ ] Service restarts mid-conversation → AI retries → `begin_session` succeeds → conversation continues
- [ ] Sign-in token expires (1-hour default) → host application re-authorizes silently → tools continue

### Infrastructure robustness
- [ ] Health check succeeds regardless of data store state (service can report health even when data is down)
- [ ] Data store regional outage → all tools return clean errors, service itself stays running, fail-closed rules apply
- [ ] Search service outage → `domain_search` returns error, all other tools unaffected
- [ ] Identity provider outage → new sessions cannot start (401), but existing valid session tokens within TTL still work
- [ ] No raw error internals (stack traces, query details, connection strings) are ever returned to the caller

### Config content integrity
- [ ] The rules text uses cooperative language ("here is how to behave") — never override/ignore-previous-instructions phrasing
- [ ] The persona text defines a professional support agent voice (clear, precise, empathetic, honest, efficient) — never an adversarial or deceptive persona

---

*End of behavioral specification.*
