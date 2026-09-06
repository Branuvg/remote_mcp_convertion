# Specification — Text Encoding Conversion MCP Server

This document covers the tool specification (parameters, return values,
errors, examples) and the reference encoding table used by this server, as
required by the project rubric item "indicate the specification, parameters,
endpoints, etc." for each MCP server developed.

## Transport / endpoint

- **Protocol:** MCP over **Streamable HTTP** (per MCP spec 2025-06-18).
- **Endpoint path:** `/mcp` (e.g. `http://127.0.0.1:8080/mcp` when running
  locally, or via the authenticated Cloud Run proxy).
- **Scope:** all tools operate on **ASCII only** (code points 0–127). Any
  input containing non-ASCII characters (accents, ñ, emojis, etc.) is
  rejected with an explicit error naming the offending character(s) — never
  silently dropped, replaced, or guessed.

## Tools

| Tool | Parameters | Returns | Example | Raises |
|---|---|---|---|---|
| `encode_to_binary` | `text: str` | `str` — 8-bit binary bytes, space-separated | `encode_to_binary("HOLA")` → `"01001000 01001111 01001100 01000001"` | `ValueError` if any character has `ord(c) > 127` |
| `decode_from_binary` | `binary: str` | `str` — decoded ASCII text | `decode_from_binary("01001000 01001111 01001100 01000001")` → `"HOLA"` | `ValueError` if stripped length isn't a multiple of 8, contains non-`0`/`1` characters, or a byte decodes to > 127 |
| `encode_to_hex` | `text: str` | `str` — uppercase 2-digit hex bytes, space-separated | `encode_to_hex("Networking")` → `"4E 65 74 77 6F 72 6B 69 6E 67"` | `ValueError` if any character has `ord(c) > 127` |
| `decode_from_hex` | `hex_string: str` | `str` — decoded ASCII text | `decode_from_hex("4E 65 74 77 6F 72 6B 69 6E 67")` → `"Networking"` | `ValueError` if stripped length is odd, contains non-hex characters, or a byte decodes to > 127 |
| `encode_to_morse` | `text: str` | `str` — Morse code (letters space-separated, words separated by `" / "`) | `encode_to_morse("HOLA")` → `".... --- .-.. .-"` | `ValueError` if (after uppercasing) any character has no entry in the Morse table |
| `decode_from_morse` | `morse: str` | `str` — decoded text, uppercase | `decode_from_morse(".... --- .-.. .-")` → `"HOLA"` | `ValueError` if any Morse token has no entry in the table |

### Notes on input handling

- `decode_from_binary` and `decode_from_hex` strip **all** whitespace before
  validating, so input may be given with or without byte separators.
- `encode_to_morse` uppercases `text` before validating and encoding; a
  single space in the original text becomes the `" / "` word separator (it is
  not looked up in the table itself).
- `decode_from_morse` expects words separated by `" / "` and, within a word,
  individual letters separated by a single space.
- All error messages name the specific character(s) or token(s) that caused
  the failure — no partial results, no `?` placeholders.

## International Morse Code table (reference)

```
A .-      B -...    C -.-.    D -..     E .       F ..-.
G --.     H ....    I ..      J .---    K -.-     L .-..
M --      N -.      O ---     P .--.    Q --.-    R .-.
S ...     T -       U ..-     V ...-    W .--     X -..-
Y -.--    Z --..

0 -----   1 .----   2 ..---   3 ...--   4 ....-
5 .....   6 -....   7 --...   8 ---..   9 ----.

. .-.-.-   , --..--   ? ..--..   ' .----.   ! -.-.--
/ -..-.    ( -.--.    ) -.--.-   & .-...    : ---...
; -.-.-.   = -...-    + .-.-.    - -....-   _ ..--.-
" .-..-.   $ ...-..-  @ .--.-.
```

(The `" "` space in plain text is represented as the `" / "` word
separator, not as a symbol in the table above.)
