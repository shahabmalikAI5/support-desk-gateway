"""sync.py — background Freshdesk sync asyncio Task.

Spawns on server startup. Polls every 15 minutes for tickets with freshdesk_id
and updates their status from Freshdesk. The first sync for any ticket requires
a manual domain_sync_to_freshdesk call (push).
"""

import asyncio
import os


_FD_STATUS_REVERSE = {3: "pending", 4: "resolved", 5: "closed"}


async def _get_fd_creds(pool) -> tuple[str | None, str | None]:
    """Read Freshdesk credentials from config store, fall back to env vars."""
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute("SELECT value FROM config WHERE key = 'freshdesk_api_key'")
                r1 = await cur.fetchone()
                await cur.execute("SELECT value FROM config WHERE key = 'freshdesk_domain'")
                r2 = await cur.fetchone()
                if r1 and r2:
                    return r1[0], r2[0]
    except Exception:
        pass
    return os.environ.get("FRESHDESK_API_KEY"), os.environ.get("FRESHDESK_DOMAIN")


async def _pull_one(pool, ticket_id: str, freshdesk_id: str, api_key: str, domain: str) -> None:
    """Pull the latest status from Freshdesk for a single synced ticket.
    Only resolves and closed propagate from FD to local. FD Status 2 is ignored."""
    try:
        import httpx
        auth = httpx.BasicAuth(api_key, "X")
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"https://{domain}.freshdesk.com/api/v2/tickets/{freshdesk_id}",
                auth=auth,
                timeout=15.0,
            )
            if resp.status_code != 200:
                return
            data = resp.json()
            fd_status = data.get("status")

            new_status = _FD_STATUS_REVERSE.get(fd_status)
            if not new_status:
                return

            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE tickets SET status = %s, freshdesk_synced_at = now() "
                        "WHERE id = %s AND freshdesk_id IS NOT NULL",
                        (new_status, ticket_id),
                    )
                    if new_status == "resolved":
                        await cur.execute(
                            "UPDATE tickets SET resolved_at = now() WHERE id = %s",
                            (ticket_id,),
                        )
                    elif new_status == "closed":
                        await cur.execute(
                            "UPDATE tickets SET closed_at = now() WHERE id = %s",
                            (ticket_id,),
                        )
    except Exception:
        pass


async def sync_loop(pool) -> None:
    """Background loop: poll Freshdesk every 15 minutes for synced tickets."""
    while True:
        try:
            api_key, domain = await _get_fd_creds(pool)
            if not api_key or not domain:
                await asyncio.sleep(900)
                continue

            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id, freshdesk_id FROM tickets "
                        "WHERE freshdesk_id IS NOT NULL "
                        "AND status IN ('open', 'in_progress')"
                    )
                    rows = await cur.fetchall()

            for ticket_id, freshdesk_id in rows:
                await _pull_one(pool, ticket_id, freshdesk_id, api_key, domain)
        except Exception:
            pass
        await asyncio.sleep(900)


def start_background_sync(pool) -> asyncio.Task:
    """Start the background sync loop as an asyncio task."""
    return asyncio.create_task(sync_loop(pool))