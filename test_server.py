"""FastMCP client smoke test for the Text Encoding Conversion MCP Server.

Connects to a running instance of `server.py` over Streamable HTTP and
exercises the 6 tools with happy-path and edge/error cases.

Usage:
    # Local development server (started separately with `uv run server.py`):
    uv run test_server.py

    # Authenticated Cloud Run deployment (via `gcloud run services proxy`,
    # which exposes the service on http://127.0.0.1:8080/mcp just like local dev):
    uv run test_server.py
"""

import asyncio
import os

from fastmcp import Client
from fastmcp.exceptions import ToolError

SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8080/mcp")


async def call_tool(client: Client, tool_name: str, **kwargs: str) -> str:
    """Call a tool and print its request/response in a readable format."""
    print(f">>> {tool_name}({kwargs})")
    result = await client.call_tool(tool_name, kwargs)
    text = result.data
    print(f"<<< {text}")
    return text


async def expect_error(client: Client, tool_name: str, **kwargs: str) -> None:
    """Call a tool expecting it to fail, and print the resulting error."""
    print(f">>> {tool_name}({kwargs})  [expecting error]")
    try:
        result = await client.call_tool(tool_name, kwargs)
    except ToolError as exc:
        print(f"<<< ERROR (as expected): {exc}")
        return
    raise AssertionError(
        f"Expected {tool_name}({kwargs}) to raise an error, but got: {result.data!r}"
    )


async def main() -> None:
    async with Client(SERVER_URL) as client:
        print("=== Happy path ===")

        result = await call_tool(client, "encode_to_binary", text="HOLA")
        assert result == "01001000 01001111 01001100 01000001", result

        result = await call_tool(
            client, "decode_from_binary", binary="01001000 01001111 01001100 01000001"
        )
        assert result == "HOLA", result

        result = await call_tool(client, "encode_to_hex", text="Networking")
        assert result == "4E 65 74 77 6F 72 6B 69 6E 67", result

        result = await call_tool(
            client, "decode_from_hex", hex_string="4E 65 74 77 6F 72 6B 69 6E 67"
        )
        assert result == "Networking", result

        result = await call_tool(client, "encode_to_morse", text="HOLA")
        assert result == ".... --- .-.. .-", result

        result = await call_tool(client, "decode_from_morse", morse=".... --- .-.. .-")
        assert result == "HOLA", result

        print("\n=== Edge / error cases ===")

        await expect_error(client, "decode_from_binary", binary="0100100")
        await expect_error(client, "decode_from_hex", hex_string="4E6")
        await expect_error(client, "decode_from_morse", morse=".......")
        await expect_error(client, "encode_to_morse", text="HOLÁ")
        await expect_error(client, "encode_to_binary", text="café")

        print("\n=== Round-trip ===")

        original = "Redes CC3067"
        encoded = await call_tool(client, "encode_to_hex", text=original)
        decoded = await call_tool(client, "decode_from_hex", hex_string=encoded)
        assert decoded == original, decoded

        print("\nAll test cases passed.")


if __name__ == "__main__":
    asyncio.run(main())
