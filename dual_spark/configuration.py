"""Generate the two small runtime configurations outside the Studio package."""

from __future__ import annotations

import ipaddress
from pathlib import Path
import re
import shlex


def private_ipv4(address: str) -> str:
    ip = ipaddress.ip_address(address)
    if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private or ip.is_loopback or ip.is_unspecified:
        raise ValueError(f"Expected a private ConnectX-7 IPv4 address, got {address!r}")
    return str(ip)


def rpc_command(binary: str, address: str, port: int) -> list[str]:
    if not Path(binary).is_absolute() or not 1 <= port <= 65535:
        raise ValueError("RPC binary must be absolute and port must be valid")
    return [binary, "--host", private_ipv4(address), "--port", str(port), "--cache"]


def rpc_system_unit(user: str, home: str, binary: str, address: str, port: int) -> str:
    """A system service; multi-user.target runs it before anyone logs in."""
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*[$]?", user):
        raise ValueError("Invalid worker username")
    for path in (home, binary):
        if not Path(path).is_absolute() or any(ch.isspace() for ch in path):
            raise ValueError("Worker service paths must be absolute and contain no whitespace")
    if not Path(binary).is_relative_to(home):
        raise ValueError("Worker RPC binary must be inside its home directory")
    command = " ".join(rpc_command(binary, address, port))
    working_dir = Path(binary).parent.parent
    return f"""[Unit]
Description=Connect Dual Spark llama.cpp RPC on ConnectX-7
Wants=network-online.target
After=network-online.target
RequiresMountsFor={home}
StartLimitIntervalSec=0

[Service]
Type=simple
User={user}
Environment=HOME={home}
WorkingDirectory={working_dir}
ExecStart={command}
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
LimitMEMLOCK=infinity
LimitNOFILE=65535
UMask=0077

[Install]
WantedBy=multi-user.target
"""


def bashrc_with_rpc(contents: str, address: str, port: int, source_dir: str | None = None) -> str:
    private_ipv4(address)
    if not 1 <= port <= 65535:
        raise ValueError("Invalid RPC port")
    if source_dir is not None and not Path(source_dir).is_absolute():
        raise ValueError("llama.cpp source directory must be absolute")
    begin = "# BEGIN Connect Dual Spark RPC"
    end = "# END Connect Dual Spark RPC"
    source_line = f"export UNSLOTH_LLAMA_CPP_PATH={shlex.quote(source_dir)}\n" if source_dir else ""
    block = f"{begin}\nexport LLAMA_ARG_RPC={address}:{port}\n{source_line}{end}\n"
    pattern = re.compile(re.escape(begin) + r"\n.*?\n" + re.escape(end) + r"\n?", re.DOTALL)
    if begin in contents:
        if not pattern.search(contents):
            raise ValueError("Existing Connect Dual Spark shell block is incomplete")
        return pattern.sub(block, contents, count=1)
    return contents.rstrip("\n") + "\n\n" + block


def studio_unit(address: str, port: int, studio_binary: str, source_dir: str | None = None) -> str:
    private_ipv4(address)
    if not 1 <= port <= 65535 or not Path(studio_binary).is_absolute():
        raise ValueError("Invalid Studio service arguments")
    if source_dir is not None and not Path(source_dir).is_absolute():
        raise ValueError("llama.cpp source directory must be absolute")
    source_environment = f"Environment=UNSLOTH_LLAMA_CPP_PATH={source_dir}\n" if source_dir else ""
    return f"""[Unit]
Description=Unsloth Studio with ConnectX-7 RPC
After=network-online.target

[Service]
Type=simple
UMask=0077
Environment=LLAMA_ARG_RPC={address}:{port}
{source_environment}ExecStart={studio_binary} studio --host 127.0.0.1 --port 8888 --silent
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""
