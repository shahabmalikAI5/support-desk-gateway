"""sync.py — background Freshdesk sync asyncio Task.

Spawns on server startup. Polls every 15 minutes for tickets with freshdesk_id
and updates their status from Freshdesk. The first sync for any ticket requires
a manual domain_sync_to_freshdesk call (push).
"""

import asyncio
import os


async def _sync_one_ticket(pool, ticket_id: str, freshdesk_id: str) -> None:
    """Pull the latest status from Freshdesk for a single synced ticket."""
    api_key = os.environ.get("FRESHDESK_API_KEY")
    domain = os.environ.get("FRESHDESK_DOMAIN")
    if not api_key or not domain:
        return
    try:
        import httpx
        auth = (api_key, "X")
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
            status_map = {2: "open", 3: "pending", 4: "in_progress", 5: "resolved", 6: "closed"}
            new_status = status_map.get(fd_status)

        if new_status:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "UPDATE tickets SET status = %s, freshdesk_synced_at = now() "
                        "WHERE id = %s AND freshdesk_id IS NOT NULL",
                        (new_status, ticket_id),
                    )
    except Exception:
        pass


async def sync_loop(pool) -> None:
    """Background loop: poll Freshdesk every 15 minutes for synced tickets."""
    while True:
        try:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT id, freshdesk_id FROM tickets "
                        "WHERE freshdesk_id IS NOT NULL AND freshdesk_synced_at IS NOT NULL"
                    )
                    rows = await cur.fetchall()

            for ticket_id, freshdesk_id in rows:
                await _sync_one_ticket(pool, ticket_id, freshdesk_id)
        except Exception:
            pass
        await asyncio.sleep(900)  # 15 minutes


def start_background_sync(pool) -> asyncio.Task:
    """Start the background sync loop as an asyncio task."""
    return asyncio.create_task(sync_loop(pool))