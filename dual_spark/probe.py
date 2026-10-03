"""Read-only discovery of one reachable DGX Spark peer on ConnectX-7."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import ipaddress
import json
import re
import shlex
import socket
from typing import Callable

from .discovery import Link, candidate_links, peer_candidates, route_uses_link
from .language import msg


@dataclass(frozen=True)
class Peer:
    host_ip: str
    host_iface: str
    worker_ip: str
    worker_iface: str
    worker_user: str
    worker_home: str
    hostname: str
    speed_mbps: int


def _speed_mbps(output: str) -> int:
    match = re.search(r"Speed:\s*(\d+)\s*Mb/s", output)
    return int(match.group(1)) if match else 0


def _mlx5_driver(output: str) -> bool:
    return bool(re.search(r"^driver:\s*mlx5_core\s*$", output, re.MULTILINE))


def _tcp_ssh_open(local_ip: str, remote_ip: str) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conn:
        conn.settimeout(0.35)
        try:
            conn.bind((local_ip, 0))
            return conn.connect_ex((remote_ip, 22)) == 0
        except OSError:
            return False


def _scan_link(link: Link) -> list[str]:
    """Probe SSH only on a directly connected /24-or-smaller cluster subnet."""
    if link.network.num_addresses > 256:
        raise RuntimeError(msg(
            f"No peer in neighbor table for {link.interface}; subnet {link.network} is too large for automatic discovery",
            f"В таблице соседей интерфейса {link.interface} нет второго Spark; подсеть {link.network} слишком велика для автоматического поиска",
        ))
    candidates = [str(ip) for ip in link.network.hosts() if str(ip) != link.address]
    found = []
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {
            pool.submit(_tcp_ssh_open, link.address, candidate): candidate
            for candidate in candidates
        }
        for future in as_completed(futures):
            if future.result():
                found.append(futures[future])
    return sorted(found, key=ipaddress.ip_address)


class ClusterProbe:
    def __init__(self, run: Callable[..., str]):
        self.run = run

    def _ssh(self, link: Link, worker_ip: str, command: str) -> str:
        return self.run(
            [
                "ssh", "-b", link.address,
                "-o", f"BindInterface={link.interface}",
                "-o", "BatchMode=yes",
                "-o", "ConnectTimeout=5",
                "-o", "StrictHostKeyChecking=accept-new",
                worker_ip, command,
            ],
            timeout=12,
        )

    def _verify_candidate(self, link: Link, worker_ip: str) -> Peer | None:
        try:
            route = self.run(["ip", "-j", "route", "get", worker_ip])
            if not route_uses_link(link, route):
                return None
            user = self._ssh(link, worker_ip, "id -un").strip()
            home = self._ssh(link, worker_ip, 'printf %s "$HOME"').strip()
            hostname = self._ssh(link, worker_ip, "hostname").strip()
            remote_route = json.loads(self._ssh(link, worker_ip, f"ip -j route get {link.address}"))
            if not user or not home.startswith("/") or not hostname or not remote_route:
                return None
            remote = remote_route[0]
            remote_iface = remote.get("dev", "")
            if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", remote_iface):
                return None
            if (remote.get("prefsrc") or remote.get("src")) != worker_ip:
                return None
            if not _mlx5_driver(self._ssh(link, worker_ip, "ethtool -i " + shlex.quote(remote_iface))):
                return None
            if _speed_mbps(self._ssh(link, worker_ip, "ethtool " + shlex.quote(remote_iface))) < 100000:
                return None
        except Exception:
            return None
        return Peer(link.address, link.interface, worker_ip, remote_iface, user, home, hostname, link.speed_mbps)

    def detect(self) -> Peer:
        addresses_json = self.run(["ip", "-j", "-4", "addr", "show"])
        speeds = {}
        for item in json.loads(addresses_json):
            name = item.get("ifname")
            if name and "LOWER_UP" in item.get("flags", []):
                try:
                    if _mlx5_driver(self.run(["ethtool", "-i", name])):
                        speeds[name] = _speed_mbps(self.run(["ethtool", name]))
                except Exception:
                    pass
        links = candidate_links(addresses_json, speeds)
        if not links:
            raise RuntimeError(msg(
                "No active ConnectX-7 link with a private IPv4 address and at least 100 Gb/s; check the QSFP cable and NVIDIA Sync cluster",
                "Не найдено активное соединение ConnectX-7 с частным IPv4-адресом и скоростью не ниже 100 Гбит/с; проверьте кабель QSFP и кластер NVIDIA Sync",
            ))

        verified = []
        for link in links:
            neighbors = self.run(["ip", "-j", "neigh", "show", "dev", link.interface])
            candidates = peer_candidates(link, neighbors)
            accepted = [peer for ip in candidates if (peer := self._verify_candidate(link, ip)) is not None]
            if not accepted:
                accepted = [peer for ip in _scan_link(link) if ip not in candidates if (peer := self._verify_candidate(link, ip)) is not None]
            verified.extend(accepted)

        hostnames = {peer.hostname for peer in verified}
        if not verified:
            raise RuntimeError(msg(
                "ConnectX-7 is up, but no second Spark passed passwordless SSH and return-route checks. Run NVIDIA Sync Cluster Assistant first.",
                "ConnectX-7 работает, но второй Spark не прошёл проверки беспарольного SSH и обратного маршрута. Сначала настройте кластер через NVIDIA Sync Cluster Assistant.",
            ))
        if len(hostnames) != 1:
            raise RuntimeError(msg(
                f"More than one peer was discovered ({', '.join(sorted(hostnames))}); this installer supports exactly two Sparks",
                f"Обнаружено больше одного второго Spark ({', '.join(sorted(hostnames))}); установщик поддерживает ровно два Spark",
            ))
        return verified[0]
