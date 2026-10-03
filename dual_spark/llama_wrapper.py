#!/usr/bin/python3
"""Standalone llama-server entry point that always uses the selected Spark pair."""

import json
import ipaddress
import os
from pathlib import Path
import re
import socket
import subprocess
import sys


INFORMATIONAL_FLAGS = {"--help", "-h", "--version"}
GUARD_REVISION = 2
DEVICE_QUERY_FLAGS = {"--list-devices"}
OVERRIDDEN_ENV = {
    "CUDA_VISIBLE_DEVICES", "LLAMA_ARG_DEVICE", "LLAMA_ARG_RPC",
    "LLAMA_ARG_SPLIT_MODE", "LLAMA_ARG_TENSOR_SPLIT", "LLAMA_ARG_N_GPU_LAYERS",
}


def informational(args):
    return any(arg.split("=", 1)[0] in INFORMATIONAL_FLAGS for arg in args)


def device_query(args):
    return any(arg.split("=", 1)[0] in DEVICE_QUERY_FLAGS for arg in args)


def sanitize_device_env(environment):
    for name in OVERRIDDEN_ENV:
        environment.pop(name, None)


def sanitize_local_env(environment):
    for name in ("LLAMA_ARG_RPC", "LLAMA_ARG_TENSOR_SPLIT", "LLAMA_ARG_SPLIT_MODE"):
        environment.pop(name, None)
    if "RPC" in environment.get("LLAMA_ARG_DEVICE", "").upper():
        environment.pop("LLAMA_ARG_DEVICE", None)


def connectx_cable_present(sys_class_net=Path("/sys/class/net")):
    """A missing hot-plugged NIC or all carriers down means no CX7 link."""
    for interface in sys_class_net.iterdir():
        driver = interface / "device/driver"
        if not driver.is_symlink() or driver.resolve().name != "mlx5_core":
            continue
        carrier = (interface / "carrier").read_text(encoding="ascii").strip()
        if carrier == "1":
            return True
        if carrier != "0":
            raise RuntimeError(f"Cannot determine ConnectX cable state on {interface.name}")
    return False


def validate_saved_pair(config):
    required = {"binary", "host_ip", "host_iface", "rpc"}
    if not isinstance(config, dict) or set(config) not in (required, required | {"guard_revision"}):
        raise RuntimeError("saved pair configuration is incomplete")
    if "guard_revision" in config and (type(config["guard_revision"]) is not int or config["guard_revision"] < 1):
        raise RuntimeError("saved pair guard revision is invalid")
    if not all(isinstance(config[key], str) and config[key] for key in required):
        raise RuntimeError("saved pair configuration is invalid")
    if not Path(config["binary"]).is_absolute() or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", config["host_iface"]):
        raise RuntimeError("saved pair paths or interface are invalid")
    try:
        host = ipaddress.ip_address(config["host_ip"])
        worker_text, port_text = config["rpc"].rsplit(":", 1)
        worker = ipaddress.ip_address(worker_text)
        port = int(port_text)
    except ValueError as exc:
        raise RuntimeError("saved pair network addresses are invalid") from exc
    if any(not isinstance(ip, ipaddress.IPv4Address) or not ip.is_private for ip in (host, worker)) or host == worker or not 1 <= port <= 65535:
        raise RuntimeError("saved pair network addresses are invalid")


def reject_placement_overrides(args, environment):
    if environment.get("LLAMA_ARG_OVERRIDE_TENSOR"):
        raise RuntimeError("tensor placement override is incompatible with the two-Spark guard")
    for arg in args:
        name = arg.split("=", 1)[0].replace("_", "-")
        if name in ("-ot", "--override-tensor"):
            raise RuntimeError("tensor placement override is incompatible with the two-Spark guard")


def _probe_args(args):
    filtered = []
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
            continue
        name = arg.split("=", 1)[0]
        if name in ("--rpc", "--device", "-dev"):
            skip_value = "=" not in arg
            continue
        filtered.append(arg)
    return filtered


def local_command(binary, args):
    """Remove stale two-node flags and let Studio/llama.cpp decide local fit."""
    result = []
    index = 0
    while index < len(args):
        arg = args[index]
        name = arg.split("=", 1)[0].replace("_", "-")
        if name in ("--rpc", "--tensor-split", "-ts", "--split-mode", "-sm"):
            index += 1 if "=" in arg else 2
            continue
        if name in ("--device", "-dev"):
            value = arg.split("=", 1)[1] if "=" in arg else (args[index + 1] if index + 1 < len(args) else "")
            if "RPC" in value.upper():
                index += 1 if "=" in arg else 2
                continue
            if "=" not in arg and index + 1 < len(args):
                result.extend((arg, value))
                index += 2
                continue
        result.append(arg)
        index += 1
    return [binary, *result]


def enforced_command(binary, args, endpoint):
    command = [binary, *args]
    if informational(args):
        return command
    if device_query(args):
        return [binary, "--rpc", endpoint, *_probe_args(args)]
    # llama.cpp applies repeated options in order; the final value wins.
    return command + [
        "--rpc", endpoint, "--device", "CUDA0,RPC0", "--split-mode", "layer", "--tensor-split", "1,1",
        "--n-gpu-layers", "all",
    ]


def route_matches_connectx(route_json, interface, host_ip):
    routes = json.loads(route_json)
    return bool(routes) and routes[0].get("dev") == interface and (
        routes[0].get("prefsrc") or routes[0].get("src") or routes[0].get("from")
    ) == host_ip


def require_peer(config):
    endpoint = config["rpc"]
    worker_ip, port = endpoint.rsplit(":", 1)
    route = subprocess.run(
        ["ip", "-j", "route", "get", worker_ip, "from", config["host_ip"]], capture_output=True, text=True,
        check=True, timeout=5,
    )
    if not route_matches_connectx(route.stdout, config["host_iface"], config["host_ip"]):
        raise RuntimeError("ConnectX-7 route changed; refusing a single-Spark model load")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as conn:
        conn.settimeout(5)
        conn.bind((config["host_ip"], 0))
        conn.connect((worker_ip, int(port)))


def main(args=None, config_path=None):
    args = sys.argv[1:] if args is None else args
    config_path = Path(config_path) if config_path is not None else Path(__file__).resolve().with_suffix(".json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    validate_saved_pair(config)
    binary = config["binary"]
    if Path(binary).resolve() == Path(__file__).resolve() or not Path(binary).is_file():
        raise RuntimeError("Configured llama-server binary is missing or points back to the wrapper")
    if informational(args):
        command = [binary, *args]
    elif connectx_cable_present():
        if not device_query(args):
            reject_placement_overrides(args, os.environ)
        sanitize_device_env(os.environ)
        require_peer(config)
        command = enforced_command(binary, args, config["rpc"])
        if not device_query(args):
            print(
                f"Connect Dual Spark: enforcing RPC {config['rpc']}, CUDA0+RPC0, and a 1:1 tensor split",
                file=sys.stderr, flush=True,
            )
    else:
        sanitize_local_env(os.environ)
        command = local_command(binary, _probe_args(args) if device_query(args) else args)
        if connectx_cable_present():
            raise RuntimeError("ConnectX-7 reconnected during standalone launch; retry the model load")
        if not device_query(args):
            print("Connect Dual Spark: no ConnectX cable; loading locally with Studio's memory settings", file=sys.stderr, flush=True)
    os.execv(binary, command)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Connect Dual Spark: {exc}", file=sys.stderr)
        raise SystemExit(78)
