from simple_chat.core import protocol
from simple_chat.core.protocol import Ack, Announce, ChatMessage, LineReader


def test_announce_round_trip():
    a = Announce("abc123", "  Office   PC ", 47475, hello=True)
    back = protocol.decode_announce(protocol.encode_announce(a))
    assert back == Announce("abc123", "Office PC", 47475, True)


def test_announce_rejects_strangers():
    assert protocol.decode_announce(b"not json") is None
    assert protocol.decode_announce(b'{"app": "other", "type": "announce"}') is None
    assert protocol.decode_announce(b'{"app": "simple-chat", "type": "announce", "id": "x", "name": "n", "port": 0}') is None
    assert protocol.decode_announce(b'{"app": "simple-chat", "type": "announce", "id": "a/b", "name": "n", "port": 5}') is None
    assert protocol.decode_announce(b"[1, 2]") is None


def test_message_is_one_line_even_with_newlines():
    m = ChatMessage("m1", "n1", "Laptop", 5000, "line one\nline two ☃", 1700000000.5)
    data = protocol.encode_message(m)
    assert data.count(b"\n") == 1 and data.endswith(b"\n")
    assert protocol.decode_line(data[:-1]) == m


def test_ack_round_trip_and_junk():
    assert protocol.decode_line(protocol.encode_ack(Ack("m1")).strip()) == Ack("m1")
    assert protocol.decode_line(b'{"type": "msg", "id": "m1"}') is None
    assert protocol.decode_line(b'{"type": "msg", "id": "m1", "from": "n", "name": "x", "port": 1, "text": "t", "at": true}') is None
    assert protocol.decode_line(b"\xff\xfe") is None


def test_line_reader_splits_and_buffers():
    r = LineReader()
    assert r.feed(b"one\ntw") == [b"one"]
    assert r.feed(b"o\nthree\n") == [b"two", b"three"]
    assert r.feed(b"") == []


def test_line_reader_refuses_endless_line():
    r = LineReader()
    r.feed(b"x" * (protocol.MAX_LINE_BYTES + 1))
    assert r.broken
    assert r.feed(b"\n") == []
