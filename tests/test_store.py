from simple_chat.core.store import DELIVERED, PENDING, ChatStore


def test_peers_are_remembered_and_updated():
    s = ChatStore()
    s.remember_peer("p1", "Pi", "192.168.1.9", 47475, seen_at=10)
    s.remember_peer("p1", "Kitchen Pi", "192.168.1.10", 47475, seen_at=20)
    s.remember_peer("p2", "attic", "192.168.1.11", 50000, seen_at=5)
    assert [p.name for p in s.peers()] == ["attic", "Kitchen Pi"]
    assert s.peer("p1").host == "192.168.1.10"
    assert s.peer("nope") is None


def test_outgoing_waits_until_delivered():
    s = ChatStore()
    s.add_outgoing("m1", "p1", "hello", 1.0)
    s.add_outgoing("m2", "p1", "again", 2.0)
    assert [m.id for m in s.pending_for("p1")] == ["m1", "m2"]
    assert s.mark_delivered("m1") == "p1"
    assert s.mark_delivered("m1") is None  # already marked
    assert [m.id for m in s.pending_for("p1")] == ["m2"]
    assert [m.status for m in s.conversation("p1")] == [DELIVERED, PENDING]


def test_incoming_duplicates_ignored_and_unread_counted():
    s = ChatStore()
    assert s.add_incoming("m1", "p1", "hi", 1.0) is not None
    assert s.add_incoming("m1", "p1", "hi", 1.0) is None
    s.add_incoming("m2", "p1", "there", 2.0)
    s.add_incoming("m3", "p2", "yo", 3.0)
    assert s.unread_counts() == {"p1": 2, "p2": 1}
    s.mark_read("p1")
    assert s.unread_counts() == {"p2": 1}


def test_conversation_is_latest_n_oldest_first():
    s = ChatStore()
    for i in range(10):
        s.add_outgoing(f"m{i}", "p1", str(i), float(i))
    assert [m.text for m in s.conversation("p1", limit=3)] == ["7", "8", "9"]


def test_forget_and_clear(tmp_path):
    path = tmp_path / "chat.db"
    s = ChatStore(path)
    s.remember_peer("p1", "Pi", "h", 1)
    s.add_incoming("m1", "p1", "hi", 1.0)
    s.add_incoming("m2", "p2", "hi", 1.0)
    s.close()
    s = ChatStore(path)  # survives a restart
    assert len(s.conversation("p1")) == 1
    s.clear_conversation("p2")
    assert s.conversation("p2") == []
    s.forget_peer("p1")
    assert s.peers() == [] and s.conversation("p1") == []
