"""Remote MCP server exposing deterministic text encoding/decoding tools.

Converts text between three ASCII-only representations: binary, hexadecimal,
and International Morse Code. Runs over Streamable HTTP so it can be deployed
as a remote MCP server (e.g. on Google Cloud Run).
"""

import asyncio
import logging
import os

from fastmcp import FastMCP

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mcp = FastMCP("Text Encoding Conversion MCP Server")

MORSE_TABLE = {
    "A": ".-", "B": "-...", "C": "-.-.", "D": "-..", "E": ".", "F": "..-.",
    "G": "--.", "H": "....", "I": "..", "J": ".---", "K": "-.-", "L": ".-..",
    "M": "--", "N": "-.", "O": "---", "P": ".--.", "Q": "--.-", "R": ".-.",
    "S": "...", "T": "-", "U": "..-", "V": "...-", "W": ".--", "X": "-..-",
    "Y": "-.--", "Z": "--..",
    "0": "-----", "1": ".----", "2": "..---", "3": "...--", "4": "....-",
    "5": ".....", "6": "-....", "7": "--...", "8": "---..", "9": "----.",
    ".": ".-.-.-", ",": "--..--", "?": "..--..", "'": ".----.", "!": "-.-.--",
    "/": "-..-.", "(": "-.--.", ")": "-.--.-", "&": ".-...", ":": "---...",
    ";": "-.-.-.", "=": "-...-", "+": ".-.-.", "-": "-....-", "_": "..--.-",
    '"': ".-..-.", "$": "...-..-", "@": ".--.-.",
}
REVERSE_MORSE_TABLE = {code: char for char, code in MORSE_TABLE.items()}

MORSE_WORD_SEPARATOR = " / "


def _log_call(tool_name: str, **kwargs: str) -> None:
    """Log a tool invocation, truncating long argument values."""
    truncated = {
        key: (value[:80] + "...") if len(value) > 80 else value
        for key, value in kwargs.items()
    }
    logger.info("Tool called: %s args=%s", tool_name, truncated)


@mcp.tool()
def encode_to_binary(text: str) -> str:
    """Encode text into 8-bit ASCII binary, one byte per character.

    Args:
        text: The ASCII text to encode.

    Returns:
        The binary representation, one 8-bit byte per character,
        separated by single spaces. Example: "HOLA" -> "01001000 01001111 01001100 01000001".

    Raises:
        ValueError: If any character in `text` is outside the ASCII range (0-127).
    """
    _log_call("encode_to_binary", text=text)
    invalid_chars = sorted({c for c in text if ord(c) > 127})
    if invalid_chars:
        raise ValueError(
            f"Cannot encode to binary, non-ASCII character(s): {', '.join(invalid_chars)}"
        )
    return " ".join(format(ord(c), "08b") for c in text)


@mcp.tool()
def decode_from_binary(binary: str) -> str:
    """Decode 8-bit ASCII binary back into text.

    Args:
        binary: A string of 8-bit binary bytes. Whitespace between (or within)
            bytes is optional and is stripped before processing.

    Returns:
        The decoded ASCII text.

    Raises:
        ValueError: If the whitespace-stripped input length is not a multiple
            of 8, if it contains characters other than "0"/"1", or if any
            8-bit byte decodes to a value outside the ASCII range (0-127).
    """
    _log_call("decode_from_binary", binary=binary)
    cleaned = "".join(binary.split())
    if len(cleaned) % 8 != 0:
        raise ValueError(
            f"Invalid binary length: {len(cleaned)} bit(s) is not a multiple of 8"
        )
    invalid_chars = sorted(set(cleaned) - {"0", "1"})
    if invalid_chars:
        raise ValueError(
            f"Invalid binary string, unexpected character(s): {', '.join(invalid_chars)}"
        )
    chars = []
    for i in range(0, len(cleaned), 8):
        byte = cleaned[i:i + 8]
        value = int(byte, 2)
        if value > 127:
            raise ValueError(
                f"Invalid binary byte '{byte}' decodes to {value}, "
                "which is outside the ASCII range (0-127)"
            )
        chars.append(chr(value))
    return "".join(chars)


@mcp.tool()
def encode_to_hex(text: str) -> str:
    """Encode text into uppercase ASCII hexadecimal, one byte per character.

    Args:
        text: The ASCII text to encode.

    Returns:
        The hexadecimal representation, one 2-digit uppercase byte per
        character, separated by single spaces.
        Example: "Networking" -> "4E 65 74 77 6F 72 6B 69 6E 67".

    Raises:
        ValueError: If any character in `text` is outside the ASCII range (0-127).
    """
    _log_call("encode_to_hex", text=text)
    invalid_chars = sorted({c for c in text if ord(c) > 127})
    if invalid_chars:
        raise ValueError(
            f"Cannot encode to hex, non-ASCII character(s): {', '.join(invalid_chars)}"
        )
    return " ".join(format(ord(c), "02X") for c in text)


@mcp.tool()
def decode_from_hex(hex_string: str) -> str:
    """Decode ASCII hexadecimal back into text.

    Args:
        hex_string: A string of 2-digit hexadecimal bytes. Whitespace between
            (or within) bytes is optional and is stripped before processing.

    Returns:
        The decoded ASCII text.

    Raises:
        ValueError: If the whitespace-stripped input length is odd, if it
            contains non-hexadecimal characters, or if any byte decodes to a
            value outside the ASCII range (0-127).
    """
    _log_call("decode_from_hex", hex_string=hex_string)
    cleaned = "".join(hex_string.split())
    if len(cleaned) % 2 != 0:
        raise ValueError(
            f"Invalid hex string length: {len(cleaned)} character(s) is not even"
        )
    invalid_chars = sorted({c for c in cleaned if c not in "0123456789ABCDEFabcdef"})
    if invalid_chars:
        raise ValueError(
            f"Invalid hex string, unexpected character(s): {', '.join(invalid_chars)}"
        )
    chars = []
    for i in range(0, len(cleaned), 2):
        pair = cleaned[i:i + 2]
        value = int(pair, 16)
        if value > 127:
            raise ValueError(
                f"Invalid hex byte '{pair}' decodes to {value}, "
                "which is outside the ASCII range (0-127)"
            )
        chars.append(chr(value))
    return "".join(chars)


@mcp.tool()
def encode_to_morse(text: str) -> str:
    """Encode text into International Morse Code.

    Args:
        text: The text to encode. It is uppercased before encoding.

    Returns:
        The Morse code representation: letters within a word are separated
        by a single space, and words are separated by " / ".
        Example: "HOLA" -> ".... --- .-.. .-".

    Raises:
        ValueError: If, after uppercasing, any character has no entry in the
            International Morse Code table.
    """
    _log_call("encode_to_morse", text=text)
    upper_text = text.upper()
    invalid_chars = sorted({c for c in upper_text if c != " " and c not in MORSE_TABLE})
    if invalid_chars:
        raise ValueError(
            f"Cannot encode to Morse, character(s) not in table: {', '.join(invalid_chars)}"
        )
    words = upper_text.split(" ")
    encoded_words = [" ".join(MORSE_TABLE[c] for c in word) for word in words]
    return MORSE_WORD_SEPARATOR.join(encoded_words)


@mcp.tool()
def decode_from_morse(morse: str) -> str:
    """Decode International Morse Code back into text.

    Args:
        morse: The Morse code string. Words are separated by " / ", and
            letters within a word are separated by a single space.

    Returns:
        The decoded text, in uppercase.

    Raises:
        ValueError: If any Morse token has no entry in the International
            Morse Code table.
    """
    _log_call("decode_from_morse", morse=morse)
    words = morse.split(MORSE_WORD_SEPARATOR)
    invalid_tokens = []
    for word in words:
        tokens = word.split(" ") if word else []
        for token in tokens:
            if token not in REVERSE_MORSE_TABLE and token not in invalid_tokens:
                invalid_tokens.append(token)
    if invalid_tokens:
        raise ValueError(
            f"Cannot decode from Morse, invalid token(s): {', '.join(invalid_tokens)}"
        )
    decoded_words = []
    for word in words:
        tokens = word.split(" ") if word else []
        decoded_words.append("".join(REVERSE_MORSE_TABLE[token] for token in tokens))
    return " ".join(decoded_words)


if __name__ == "__main__":
    asyncio.run(
        mcp.run_async(
            transport="streamable-http",
            host="0.0.0.0",
            port=int(os.getenv("PORT", 8080)),
        )
    )
