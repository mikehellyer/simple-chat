"""Encrypting everything Simple-Chat sends, with a passphrase shared by
all your machines.

The passphrase is stretched with scrypt into a 256-bit key; only the key
is saved, never the passphrase. Every UDP announcement and every TCP line
is then sealed with AES-256-GCM under a fresh random nonce, which both
hides it and proves it came from a machine that knows the passphrase —
anything else fails to open and is dropped, so machines with a different
passphrase (or none) can neither read nor message yours, nor even see
them.

There is no key exchange, so every machine must turn the same passphrase
into the same key: the scrypt salt is therefore fixed rather than random.
That's the usual trade-off for a shared-passphrase scheme; scrypt's cost
is what protects a weak passphrase against guessing.

A Channel with no key is the old plain mode: bytes pass through as they
are, and anything sealed is ignored since it can't be read.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
from typing import Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

SALT = b"simple-chat network key v1"
# ~32 MB and a fraction of a second, even on a Raspberry Pi; done once,
# when the passphrase is set.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 15, 8, 1
KEY_BYTES = 32
NONCE_BYTES = 12
MIN_PASSPHRASE = 8

# Sealed datagrams start with these bytes; sealed TCP lines with LINE_MAGIC
# then base64 (which has no newlines, so the line framing still works).
# Plain ones are JSON and always start with "{".
DATAGRAM_MAGIC = b"SC1"
LINE_MAGIC = b"E1:"
# Associated data, so a sealed UDP packet can't be replayed into a TCP
# stream or the other way round.
_AAD_UDP = b"simple-chat/udp/v1"
_AAD_TCP = b"simple-chat/tcp/v1"


def derive_key(passphrase: str) -> bytes:
    """Slow on purpose (see SCRYPT_N): run it off the GUI thread."""
    kdf = Scrypt(salt=SALT, length=KEY_BYTES, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def key_from_hex(text: str) -> Optional[bytes]:
    try:
        key = bytes.fromhex(text)
    except ValueError:
        return None
    return key if len(key) == KEY_BYTES else None


def fingerprint(key: bytes) -> str:
    """A short code to check two machines have the same passphrase,
    without showing the key: e.g. "7Q2K-M9XD"."""
    digest = hashlib.sha256(b"simple-chat fingerprint" + key).digest()
    code = base64.b32encode(digest)[:8].decode()
    return f"{code[:4]}-{code[4:]}"


class Channel:
    def __init__(self, key: Optional[bytes] = None):
        if key is not None and len(key) != KEY_BYTES:
            raise ValueError("key must be 32 bytes")
        self._aead = AESGCM(key) if key is not None else None

    @property
    def encrypted(self) -> bool:
        return self._aead is not None

    def seal_datagram(self, data: bytes) -> bytes:
        if self._aead is None:
            return data
        nonce = os.urandom(NONCE_BYTES)
        return DATAGRAM_MAGIC + nonce + self._aead.encrypt(nonce, data, _AAD_UDP)

    def open_datagram(self, data: bytes) -> Optional[bytes]:
        if self._aead is None:
            return None if data.startswith(DATAGRAM_MAGIC) else data
        if not data.startswith(DATAGRAM_MAGIC):
            return None  # plain, from a machine without the passphrase
        return self._open(data[len(DATAGRAM_MAGIC):], _AAD_UDP)

    def seal_line(self, line: bytes) -> bytes:
        """`line` ends in a newline, and so does the result."""
        if self._aead is None:
            return line
        nonce = os.urandom(NONCE_BYTES)
        sealed = nonce + self._aead.encrypt(nonce, line.rstrip(b"\n"), _AAD_TCP)
        return LINE_MAGIC + base64.b64encode(sealed) + b"\n"

    def open_line(self, line: bytes) -> Optional[bytes]:
        """A line as LineReader gives it (no newline)."""
        if self._aead is None:
            return None if line.startswith(LINE_MAGIC) else line
        if not line.startswith(LINE_MAGIC):
            return None
        try:
            sealed = base64.b64decode(line[len(LINE_MAGIC):], validate=True)
        except (binascii.Error, ValueError):
            return None
        return self._open(sealed, _AAD_TCP)

    def _open(self, sealed: bytes, aad: bytes) -> Optional[bytes]:
        if len(sealed) < NONCE_BYTES + 16:
            return None
        try:
            return self._aead.decrypt(sealed[:NONCE_BYTES], sealed[NONCE_BYTES:], aad)
        except InvalidTag:
            return None
