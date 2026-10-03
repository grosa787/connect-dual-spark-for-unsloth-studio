"""Identify the directly connected ConnectX-7 interface and peer."""

from dataclasses import dataclass
import ipaddress
import json


@dataclass(frozen=True)
class Link:
    interface: str
    address: str
    network: ipaddress.IPv4Network
    speed_mbps: int


def candidate_links(addresses_json: str, speeds_mbps: dict[str, int]) -> list[Link]:
    """Return active, numbered ConnectX-7 links negotiated at 100 Gb/s or more."""
    addresses = json.loads(addresses_json)
    links = []
    for item in addresses:
        name = item.get("ifname")
        if name not in speeds_mbps or "LOWER_UP" not in item.get("flags", []):
            continue
        speed = speeds_mbps.get(name, 0)
        if speed < 100000:
            continue
        for addr in item.get("addr_info", []):
            if addr.get("family") != "inet":
                continue
            interface = ipaddress.ip_interface(
                f"{addr['local']}/{addr['prefixlen']}"
            )
            if not interface.ip.is_private:
                continue
            links.append(Link(name, str(interface.ip), interface.network, speed))
    return links


def peer_candidates(link: Link, neighbors_json: str) -> list[str]:
    """Use the kernel's neighbor table before falling back to a bounded scan."""
    result = []
    for entry in json.loads(neighbors_json):
        try:
            address = ipaddress.ip_address(entry["dst"])
        except (KeyError, ValueError):
            continue
        if address not in link.network or str(address) == link.address:
            continue
        if set(entry.get("state", [])) & {"FAILED", "INCOMPLETE"}:
            continue
        if isinstance(address, ipaddress.IPv4Address):
            result.append(str(address))
    return sorted(set(result), key=ipaddress.ip_address)


def route_uses_link(link: Link, route_json: str) -> bool:
    """Reject routes that leave over the management LAN."""
    routes = json.loads(route_json)
    return bool(routes) and routes[0].get("dev") == link.interface and (
        routes[0].get("prefsrc") or routes[0].get("src")
    ) == link.address
