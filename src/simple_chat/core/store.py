"""The machines this one knows and every message to and from them, kept
in SQLite so chats survive a restart and messages to a switched-off
machine wait until it comes back."""
from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from platformdirs import user_data_dir

# A message's status. Outgoing ones are PENDING until the other machine
# acks them; incoming ones are always RECEIVED.
PENDING = "pending"
DELIVERED = "delivered"
RECEIVED = "received"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS peers (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '',
    port INTEGER NOT NULL DEFAULT 0,
    last_seen REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    peer_id TEXT NOT NULL,
    outgoing INTEGER NOT NULL,
    text TEXT NOT NULL,
    sent_at REAL NOT NULL,
    status TEXT NOT NULL,
    unread INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS messages_by_peer ON messages (peer_id, sent_at);
"""


@dataclass(frozen=True)
class KnownPeer:
    id: str
    name: str
    host: str
    port: int
    last_seen: float


@dataclass(frozen=True)
class StoredMessage:
    id: str
    peer_id: str
    outgoing: bool
    text: str
    sent_at: float
    status: str


def default_path(profile: str = "") -> Path:
    base = Path(user_data_dir("Simple-Chat"))
    return base / (f"chat-{profile}.db" if profile else "chat.db")


class ChatStore:
    def __init__(self, path: Optional[Path] = None):
        """path=None keeps everything in memory (tests)."""
        if path is None:
            target = ":memory:"
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            target = str(path)
        self._db = sqlite3.connect(target)
        self._db.executescript(_SCHEMA)
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    # --- machines

    def remember_peer(self, peer_id: str, name: str, host: str, port: int, seen_at: Optional[float] = None) -> None:
        self._db.execute(
            "INSERT INTO peers (id, name, host, port, last_seen) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name, host=excluded.host, port=excluded.port, "
            "last_seen=excluded.last_seen",
            (peer_id, name, host, port, time.time() if seen_at is None else seen_at),
        )
        self._db.commit()

    def peers(self) -> list[KnownPeer]:
        rows = self._db.execute("SELECT id, name, host, port, last_seen FROM peers ORDER BY name COLLATE NOCASE")
        return [KnownPeer(*row) for row in rows]

    def peer(self, peer_id: str) -> Optional[KnownPeer]:
        row = self._db.execute("SELECT id, name, host, port, last_seen FROM peers WHERE id=?", (peer_id,)).fetchone()
        return KnownPeer(*row) if row else None

    def forget_peer(self, peer_id: str) -> None:
        """Drops the machine and its whole chat."""
        self._db.execute("DELETE FROM messages WHERE peer_id=?", (peer_id,))
        self._db.execute("DELETE FROM peers WHERE id=?", (peer_id,))
        self._db.commit()

    # --- messages

    def add_outgoing(self, message_id: str, peer_id: str, text: str, sent_at: float) -> StoredMessage:
        self._db.execute(
            "INSERT INTO messages (id, peer_id, outgoing, text, sent_at, status) VALUES (?, ?, 1, ?, ?, ?)",
            (message_id, peer_id, text, sent_at, PENDING),
        )
        self._db.commit()
        return StoredMessage(message_id, peer_id, True, text, sent_at, PENDING)

    def add_incoming(self, message_id: str, peer_id: str, text: str, sent_at: float, unread: bool = True) -> Optional[StoredMessage]:
        """None if this message was already received — the sender resends
        anything whose ack it didn't get, so duplicates are normal."""
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO messages (id, peer_id, outgoing, text, sent_at, status, unread) "
            "VALUES (?, ?, 0, ?, ?, ?, ?)",
            (message_id, peer_id, text, sent_at, RECEIVED, int(unread)),
        )
        self._db.commit()
        if cursor.rowcount == 0:
            return None
        return StoredMessage(message_id, peer_id, False, text, sent_at, RECEIVED)

    def mark_delivered(self, message_id: str) -> Optional[str]:
        """The peer the message went to, or None if it was unknown or
        already marked."""
        row = self._db.execute(
            "SELECT peer_id FROM messages WHERE id=? AND outgoing=1 AND status=?", (message_id, PENDING)
        ).fetchone()
        if row is None:
            return None
        self._db.execute("UPDATE messages SET status=? WHERE id=?", (DELIVERED, message_id))
        self._db.commit()
        return row[0]

    def pending_for(self, peer_id: str) -> list[StoredMessage]:
        return self._select("WHERE peer_id=? AND outgoing=1 AND status=? ORDER BY sent_at", (peer_id, PENDING))

    def conversation(self, peer_id: str, limit: int = 500) -> list[StoredMessage]:
        """The latest `limit` messages, oldest first."""
        newest = self._select("WHERE peer_id=? ORDER BY sent_at DESC LIMIT ?", (peer_id, limit))
        return newest[::-1]

    def unread_counts(self) -> dict[str, int]:
        rows = self._db.execute("SELECT peer_id, COUNT(*) FROM messages WHERE unread=1 GROUP BY peer_id")
        return dict(rows.fetchall())

    def mark_read(self, peer_id: str) -> None:
        self._db.execute("UPDATE messages SET unread=0 WHERE peer_id=? AND unread=1", (peer_id,))
        self._db.commit()

    def delete_message(self, message_id: str) -> None:
        self._db.execute("DELETE FROM messages WHERE id=?", (message_id,))
        self._db.commit()

    def clear_conversation(self, peer_id: str) -> None:
        self._db.execute("DELETE FROM messages WHERE peer_id=?", (peer_id,))
        self._db.commit()

    def _select(self, where: str, args: tuple) -> list[StoredMessage]:
        rows = self._db.execute(f"SELECT id, peer_id, outgoing, text, sent_at, status FROM messages {where}", args)
        return [StoredMessage(r[0], r[1], bool(r[2]), r[3], r[4], r[5]) for r in rows]
