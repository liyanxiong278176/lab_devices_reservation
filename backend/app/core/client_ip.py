"""Resolve client addresses without trusting arbitrary forwarding headers."""

from __future__ import annotations

from ipaddress import ip_address, ip_network


def resolve_client_ip(
    peer: str | None,
    forwarded_for: str | None,
    trusted_proxy_ips: list[str] | tuple[str, ...] = (),
) -> str:
    """Return the nearest untrusted address in a trusted proxy chain.

    X-Forwarded-For is ignored unless the direct TCP peer matches an explicitly
    configured proxy CIDR. Invalid or excessively long chains fail closed to
    the direct peer so attacker-controlled headers cannot create arbitrary keys.
    """
    if not peer:
        return "unknown"
    try:
        peer_ip = ip_address(peer)
        trusted = [ip_network(value, strict=False) for value in trusted_proxy_ips]
    except ValueError:
        return peer

    def is_trusted(address) -> bool:
        return any(address.version == network.version and address in network for network in trusted)

    if not forwarded_for or len(forwarded_for) > 1024 or not is_trusted(peer_ip):
        return str(peer_ip)
    raw_chain = [value.strip() for value in forwarded_for.split(",")]
    if not raw_chain or len(raw_chain) > 16:
        return str(peer_ip)
    try:
        chain = [ip_address(value) for value in raw_chain] + [peer_ip]
    except ValueError:
        return str(peer_ip)

    for address in reversed(chain):
        if not is_trusted(address):
            return str(address)
    return str(chain[0])
