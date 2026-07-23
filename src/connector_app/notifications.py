"""notifications.py — SendGrid email + webhook dispatch for ticket events."""

import hmac
import json
import os
import hashlib

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
                    "X-Support-Desk-Signature": signature,
                },
                timeout=15.0,
            )
            return resp.status_code < 500
    except Exception:
        return False


async def dispatch(ticket_id: str, event: str, sub: str, pool) -> None:
    """Dispatch notifications for a ticket event to all configured recipients."""
    try:
        async with pool.connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT user_sub, email, webhook_url, events FROM notification_config "
                    "WHERE %s = ANY(events)", (event,)
                )
                rows = await cur.fetchall()

        for row in rows:
            user_sub, email, webhook_url, events = row
            subject = f"Support Desk: Ticket {ticket_id} — {event.replace('_', ' ').title()}"
            body = f"Event: {event}\nTicket: {ticket_id}\nUser: {sub}"
            if email:
                await send_email(email, subject, body)
            if webhook_url:
                await send_webhook(webhook_url, event, {
                    "ticket_id": ticket_id, "event": event, "user": sub,
                })
    except Exception:
        pass