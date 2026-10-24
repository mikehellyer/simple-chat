"""Which addresses a network scan should knock on."""
from __future__ import annotations

import ipaddress

# A network bigger than this (a /22 holds 1022 machines) is only scanned
# around this machine's own address, in its /24 — knocking on 65,000
# addresses of a /16 would take ages and find nothing more at home.
MAX_HOSTS = 1022


def scan_targets(networks: list[tuple[str, int]], own: set[str] | None = None) -> list[str]:
    """Every host address on the given networks — (this machine's address
    on it, prefix length) pairs — except this machine's own, in order and
    without duplicates. Loopback and link-local networks are skipped."""
    own = set(own or ()) | {ip for ip, _ in networks}
    targets: dict[str, None] = {}
    for ip, prefix in networks:
        try:
            address = ipaddress.IPv4Address(ip)
            network = ipaddress.IPv4Network(f"{ip}/{prefix}", strict=False)
        except ValueError:
            continue
        if address.is_loopback or address.is_link_local:
            continue
        if network.num_addresses - 2 > MAX_HOSTS:
            network = ipaddress.IPv4Network(f"{ip}/24", strict=False)
        for host in network.hosts():
            text = str(host)
            if text not in own:
                targets[text] = None
    return list(targets)
