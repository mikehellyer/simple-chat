"""Two ChatNodes in one process, talking over real sockets on this machine."""
import socket
import time

import pytest
from PySide6.QtCore import QCoreApplication

from simple_chat.core.store import DELIVERED, ChatStore
from simple_chat.net.node import ChatNode


@pytest.fixture(scope="module")
def app():
    return QCoreApplication.instance() or QCoreApplication([])


def free_udp_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def spin(until, seconds=5.0):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QCoreApplication.processEvents()
        if until():
            return True
        time.sleep(0.01)
    return False


def make(name, discovery, node_id):
    store = ChatStore()
    node = ChatNode(store, node_id, name, discovery_port=discovery, message_port=0)
    assert node.start()
    return node, store


def introduce(a, b):
    """What discovery does, minus the broadcast (which a test machine may
    not route)."""
    a._hear(b.node_id, b.name, "127.0.0.1", b.port)
    b._hear(a.node_id, a.name, "127.0.0.1", a.port)


def test_message_is_delivered_and_acked(app):
    port = free_udp_port()
    a, a_store = make("Alpha", port, "aaaa")
    b, b_store = make("Beta", port, "bbbb")
    try:
        got = []
        b.message_received.connect(got.append)
        delivered = []
        a.message_delivered.connect(lambda mid, pid: delivered.append((mid, pid)))
        introduce(a, b)
        sent = a.send("bbbb", "hello\nfrom alpha")
        assert spin(lambda: delivered)
        assert got[0].text == "hello\nfrom alpha" and got[0].peer_id == "aaaa"
        assert delivered == [(sent.id, "bbbb")]
        assert a_store.conversation("bbbb")[0].status == DELIVERED
        assert b_store.peer("aaaa").name == "Alpha"
        # and back the other way, several at once
        for i in range(5):
            b.send("aaaa", f"reply {i}")
        assert spin(lambda: len(a_store.conversation("bbbb")) == 6 and not b_store.pending_for("aaaa"))
        assert [m.text for m in a_store.conversation("bbbb")][1:] == [f"reply {i}" for i in range(5)]
    finally:
        a.stop()
        b.stop()


def test_message_to_offline_machine_waits(app):
    port = free_udp_port()
    a, a_store = make("Alpha", port, "aaaa")
    a_store.remember_peer("bbbb", "Beta", "127.0.0.1", 1)  # known but never heard
    try:
        a.send("bbbb", "are you there?")
        spin(lambda: False, 0.3)
        assert len(a_store.pending_for("bbbb")) == 1
        b, b_store = make("Beta", port, "bbbb")
        try:
            introduce(a, b)  # it comes online
            assert spin(lambda: not a_store.pending_for("bbbb"))
            assert b_store.conversation("aaaa")[0].text == "are you there?"
        finally:
            b.stop()
    finally:
        a.stop()


def test_unreachable_machine_keeps_message_pending(app):
    port = free_udp_port()
    a, a_store = make("Alpha", port, "aaaa")
    try:
        with socket.socket() as closed:
            closed.bind(("127.0.0.1", 0))
            dead_port = closed.getsockname()[1]
        a._hear("bbbb", "Beta", "127.0.0.1", dead_port)
        a.send("bbbb", "lost?")
        assert spin(lambda: not a._senders)
        assert len(a_store.pending_for("bbbb")) == 1
    finally:
        a.stop()


def test_discovery_by_broadcast(app):
    port = free_udp_port()
    a, _ = make("Alpha", port, "aaaa")
    b, b_store = make("Beta", port, "bbbb")
    try:
        if not a._broadcast_targets():
            pytest.skip("no broadcast-capable network here")
        if not spin(lambda: a.is_online("bbbb") and b.is_online("aaaa"), 8):
            pytest.skip("broadcasts don't loop back on this machine")
        assert b_store.peer("aaaa").name == "Alpha"
    finally:
        a.stop()
        b.stop()


def test_scan_finds_machine_by_tcp(app):
    from simple_chat.net.scanner import NetworkScanner

    # separate discovery ports, so only the TCP knock can find Beta
    a, a_store = make("Alpha", free_udp_port(), "aaaa")
    b, _ = make("Beta", free_udp_port(), "bbbb")
    try:
        with socket.socket() as closed:  # a port with nothing listening
            closed.bind(("127.0.0.1", 0))
            dead = closed.getsockname()[1]
        results = []
        scanner = NetworkScanner(a, targets=["127.0.0.1"], port=b.port)
        scanner.finished.connect(results.append)
        progress = []
        scanner.progress.connect(lambda done, total: progress.append((done, total)))
        scanner.start()
        assert spin(lambda: results, 6)
        assert results[0].get("bbbb") == "127.0.0.1"
        assert a_store.peer("bbbb").name == "Beta" and a.is_online("bbbb")
        assert progress[-1] == (1, 1)
        # nothing there: finishes empty
        results.clear()
        empty = NetworkScanner(a, targets=["127.0.0.1"], port=dead)
        empty.finished.connect(results.append)
        empty.start()
        assert spin(lambda: results, 6) and "bbbb" not in results[0]
    finally:
        a.stop()
        b.stop()


def test_scan_can_be_cancelled(app):
    from simple_chat.net.scanner import NetworkScanner

    a, _ = make("Alpha", free_udp_port(), "aaaa")
    try:
        results = []
        scanner = NetworkScanner(a, targets=[f"10.255.{i // 250}.{i % 250 + 1}" for i in range(300)], port=9)
        scanner.finished.connect(results.append)
        scanner.start()
        spin(lambda: False, 0.2)
        scanner.cancel()
        assert results == [{}]
        spin(lambda: False, 0.3)
        assert len(results) == 1
    finally:
        a.stop()


def test_encrypted_machines_talk_and_others_cannot(app):
    import os

    from simple_chat.core.crypto import Channel

    key = os.urandom(32)
    port = free_udp_port()
    a, a_store = make("Alpha", port, "aaaa")
    b, b_store = make("Beta", port, "bbbb")
    c, c_store = make("Gamma", port, "cccc")  # no passphrase
    d, d_store = make("Delta", port, "dddd")  # a different one
    a.set_channel(Channel(key))
    b.set_channel(Channel(key))
    d.set_channel(Channel(os.urandom(32)))
    try:
        introduce(a, b)
        a.send("bbbb", "for Beta only")
        assert spin(lambda: not a_store.pending_for("bbbb"))
        assert b_store.conversation("aaaa")[0].text == "for Beta only"
        # machines on another passphrase (or none) get nothing through
        for other, store in ((c, c_store), (d, d_store)):
            introduce(a, other)
            a.send(other.node_id, "should not arrive")
            other.send("aaaa", "nor this")
        spin(lambda: False, 1.0)
        for store in (a_store, c_store, d_store):
            others = [p for p in ("aaaa", "cccc", "dddd") if store is not a_store or p != "aaaa"]
            received = [m for p in others for m in store.conversation(p) if not m.outgoing]
            assert received == []
        # each side's message is still waiting, unsent
        assert len(a_store.pending_for("cccc")) == 1 and len(a_store.pending_for("dddd")) == 1
        assert len(c_store.pending_for("aaaa")) == 1 and len(d_store.pending_for("aaaa")) == 1
        # the scan doesn't find them either, but does find Beta
        from simple_chat.net.scanner import NetworkScanner

        for target, expect in ((b, True), (c, False), (d, False)):
            results = []
            scanner = NetworkScanner(a, targets=["127.0.0.1"], port=target.port)
            scanner.finished.connect(results.append)
            a._heard.pop(target.node_id, None)
            scanner.start()
            assert spin(lambda: results, 6)
            assert (target.node_id in results[0]) == expect
    finally:
        for n in (a, b, c, d):
            n.stop()


def test_changing_passphrase_drops_old_machines(app):
    import os

    from simple_chat.core.crypto import Channel

    a, _ = make("Alpha", free_udp_port(), "aaaa")
    try:
        a._hear("bbbb", "Beta", "127.0.0.1", 9)
        assert a.is_online("bbbb")
        a.set_channel(Channel(os.urandom(32)))
        assert not a.is_online("bbbb")
    finally:
        a.stop()
