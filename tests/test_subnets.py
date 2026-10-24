from simple_chat.core.subnets import scan_targets


def test_a_home_network():
    targets = scan_targets([("192.168.1.201", 24)])
    assert len(targets) == 253  # 254 hosts minus this one
    assert targets[0] == "192.168.1.1" and "192.168.1.201" not in targets and "192.168.1.255" not in targets


def test_big_networks_are_cut_to_our_24():
    targets = scan_targets([("10.20.30.40", 16)])
    assert len(targets) == 253 and all(t.startswith("10.20.30.") for t in targets)


def test_loopback_link_local_and_junk_skipped_and_overlaps_merged():
    assert scan_targets([("127.0.0.1", 8), ("169.254.3.4", 16), ("nonsense", 24)]) == []
    both = scan_targets([("192.168.1.5", 24), ("192.168.1.6", 24)])
    assert len(both) == 252 and len(set(both)) == 252
