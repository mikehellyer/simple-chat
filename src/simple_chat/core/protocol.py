"""What Simple-Chat machines say to each other, as bytes.

Two channels:

- Discovery, over UDP broadcast on DISCOVERY_PORT: every few seconds each
  machine announces "I'm here, called X, listening on TCP port P". A
  machine that hears an announcement from one it didn't know yet answers
  straight back, so new arrivals show up at once rather than after the
  next round.
- Messages, over TCP: one JSON object per line. The receiver answers
  every chat message with an "ack" line carrying its id, and only then
  does the sender mark it delivered — a message to a machine that's
  switched off stays queued until it's next seen.

Pure Python, no Qt, so it can all be tested without a network.
"""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

APP_TAG = "simple-chat"
PROTOCOL_VERSION = 1
DISCOVERY_PORT = 47474
# Tried first for incoming messages, so a firewall rule can name it; any
# free port is used if it's taken (e.g. a second copy on one machine).
PREFERRED_MESSAGE_PORT = 47475
# Longer lines than this are refused rather than buffered forever.
MAX_LINE_BYTES = 1_000_000
MAX_TEXT_CHARS = 100_000


def new_id() -> str:
    return uuid.uuid4().hex


@dataclass(frozen=True)
class Announce:
    node_id: str
    name: str
    port: int
    # True asks every machine that hears it to announce straight back
    # (sent on start-up and to an address typed in by hand).
    hello: bool = False


@dataclass(frozen=True)
class ChatMessage:
    id: str
    sender_id: str
    sender_name: str
    sender_port: int
    text: str
    sent_at: float = field(default_factory=time.time)


@dataclass(frozen=True)
class Ack:
    id: str


def encode_announce(announce: Announce) -> bytes:
    return json.dumps({
        "app": APP_TAG, "v": PROTOCOL_VERSION, "type": "announce",
        "id": announce.node_id, "name": announce.name, "port": announce.port, "hello": announce.hello,
    }).encode()


def decode_announce(data: bytes) -> Optional[Announce]:
    """None for anything that isn't a well-formed Simple-Chat announcement
    (other programs use broadcasts too)."""
    obj = _loads(data)
    if obj is None or obj.get("app") != APP_TAG or obj.get("type") != "announce":
        return None
    node_id, name, port = obj.get("id"), obj.get("name"), obj.get("port")
    if not (_is_id(node_id) and isinstance(name, str) and _is_port(port)):
        return None
    return Announce(node_id, _clean_name(name), port, bool(obj.get("hello")))


def encode_message(message: ChatMessage) -> bytes:
    return _line({
        "type": "msg", "id": message.id, "from": message.sender_id, "name": message.sender_name,
        "port": message.sender_port, "text": message.text, "at": message.sent_at,
    })


def encode_ack(ack: Ack) -> bytes:
    return _line({"type": "ack", "id": ack.id})


def decode_line(line: bytes) -> ChatMessage | Ack | None:
    obj = _loads(line)
    if obj is None:
        return None
    kind = obj.get("type")
    if kind == "ack":
        return Ack(obj["id"]) if _is_id(obj.get("id")) else None
    if kind != "msg":
        return None
    mid, sender, name, port, text, at = (obj.get(k) for k in ("id", "from", "name", "port", "text", "at"))
    if not (_is_id(mid) and _is_id(sender) and isinstance(name, str) and _is_port(port)
            and isinstance(text, str) and isinstance(at, (int, float)) and not isinstance(at, bool)):
        return None
    return ChatMessage(mid, sender, _clean_name(name), port, text[:MAX_TEXT_CHARS], float(at))


class LineReader:
    """Splits a TCP byte stream into lines. A line that grows past
    MAX_LINE_BYTES marks the stream as broken (the caller drops the
    connection) instead of eating memory."""

    def __init__(self):
        self._buffer = bytearray()
        self.broken = False

    def feed(self, data: bytes) -> list[bytes]:
        if self.broken:
            return []
        self._buffer += data
        lines = []
        while True:
            end = self._buffer.find(b"\n")
            if end < 0:
                break
            lines.append(bytes(self._buffer[:end]))
            del self._buffer[:end + 1]
        if len(self._buffer) > MAX_LINE_BYTES:
            self.broken = True
            self._buffer.clear()
        return lines


def _line(obj: dict) -> bytes:
    # ensure_ascii keeps every newline inside the text escaped, so a raw
    # b"\n" only ever ends a line
    return json.dumps(obj, ensure_ascii=True).encode() + b"\n"


def _loads(data: bytes) -> Optional[dict]:
    try:
        obj = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _is_id(value) -> bool:
    return isinstance(value, str) and 0 < len(value) <= 64 and value.isalnum()


def _is_port(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 < value < 65536


def _clean_name(name: str) -> str:
    name = " ".join(name.split())[:60]
    return name or "Unnamed machine"
