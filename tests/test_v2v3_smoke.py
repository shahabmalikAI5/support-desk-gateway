"""Smoke tests for v2/v3 implementation (requires live database)."""

import os
import asyncio

import pytest
import uvicorn

os.environ["AUTH_DISABLED"] = "1"
os.environ["SESSION_SIGNING_SECRET"] = "test-secret-smoke"
os.environ["DEV_SUB"] = "dev-user-001"

from connector_app.server import mcp


@pytest.fixture(scope="module")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="module")
async def session_token():
    config = uvicorn.Config(mcp.http_app(path="/mcp"), host="127.0.0.1", port=18902, log_level="error")
    srv = uvicorn.Server(config)
    task = asyncio.create_task(srv.serve())
    await asyncio.sleep(3)

    import httpx
    async with httpx.AsyncClient() as cl:
        r = await cl.post("http://127.0.0.1:18902/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "begin_session", "arguments": {}},
        })
        data = r.json()
        st = data["result"]["session_token"]
        yield st

    srv.should_exit = True
    await asyncio.sleep(0.5)


async def _mcp_call(client, tool, args):
    r = await client.post("http://127.0.0.1:18902/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    })
    return r.json()["result"]


@pytest.mark.asyncio
async def test_1_health(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        r = await cl.post("http://127.0.0.1:18902/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "health", "arguments": {}},
        })
        result = r.json()["result"]
        assert result.get("status") == "ok" or "ok" in str(result)


@pytest.mark.asyncio
async def test_2_session_works(session_token):
    assert len(session_token) > 20


@pytest.mark.asyncio
async def test_3_get_ticket_seed(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        result = await _mcp_call(cl, "domain_get_ticket", {"id": "tkt-001", "session_token": session_token})
        assert result["id"] == "tkt-001"
        assert "attachment_count" in result
        assert "attachment_ids" in result


@pytest.mark.asyncio
async def test_4_create_ticket_with_category(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        result = await _mcp_call(cl, "domain_create_ticket", {
            "subject": "Smoke test ticket", "body": "Testing v2/v3",
            "priority": "low", "category": "technical", "session_token": session_token,
        })
        assert "ticket_id" in result
        # verify it's stored with category
        tid = result["ticket_id"]
        r2 = await _mcp_call(cl, "domain_get_ticket", {"id": tid, "session_token": session_token})
        assert r2["category"] == "technical"
        assert r2["attachment_count"] == 0
        return tid  # keep for next tests


@pytest.mark.asyncio
async def test_5_submit_csat_rejects_open(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        tid = await test_4_create_ticket_with_category(session_token)
        result = await _mcp_call(cl, "domain_submit_csat", {
            "ticket_id": tid, "score": 5, "session_token": session_token,
        })
        assert "error" in result
        assert "resolved" in result["error"]


@pytest.mark.asyncio
async def test_6_customer_profile_has_csat_trend(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        result = await _mcp_call(cl, "domain_get_customer_profile", {"session_token": session_token})
        assert "csat_trend" in result


@pytest.mark.asyncio
async def test_7_audit_log_has_entries(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        result = await _mcp_call(cl, "domain_get_audit_log", {"session_token": session_token})
        assert "entries" in result
        assert isinstance(result["entries"], list)


@pytest.mark.asyncio
async def test_8_agent_tools_gated(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        result = await _mcp_call(cl, "domain_assign_ticket", {
            "ticket_id": "tkt-001", "agent": "tester", "session_token": session_token,
        })
        # dev-user-001 has no role, so agent tools should be 'not found'
        assert result.get("message") == "not found"


@pytest.mark.asyncio
async def test_9_attach_file_with_validation(session_token):
    import httpx
    import base64
    async with httpx.AsyncClient() as cl:
        tid = await test_4_create_ticket_with_category(session_token)
        # valid attachment
        result = await _mcp_call(cl, "domain_attach_file", {
            "ticket_id": tid, "file_name": "test.txt",
            "file_data": base64.b64encode(b"hello world").decode(),
            "mime_type": "text/plain", "session_token": session_token,
        })
        assert "attachment_id" in result

        # bad mime type
        result = await _mcp_call(cl, "domain_attach_file", {
            "ticket_id": tid, "file_name": "evil.exe",
            "file_data": base64.b64encode(b"evil").decode(),
            "mime_type": "application/x-msdownload", "session_token": session_token,
        })
        assert "unsupported" in result.get("error", "")

        # invalid base64
        result = await _mcp_call(cl, "domain_attach_file", {
            "ticket_id": tid, "file_name": "bad.txt",
            "file_data": "not-valid-base64!!!",
            "mime_type": "text/plain", "session_token": session_token,
        })
        assert "base64" in result.get("error", "")


@pytest.mark.asyncio
async def test_10_get_attachment_returns_presigned_url_or_base64(session_token):
    import httpx
    import base64
    async with httpx.AsyncClient() as cl:
        tid = await test_4_create_ticket_with_category(session_token)
        result = await _mcp_call(cl, "domain_attach_file", {
            "ticket_id": tid, "file_name": "photo.png",
            "file_data": base64.b64encode(b"fake-png-data").decode(),
            "mime_type": "image/png", "session_token": session_token,
        })
        att_id = result["attachment_id"]

        result = await _mcp_call(cl, "domain_get_attachment", {
            "attachment_id": att_id, "session_token": session_token,
        })
        assert "attachment_id" in result
        # May have presigned_url (if R2 configured) or file_data (in-memory fallback)
        assert "presigned_url" in result or "file_data" in result
        assert "url_expires_at" in result


@pytest.mark.asyncio
async def test_11_catalog_list_all(session_token):
    import httpx
    async with httpx.AsyncClient() as cl:
        result = await _mcp_call(cl, "catalog_list_all", {
            "entity_type": "policy", "session_token": session_token,
        })
        assert "items" in result
        assert isinstance(result["items"], list)
