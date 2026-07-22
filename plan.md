# Support Desk — Technical Plan

## Stack

| Component | Choice | Trade-off |
|-----------|--------|-----------|
| **MCP framework** | FastMCP 3.x (`uv add fastmcp`) | Required by course. API changes fast (2→3 was breaking) but Context7 keeps us current. |
| **Transport** | Streamable HTTP, stateless + JSON responses | Stateless avoids session-manager complexity; JSON responses required for MCP clients. Cost: no server-side session pooling. |
| **Auth wiring** | Custom `TokenVerifier` subclass wrapping the given `auth.py`, passed to `RemoteAuthProvider` | Must use `auth.py` (given, immutable). FastMCP's built-in `JWTVerifier` duplicates it — the subclass bridges them. Cost: ~30 lines of glue. |
| **Web server** | Starlette + uvicorn, wrapping FastMCP's `http_app()` | Source-of-truth says `mcp.run()` doesn't auto-mount well-known routes. Starlette deployment pattern (`Mount` + `get_well_known_routes()` + lifespan composition) fixes that. Cost: more boilerplate than plain `mcp.run()`. |
| **Database driver** | `psycopg[binary,pool]` with `AsyncConnectionPool` | Source-of-truth rule: async from day one. Cost: every DB call is `await`, tool functions must be `async`. |
| **Vector search** | pgvector in Neon + Mistral embedding API (`mistral-embed`) | Spec requires 1024-dim semantic search. Mistral's free tier covers dev. Cost: external API dependency; returns "Search temporarily unavailable" on outage (per spec). |
| **Identity read** | `get_access_token()` (FastMCP dependency injection) inside tools | Reads the verified `sub` from the token FastMCP already validated. Never reads from a tool argument. Cost: tools must be `async` for DI. |
| **Config loading** | `python-dotenv` (already in transitive deps via mock-auth) | Source-of-truth rule: `load_dotenv()` must run before any import that reads `os.environ`. |

---

## File Structure (new files only)

`auth.py`, `session.py`, `__init__.py` are given and untouched.

```
src/connector_app/
├── __init__.py            # given
├── auth.py                # given — OAuth 4 checks
├── session.py             # given — session token gate
├── server.py              # NEW — FastMCP app, Starlette wrapper, all 13 tools
├── db.py                  # NEW — async Neon access (pool, queries, state fallback)
├── config_store.py        # NEW — reads config from DB, falls back to hardcoded text
├── seed_data.py           # NEW — 7 seed records, embedding-compute helper
└── schema.sql             # NEW — DDL for 6 tables + pgvector extension + ticket_id_seq
```

Every tool lives in `server.py`. AGENTS.md says "Keep server.py to one FastMCP app" — tools are part of the same app. `db.py` and `config_store.py` are factored out because the spec explicitly names them.

---

## Key Technical Decisions

### Decision 1: Auth wiring — Custom `TokenVerifier` wrapping `auth.py`

**Why not use FastMCP's `JWTVerifier` directly?** Because `auth.py` is given, complete, and the human reads it line-by-line. We must wire through it, not replace it.

**How:** Create a `class CustomTokenVerifier(TokenVerifier)` whose `verify_token()` calls `auth.verified_claims(token_str)`. On success, return an `AccessToken` with `claims` dict. On `AuthError`, raise the expected FastMCP auth exception (which triggers 401). Then pass this verifier to `RemoteAuthProvider` along with the issuer URL and `RESOURCE_URL` as `base_url`.

`RemoteAuthProvider` handles the well-known discovery route (`/.well-known/oauth-protected-resource`) and the 401 → client re-auth flow. We don't manually build that.

**Trade-off:** Couples to FastMCP's internal `TokenVerifier` API, which could change across versions. But the alternative (manual Starlette middleware) is more code and doesn't integrate with `get_access_token()` — tools couldn't read the verified `sub` without custom plumbing.

### Decision 2: `AUTH_DISABLED` — conditional FastMCP construction

**Two auth modes:**

**Development with mock_auth:** The base project includes `mock_auth/server.py`. For local auth testing before Clerk is set up, start it alongside the server (`uv run uvicorn mock_auth.server:app --port 9000`) and point `AUTH_ISSUER` and `AUTH_JWKS_URL` at it. The same `auth.py` code path runs unchanged — no difference in verification logic. This is used for the auth test suite (A1-A12).

**Demo mode (`AUTH_DISABLED=1`):**
- No `RemoteAuthProvider` is set on FastMCP → no 401, no well-known, no token validation.
- `get_access_token()` returns `None` inside tools.
- A helper `_get_sub()` falls back to `DEV_SUB` from env.
- `begin_session` skips `auth.verified_claims` and uses `DEV_SUB`.

**Production mode (`AUTH_DISABLED=0`, default):**
- Full auth wiring is active. 401 on missing/invalid token.
- `get_access_token()` returns the verified token; `_get_sub()` reads `sub` from claims.

**Trade-off:** Two code paths in one server. But AGENTS.md says this is a course demo, not production, and `AUTH_DISABLED=1` is explicitly the Part 5 live-demo path. mock_auth is the local testing path — no account required. Transition to Clerk: swap 3 env vars.

### Decision 3: Async database from the start

`db.py` exports an async function `get_pool()` that returns a lazily-initialized `AsyncConnectionPool`. Every tool is `async def` and uses `async with pool.connection()`. No sync fallback.

**Trade-off:** More verbose per-tool (async/await). But source-of-truth says rewriting sync→async doubles the work, and FastMCP tools work fine as async. psycopg `AsyncConnectionPool` is mature.

### Decision 4: Config store — DB first, hardcoded fallback

`config_store.py` exports two async functions:
- `get_rules()` — reads `config` key `'rules'` from DB. On any error, returns the hardcoded fallback text (which includes the fail-closed paragraph).
- `get_persona()` — same pattern for key `'persona'`.

Both `begin_session` and the standalone `config_get_*` tools call these same functions. One source of truth.

**State fallback (db.py):** `db.get_state(sub)` queries `user_state` for the given `sub`. On DB error (connection refused, timeout), catches the exception and returns `{"session_started_at": "<current ISO 8601 timestamp>"}` — no crash, no error propagated. This ensures `begin_session` always returns a state object with at minimum `session_started_at`, even when the data store is down.

**Trade-off:** Hardcoded strings in Python (the fallback texts) duplicate the spec. If the spec's rules text changes, the code must change too. But the spec says the fallback rules MUST be delivered if DB is down — it's structurally required.

### Decision 5: Semantic search — pgvector + Mistral API

`domain_search(query)`:
1. Calls Mistral embeddings API (`mistral-embed`, 1024-dim) to embed the query string.
2. Runs `SELECT ... ORDER BY embedding <=> $1::vector LIMIT 5` against the `support_embeddings` table, filtering results where cosine similarity >= 0.5.
3. Returns at most 5 ranked results above the threshold.

Seed data embeddings are pre-computed during seeding (one-time startup cost). The Mistral API key goes in `.env`.

**Trade-off:** External API dependency for every search. But the spec says Mistral 1024-dim, and pgvector in Neon provides the cosine distance operator (`<=>`). On API outage, returns "Search temporarily unavailable" — the spec requires other tools remain functional.

### Decision 6: Session token gating — `require_session` with identity matching

Every gated tool accepts a `session_token: str` parameter and a `sub: str` (the verified identity from the OAuth token). On each call, the tool calls `session.require_session(session_token, expected_sub=sub)` to validate. This checks: token present, not expired, signature valid, scope = "session", AND the session token's `sub` claim matches the passed `expected_sub`. If any check fails, the tool returns the spec-required error message ("no session — call begin_session first", "invalid session", or "wrong token type").

This means a session token stolen by a different user is rejected — their sign-in sub won't match the token's sub. The `sub` is embedded in the session token at mint time (`new_session_token(sub)`) and verified at use time.

The AI receives the session token from `begin_session` and passes it on subsequent calls. This is explicit, auditable, and works with stateless transport (no server-side session store needed).

**Trade-off:** Every tool has a `session_token` parameter that the AI must pass. This is visible in the tool signature — the AI learns to pass it. The identity check adds a parameter (`sub`) that tools must thread through, but this is the spec-required behavior.

### Decision 7: Starlette deployment for well-known routes

Per source-of-truth rule #5:
```python
mcp_app = mcp.http_app(stateless_http=True)
well_known_routes = mcp_app.get_well_known_routes()  # from RemoteAuthProvider
app = Starlette(
    routes=[Mount("/", app=mcp_app)] + well_known_routes,
    lifespan=mcp_app.lifespan,  # compose FastMCP's internal lifespan
)
uvicorn.run(app, host="127.0.0.1", port=8000)
```

**Trade-off:** More lines than `mcp.run()`. But `mcp.run()` doesn't mount the well-known discovery route, so OAuth clients can't discover the authorization server. The Starlette pattern is documented as the canonical way.

### Decision 8: Audit logging — `@audit_log` decorator

Every tool (all 13) is wrapped with an `@audit_log(tool_name)` decorator. After the tool executes, the decorator writes a row to the `audit_log` table: `user_id` (the verified `sub`), `tool_name`, `input_summary` (first 200 chars of serialized inputs), `output_summary` (first 200 chars of serialized output or error message), and `created_at`. For `begin_session`, the decorator captures the session creation event. For `health`, it captures the ping event.

The decorator lives in `server.py` (or a shared `decorators.py`) and is applied like:
```python
@mcp.tool()
@audit_log("domain_get_ticket")
async def domain_get_ticket(id: str, session_token: str, sub: str) -> dict:
    ...
```

**Trade-off:** Every tool call writes a row — adds latency. But audit trails are spec-required, and the decorator keeps it DRY. DB errors during logging are caught silently (logging must never break the tool's primary function).

### Decision 9: Ticket ID generation — PostgreSQL SEQUENCE

Ticket IDs follow the format `tkt-NNN` (e.g., `tkt-004`). A PostgreSQL SEQUENCE (`ticket_id_seq`) generates the numeric portion. `schema.sql` creates it. When `domain_create_ticket` inserts a new row, `db.create_ticket()` uses `nextval('ticket_id_seq')` and formats it as `tkt-{nextval}`.

Seed tickets (tkt-001, tkt-002, tkt-003) are inserted with explicit IDs — the sequence is advanced to start after the highest seed ID.

**Trade-off:** Sequential IDs are predictable, not cryptographically random. But the spec says "service generates sequential" and ticket IDs are not secret (they're shared per `domain_get_ticket` access model).

### Decision 10: Per-tool reminder — `@with_reminder` decorator

Every gated tool (11 tools: domain_*, user_*, config_*) is wrapped with a `@with_reminder` decorator that appends the reminder line to the tool's return value. The decorator intercepts the tool's return dict and injects a `_reminder` key (or appends to a `reminder` field). `begin_session` already includes the reminder as the `reminder` field in its return shape — no decorator needed there. `health` is NOT wrapped (it's ungated, no reminder per spec).

```python
@mcp.tool()
@with_reminder
@audit_log("domain_get_ticket")
async def domain_get_ticket(id: str, ...) -> dict:
    ...
```

**Trade-off:** Decorator stacking order matters. `@with_reminder` runs outermost (after the tool returns, before `@audit_log` captures the output). This means the audit log records the tool's raw output, not the reminder-included version — the reminder is presentation-only.

### Decision 11: `seed/articles.json` vs spec seed data

The existing `seed/articles.json` has 3 articles (a1, a2, a3) from a previous iteration. The spec defines 7 different seed records (3 tickets, 2 orders, 2 policies). We build from the spec — `seed_data.py` contains the spec's 7 records. `articles.json` is superseded and won't be touched.

---

## Build Order (matching spec concepts)

1. **Add deps:** `uv add fastmcp psycopg[binary,pool] python-dotenv` (httpx already present)
2. **`server.py` + `db.py` + `config_store.py` + `schema.sql`** — scaffold all 13 tools as stubs, Starlette+uvicorn shell, DDL for 6 tables + pgvector extension + ticket_id_seq
3. **Neon MCP server** — run `schema.sql` to create tables, then run `seed_data.py` which: INSERTs 3 seed tickets into `tickets` table, calls Mistral API to embed the 4 catalog records (2 orders + 2 policies), INSERTs them into `support_embeddings` with computed embeddings, and INSERTs config rows (rules + persona). Writes `DATABASE_URL` to `.env`.
4. **Implement tools** — `health`, then domain tools (5), then user tools (2), then config tools (2), then `begin_session`
5. **Auth wiring** — Custom `TokenVerifier` → `RemoteAuthProvider`, verify 401/no-token/wrong-aud. Use `mock_auth` for local auth testing.
6. **Decorators** — add `@audit_log` to all 13 tools, add `@with_reminder` to 11 gated tools
7. **Session gating** — `begin_session` + `require_session(token, expected_sub=sub)` on all gated tools
8. **Fail-closed** — verify fallback config, per-tool reminder line, DB-down → clean errors
9. **Live demo** — `AUTH_DISABLED=1`, cloudflared tunnel, claude.ai

---

## Risks

| Risk | Mitigation |
|------|-----------|
| FastMCP `TokenVerifier` API shape differs from docs | Query Context7 at build time for the exact signature |
| `get_well_known_routes()` may not exist in current FastMCP | Fall back to manually building the route with a `@mcp.custom_route` |
| `get_http_headers()` may strip `authorization` header (known FastMCP 3.x bug) | Test at build time with a tool returning headers. If stripped, read from `request.headers` directly via Starlette `Request` object |
| Mistral embedding API requires a key the human may not have | Make `MISTRAL_API_KEY` optional; `domain_search` fails gracefully if missing during seeding |
| psycopg 3 async pool connection lifecycle in stateless FastMCP | Use `async with pool.connection()` per-tool (short-lived connections, pool manages reuse) |
| WSL `/mnt/d/` mount causes watchfiles hangs | Copy project to `/tmp/` before running (source-of-truth rule #1) |

---

## Source-of-Truth Rules (from `learned-source-of-truth.md`)

1. Copy WSL `/mnt/d/` projects to `/tmp/` before running servers (watchfiles/inotify hang)
2. FastMCP 3.4: `stateless_http=True`, `json_response=True` (or `FASTMCP_JSON_RESPONSE=true` env)
3. `dotenv.load_dotenv()` must run before any import that reads `os.environ`
4. `RemoteAuthProvider` routes not auto-mounted by `mcp.run()` — use Starlette deployment pattern
5. Custom Starlette lifespan must compose FastMCP's internal lifespan
6. MCP streamable-http requires session negotiation (initialize → initialized → tools/call)
7. `cloudflared tunnel` needs `--http-host-header 127.0.0.1:8000`
8. Identity (`sub`) from verified OAuth token, never from a tool argument
9. Design database access as async from the start
