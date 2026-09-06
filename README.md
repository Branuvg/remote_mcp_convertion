# remote_mcp_convertion

A remote **MCP (Model Context Protocol)** server that exposes deterministic
text encoding/decoding tools — binary, hexadecimal, and International Morse
Code. Built with [FastMCP](https://gofastmcp.com) and designed to run on
**Google Cloud Run** over the **Streamable HTTP** transport.

> Project context: CC3067 Redes (UVG), Project 1, item 7 — "Create an MCP
> server that runs remotely." See [`SPEC.md`](./SPEC.md) for the full tool
> specification.

## 1. Overview

LLMs are surprisingly unreliable at exact, character-by-character encoding
tasks (binary, hex, Morse) — they tend to "eyeball" the conversion and
occasionally get individual bytes or letters wrong. This server removes that
guesswork: instead of asking the LLM to compute the conversion itself, an MCP
host delegates the work to this server, which performs it with plain,
deterministic string logic and returns an exact result every time.

It exposes **6 tools** — an `encode`/`decode` pair for each of 3 formats
(binary, hex, Morse) — restricted to the **ASCII (0–127)** character set. Any
attempt to encode a non-ASCII character (accents, `ñ`, emojis, etc.) fails
with an explicit error naming the problematic character(s), rather than
silently dropping or guessing at it.

The server runs remotely on Cloud Run using the **Streamable HTTP** MCP
transport (the transport recommended by MCP spec 2025-06-18; SSE is
deprecated), and can be consumed by any MCP-compatible host, including
[`host_mcp_redes`](https://github.com/Branuvg/host_mcp_redes), the console
chatbot built for this same project.

## 2. Tools

| Tool | Parameters | Returns | Example | Errors |
|---|---|---|---|---|
| `encode_to_binary` | `text: str` | `str` | `encode_to_binary("HOLA")` → `"01001000 01001111 01001100 01000001"` | Non-ASCII character in `text` |
| `decode_from_binary` | `binary: str` | `str` | `decode_from_binary("01001000 01001111 01001100 01000001")` → `"HOLA"` | Length not a multiple of 8, non-`0`/`1` characters, or byte > 127 |
| `encode_to_hex` | `text: str` | `str` | `encode_to_hex("Networking")` → `"4E 65 74 77 6F 72 6B 69 6E 67"` | Non-ASCII character in `text` |
| `decode_from_hex` | `hex_string: str` | `str` | `decode_from_hex("4E 65 74 77 6F 72 6B 69 6E 67")` → `"Networking"` | Odd length, non-hex characters, or byte > 127 |
| `encode_to_morse` | `text: str` | `str` | `encode_to_morse("HOLA")` → `".... --- .-.. .-"` | Character with no entry in the Morse table |
| `decode_from_morse` | `morse: str` | `str` | `decode_from_morse(".... --- .-.. .-")` → `"HOLA"` | Token with no entry in the Morse table |

All errors are raised as `ValueError`, which FastMCP surfaces to the calling
client as a tool error (no manual try/except-and-swallow on the server side).
See [`SPEC.md`](./SPEC.md) for full parameter/return details and the complete
Morse code table.

## 3. Local development

Requirements: [`uv`](https://docs.astral.sh/uv/) and Python 3.13+.

```bash
uv sync
uv run server.py
```

This starts the server with the **streamable-http** transport, listening on
`http://localhost:8080/mcp` (the port can be overridden with the `PORT`
environment variable).

## 4. Testing

With the server running locally (see above, in a separate terminal), run the
FastMCP client test script:

```bash
uv run test_server.py
```

This exercises all 6 tools with one happy-path case each (from the examples
above) plus 6 edge/error cases (invalid lengths, invalid tokens, non-ASCII
input, and a hex round-trip), printing each request/response with `>>>` /
`<<<` markers.

To point the test script at a different server (e.g. the Cloud Run proxy
below), set `MCP_SERVER_URL`:

```bash
MCP_SERVER_URL=http://127.0.0.1:8080/mcp uv run test_server.py
```

## 5. Deployment to Cloud Run

This follows the pattern from
[Google's Cloud Run remote MCP tutorial](https://cloud.google.com/blog/topics/developers-practitioners/build-and-deploy-a-remote-mcp-server-to-google-cloud-run-in-under-10-minutes).

```bash
gcloud run deploy remote-mcp-convertion \
    --no-allow-unauthenticated \
    --region=us-central1 \
    --source .
```

`--source .` builds the container from the `Dockerfile` in this repo via
Cloud Build — no local Docker installation is required. `--no-allow-unauthenticated`
means the service requires IAM-authenticated requests (see below); this is
intentional, since the service accepts arbitrary text as input.

## 6. Authentication

The deployed service does **not** accept unauthenticated requests. Any
caller (including a human tester or the MCP host in `host_mcp_redes`) needs
the `roles/run.invoker` IAM role on the Cloud Run service:

```bash
gcloud run services add-iam-policy-binding remote-mcp-convertion \
    --region=us-central1 \
    --member="user:<caller-email>" \
    --role="roles/run.invoker"
```

The simplest way to consume the service locally (for testing, or from a host
that only speaks plain HTTP) is to run the authenticated Cloud Run proxy,
which forwards `http://127.0.0.1:8080` to the remote service while injecting
the caller's IAM credentials:

```bash
gcloud run services proxy remote-mcp-convertion --region=us-central1
```

With the proxy running, the server is reachable exactly as if it were local,
at `http://127.0.0.1:8080/mcp`.

## 7. Using it from an MCP host

With the authenticated proxy running (see above), add an entry to the host's
`mcp_config.json` using the `streamable-http` transport:

```json
{
  "mcpServers": {
    "text_conversion": {
      "transport": "streamable-http",
      "url": "http://127.0.0.1:8080/mcp"
    }
  }
}
```

## Repository layout

```
remote_mcp_convertion/
├── pyproject.toml    # uv project + fastmcp dependency
├── server.py         # FastMCP server, 6 tools, streamable-http transport
├── test_server.py    # FastMCP client smoke test (happy-path + edge cases)
├── Dockerfile         # python:3.13-slim + uv, for Cloud Run --source deploy
├── .dockerignore
├── README.md          # this file
└── SPEC.md            # tool specification: parameters, returns, errors, Morse table
```
