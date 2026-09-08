"""End-to-end test of the hand-rolled JSON-RPC/Streamable HTTP protocol
layer (`jsonrpc_mcp_http.py`), exercised against the server's real 6 tools
through Starlette's in-process `TestClient` — no `mcp` SDK, no FastMCP, and
no real network socket involved.
"""

from __future__ import annotations

import json

import pytest
from starlette.testclient import TestClient

from server import mcp

SESSION_HEADER = "Mcp-Session-Id"


def _parse_sse(response) -> dict:
    for line in response.text.splitlines():
        if line.startswith("data:"):
            return json.loads(line[len("data:"):].strip())
    raise AssertionError(f"No SSE 'data:' line in {response.text!r}")


@pytest.fixture()
def client() -> TestClient:
    return TestClient(mcp.asgi_app())


def _initialize(client: TestClient) -> str:
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    )
    assert response.status_code == 200
    assert SESSION_HEADER in response.headers
    session_id = response.headers[SESSION_HEADER]
    client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={SESSION_HEADER: session_id})
    return session_id


def test_initialize_returns_session_id_and_server_info(client: TestClient):
    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert SESSION_HEADER in response.headers
    body = _parse_sse(response)
    assert body["result"]["protocolVersion"] == "2025-06-18"


def test_request_without_session_id_is_rejected(client: TestClient):
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})

    assert response.status_code == 400


def test_tools_list_exposes_all_six_tools(client: TestClient):
    session_id = _initialize(client)

    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers={SESSION_HEADER: session_id})
    tools = _parse_sse(response)["result"]["tools"]
    names = {t["name"] for t in tools}

    assert names == {
        "encode_to_binary", "decode_from_binary",
        "encode_to_hex", "decode_from_hex",
        "encode_to_morse", "decode_from_morse",
    }


def test_tools_call_happy_path(client: TestClient):
    session_id = _initialize(client)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "encode_to_hex", "arguments": {"text": "HOLA"}}},
        headers={SESSION_HEADER: session_id},
    )
    result = _parse_sse(response)["result"]

    assert result.get("isError") is not True
    assert result["content"][0]["text"] == "48 4F 4C 41"


def test_tools_call_non_ascii_returns_tool_error_not_500(client: TestClient):
    session_id = _initialize(client)

    response = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "encode_to_binary", "arguments": {"text": "café"}}},
        headers={SESSION_HEADER: session_id},
    )
    result = _parse_sse(response)["result"]

    assert result["isError"] is True
    assert "é" in result["content"][0]["text"]


def test_notification_gets_202_with_empty_body(client: TestClient):
    session_id = _initialize(client)

    response = client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}, headers={SESSION_HEADER: session_id}
    )

    assert response.status_code == 202
    assert response.text == ""


def test_delete_terminates_session(client: TestClient):
    session_id = _initialize(client)

    delete_response = client.delete("/mcp", headers={SESSION_HEADER: session_id})
    assert delete_response.status_code == 200

    # The session id is no longer valid after DELETE.
    followup = client.post("/mcp", json={"jsonrpc": "2.0", "id": 5, "method": "tools/list"}, headers={SESSION_HEADER: session_id})
    assert followup.status_code == 400
