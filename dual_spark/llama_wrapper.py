#!/usr/bin/python3
"""Standalone llama-server entry point that always uses the selected Spark pair."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys


INFORMATIONAL_FLAGS = {"--help", "-h", "--version"}
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


def main(args=None):
    args = sys.argv[1:] if args is None else args
    config_path = Path(__file__).resolve().with_suffix(".json")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    binary = config["binary"]
    if Path(binary).resolve() == Path(__file__).resolve() or not Path(binary).is_file():
        raise RuntimeError("Configured llama-server binary is missing or points back to the wrapper")
    if not informational(args):
        if not device_query(args):
            reject_placement_overrides(args, os.environ)
        sanitize_device_env(os.environ)
        require_peer(config)
        if not device_query(args):
            print(
                f"Connect Dual Spark: enforcing RPC {config['rpc']}, CUDA0+RPC0, and a 1:1 tensor split",
                file=sys.stderr, flush=True,
            )
    os.execv(binary, enforced_command(binary, args, config["rpc"]))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"Connect Dual Spark: {exc}", file=sys.stderr)
        raise SystemExit(78)
