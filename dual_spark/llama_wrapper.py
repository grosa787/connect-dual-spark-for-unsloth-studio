#!/usr/bin/python3
"""Standalone llama-server entry point that always uses the selected Spark pair."""

import json
import ipaddress
import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
import re
import socket
import subprocess
import sys


INFORMATIONAL_FLAGS = {"--help", "-h", "--version"}
GUARD_REVISION = 3
DEVICE_QUERY_FLAGS = {"--list-devices"}
FASTLOAD_FIELDS = {
    "upstream_root", "worker_user", "worker_home", "worker_exec_path", "worker_service",
}
LOAD_MODE_OPTIONS_WITH_VALUE = {"--load-mode", "-lm"}
PAIR_OPTIONS_WITH_VALUE = {
    "--rpc", "--device", "-dev", "--tensor-split", "-ts", "--split-mode", "-sm",
    "--n-gpu-layers", "--gpu-layers", "-ngl",
}
OVERRIDDEN_ENV = {
    "CUDA_VISIBLE_DEVICES", "LLAMA_ARG_DEVICE", "LLAMA_ARG_RPC",
    "LLAMA_ARG_SPLIT_MODE", "LLAMA_ARG_TENSOR_SPLIT", "LLAMA_ARG_N_GPU_LAYERS",
}


def informational(args):
    return any(arg.split("=", 1)[0] in INFORMATIONAL_FLAGS for arg in args)


def device_query(args):
    return any(arg.split("=", 1)[0] in DEVICE_QUERY_FLAGS for arg in args)


def sanitize_device_env(environment, *, fastload=False):
    for name in OVERRIDDEN_ENV:
        environment.pop(name, None)
    if fastload:
        environment.pop("LLAMA_ARG_LOAD_MODE", None)
        environment.pop("GGML_RPC_NO_RDMA", None)
        environment["GGML_RPC_NO_HASH_CACHE"] = "1"


def sanitize_local_env(environment):
    for name in ("LLAMA_ARG_RPC", "LLAMA_ARG_TENSOR_SPLIT", "LLAMA_ARG_SPLIT_MODE"):
        environment.pop(name, None)
    environment.pop("GGML_RPC_NO_HASH_CACHE", None)
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
    accepted = (required, required | {"guard_revision"}, required | {"guard_revision"} | FASTLOAD_FIELDS)
    if not isinstance(config, dict) or set(config) not in accepted:
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
    if FASTLOAD_FIELDS.issubset(config):
        if config.get("guard_revision", 0) < 3:
            raise RuntimeError("saved pair fastload guard revision is invalid")
        if not all(isinstance(config[key], str) and config[key] for key in FASTLOAD_FIELDS):
            raise RuntimeError("saved pair worker or upstream configuration is invalid")
        worker_home = Path(config["worker_home"])
        worker_exec_path = Path(config["worker_exec_path"])
        if (
            not Path(config["upstream_root"]).is_absolute()
            or not worker_home.is_absolute()
            or not worker_exec_path.is_absolute()
            or not worker_exec_path.is_relative_to(worker_home)
            or not re.fullmatch(r"[a-z_][a-z0-9_-]*[$]?", config["worker_user"])
            or not re.fullmatch(r"[a-zA-Z0-9_.@-]+\.service", config["worker_service"])
        ):
            raise RuntimeError("saved pair worker or upstream configuration is invalid")


def fastload_enabled(config):
    return FASTLOAD_FIELDS.issubset(config)


@contextmanager
def paired_launch_lock(path):
    """Keep the selected host/worker release fixed through the model's life."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH)
        os.set_inheritable(descriptor, True)
        yield descriptor
    finally:
        os.close(descriptor)


def reject_placement_overrides(args, environment):
    if environment.get("LLAMA_ARG_OVERRIDE_TENSOR"):
        raise RuntimeError("tensor placement override is incompatible with the two-Spark guard")
    for arg in args:
        name = arg.split("=", 1)[0].replace("_", "-")
        if name in ("-ot", "--override-tensor"):
            raise RuntimeError("tensor placement override is incompatible with the two-Spark guard")


def _strip_pair_options(args, *, fastload=False):
    filtered = []
    skip_value = False
    for arg in args:
        if skip_value:
            skip_value = False
            continue
        name = arg.split("=", 1)[0].replace("_", "-")
        if name in PAIR_OPTIONS_WITH_VALUE or (fastload and name in LOAD_MODE_OPTIONS_WITH_VALUE):
            skip_value = "=" not in arg
            continue
        filtered.append(arg)
    return filtered


def _probe_args(args):
    return _strip_pair_options(args)


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


def enforced_command(binary, args, endpoint, *, fastload=False):
    command = [binary, *args]
    if informational(args):
        return command
    if device_query(args):
        return [binary, "--rpc", endpoint, *_probe_args(args)]
    # --rpc registers devices as it is parsed, so remove old endpoints first.
    command = [binary, *_strip_pair_options(args, fastload=fastload)] + [
        "--rpc", endpoint, "--device", "CUDA0,RPC0", "--split-mode", "layer", "--tensor-split", "1,1",
        "--n-gpu-layers", "all",
    ]
    if fastload:
        command.extend(("--load-mode", "dio"))
    return command


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


def _read_guard_config(config_path):
    config = json.loads(Path(config_path).read_text(encoding="utf-8"))
    validate_saved_pair(config)
    return config


def _launch_connected(args, config_path):
    """Recheck the selected pair under a model-lifetime promotion barrier."""
    lock = config_path.parent / "fastload/.selection.lock"
    manager = config_path.with_name("fastload_manager.py")
    for _ in range(5):
        config = _read_guard_config(config_path)
        fastload = fastload_enabled(config)
        if not device_query(args):
            reject_placement_overrides(args, os.environ)
        require_peer(config)
        if fastload:
            if not manager.is_file():
                raise RuntimeError("Connect Dual Spark fastload manager is missing")
            result = subprocess.run([sys.executable, str(manager), "ensure", "--config", str(config_path)], check=False, timeout=3600)
            if result.returncode != 0:
                raise RuntimeError(f"Connect Dual Spark fastload refresh failed (exit {result.returncode})")
        with paired_launch_lock(lock):
            latest = _read_guard_config(config_path)
            if latest != config:
                continue
            if not connectx_cable_present():
                raise RuntimeError("ConnectX-7 disconnected before model launch; retry")
            require_peer(latest)
            if fastload:
                status = subprocess.run([sys.executable, str(manager), "status", "--config", str(config_path)], check=False, timeout=60)
                if status.returncode == 3:
                    continue
                if status.returncode != 0:
                    raise RuntimeError(f"Connect Dual Spark fastload verification failed (exit {status.returncode})")
            binary = latest["binary"]
            if Path(binary).resolve() == Path(__file__).resolve() or not Path(binary).is_file():
                raise RuntimeError("Configured llama-server binary is missing or points back to the wrapper")
            sanitize_device_env(os.environ, fastload=fastload)
            command = enforced_command(binary, args, latest["rpc"], fastload=fastload)
            if not device_query(args):
                print(
                    f"Connect Dual Spark: enforcing RPC {latest['rpc']}, CUDA0+RPC0, and a 1:1 tensor split",
                    file=sys.stderr, flush=True,
                )
            os.execv(binary, command)
            return
    raise RuntimeError("Pair configuration changed repeatedly before model launch")


def main(args=None, config_path=None):
    args = sys.argv[1:] if args is None else args
    config_path = Path(config_path) if config_path is not None else Path(__file__).resolve().with_suffix(".json")
    config = _read_guard_config(config_path)
    fastload = fastload_enabled(config)
    binary = config["binary"]
    if informational(args):
        if fastload:
            binary = str(Path(config["upstream_root"]) / "build/bin/llama-server")
        if Path(binary).resolve() == Path(__file__).resolve() or not Path(binary).is_file():
            raise RuntimeError("Configured llama-server binary is missing or points back to the wrapper")
        command = [binary, *args]
    elif connectx_cable_present():
        _launch_connected(args, config_path)
        return
    else:
        if fastload:
            binary = str(Path(config["upstream_root"]) / "build/bin/llama-server")
        if Path(binary).resolve() == Path(__file__).resolve() or not Path(binary).is_file():
            raise RuntimeError("Configured llama-server binary is missing or points back to the wrapper")
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
