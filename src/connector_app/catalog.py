"""catalog.py — embedding pipeline for catalog items (orders, policies)."""

import json
import os
from psycopg.types.json import Jsonb


async def _get_embedding(text: str) -> list[float] | None:
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
    if not title or not title.strip():
        return {"error": "title is required", "_reminder": reminder}
    if not body or not body.strip():
        return {"error": "body is required", "_reminder": reminder}
    if not applies_to or not applies_to.strip():
        return {"error": "applies_to is required", "_reminder": reminder}
    try:
        content = {"title": title.strip(), "body": body.strip(), "applies_to": applies_to.strip()}
        text = _item_text("policy", content)
        embedding = await _get_embedding(text) if text else None
        embedding_regenerated = embedding is not None

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if embedding:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content, embedding) "
                        "VALUES (%s, 'policy', %s::jsonb, %s::vector) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding",
                        (policy_id, Jsonb(content), embedding),
                    )
                else:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content) "
                        "                        VALUES (%s, 'policy', %s::jsonb) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = NULL",
                        (policy_id, Jsonb(content)),
                    )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "catalog_set_policy", f"id={policy_id}", "saved")
        result = {
            "id": policy_id, "status": "updated", "entity_type": "policy",
            "embedding_regenerated": embedding_regenerated,
            "updated_at": _now_iso(), "_reminder": reminder,
        }
        if not embedding_regenerated:
            result["warning"] = ("Embedding unavailable. Policy saved but will not appear "
                                 "in semantic search results until re-indexed.")
        return result
    except Exception:
        return {"error": "I cannot access the catalog right now.", "_reminder": reminder}


async def set_order(pool, sub: str, role: str, order_id: str, content: dict, reminder: str) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    if not isinstance(content, dict):
        return {"error": "content must be a JSON object", "_reminder": reminder}
    try:
        serialized = json.dumps(content)
        if len(serialized.encode("utf-8")) > 50 * 1024:
            return {"error": "content exceeds 50KB limit", "_reminder": reminder}
    except (TypeError, ValueError):
        return {"error": "content must be a JSON object", "_reminder": reminder}
    try:
        text = _item_text("order", content)
        embedding = await _get_embedding(text) if text else None
        embedding_regenerated = embedding is not None

        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if embedding:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content, embedding) "
                        "VALUES (%s, 'order', %s::jsonb, %s::vector) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding",
                        (order_id, Jsonb(content), embedding),
                    )
                else:
                    await cur.execute(
                        "INSERT INTO support_embeddings (id, entity_type, content) "
                        "VALUES (%s, 'order', %s::jsonb) "
                        "ON CONFLICT (id, entity_type) DO UPDATE SET content = EXCLUDED.content, embedding = NULL",
                        (order_id, Jsonb(content)),
                    )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "catalog_set_order", f"id={order_id}", "saved")
        result = {
            "id": order_id, "status": "updated", "entity_type": "order",
            "embedding_regenerated": embedding_regenerated,
            "updated_at": _now_iso(), "_reminder": reminder,
        }
        if not embedding_regenerated:
            result["warning"] = ("Embedding unavailable. Order saved but will not appear "
                                 "in semantic search results until re-indexed.")
        return result
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
                    "SELECT id FROM support_embeddings WHERE id = %s AND entity_type = %s",
                    (item_id, entity_type),
                )
                if await cur.fetchone() is None:
                    return {"message": "not found", "_reminder": reminder}
                await cur.execute(
                    "DELETE FROM support_embeddings WHERE id = %s AND entity_type = %s",
                    (item_id, entity_type),
                )

        from connector_app.tools.domain import log_audit
        await log_audit(pool, sub, "catalog_delete_item", f"id={item_id},type={entity_type}", "deleted")
        return {"id": item_id, "status": "deleted", "deleted_at": _now_iso(), "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the catalog right now.", "_reminder": reminder}


async def list_all(pool, sub: str, role: str, entity_type: str | None, reminder: str, *,
                   limit: int = 50, offset: int = 0) -> dict:
    allowed_roles = ["admin"]
    if role is None or role not in allowed_roles:
        return {"message": "not found", "_reminder": reminder}
    actual_limit = min(limit, 200)
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                if entity_type:
                    await cur.execute(
                        "SELECT COUNT(*) FROM support_embeddings WHERE entity_type = %s",
                        (entity_type,),
                    )
                else:
                    await cur.execute("SELECT COUNT(*) FROM support_embeddings")
                total = (await cur.fetchone())[0]

                if entity_type:
                    await cur.execute(
                        "SELECT id, entity_type, content, updated_at FROM support_embeddings "
                        "WHERE entity_type = %s ORDER BY id LIMIT %s OFFSET %s",
                        (entity_type, actual_limit, offset),
                    )
                else:
                    await cur.execute(
                        "SELECT id, entity_type, content, updated_at FROM support_embeddings "
                        "ORDER BY entity_type, id LIMIT %s OFFSET %s",
                        (actual_limit, offset),
                    )
                rows = await cur.fetchall()

        items = []
        for r in rows:
            c = r[2] if isinstance(r[2], dict) else {}
            item = {"id": r[0], "entity_type": r[1]}
            if r[1] == "policy":
                item["title"] = c.get("title")
                item["applies_to"] = c.get("applies_to")
            else:
                item["content"] = c
            item["updated_at"] = r[3].isoformat() if r[3] else None
            items.append(item)

        return {"items": items, "total": total, "returned": len(items), "offset": offset, "_reminder": reminder}
    except Exception:
        return {"error": "I cannot access the catalog right now.", "_reminder": reminder}


from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()