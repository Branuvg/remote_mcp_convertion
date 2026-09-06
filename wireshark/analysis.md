# Wireshark capture analysis — host ↔ remote MCP server

Covers project item 8 (classify captured JSON-RPC messages as sync/request/response)
and feeds item 10 (link/network/transport/application layer explanation).

## 1. Setup

- **File:** `mcp_loopback_capture.pcapng` (131 packets, ~16.8 s, loopback interface,
  filter `tcp port 8080`).
- **What's on the wire:** the connection between `host_mcp_redes` (the MCP client)
  and `gcloud run services proxy`, which forwards to the deployed Cloud Run
  service (`https://remote-mcp-convertion-uuad3nj3rq-uc.a.run.app`) while
  injecting the caller's IAM credentials. This hop is **plaintext HTTP**, which
  is what makes the JSON-RPC content readable in Wireshark.
- **What's *not* on the wire here:** the real internet-facing hop, from the
  proxy process to Cloud Run over `https://*.run.app` (port 443), is a
  separate TLS-encrypted TCP connection made by the proxy binary itself. It
  isn't visible in this capture (a second capture on the real network adapter
  would show its TCP/TLS handshake, but not decrypted JSON-RPC content).
- **Scenario captured:** the chatbot host was asked, in one session, to (1)
  encode "Networking" to hex and decode it back, then (2) encode "CC3067" to
  Morse and decode it back — exercising `initialize`, `tools/list`, and 4
  `tools/call` invocations against the remote server.

## 2. JSON-RPC message classification

JSON-RPC 2.0 defines three message shapes: **Request** (has `id`, expects a
reply), **Notification** (no `id`, no reply expected), and **Response** (has
`id` + `result`/`error`). Mapped onto the captured frames:

| Frame(s) | t (s) | HTTP | JSON-RPC message | Type |
|---|---|---|---|---|
| 6 | 0.001 | `POST /mcp` | `{"id":1,"method":"initialize",...}` | **Request** |
| 8, 10 | 5.701 | `200 OK` (SSE) | `{"id":1,"result":{"protocolVersion":...,"serverInfo":...}}` | **Response** |
| 24 | 5.705 | `POST /mcp` | `{"method":"notifications/initialized"}` (no `id`) | **Notification** (sync) |
| 26 | 5.705 | `GET /mcp` | *(no JSON-RPC body)* — opens the transport's server-push SSE channel | Transport-level session setup |
| 28 | 5.884 | `202 Accepted` (empty body) | *(HTTP-level ack of the notification only — JSON-RPC notifications never get a JSON-RPC response)* | Transport ack |
| 39 | 5.887 | `POST /mcp` | `{"id":2,"method":"tools/list",...}` | **Request** |
| 43 | 6.767 | `200 OK` (SSE) | `{"id":2,"result":{"tools":[...6 tools...]}}` | **Response** |
| 54 | 8.509 | `POST /mcp` | `{"id":3,"method":"tools/call","params":{"name":"encode_to_hex","arguments":{"text":"Networking"}}}` | **Request** |
| 58 | 8.641 | `200 OK` (SSE) | `{"id":3,"result":{"content":[{"text":"4E 65 74 77 6F 72 6B 69 6E 67"}]}}` | **Response** |
| 69 | 10.237 | `POST /mcp` | `{"id":4,"method":"tools/call","params":{"name":"decode_from_hex","arguments":{"hex_string":"4E 65 74 77 6F 72 6B 69 6E 67"}}}` | **Request** |
| 75 | 10.381 | `200 OK` (SSE) | `{"id":4,"result":{"content":[{"text":"Networking"}]}}` | **Response** |
| 86 | 13.468 | `POST /mcp` | `{"id":5,"method":"tools/call","params":{"name":"encode_to_morse","arguments":{"text":"CC3067"}}}` | **Request** |
| 92 | 13.661 | `200 OK` (SSE) | `{"id":5,"result":{"content":[{"text":"-.-. -.-. ...-- ----- -.... --..."}]}}` | **Response** |
| 103 | 15.032 | `POST /mcp` | `{"id":6,"method":"tools/call","params":{"name":"decode_from_morse","arguments":{"morse":"-.-. -.-. ...-- ----- -.... --..."}}}` | **Request** |
| 109 | 15.212 | `200 OK` (SSE) | `{"id":6,"result":{"content":[{"text":"CC3067"}]}}` | **Response** |
| 118 | 16.671 | `DELETE /mcp` | *(no JSON-RPC body — `Mcp-Session-Id` header identifies the session to close)* | Transport-level session teardown |
| 120, 121 | 16.835 | `200 OK` ×2 | *(closes the standing GET/SSE stream from frame 26, and acks the DELETE)* | Transport ack |

**Summary:** 6 JSON-RPC **requests** (`initialize`, `tools/list`, 4×
`tools/call`), 6 matching **responses** (same `id`s), and 1 **notification**
(`notifications/initialized`) — the message the MCP handshake uses to tell
the server "I've received your `initialize` response and I'm ready," which
is the closest JSON-RPC equivalent to a synchronization signal here. The
`GET`/`DELETE` exchanges around it aren't JSON-RPC payloads themselves —
they're Streamable HTTP transport plumbing (opening/closing the session and
its server-push channel).

## 3. Layer-by-layer walkthrough (for item 10)

- **Link layer:** captured on Npcap's loopback pseudo-interface
  (`\Device\NPF_Loopback`, encapsulation `NULL/Loopback`), so frames carry a
  4-byte address-family marker instead of a real Ethernet header — there's no
  genuine MAC addressing here, since loopback traffic never touches a NIC.
  (The real proxy→Cloud Run hop, not captured, would show real Ethernet/Wi-Fi
  framing with actual MAC addresses.)
- **Network layer:** IPv4, source and destination both `127.0.0.1` — the
  loopback address, so no actual routing decision is made; the packet is
  handed directly back up the stack by the OS.
- **Transport layer:** TCP. Each JSON-RPC exchange rides its own short-lived
  connection: a full 3-way handshake (`SYN` → `SYN,ACK` → `ACK`, e.g. frames
  1–3 for the `initialize` call), data segments (`PSH,ACK`) carrying the HTTP
  request/response, then a 4-way close (`FIN,ACK` both directions). Note that
  despite the client sending `Connection: keep-alive`, a **new TCP connection
  (new ephemeral source port) is opened for almost every request** — visible
  as repeated `tcp.stream` values (0, 1, 3, 4, 5, 6, 7, 8) each with their own
  handshake — because Google's frontend closes the connection after serving
  each response rather than keeping it warm.
- **Application layer:** HTTP/1.1 (`POST`/`GET`/`DELETE` to `/mcp`) carrying
  JSON-RPC 2.0. Every JSON-RPC response — even a one-off `tools/call` result —
  is wrapped as a Server-Sent Event (`Content-Type: text/event-stream`,
  body framed as `event: message\ndata: {...}\n\n`), which is the defining
  trait of the MCP **Streamable HTTP** transport: a single POST can still get
  its reply delivered as one SSE event rather than a bare JSON body, and the
  standing `GET` (frame 26) is the channel reserved for the server to push
  additional messages outside of a request/response cycle.
