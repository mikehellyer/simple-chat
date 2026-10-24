import os

import pytest

from simple_chat.core import crypto
from simple_chat.core.crypto import Channel


@pytest.fixture(scope="module")
def key():
    return crypto.derive_key("correct horse battery")


def test_same_passphrase_same_key(key):
    assert crypto.derive_key("correct horse battery") == key
    assert crypto.derive_key("correct horse batterY") != key
    assert len(key) == 32
    assert crypto.key_from_hex(key.hex()) == key
    assert crypto.key_from_hex("abc") is None and crypto.key_from_hex("zz" * 32) is None


def test_fingerprint_short_and_stable(key):
    code = crypto.fingerprint(key)
    assert len(code) == 9 and code[4] == "-" and code == crypto.fingerprint(key)
    assert code != crypto.fingerprint(os.urandom(32))


def test_lines_round_trip_and_hide_text(key):
    ch = Channel(key)
    sealed = ch.seal_line(b'{"text": "secret plans"}\n')
    assert sealed.endswith(b"\n") and sealed.count(b"\n") == 1
    assert b"secret" not in sealed
    assert ch.open_line(sealed.rstrip(b"\n")) == b'{"text": "secret plans"}'
    # a fresh nonce each time
    assert ch.seal_line(b"x\n") != ch.seal_line(b"x\n")


def test_datagrams_round_trip(key):
    ch = Channel(key)
    assert ch.open_datagram(ch.seal_datagram(b"{hello}")) == b"{hello}"


def test_wrong_key_tampering_and_plain_rejected(key):
    ch, other = Channel(key), Channel(os.urandom(32))
    sealed = ch.seal_line(b"hi\n").rstrip(b"\n")
    assert other.open_line(sealed) is None
    tampered = sealed[:-2] + (b"A" if sealed[-2:-1] != b"A" else b"B") + sealed[-1:]
    assert ch.open_line(tampered) is None
    assert ch.open_line(b'{"type": "msg"}') is None
    assert ch.open_line(b"E1:not base64!!") is None
    assert ch.open_datagram(b'{"app": "simple-chat"}') is None
    # a sealed UDP packet is no good on TCP, and the other way round
    datagram = ch.seal_datagram(b"hi")
    assert ch.open_line(b"E1:" + __import__("base64").b64encode(datagram[3:])) is None


def test_plain_channel_passes_plain_and_ignores_sealed(key):
    plain = Channel()
    assert not plain.encrypted and Channel(key).encrypted
    assert plain.seal_line(b"x\n") == b"x\n" and plain.open_line(b"x") == b"x"
    assert plain.open_line(Channel(key).seal_line(b"x\n").rstrip()) is None
    assert plain.open_datagram(Channel(key).seal_datagram(b"x")) is None
