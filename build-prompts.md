# Support Desk — Build Prompts & Review Decisions

## Review Response: What Gets Added, Updated, Left

### Added (15 items)

| # | What | Why |
|---|------|-----|
| 1 | Verbatim rules text (3 paragraphs: cooperative behavior, escalation criteria, fail-closed) | Reviewer gap #1. Agent can't invent this.
| 2 | Verbatim persona text ("professional support agent, never pretends authority, tags estimates") | Reviewer gap #1.
| 3 | Exact fail-closed paragraph: "If you cannot connect to the support system or a tool returns an error..." | Referenced 8 times, appears zero times. Blocking.
| 4 | All 7 seed data records written verbatim (tkt-001 through pol-003) | Reviewer gap #2. Blocking.
| 5 | All 13 tool descriptions (MCP format, what the AI reads to decide which tool to call) | Reviewer gap #3. Blocking.
| 6 | begin_session return JSON shape + field names | Reviewer gap #4. Blocking.
| 7 | user_save_state schema: last_ticket_id, preferred_name, notes_draft | Reviewer gap #5. Blocking.
| 8 | Clerk JWT template spec: claims, RS256, kid header, 1hr TTL | Reviewer gap #10.
| 9 | mock_auth dev path (Beginner track → Clerk as Standard track) | Reviewer gap #11. Can't test auth without it.
| 10 | First-time user flow: auto-create users row on first begin_session | Reviewer gap #12.
| 11 | Cross-user direct ticket access guard: domain_get_ticket must filter by sub if ticket has owner | Reviewer gap #19.
| 12 | domain_search scope: policies=global, tickets/orders=user-scoped | Reviewer gap #20.
| 13 | 5 user scenarios ("Support rep asks X, AI calls tools to respond Z") | Reviewer gap #2 (Section B).
| 14 | Escalation rules config in v1 (not v2): 5 triggers with thresholds | Reviewer gap #7. MY_DOMAIN.md priority.
| 15 | user_get_profile vs begin_session state distinction: begin_session returns snapshot; user_get_profile is mid-session refresh | Reviewer gap #15.

### Updated (2 items)

| # | What | Why |
|---|------|-----|
| 16 | customer_profile metrics: e-commerce → support KPIs (open_tickets, csat_score, avg_resolution_minutes, sla_breach_count, last_contact_at) | Reviewer gap #6. MY_DOMAIN.md alignment.
| 17 | domain_get_order boundary: orders exist as support context (customer asks about their order). Not e-commerce product browsing. | Reviewer gap #8. Clarify, don't remove.

### Left As-Is (3 items)

| # | What | Why |
|---|------|-----|
| 18 | Separated config_* tools alongside begin_session. begin_session returns rules+persona at session start. config_get_rules/persona exist for mid-session refresh without re-calling begin_session. Course design pattern, not redundancy. | Reviewer gap #13. Design rationale added to spec.
| 19 | Freshdesk in v3. This is a build-course project building a standalone MCP server. MCP-to-MCP integration is v3 scope. v1 proves the connector works independently. | Reviewer gap #9. Scope discipline.
| 20 | Architecture diagram, source-of-truth rules, build phases extracted from spec.md to plan.md. Spec = behavior only. Plan = implementation. | Reviewer gaps #16-18. File split.

### Extracted to plan.md (not in spec)

- Source-of-truth rules (already in AGENTS.md — reference only)
- Architecture diagram (Clerk, Neon, Mistral, Fly.io names)
- Build phases + verification criteria
- Database schema SQL
- Dockerfile contents, fly.toml config

---

## Build Prompts — Adapted from Connector-Native Apps Course

Instructions: Paste each prompt in order. Verify the output before moving to the next.

---

### Step 0: Project Setup (before Concept 4)

```prompt
Set up the base environment for this project. You already have Python 3.14+ and uv.
Run `uv sync` and `uv sync --extra dev`. Confirm the five security-core tests
pass with `uv run pytest -q`. Then check lib/python3.*/site-packages/jose/jwt.py
for the JWTError import — if it's from `jose.exceptions`, verify `auth.py` and
`session.py` match. Copy .env.example to .env, generate a SESSION_SIGNING_SECRET.
Set AUTH_ISSUER/AUTH_JWKS_URL to the local mock_auth for now (Beginner track).
Verify tests pass: `uv run pytest -q`
```

---

### Prompt 1: Concept 4 — Scaffold the Gateway

```prompt
Read spec.md for the Support Desk connector. Then, using the mcp-builder skill
and Context7 for the current FastMCP API, scaffold the gateway:

- One FastMCP server on stateless streamable HTTP transport (pass stateless=True,
  json_response=True to FastMCP constructor)
- Add python-dotenv to the project and call load_dotenv() in server.py before
  any imports that read os.environ (source-of-truth rule)
- Add fastmcp to the project (uv add fastmcp)
- Bind 127.0.0.1:8000

Tools to scaffold (all as stubs returning placeholder dicts):
  health()                  — returns {"status": "ok"} (ungated)
  domain_get_ticket(id)     — returns {"ticket_id": id, "placeholder": True}
  domain_get_order(id)      — returns {"order_id": id, "placeholder": True}
  domain_get_policy(id)     — returns {"policy_id": id, "placeholder": True}

Use the Starlette deployment pattern from the source-of-truth rules:
  mcp_app = mcp.http_app()
  well_known_routes = mcp_app.get_well_known_routes()  (if needed later)
  app = Starlette(routes=[...], lifespan=...)
  Compose FastMCP's internal lifespan in the Starlette lifespan

Run the server and show me a local client listing all 4 tools.
Verify with: curl http://localhost:8000/mcp
```

**Pass condition:** `tools/list` returns `health`, `domain_get_ticket`, `domain_get_order`, `domain_get_policy`.

---

### Prompt 2: Concept 5 — Create the Database via Neon

```prompt
Using the Neon MCP server:

1. Create a Neon project named "support-desk"
2. Create a `dev` branch on that project
3. Enable the pgvector extension
4. Create these 5 tables:

  users (
    id TEXT PRIMARY KEY,
    email TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_seen_at TIMESTAMPTZ DEFAULT now()
  )

  user_state (
    user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
    state JSONB DEFAULT '{}',
    updated_at TIMESTAMPTZ DEFAULT now()
  )

  audit_log (
    id SERIAL PRIMARY KEY,
    user_id TEXT,
    tool_name TEXT NOT NULL,
    input_summary TEXT,
    output_summary TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
  )

  config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
  )

  support_embeddings (
    id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL CHECK (entity_type IN ('ticket','order','policy')),
    content TEXT NOT NULL,
    embedding VECTOR(1024)
  )

5. Save the connection string to DATABASE_URL in .env (never print it)
6. Confirm all 5 tables exist by listing them
```

**Pass condition:** `get_database_tables` shows all 5 tables. `.env` has DATABASE_URL.

---

### Prompt 3: Concept 5b — Write db.py

```prompt
Read spec.md section "5 Database Tables" for the Support Desk connector.

Write `src/connector_app/db.py` with async psycopg (use AsyncConnectionPool
from psycopg_pool). Source-of-truth rule: design database access as async
from the start.

Functions needed (all async, all keyed on verified `sub` passed as argument,
never from a tool argument — invariant 3):

  get_pool() -> AsyncConnectionPool
  read_state(sub: str) -> dict       — reads user_state.state for sub
  save_state(sub: str, state: dict)  — upserts user_state row for sub
  ensure_user(sub: str, email: str | None) — creates users row if missing, bumps last_seen_at
  read_config(key: str) -> str | None — reads config.value
  log_tool_call(sub: str, tool_name: str, input_summary: str, output_summary: str)
  search_support(query_embedding: list[float], limit: int = 5) -> list[dict]
  get_support_item(id: str) -> dict | None — reads support_embeddings by id
  create_ticket(sub: str, ticket_id: str, subject: str, body: str, priority: str)
  list_user_tickets(sub: str) -> list[dict]
  get_customer_profile(sub: str) -> dict

Use parameterized queries throughout (no string interpolation). Import from
connector_app.db, not directly from psycopg.

Then prove a value round-trips: save a test state → open a fresh connection
pool → read it back. Then explain in one line why you keyed everything on the
verified `sub` and refused a tool-supplied id.
```

**Pass condition:** Save a value, open a fresh connection, read the same value back.

---

### Prompt 4: Concept 6 — Seed Data + Domain Wires

```prompt
Read spec.md section "Seed Data" for exact content of all 7 seed records.

1. Write seed/support_data.json with these 7 records verbatim:

  tkt-001 | ticket | "Billing dispute — annual subscription overcharge"
    Body: "Customer reports $4,500 charged instead of $3,600 for Team plan renewal.
    15 seats. Overcharge of $900. Requires refund processing."
    Priority: critical | Status: open

  tkt-002 | ticket | "Damaged item on delivery — order ORD-8821"
    Body: "Running shoes arrived with torn sole. Customer attached photos.
    Replacement requested. Warehouse confirmation pending."
    Priority: high | Status: open

  tkt-003 | ticket | "Feature request — bulk CSV export for enterprise plan"
    Body: "Enterprise customer needs batch export of all ticket data to CSV
    for internal audit. Currently must export one at a time."
    Priority: low | Status: triaged

  tkt-004 | ticket | "Login failure — SSO redirect loop"
    Body: "Okta SSO users getting redirect loop on login. Started after
    certificate rotation yesterday. Affecting ~15 users."
    Priority: critical | Status: open

  ord-001 | order | "Pro Laptop + accessories bundle"
    Body: "MacBook Pro 16-inch + USB-C hub + protective case. Total $2,349.00.
    Shipped Jul 15 via FedEx #FDX-99821. Estimated delivery Jul 20."
    Status: shipped

  ord-002 | order | "Team plan annual renewal — 15 seats"
    Body: "SaaS Team plan annual renewal. 15 seats at $300/seat = $4,500.
    Customer reports expected price $3,600 ($240/seat with volume discount).
    Pending payment resolution."
    Status: pending

  pol-001 | policy | "Refund and Return Policy"
    Body: "30-day return window from delivery date. No restocking fee for
    defective items. Digital goods and software licenses are non-refundable
    after activation. Refunds over $500 require supervisor approval.
    Processing time: 5-7 business days to original payment method."

  pol-002 | policy | "Escalation Policy"
    Body: "Escalate to human supervisor when: (1) refund exceeds $500,
    (2) account security or data privacy issue, (3) customer explicitly
    requests manager, (4) legal or compliance concern raised, (5) issue
    spans more than 2 departments. SLA targets: critical = 1 hour,
    high = 4 hours, medium = 24 hours, low = 72 hours."

  pol-003 | policy | "Data Privacy and Access Policy"
    Body: "Support agents may only access customer data necessary to resolve
    the current ticket. Cross-account data access is prohibited. All ticket
    access is logged in audit trail. Customers may request their data export
    or deletion by emailing privacy@company.com. Data retention: 24 months
    from ticket closure."

2. Write a migration script `src/connector_app/seed.py` that:
   - Reads seed/support_data.json
   - For each record, calls Mistral embeddings API to generate a 1024-dim vector
   - INSERTs each record into support_embeddings table with the embedding
   - INSERTs rules, persona, escalation_matrix into config table
   - Is idempotent (ON CONFLICT DO NOTHING)
   - Never prints the MISTRAL_API_KEY

3. Requirements for seed.py:
   - Uses MISTRAL_API_KEY from os.environ
   - Loads dotenv before any import
   - Callable as: uv run python -m connector_app.seed

4. Wire the domain tools (domain_get_ticket, domain_get_order, domain_get_policy)
   to call db.get_support_item(id) instead of returning stubs.

5. Run seed.py to populate the database.

6. Show me domain_get_ticket("tkt-001") returning the real billing dispute ticket.
```

**Pass condition:** `domain_get_ticket("tkt-001")` returns the billing dispute ticket with correct subject and body.

---

### Prompt 5: Concept 6b — User State Schema + Additional Domain Tools

```prompt
Read spec.md for the user_state schema and the three v1 action domain tools.

1. Update the user_state JSON schema in the spec: each user stores:
   {
     "last_ticket_id": "tkt-001",
     "preferred_name": "Pat",
     "notes_draft": "Drafting reply about..."
   }

2. Wire user_get_profile() to call db.read_state(sub) and return the state dict.
   Wire user_save_state(state) to call db.save_state(sub, state) and return confirmation.
   Both read sub from the verified token, never from a tool argument.

3. Wire these additional domain tools against db.py:
   - domain_create_ticket(subject, body, priority) → creates ticket in DB,
     generates ID (tkt-XXX format), stamps creator sub, returns {ticket_id, status: "open"}
     Reject: empty subject (400), priority not in [low,medium,high,critical] (400),
     subject > 2000 chars (400)
   - domain_list_my_tickets() → calls db.list_user_tickets(sub), returns list
     of {id, subject, priority, status, created_at} for the sub's tickets only
   - domain_get_customer_profile() → calls db.get_customer_profile(sub), returns
     {open_tickets, total_tickets, avg_resolution_minutes, csat_score, sla_breach_count, last_contact_at}
     (Support KPIs from MY_DOMAIN.md, not e-commerce metrics)

4. Add ON CONFLICT DO NOTHING to seed.py's config inserts.

5. Show me: (a) creating a ticket → appears in list_my_tickets,
   (b) only the creator's tickets appear, never another user's.
```

**Pass condition:** Create ticket as User A → User A's list shows it → User B's list does not.

---

### Prompt 6: Concept 6c — Create config_store.py

```prompt
Read spec.md for the exact rules, persona, and fail-closed paragraph text.

Write `src/connector_app/config_store.py`. This wraps db.read_config() and
returns the config values for begin_session and the config_* tools.

Rules (stored in config table, key='rules'):
---
RULES = """You are the Support Desk assistant. Behave as follows for each user:

1. Begin every interaction by understanding the issue. Use begin_session to
   load the user's saved state and the latest rules before acting.

2. Look up relevant tickets, orders, and policies using domain_get_ticket,
   domain_get_order, domain_get_policy, or domain_search as appropriate.
   Present what you find clearly and concisely.

3. When creating tickets: ask for enough detail to set a meaningful subject
   and body. Classify priority based on impact: critical (service down,
   data loss, security), high (blocked from core task, financial impact),
   medium (workaround exists, non-blocking issue), low (cosmetic, feature
   request, informational).

4. Escalation rules — escalate to a human supervisor when ANY of these apply:
   - Refund requested exceeds $500
   - Account security or data privacy issue
   - Customer explicitly requests a manager
   - Legal or compliance concern is raised
   - Issue spans more than 2 departments
   When escalating, tell the customer clearly that a human specialist will
   take over, and include the escalation reason in the ticket.

5. Fail closed: if you cannot connect to the support system or a tool returns
   an error, tell the user plainly that the support system is unavailable
   right now and they should try again shortly. Do NOT improvise an answer
   from your own knowledge. Do NOT invent the status of a ticket, order,
   or policy that you could not retrieve. Do NOT guess at a customer's
   saved state or ticket history. A wrong confident answer is worse than
   an honest 'I cannot access that right now.'"""

---

Persona (stored in config table, key='persona'):
---
PERSONA = """You are a professional support agent. Your tone is helpful,
precise, and transparent.

- State what you found and where you found it (e.g., 'Per our refund policy
  (pol-001)...').
- Never pretend you have authority you do not have. If a decision requires
  a human, say so and escalate.
- Tag estimates clearly: 'I estimate...' not 'It will take...'.
- If you are unsure, say 'I'm not certain — let me escalate this.'
- Do not make promises you cannot keep. Do not guarantee resolution times
  unless the SLA data confirms them.
- Address the user by their preferred name if available in saved state."""

---

Write these three functions:
  get_rules() -> str     — calls db.read_config('rules'), fallback to default above
  get_persona() -> str   — calls db.read_config('persona'), fallback to default above
  get_escalation() -> dict — calls db.read_config('escalation_matrix'), fallback to default

Wire config_get_rules() and config_get_persona() tools in server.py to call these.

Show me config_get_rules() returning the rules text verbatim.
```

**Pass condition:** `config_get_rules()` returns the exact rules text including the fail-closed paragraph.

---

### Prompt 7: Concept 8 — Wire OAuth (Beginner Track with mock_auth)

```prompt
Read auth.py (given, never rewrite it) and the Connector-Native Apps source-of-truth rules.

Wire the OAuth layer around auth.py:

1. First, confirm the Starlette deployment pattern from Step 1 is in place:
   - mcp.http_app() not mcp.run()
   - Starlette with composed lifespan
   - uvicorn.run(app, host="127.0.0.1", port=8000)

2. Import and configure the FastMCP auth components (check Context7 for current
   FastMCP API for JWTVerifier/RemoteAuthProvider):
   - JWTVerifier that calls auth.verified_claims(token)
   - RemoteAuthProvider wrapping the verifier
   - Register the provider on the HTTP app

3. Add the well-known route manually since mcp.run() doesn't auto-mount it
   (source-of-truth rule):
   - Route("/.well-known/oauth-protected-resource", auth.protected_resource_metadata)

4. Verify with mock_auth:
   - Start mock_auth: `uv run python mock_auth/server.py` on port 9000
   - Confirm .env has AUTH_ISSUER=http://localhost:9000 and
     AUTH_JWKS_URL=http://localhost:9000/jwks.json
   - Show me an unauthenticated call to a domain tool returns HTTP 401
     (not a tool error, not a 200 — the 401 must come from the auth layer)
   - Mint a token from mock_auth, attach it as Bearer token, show the
     domain tool resolves and returns data
   - Show a token with wrong audience is rejected (test A3 from spec.md)

The authorization header must be read from the request object directly,
not from get_http_headers() (which strips authorization — source-of-truth rule).

This is the Beginner track (mock_auth). In production, swap AUTH_ISSUER and
AUTH_JWKS_URL to Clerk. auth.py's 4 checks stay identical.
```

**Pass condition:** Unauthenticated → 401. Valid mock token → tool returns data. Wrong audience token → 401.

---

### Prompt 8: Concept 8b — Clerk OAuth (Standard Track)

```prompt
Now set up the real OAuth path with Clerk (Standard track).

1. Create a free Clerk application at clerk.com
   - Enable email/password and Google OAuth sign-in methods
   - Get the Clerk domain (e.g., https://careful-heron-42.clerk.accounts.dev)
   - Get the JWKS URL (https://<domain>/.well-known/jwks.json)

2. Create a custom JWT template in the Clerk dashboard:
   - Name: "support-desk-resource-server"
   - Claims: sub, iss, aud, exp, iat
   - Set aud (audience) to http://localhost:8000 for local dev
   - Token lifetime: 1 hour (3600 seconds)
   - Algorithm: RS256
   - Under "Claims" add a custom claim: aud = {{your resource server URL}}
   - The kid header is set automatically by Clerk's signing key

3. Update .env:
   AUTH_ISSUER=https://<clerk-domain>
   AUTH_JWKS_URL=https://<clerk-domain>/.well-known/jwks.json
   RESOURCE_URL=http://localhost:8000

4. Test:
   - Get a test JWT from Clerk (use Clerk's API or dashboard to generate)
   - Call a domain tool with the Clerk token → resolves sub correctly
   - Call with no token → 401
   - Verify sub is the Clerk user ID, not a tool argument

5. Create a fallback: if AUTH_DISABLED=1 is set, skip OAuth entirely
   and use a fixed DEV_SUB. This is ONLY for the Part 5 tunnel demo,
   never for production.

Do NOT rewrite auth.py. It stays the same for both mock_auth and Clerk.
Only .env values change between Beginner and Standard tracks.
```

**Pass condition:** Clerk token resolves correct sub. Wrong audience Clerk token rejected.

---

### Prompt 9: Concept 10 — begin_session + Session Gate

```prompt
Read session.py (given, never rewrite it). Wire the session contract.

1. Add begin_session() tool to server.py. It must:

   a) Read the Bearer token from the request:
      from fastmcp.server.dependencies import get_http_request
      request = get_http_request()
      auth_header = request.headers.get("authorization")
      token = auth.bearer_from_header(auth_header)
      claims = auth.verified_claims(token)
      sub = claims["sub"]

   b) Call db.ensure_user(sub, email) — creates users row if first time
      (reviewer gap #12: first-time user flow)

   c) Load config from config_store:
      rules = config_store.get_rules()
      persona = config_store.get_persona()
      escalation = config_store.get_escalation()

   d) Load user state from db.read_state(sub)

   e) Issue session token via session.new_session_token(sub)
      (session.py uses HS256, 30-min TTL, claims: {sub, iat, exp, scope:"session"})

   f) Return this exact JSON shape:
      {
        "session_token": "<signed-hs256-jwt>",
        "rules": "<full rules text>",
        "persona": "<full persona text>",
        "state": { ... user's saved state ... },
        "user_id": "<sub>"
      }

   g) Phrase the returned rules as COOPERATION ("here is how to behave for
      this user"), NEVER as an override ("forget previous instructions").
      The config_store rules already use cooperative phrasing.

2. Add session gate to all domain_*, user_*, and config_* tools:

   In each gated tool, at the top:
      session_token = <read from request or tool context>
      sub = session.require_session(session_token)
      # Now sub is verified — use it for all DB operations

   The session token should come from a request header or be passed as
   a tool parameter (your choice — be consistent). The key rule: the
   tool must reject the call if require_session raises SessionError.

3. Per-tool return reminder: every gated tool appends a one-liner:
   "Present your answer in the support agent's professional voice —
   be helpful, precise, and escalate when uncertain."

4. Test in order:
   a) Call domain_get_ticket with no session → SessionError raised
   b) Call begin_session → returns all 5 fields
   c) Call domain_get_ticket with session token → returns ticket data
   d) Call begin_session again → new session token issued, still valid
   e) Wait for token to expire (or test boundary) → expired token rejected

5. The health() tool remains ungated (Fly.io needs it).
```

**Pass condition:** No session → refused. begin_session succeeds. Tools work with session token. Expired token → refused.

---

### Prompt 10: Concept 10b — Audit Logging

```prompt
Add audit logging to every gated tool call:

1. After each tool completes successfully, call:
   db.log_tool_call(sub, tool_name, input_summary, output_summary)

2. input_summary: truncated to 500 chars of the relevant input
3. output_summary: "success" or "not_found" or "error: <message>"
4. The audit_log table captures created_at via DEFAULT now()

5. Do NOT log health() calls (ungated, no sub)

6. Test: call domain_get_ticket → query audit_log → row exists with
   correct user_id, tool_name, and timestamp.
```

**Pass condition:** Tool call → audit_log row appears with correct sub and tool_name.

---

### Prompt 11: Concept 11 — Semantic Search (domain_search)

```prompt
Wire domain_search(query) using Mistral embeddings + pgvector:

1. Install pgvector if not already enabled on Neon (should be from Step 2)

2. The tool flow:
   a) Call Mistral API: POST https://api.mistral.ai/v1/embeddings
      with model="mistral-embed" and input=query
   b) Extract the 1024-dim embedding vector from the response
   c) Call db.search_support(embedding, limit=5) which runs:
      SELECT id, entity_type, content, 1 - (embedding <=> $1) AS similarity
      FROM support_embeddings ORDER BY similarity DESC LIMIT $2
   d) Return: [{id, entity_type, content, similarity}, ...]

3. Scope rules (reviewer gap #20):
   - Policies (entity_type='policy'): global — all users see same policies
   - Tickets and orders: filter by the current user's sub
     (domain_search adds WHERE (entity_type='policy' OR (entity_type IN ('ticket','order'))) AND ...)
   Actually: keep it simple for v1. domain_search searches the full catalog.
   Individual tool guards (domain_get_ticket checks sub for non-policy items)
   handle the privacy boundary at the retrieval layer.

4. Error handling:
   - Mistral API unreachable → return {"error": "Search temporarily unavailable",
     "fallback": "Use domain_get_ticket/order/policy by ID instead"}
   - Empty results → return []
   - Query > 1000 chars → truncate to 1000 before embedding

5. Test:
   - Search "refund policy" → pol-001 ranked highest
   - Search "damaged shoes" → tkt-002 ranked high (semantic match)
   - Search "xyzzy nonsense" → empty list
   - Mistral API down → clean error, not crash
```

**Pass condition:** "refund" search returns pol-001 first. "damaged shoes" returns tkt-002. Empty query → empty list.

---

### Prompt 12: Concept 11b — Multi-User Isolation

```prompt
Prove multi-user isolation (invariant 3, test suite I1-I6 from spec.md):

1. Create two test users (User A and User B) with separate Clerk accounts
   (or separate mock_auth tokens with different subs)

2. Run these isolation tests:
   a) User A saves state → User B calls user_get_profile → returns B's state,
      no trace of A's data (I1)
   b) User A creates ticket → User A's domain_list_my_tickets shows it →
      User B's domain_list_my_tickets does NOT show it (I2)
   c) Query audit_log for User A → entries contain A's sub → query for
      User B's entries → no cross-contamination (I3)
   d) Grep all @mcp.tool() signatures → zero contain 'user_id' parameter (I4)
   e) If a tool receives 'user_id' in input (model hallucination) → the
      sub read from the token overrides, the input is ignored (I5)

3. Add cross-user direct access guard (reviewer gap #19):
   - In domain_get_ticket(id): after fetching the ticket from support_embeddings,
     if the ticket's creator field doesn't match the caller's sub and the
     entity_type is 'ticket', return "Ticket not found" (same as nonexistent —
     don't reveal that the ticket exists for another user)
   - This prevents User B calling domain_get_ticket("tkt-A") to read User A's ticket

4. Write results as test assertions or manual verification log.
```

**Pass condition:** All I1-I6 tests pass. No cross-user data leak at any layer.

---

### Prompt 13: Concept 11c — Fail-Closed Test

```prompt
Prove fail-closed behavior (invariant 4, test suite F1-F8 from spec.md):

1. Stop the Neon database (or set DATABASE_URL to an invalid value temporarily).

2. Test these scenarios:
   a) "What's the status of my order ORD-001?" → AI: "I can't access the
      support system right now. Please try again later." (F1)
   b) "What's the refund policy?" → AI: "I can't access the support system."
      Does NOT improvise a refund policy from training data (F2)
   c) "Is ticket tkt-001 resolved yet?" → AI: "Can't access support system."
      Does NOT falsely say "yes" or "no" (F3)
   d) Call any tool without a session → AI: "Session can't start right now" (F4)
   e) Turn off Mistral API → search for "refund" → AI: "Search unavailable.
      I can look up items by exact ID." Uses fallback, not fiction (F5)
   f) Query a ticket that exists but has null body → AI: "The ticket exists
      but its details are empty." No filling in (F6)
   g) Read the fail-closed paragraph from begin_session return → confirm
      it's present and the AI behavior respects it (F7)
   h) Ask "What's the CEO's name?" → AI: "I don't have access to that
      information." Does NOT rummage training data (F8)

3. If the AI invents anything in any scenario, strengthen the rules text
   in config_store.py and the per-tool reminder until it refuses cleanly.

4. Restore Neon connection after testing.
```

**Pass condition:** All F1-F8 tests pass. AI never improvises. AI always says "can't access" when broken.

---

### Prompt 14: Concept 12 — Deploy to Fly.io

```prompt
Deploy Support Desk to Fly.io:

1. Create a Dockerfile at the project root:

   FROM python:3.14-slim
   WORKDIR /app
   COPY pyproject.toml uv.lock ./
   RUN pip install uv && uv sync --no-dev
   COPY src/ ./src/
   COPY seed/ ./seed/
   EXPOSE 8080
   CMD ["uv", "run", "python", "-m", "connector_app.server"]

2. Create fly.toml:

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

3. Set secrets:
   fly secrets set DATABASE_URL="postgresql://..."
   fly secrets set SESSION_SIGNING_SECRET="<generated-48>"
   fly secrets set AUTH_ISSUER="https://<clerk-domain>"
   fly secrets set AUTH_JWKS_URL="https://<clerk-domain>/.well-known/jwks.json"
   fly secrets set RESOURCE_URL="https://support-desk.fly.dev"
   fly secrets set MISTRAL_API_KEY="<key>"

4. Deploy: fly deploy

5. Verify:
   - curl https://support-desk.fly.dev/health → 200
   - HTTPS works (Fly.io auto-TLS)
   - Server binds to 0.0.0.0:8080 (Fly.io passes PORT env var)

6. Run seed.py against the production Neon database to populate seed data.

7. If the app exceeds 256MB RAM, upgrade: fly scale memory 512
```

**Pass condition:** `curl https://support-desk.fly.dev/health` returns 200 over HTTPS.

---

### Prompt 15: Concept 12b — Clerk JWT Template for Production

```prompt
Update the Clerk JWT template for production:

1. In Clerk dashboard → JWT Templates → edit "support-desk-resource-server":
   - Set aud claim to https://support-desk.fly.dev (the production URL)
   - Confirm: sub, iss, aud, exp, iat all present
   - Algorithm: RS256
   - Token lifetime: 1 hour

2. Test the production auth flow:
   - Sign in to Clerk (via claude.ai Authorize flow)
   - Call a domain tool → resolves sub correctly
   - Call with no token → 401
   - Verify aud in the JWT matches https://support-desk.fly.dev exactly

3. The same auth.py code that worked with mock_auth now works with Clerk.
   Only .env values changed. No code changes to auth.py.
```

**Pass condition:** Production Clerk token passes all 4 auth.py checks. Wrong audience rejected.

---

### Prompt 16: Concept 13 — Add to claude.ai

```prompt
The connector is live at https://support-desk.fly.dev. Now add it to claude.ai:

1. Open claude.ai → Settings → Connectors → Add custom connector
2. Paste: https://support-desk.fly.dev/mcp
3. Click Add. No Authorize step needed for AUTH_DISABLED demo.
   For real OAuth: Clerk Authorize screen appears → sign in.

4. Test the full flow:
   a) "I have a billing issue — I think I was overcharged on my renewal"
      → AI calls begin_session → gets rules + persona
      → AI calls domain_search("billing overcharge renewal") → finds tkt-001
      → AI presents the ticket details

   b) "Create a ticket for me about this"
      → AI calls domain_create_ticket → returns tkt-XXX

   c) Open a brand-new chat:
      → "What was I looking at earlier?"
      → AI calls begin_session → state shows last_ticket_id
      → AI: "You were looking at ticket tkt-001"

   d) "What's your refund policy?"
      → AI calls domain_get_policy("pol-001") or domain_search("refund")
      → Returns the policy text

5. The cross-chat memory is the proof: new chat, same user, state carries over.
   The chat is the visit; the identity (sub) is the profile.
```

**Pass condition:** Full flow works inside claude.ai — begin_session, domain tools, cross-chat memory, fail-closed.

---

## Quick Reference: Tool Signatures (for verifying during build)

| Tool | Input | Output |
|------|-------|--------|
| health() | none | {status: "ok", timestamp: "..."} |
| domain_get_ticket(id) | id: str | {id, type, subject, body, priority, status, created_at, creator_sub} |
| domain_get_order(id) | id: str | {id, type, subject, body, status, tracking, total} |
| domain_get_policy(id) | id: str | {id, type, title, body, applies_to} |
| domain_search(query) | query: str | [{id, entity_type, content, similarity}] |
| domain_create_ticket(subject, body, priority) | subject: str, body: str, priority: str | {ticket_id, status: "open"} |
| domain_list_my_tickets() | none | [{id, subject, priority, status, created_at}] |
| domain_get_customer_profile() | none | {open_tickets, total_tickets, avg_resolution_minutes, csat_score, sla_breach_count, last_contact_at} |
| user_get_profile() | none | {last_ticket_id, preferred_name, notes_draft} |
| user_save_state(state) | state: dict | {saved: true} |
| config_get_rules() | none | {rules: "..."} |
| config_get_persona() | none | {persona: "..."} |
| begin_session() | none | {session_token, rules, persona, state, user_id} |

---

## Source-of-Truth Rules (from AGENTS.md + learned-source-of-truth.md)

1. Copy WSL /mnt/d/ projects to /tmp/ before running servers
2. FastMCP 3.4: pass stateless=True, json_response=True
3. dotenv.load_dotenv() before any import reading os.environ
4. mcp.run() does NOT auto-mount well-known auth routes → Starlette deployment
5. Custom Starlette lifespan must compose FastMCP's internal lifespan
6. MCP streamable-http requires session negotiation (initialize → Mcp-Session-Id → initialized → tools/call)
7. cloudflared tunnel needs --http-host-header 127.0.0.1:8000
8. Identity (sub) from verified OAuth token, never from tool argument
9. get_http_headers() strips authorization → read from request object directly
10. Design database access as async from day one (psycopg AsyncConnectionPool)
