"""catalog.py — embedding pipeline for catalog items (orders, policies)."""

import os

_EMBEDDING_DIM = 1024


async def _get_embedding(text: str) -> list[float] | None:
    """Generate Mistral embedding for the given text. Returns None on failure."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return None
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.mistral.ai/v1/embeddings",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "mistral-embed", "input": [text]},
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
    except Exception:
        return None


def _item_text(entity_type: str, content: dict) -> str:
    """Build a searchable text string from a catalog item for embedding."""
    if entity_type == "policy":
        return f"{content.get('title', '')} {content.get('body', '')} {content.get('applies_to', '')}"
    elif entity_type == "order":
        parts = [content.get("customer", ""), content.get("plan", ""),
                 " ".join(content.get("items", [])),
                 content.get("status", ""), str(content.get("total", ""))]
        return " ".join(p for p in parts if p)
    return ""


async def set_policy(pool, sub: str, role: str, policy_id: str, title: str, body: str,
                     applies_to: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        content = {"title": title, "body": body, "applies_to": applies_to}
        text = _item_text("policy", content)
        embedding = await _get_embedding(text) if text else None

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if embedding:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content, embedding) "
                        "VALUES (%s, 'policy', %s::jsonb, %s::vector) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding",
                        (policy_id, content, embedding),
                    )
                else:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content) "
                        "VALUES (%s, 'policy', %s::jsonb) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = NULL",
                        (policy_id, content),
                    )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "catalog_set_policy", f"id={policy_id}", "saved")
        return {"status": "saved", "id": policy_id, "embedded": embedding is not None, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the catalog right now.", "_reminder": reminder}


async def set_order(pool, sub: str, role: str, order_id: str, content: dict, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    try:
        text = _item_text("order", content)
        embedding = await _get_embedding(text) if text else None

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if embedding:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content, embedding) "
                        "VALUES (%s, 'order', %s::jsonb, %s::vector) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding",
                        (order_id, content, embedding),
                    )
                else:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content) "
                        "VALUES (%s, 'order', %s::jsonb) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = NULL",
                        (order_id, content),
                    )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "catalog_set_order", f"id={order_id}", "saved")
        return {"status": "saved", "id": order_id, "embedded": embedding is not None, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the catalog right now.", "_reminder": reminder}


async def delete_item(pool, sub: str, role: str, item_id: str, entity_type: str, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if entity_type not in ("policy", "order"):
        return {"error": "entity_type must be 'policy' or 'order'", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM support_embeddings WHERE id = %s AND entity_type = %s",
                    (item_id, entity_type),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "catalog_delete_item", f"id={item_id},type={entity_type}", "deleted")
        return {"status": "deleted", "id": item_id, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the catalog right now.", "_reminder": reminder}


async def list_all(pool, sub: str, role: str, entity_type: str, reminder: str) -> dict:
    allowed_roles = ["admin", "staff"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if entity_type not in ("policy", "order"):
        return {"error": "entity_type must be 'policy' or 'order'", "_reminder": reminder}
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT id, content FROM support_embeddings WHERE entity_type = %s ORDER BY id",
                    (entity_type,),
                )
                rows = await cur.fetchall()

        items = [{"id": r[0], "content": r[1] if isinstance(r[1], dict) else {}} for r in rows]
        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "catalog_list_all", f"type={entity_type}", f"{len(items)} items")
        return {"items": items, "count": len(items), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the catalog right now.", "_reminder": reminder}