"""notifications.py — SendGrid email + webhook dispatch for ticket events."""

import hmac
import json
import os
import hashlib
from datetime import datetime, timezone


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

_WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
_SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")


async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send a transactional email via SendGrid REST API. Returns True on success."""
    if not _SENDGRID_API_KEY:
        return False
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {_SENDGRID_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "personalizations": [{"to": [{"email": to_email}]}],
                    "from": {"email": "support@connector.app", "name": "Support Desk"},
                    "subject": subject,
                    "content": [{"type": "text/plain", "value": body}],
                },
                timeout=15.0,
            )
            return resp.status_code in (200, 201, 202)
    except Exception:
        return False


async def send_webhook(webhook_url: str, event: str, payload: dict) -> bool:
    """POST a JSON webhook with HMAC signature header. Returns True on success."""
    if not webhook_url:
        return False
    try:
        import httpx
        body = json.dumps({"event": event, "payload": payload}).encode()
        signature = hmac.new(_WEBHOOK_SECRET.encode(), body, hashlib.sha256).hexdigest()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                webhook_url,
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Webhook-Signature": signature,
                },
                timeout=15.0,
            )
            return resp.status_code < 500
    except Exception:
        return False


async def dispatch(ticket_id: str, event: str, ticket_creator_sub: str, pool) -> None:
    """Dispatch notifications for a ticket event to the ticket's creator only."""
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT email, webhook_url, events FROM notification_config "
                    "WHERE user_sub = %s AND %s = ANY(events)",
                    (ticket_creator_sub, event),
                )
                row = await cur.fetchone()
                if row is None:
                    return

                email, webhook_url, events = row
                desc = event.replace("_", " ").title()
                subject = f"Support Desk: Ticket {ticket_id} — {desc}"
                body = f"Event: {event}\nTicket: {ticket_id}"
                if email:
                    await send_email(email, subject, body)
                if webhook_url:
                    await send_webhook(webhook_url, event, {
                        "ticket_id": ticket_id, "event": event, "timestamp": _now_iso(),
                    })
    except Exception:
        pass