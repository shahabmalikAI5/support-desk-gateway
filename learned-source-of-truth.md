# Source of Truth — Mistakes to Never Repeat And What Learned From it


## Connector-Native Apps Course

### Copy WSL `/mnt/d/` projects to `/tmp/` before running servers

`watchfiles`/`inotify` deps hang in kernel D-state on Windows mounts. Always `cp -r` to `/tmp/` first.

### FastMCP 3.4 streamable HTTP: pass `stateless=True, json_response=True`

Without them the server returns 400/406 on raw POSTs. Never assume default transport settings work.


### `dotenv.load_dotenv()` must run before any import that reads `os.environ`

Python evaluates module-level code at import time. If a module does `os.environ["KEY"]` at the top level, the import crashes with `KeyError` unless dotenv ran first. Place it above all project imports.

### FastMCP `mcp.run()` does not auto-mount well-known auth routes

`RemoteAuthProvider` routes (`/.well-known/oauth-protected-resource`) are not served by `mcp.run()`. Use the Starlette deployment pattern: `mcp.http_app()` → `mcp_app.get_well_known_routes()` → `Starlette(routes=[...])` → `uvicorn.run()`.

### Custom Starlette lifespan must compose FastMCP's internal lifespan

If your `@app.on_event("startup")` or custom lifespan replaces the ASGI app's lifespan, the `StreamableHTTPSessionManager` won't initialize → `RuntimeError: Task group is not initialized`. Compose: `async with mcp_app.router.lifespan_context(app): yield`.

### MCP streamable-http requires session negotiation before `tools/call`

Clients must `POST initialize` → get `Mcp-Session-Id` from headers → `POST notifications/initialized` → then call tools. This is the MCP protocol layer, separate from auth. Raw tool calls without the handshake return 400.

### `cloudflared tunnel` needs `--http-host-header 127.0.0.1:8000`

Without it, the tunnel's random hostname triggers uvicorn DNS-rebinding protection → every request gets `421 Misdirected Request`.

### Identity (`sub`) comes from the verified OAuth token, never from a tool argument

If a tool signature contains `user_id` or similar, ignore it. Read identity from `get_access_token().claims["sub"]` (the verified token's `sub` claim). The model chooses what to ask, not whose data to read.

### Design database access as async from the start when the server is async

Rewriting a sync `db.py` to async after the server goes async doubles the work. Use `psycopg[binary,pool]` with `AsyncConnectionPool` and `async/await` from the first line.
