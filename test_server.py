"""Raw JSON-RPC / Streamable HTTP smoke test for the Text Encoding
Conversion MCP Server — no MCP SDK, no FastMCP client. Speaks the wire
protocol directly with `httpx`: POST /mcp for `initialize` and `tools/call`,
parsing the single-event SSE body the server returns for each response.

Connects to a running instance of `server.py` and exercises the 6 tools with
happy-path and edge/error cases.

Usage:
    # Local development server (started separately with `uv run server.py`):
    uv run test_server.py

    # Authenticated Cloud Run deployment (via `gcloud run services proxy`,
    # which exposes the service on http://127.0.0.1:8080/mcp just like local dev):
    uv run test_server.py
"""

import itertools
import os

import httpx

SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8080/mcp")
_id_counter = itertools.count(1)


class ToolError(Exception):
    """Raised when a `tools/call` result comes back with `isError: true`."""


def _parse_sse_body(response: httpx.Response) -> dict:
    """Extract the single JSON-RPC message from a `text/event-stream` body."""
    for line in response.text.splitlines():
        if line.startswith("data:"):
            import json

            return json.loads(line[len("data:"):].strip())
    raise RuntimeError(f"No SSE 'data:' line in response body: {response.text!r}")


class MCPHttpClient:
    """A tiny, spec-following Streamable HTTP JSON-RPC client."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client = httpx.Client(timeout=30.0)
        self._session_id: str | None = None

    def _post(self, method: str, params: dict | None = None, msg_id: int | None = None) -> httpx.Response:
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        if msg_id is not None:
            msg["id"] = msg_id
        headers = {"Accept": "application/json, text/event-stream"}
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        response = self._client.post(self._url, json=msg, headers=headers)
        response.raise_for_status()
        if "Mcp-Session-Id" in response.headers:
            self._session_id = response.headers["Mcp-Session-Id"]
        return response

    def initialize(self) -> dict:
        response = self._post("initialize", {"protocolVersion": "2025-06-18"}, msg_id=next(_id_counter))
        result = _parse_sse_body(response)["result"]
        self._post("notifications/initialized")  # notification: no id, no reply expected
        return result

    def list_tools(self) -> list[dict]:
        response = self._post("tools/list", msg_id=next(_id_counter))
        return _parse_sse_body(response)["result"]["tools"]

    def call_tool(self, name: str, **arguments: str) -> str:
        response = self._post("tools/call", {"name": name, "arguments": arguments}, msg_id=next(_id_counter))
        result = _parse_sse_body(response)["result"]
        text = result["content"][0]["text"]
        if result.get("isError"):
            raise ToolError(text)
        return text

    def close(self) -> None:
        if self._session_id:
            self._client.delete(self._url, headers={"Mcp-Session-Id": self._session_id})
        self._client.close()


def call_tool(client: MCPHttpClient, tool_name: str, **kwargs: str) -> str:
    """Call a tool and print its request/response in a readable format."""
    print(f">>> {tool_name}({kwargs})")
    text = client.call_tool(tool_name, **kwargs)
    print(f"<<< {text}")
    return text


def expect_error(client: MCPHttpClient, tool_name: str, **kwargs: str) -> None:
    """Call a tool expecting it to fail, and print the resulting error."""
    print(f">>> {tool_name}({kwargs})  [expecting error]")
    try:
        result = client.call_tool(tool_name, **kwargs)
    except ToolError as exc:
        print(f"<<< ERROR (as expected): {exc}")
        return
    raise AssertionError(f"Expected {tool_name}({kwargs}) to raise an error, but got: {result!r}")


def main() -> None:
    client = MCPHttpClient(SERVER_URL)
    try:
        init_result = client.initialize()
        print(f"Initialized: {init_result['serverInfo']} (protocol {init_result['protocolVersion']})")
        tool_names = sorted(t["name"] for t in client.list_tools())
        print(f"Discovered {len(tool_names)} tools: {tool_names}\n")

        print("=== Happy path ===")

        result = call_tool(client, "encode_to_binary", text="HOLA")
        assert result == "01001000 01001111 01001100 01000001", result

        result = call_tool(client, "decode_from_binary", binary="01001000 01001111 01001100 01000001")
        assert result == "HOLA", result

        result = call_tool(client, "encode_to_hex", text="Networking")
        assert result == "4E 65 74 77 6F 72 6B 69 6E 67", result

        result = call_tool(client, "decode_from_hex", hex_string="4E 65 74 77 6F 72 6B 69 6E 67")
        assert result == "Networking", result

        result = call_tool(client, "encode_to_morse", text="HOLA")
        assert result == ".... --- .-.. .-", result

        result = call_tool(client, "decode_from_morse", morse=".... --- .-.. .-")
        assert result == "HOLA", result

        print("\n=== Edge / error cases ===")

        expect_error(client, "decode_from_binary", binary="0100100")
        expect_error(client, "decode_from_hex", hex_string="4E6")
        expect_error(client, "decode_from_morse", morse=".......")
        expect_error(client, "encode_to_morse", text="HOLÁ")
        expect_error(client, "encode_to_binary", text="café")

        print("\n=== Round-trip ===")

        original = "Redes CC3067"
        encoded = call_tool(client, "encode_to_hex", text=original)
        decoded = call_tool(client, "decode_from_hex", hex_string=encoded)
        assert decoded == original, decoded

        print("\nAll test cases passed.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
