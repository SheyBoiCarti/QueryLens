"""Network destination validation, DNS resolution, and SSRF prevention (Contract C03)."""

from __future__ import annotations

import ipaddress
import socket
from typing import Sequence

# Prohibited CIDR networks (Contract C03)
PROHIBITED_NETWORKS = [
    # Cloud metadata service
    ipaddress.ip_network("169.254.169.254/32"),
    # IPv4 Link-local
    ipaddress.ip_network("169.254.0.0/16"),
    # IPv4 Multicast
    ipaddress.ip_network("224.0.0.0/4"),
    # IPv4 Unspecified
    ipaddress.ip_network("0.0.0.0/32"),
    # IPv6 Link-local
    ipaddress.ip_network("fe80::/10"),
    # IPv6 Multicast
    ipaddress.ip_network("ff00::/8"),
    # IPv6 Unspecified
    ipaddress.ip_network("::/128"),
]

LOOPBACK_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
]


class NetworkSecurityError(Exception):
    """Raised when destination address violates network policy."""

    pass


def validate_destination_address(
    host: str,
    port: int,
    allow_loopback: bool | None = None,
    permitted_cidrs: Sequence[str] | None = None,
) -> str:
    """Resolve host using AF_UNSPEC and validate all IP addresses.

    Returns:
        The first validated numeric IP string to bind the socket directly.
    """
    if not (1 <= port <= 65535):
        raise NetworkSecurityError(f"Invalid port: {port}")

    from querylens.config import get_settings

    settings = get_settings()
    if allow_loopback is None:
        allow_loopback = (
            settings.network_allow_loopback
            if settings.network_allow_loopback is not None
            else settings.environment != "production"
        )
    if permitted_cidrs is None:
        permitted_cidrs = settings.source_permitted_cidrs
    permitted_nets = [ipaddress.ip_network(cidr) for cidr in permitted_cidrs] if permitted_cidrs else None

    try:
        # Resolve all A and AAAA records
        addr_info = socket.getaddrinfo(host, port, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise NetworkSecurityError(f"DNS resolution failed for host {host}: {e}") from e

    if not addr_info:
        raise NetworkSecurityError(f"No DNS records returned for host {host}")

    resolved_ips: list[ipaddress.IPv4Address | ipaddress.IPv6Address] = []
    for item in addr_info:
        sockaddr = item[4]
        ip_str = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            resolved_ips.append(
                ip_obj.ipv4_mapped if isinstance(ip_obj, ipaddress.IPv6Address) and ip_obj.ipv4_mapped else ip_obj
            )
        except ValueError:
            raise NetworkSecurityError(f"Invalid IP address returned: {ip_str}")

    # Validate EVERY resolved IP
    validated_ips: list[str] = []
    for ip_obj in resolved_ips:
        # Check prohibited networks
        for prohibited in PROHIBITED_NETWORKS:
            if ip_obj in prohibited:
                raise NetworkSecurityError(f"Destination {ip_obj} is in prohibited network {prohibited}")

        # Check loopback
        is_loopback = any(ip_obj in loopback_net for loopback_net in LOOPBACK_NETWORKS)
        if is_loopback and not allow_loopback:
            raise NetworkSecurityError(f"Loopback destination {ip_obj} prohibited in this environment")

        # Check operator permitted CIDRs if provided
        if permitted_nets is not None:
            if not any(ip_obj in net for net in permitted_nets):
                raise NetworkSecurityError(f"Destination {ip_obj} not within permitted CIDR ranges")

        private_allowed = (
            settings.network_allow_private
            if settings.network_allow_private is not None
            else settings.environment != "production"
        )
        if not ip_obj.is_global and not is_loopback and not private_allowed and permitted_nets is None:
            raise NetworkSecurityError("Private/reserved sources require an explicit permitted CIDR")
        validated_ips.append(str(ip_obj))

    # All answers must be valid (no mixed permitted/prohibited answers)
    if not validated_ips:
        raise NetworkSecurityError(f"Host {host} resolved to no permitted IP addresses")

    return validated_ips[0]
