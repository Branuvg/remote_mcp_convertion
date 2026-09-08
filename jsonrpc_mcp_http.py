"""Minimal hand-rolled MCP server: JSON-RPC 2.0 over the `streamable-http`
transport (MCP spec 2025-06-18).

No dependency on the `mcp` SDK or FastMCP — this is the raw-JSON-RPC
implementation requested by the project's extra-credit item (section 4.1).
Built directly on Starlette + uvicorn (general-purpose ASGI tooling, not an
MCP SDK) instead.

Implements the three endpoints of the Streamable HTTP transport at a single
`/mcp` path:

- `POST /mcp`   — the actual JSON-RPC traffic: `initialize`,
  `notifications/initialized`, `tools/list`, `tools/call`. A successful
  JSON-RPC response is framed as a single Server-Sent Event
  (`Content-Type: text/event-stream`, `event: message\\ndata: <json>\\n\\n`),
  matching this transport's message framing; a notification (no `id`) gets a
  bare `202 Accepted` with an empty body, since notifications never receive a
  JSON-RPC reply.
- `GET /mcp`    — opens the transport's standing server-push channel. This
  server never has anything to push unsolicited (every tool here is a plain
  request/response calculation), so the stream just stays open, idling,
  until the client disconnects.
- `DELETE /mcp` — terminates a session.

Session lifecycle: `initialize` mints a new session id (returned via the
`Mcp-Session-Id` response header); every other request must carry that
header naming a session this process still recognizes.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import typing
import types
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)

JSONRPC_VERSION = "2.0"
PROTOCOL_VERSION = "2025-06-18"
SESSION_HEADER = "Mcp-Session-Id"

METHOD_NOT_FOUND = -32601
INVALID_REQUEST = -32600
PARSE_ERROR = -32700


class ToolError(Exception):
    """Raised by a tool implementation to report a client-facing tool error.

    This server's tools actually raise the plain built-in `ValueError`
    (see `server.py`); `ToolError` is accepted too so the protocol layer
    matches the sibling `mcp_f1_strategy` server's convention.
    """


@dataclass
class _RegisteredTool:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    func: Callable[..., Any] | None = None


def _schema_for_annotation(annotation: Any) -> dict[str, Any]:
    """Best-effort JSON Schema for a single parameter's Python type hint."""
    if annotation is inspect.Parameter.empty or annotation is Any:
        return {}

    origin = typing.get_origin(annotation)

    if origin is typing.Union or origin is types.UnionType:
        members = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(members) == 1:
            return _schema_for_annotation(members[0])
        return {}

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}

    return {}


def _build_input_schema(func: Callable[..., Any]) -> dict[str, Any]:
    signature = inspect.signature(func)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for param_name, param in signature.parameters.items():
        properties[param_name] = _schema_for_annotation(param.annotation)
        if param.default is inspect.Parameter.empty:
            required.append(param_name)
    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _description_for(func: Callable[..., Any]) -> str:
    doc = inspect.getdoc(func) or ""
    first_paragraph = doc.split("\n\n", 1)[0]
    return " ".join(line.strip() for line in first_paragraph.splitlines()).strip()


def _jsonrpc_response(msg_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "result": result}


def _jsonrpc_error(msg_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": JSONRPC_VERSION, "id": msg_id, "error": {"code": code, "message": message}}


def _sse_response(payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> Response:
    """Frame one JSON-RPC message as a single Server-Sent Event."""
    body = f"event: message\ndata: {json.dumps(payload)}\n\n"
    headers = {"Cache-Control": "no-cache"}
    if extra_headers:
        headers.update(extra_headers)
    return Response(content=body, media_type="text/event-stream", headers=headers)


class MCPServer:
    """A minimal MCP server: tool registration, JSON-RPC dispatch, and a
    Streamable HTTP ASGI app — all with no MCP SDK involved."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._tools: dict[str, _RegisteredTool] = {}
        self._sessions: set[str] = set()

    def tool(self) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            self._tools[func.__name__] = _RegisteredTool(
                name=func.__name__,
                description=_description_for(func),
                input_schema=_build_input_schema(func),
                func=func,
            )
            return func

        return decorator

    # ------------------------------------------------------------------ #
    #  MCP lifecycle / JSON-RPC method dispatch
    # ------------------------------------------------------------------ #

    def _handle_initialize(self, msg_id: Any) -> dict[str, Any]:
        return _jsonrpc_response(
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": self.name, "version": "0.1.0"},
            },
        )

    def _handle_tools_list(self, msg_id: Any) -> dict[str, Any]:
        tools = [
            {"name": t.name, "description": t.description, "inputSchema": t.input_schema}
            for t in self._tools.values()
        ]
        return _jsonrpc_response(msg_id, {"tools": tools})

    def _handle_tools_call(self, msg_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name")
        arguments: dict[str, Any] = params.get("arguments") or {}

        tool = self._tools.get(tool_name) if tool_name else None
        if tool is None or tool.func is None:
            return _jsonrpc_response(
                msg_id,
                {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}], "isError": True},
            )

        try:
            result = tool.func(**arguments)
            text = result if isinstance(result, str) else json.dumps(result, indent=2)
            return _jsonrpc_response(msg_id, {"content": [{"type": "text", "text": text}]})
        except (ToolError, ValueError) as exc:
            return _jsonrpc_response(
                msg_id, {"content": [{"type": "text", "text": str(exc)}], "isError": True}
            )
        except Exception:  # never leak a raw traceback to the client
            logger.exception("Unexpected error in tool '%s'", tool_name)
            return _jsonrpc_response(
                msg_id,
                {"content": [{"type": "text", "text": f"Internal error executing '{tool_name}'."}], "isError": True},
            )

    def dispatch(self, msg: dict[str, Any]) -> dict[str, Any] | None:
        """Route one parsed JSON-RPC message; return the response, or None
        for notifications (no `id`), which never get a JSON-RPC reply."""
        method = msg.get("method", "")
        msg_id = msg.get("id")

        if method == "initialize":
            return self._handle_initialize(msg_id)
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return self._handle_tools_list(msg_id)
        if method == "tools/call":
            return self._handle_tools_call(msg_id, msg.get("params") or {})

        if msg_id is None:
            return None
        return _jsonrpc_error(msg_id, METHOD_NOT_FOUND, f"Method not found: {method}")

    # ------------------------------------------------------------------ #
    #  Transport: Streamable HTTP (POST/GET/DELETE /mcp)
    # ------------------------------------------------------------------ #

    def asgi_app(self) -> Starlette:
        async def mcp_post(request: Request) -> Response:
            raw_body = await request.body()
            try:
                msg = json.loads(raw_body)
            except json.JSONDecodeError:
                return _sse_response(_jsonrpc_error(None, PARSE_ERROR, "Parse error"))

            method = msg.get("method")
            msg_id = msg.get("id")

            if method == "initialize":
                session_id = uuid.uuid4().hex
                self._sessions.add(session_id)
                return _sse_response(self._handle_initialize(msg_id), {SESSION_HEADER: session_id})

            session_id = request.headers.get(SESSION_HEADER)
            if session_id is None or session_id not in self._sessions:
                return Response(
                    status_code=400,
                    content=json.dumps(_jsonrpc_error(msg_id, INVALID_REQUEST, "Missing or unknown Mcp-Session-Id")),
                    media_type="application/json",
                )

            response = self.dispatch(msg)
            if response is None:
                return Response(status_code=202)
            return _sse_response(response)

        async def mcp_get(request: Request) -> Response:
            session_id = request.headers.get(SESSION_HEADER)
            if session_id is None or session_id not in self._sessions:
                return Response(status_code=400, content="Missing or unknown Mcp-Session-Id")

            async def event_stream() -> typing.AsyncIterator[bytes]:
                # Standing server-push channel required by the transport.
                # This server has nothing to push unsolicited, so it just
                # idles (a periodic SSE comment keeps intermediate proxies
                # from timing the connection out) until the client hangs up.
                try:
                    while True:
                        await asyncio.sleep(15)
                        yield b": ping\n\n"
                except asyncio.CancelledError:
                    return

            return StreamingResponse(event_stream(), media_type="text/event-stream")

        async def mcp_delete(request: Request) -> Response:
            session_id = request.headers.get(SESSION_HEADER)
            if session_id:
                self._sessions.discard(session_id)
            return Response(status_code=200)

        return Starlette(
            routes=[
                Route("/mcp", mcp_post, methods=["POST"]),
                Route("/mcp", mcp_get, methods=["GET"]),
                Route("/mcp", mcp_delete, methods=["DELETE"]),
            ]
        )

    def run(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        import uvicorn

        uvicorn.run(self.asgi_app(), host=host, port=port)
