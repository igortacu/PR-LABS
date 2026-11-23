"""Versioned JSON wire protocol for the LAN chat."""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from typing import Any

from .constants import (
    MAX_DATAGRAM_BYTES,
    MAX_NAME_CHARS,
    MAX_TEXT_CHARS,
    MESSAGE_TYPES,
    PROTOCOL_NAME,
    PROTOCOL_VERSION,
)


class InvalidMessage(ValueError):
    """A datagram is not a valid message of this chat protocol."""


class MessageTooLarge(InvalidMessage):
    """A valid-looking message does not fit the configured UDP budget."""


COMMON_FIELDS = {
    "protocol",
    "version",
    "type",
    "sender",
    "sender_id",
    "private_port",
}

TYPE_FIELDS = {
    "join": set(),
    "heartbeat": set(),
    "leave": set(),
    "presence": {"target_id"},
    "conflict": {"target_id", "name"},
    "general": {"message_id", "text"},
    "private": {"message_id", "recipient", "nonce", "ciphertext"},
}


def validate_chat_text(text: str) -> None:
    if not isinstance(text, str):
        raise InvalidMessage("message text must be a string")
    if not text:
        raise InvalidMessage("message text must not be empty")
    if len(text) > MAX_TEXT_CHARS:
        raise InvalidMessage(f"message text exceeds {MAX_TEXT_CHARS} characters")
    if any(ord(character) < 32 and character not in "\t" for character in text):
        raise InvalidMessage("message text contains control characters")


def validate_name(name: Any, field: str = "sender") -> None:
    if not isinstance(name, str) or not (1 <= len(name) <= MAX_NAME_CHARS):
        raise InvalidMessage(f"{field} must contain 1-{MAX_NAME_CHARS} characters")
    if name.startswith("/") or any(character.isspace() or ord(character) < 32 for character in name):
        raise InvalidMessage(f"{field} must not contain whitespace, controls, or start with slash")


def _validate_uuid(value: Any, field: str) -> None:
    if not isinstance(value, str):
        raise InvalidMessage(f"{field} must be a UUID string")
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as error:
        raise InvalidMessage(f"{field} must be a valid UUID") from error
    if str(parsed) != value:
        raise InvalidMessage(f"{field} must be a canonical UUID")


def _validate_base64(value: Any, field: str, minimum_bytes: int, exact_bytes: int | None = None) -> None:
    if not isinstance(value, str) or not value:
        raise InvalidMessage(f"{field} must be non-empty Base64 text")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise InvalidMessage(f"{field} must be valid Base64") from error
    if exact_bytes is not None and len(decoded) != exact_bytes:
        raise InvalidMessage(f"{field} must decode to {exact_bytes} bytes")
    if len(decoded) < minimum_bytes:
        raise InvalidMessage(f"{field} is too short")


def validate_message(message: Any) -> None:
    if not isinstance(message, dict):
        raise InvalidMessage("message must be a JSON object")
    kind = message.get("type")
    if kind not in MESSAGE_TYPES:
        raise InvalidMessage("unknown message type")
    expected_fields = COMMON_FIELDS | TYPE_FIELDS[kind]
    if set(message) != expected_fields:
        missing = expected_fields - set(message)
        extra = set(message) - expected_fields
        raise InvalidMessage(f"wrong fields; missing={sorted(missing)}, extra={sorted(extra)}")
    if message["protocol"] != PROTOCOL_NAME or message["version"] != PROTOCOL_VERSION:
        raise InvalidMessage("unsupported protocol or version")
    validate_name(message["sender"])
    _validate_uuid(message["sender_id"], "sender_id")
    port = message["private_port"]
    if isinstance(port, bool) or not isinstance(port, int) or not (1 <= port <= 65535):
        raise InvalidMessage("private_port must be an integer from 1 to 65535")

    if "target_id" in message:
        _validate_uuid(message["target_id"], "target_id")
    if kind == "conflict":
        validate_name(message["name"], "name")
    if "message_id" in message:
        _validate_uuid(message["message_id"], "message_id")
    if kind == "general":
        validate_chat_text(message["text"])
    if kind == "private":
        validate_name(message["recipient"], "recipient")
        _validate_base64(message["nonce"], "nonce", minimum_bytes=12, exact_bytes=12)
        _validate_base64(message["ciphertext"], "ciphertext", minimum_bytes=16)


def encode_message(message: dict[str, Any]) -> bytes:
    validate_message(message)
    data = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(data) > MAX_DATAGRAM_BYTES:
        raise MessageTooLarge(f"datagram is {len(data)} bytes; maximum is {MAX_DATAGRAM_BYTES}")
    return data


def decode_message(data: bytes) -> dict[str, Any]:
    if not isinstance(data, bytes):
        raise InvalidMessage("datagram must be bytes")
    if len(data) > MAX_DATAGRAM_BYTES:
        raise MessageTooLarge(f"datagram is {len(data)} bytes; maximum is {MAX_DATAGRAM_BYTES}")
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidMessage("datagram is not valid UTF-8 JSON") from error
    validate_message(message)
    return message
