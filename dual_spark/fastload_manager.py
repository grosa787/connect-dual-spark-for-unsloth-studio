#!/usr/bin/python3
"""Build and atomically select version-matched fastload host/worker pairs."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable, Mapping, Optional, Sequence

try:
    from .fastload import (
        UpstreamIdentity,
        build_id,
        manifest_matches,
        patch_rpc_source,
        read_upstream_identity,
    )
except ImportError:  # Allow the installed adjacent script to run directly.
    from fastload import (  # type: ignore
        UpstreamIdentity,
        build_id,
        manifest_matches,
        patch_rpc_source,
        read_upstream_identity,
    )


RPC_SOURCE = Path("ggml/src/ggml-rpc/ggml-rpc.cpp")
HOST_BINARY = Path("source/build/bin/llama-server")
HOST_RPC_LIBRARY = Path("source/build/bin/libggml-rpc.so")
WORKER_BINARY = Path("source/build/bin/ggml-rpc-server")
MANIFEST = Path("manifest.json")

CMAKE_FLAGS = (
    "-DGGML_CUDA=ON",
    "-DGGML_RPC=ON",
    "-DGGML_RPC_RDMA=ON",
    "-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc",
    "-DCMAKE_BUILD_TYPE=Release",
)

# A remote compiler must stop when its SSH channel disappears after a local
# updater timeout or crash. The helper owns the compiler process group and
# writes a small heartbeat to SSH stderr so a closed channel is noticed.
REMOTE_BUILD_GUARD_CODE = r'''
import os
import signal
import subprocess
import sys
import time

child = None

def stop_child():
    if child is None or child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()

def cancelled(signum, frame):
    stop_child()
    raise SystemExit(128 + signum)

for signum in (signal.SIGHUP, signal.SIGTERM, signal.SIGINT):
    signal.signal(signum, cancelled)

child = subprocess.Popen(sys.argv[1:], start_new_session=True, stdin=subprocess.DEVNULL)
while child.poll() is None:
    try:
        os.write(2, b".")
    except OSError:
        stop_child()
        raise SystemExit(143)
    time.sleep(0.25)
raise SystemExit(child.returncode)
'''

_REQUIRED_CONFIG = {
    "binary",
    "host_ip",
    "host_iface",
    "rpc",
    "guard_revision",
    "upstream_root",
    "worker_user",
    "worker_home",
    "worker_exec_path",
    "worker_service",
}


@dataclass(frozen=True)
class RefreshResult:
    state: str
    build_id: str
    changed: bool
    message: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_symlink(link: Path, target: Path) -> None:
    link.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = link.parent / f".{link.name}.{os.getpid()}.{time.time_ns()}"
    temporary.symlink_to(target)
    try:
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)


def _validated_config(config: Mapping[str, object], base_dir: Path) -> dict[str, object]:
    if not isinstance(config, Mapping) or not _REQUIRED_CONFIG.issubset(config):
        missing = sorted(_REQUIRED_CONFIG.difference(config if isinstance(config, Mapping) else ()))
        raise ValueError(f"Fastload guard configuration is incomplete: {', '.join(missing)}")
    result = dict(config)
    string_keys = _REQUIRED_CONFIG.difference({"guard_revision"})
    if any(not isinstance(result[key], str) or not result[key] for key in string_keys):
        raise ValueError("Fastload guard configuration contains invalid strings")
    if type(result["guard_revision"]) is not int or result["guard_revision"] < 1:
        raise ValueError("Fastload guard revision is invalid")

    for key in ("binary", "upstream_root", "worker_home", "worker_exec_path"):
        if not Path(str(result[key])).is_absolute():
            raise ValueError(f"Fastload configuration path {key} must be absolute")
    worker_home = Path(str(result["worker_home"]))
    worker_exec = Path(str(result["worker_exec_path"]))
    if any(
        not re.fullmatch(r"/[A-Za-z0-9._/-]+", str(result[key]))
        or ".." in Path(str(result[key])).parts
        for key in ("worker_home", "worker_exec_path")
    ):
        raise ValueError("Worker paths contain unsafe remote shell characters")
    if not worker_exec.is_relative_to(worker_home):
        raise ValueError("Worker executable path must be inside worker_home")
    if any(char.isspace() for key in ("worker_home", "worker_exec_path") for char in str(result[key])):
        raise ValueError("Worker paths cannot contain whitespace")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*[$]?", str(result["worker_user"])):
        raise ValueError("Worker username is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.@:-]+", str(result["worker_service"])):
        raise ValueError("Worker service name is invalid")
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", str(result["host_iface"])):
        raise ValueError("Host interface name is invalid")
    try:
        host = ipaddress.ip_address(str(result["host_ip"]))
        worker_text, port_text = str(result["rpc"]).rsplit(":", 1)
        worker = ipaddress.ip_address(worker_text)
        port = int(port_text)
    except ValueError as exc:
        raise ValueError("Fastload network configuration is invalid") from exc
    if (
        not isinstance(host, ipaddress.IPv4Address)
        or not isinstance(worker, ipaddress.IPv4Address)
        or not host.is_private
        or not worker.is_private
        or host == worker
        or not 1 <= port <= 65535
    ):
        raise ValueError("Fastload network configuration is invalid")

    expected_binary = base_dir / "fastload/current" / HOST_BINARY
    if Path(str(result["binary"])) != expected_binary:
        raise ValueError(f"Fastload binary must be the managed stable path {expected_binary}")
    return result


class CommandRunner:
    """External build and worker operations; all subprocesses use argv lists."""

    def __init__(self, *, run_process=subprocess.run, sleep=time.sleep) -> None:
        self._run_process = run_process
        self._sleep = sleep

    @staticmethod
    def _run_protected(argv: Sequence[str], env: Optional[Mapping[str, str]]):
        """Kill a build's whole process group if its manager is killed."""
        command = subprocess.Popen(
            list(argv), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, env=None if env is None else dict(env), start_new_session=True,
        )
        read_fd, write_fd = os.pipe()
        watchdog_code = (
            "import os,signal,sys,time; "
            "fd=int(sys.argv[1]); pgid=int(sys.argv[2]); "
            "done=os.read(fd,1); os.close(fd); "
            "\nif done != b'D':\n"
            " try: os.killpg(pgid,signal.SIGTERM)\n"
            " except ProcessLookupError: pass\n"
            " time.sleep(0.3)\n"
            " try: os.killpg(pgid,signal.SIGKILL)\n"
            " except ProcessLookupError: pass\n"
        )
        try:
            watchdog = subprocess.Popen(
                [sys.executable, "-c", watchdog_code, str(read_fd), str(command.pid)],
                pass_fds=(read_fd,), start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except BaseException:
            os.close(read_fd)
            os.close(write_fd)
            os.killpg(command.pid, signal.SIGTERM)
            command.wait(timeout=5)
            raise
        os.close(read_fd)
        try:
            stdout, stderr = command.communicate(timeout=3600)
            os.write(write_fd, b"D")
        except BaseException:
            try:
                os.killpg(command.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                command.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(command.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                command.wait()
            raise
        finally:
            os.close(write_fd)
            watchdog.wait(timeout=5)
        return subprocess.CompletedProcess(list(argv), command.returncode, stdout, stderr)

    def _run(self, command: Sequence[object], *, check: bool = True,
             env: Optional[Mapping[str, str]] = None):
        argv = [os.fspath(item) for item in command]
        if self._run_process is subprocess.run:
            completed = self._run_protected(argv, env)
        else:
            completed = self._run_process(
                argv, check=False, capture_output=True, text=True,
                env=None if env is None else dict(env),
            )
        if check and completed.returncode:
            detail = (completed.stderr or completed.stdout or "no diagnostic output").strip()
            raise RuntimeError(f"Command failed ({completed.returncode}): {shlex.join(argv)}: {detail}")
        return completed

    @staticmethod
    def _worker_parts(config: Mapping[str, object]):
        worker_ip, port = str(config["rpc"]).rsplit(":", 1)
        destination = f"{config['worker_user']}@{worker_ip}"
        ssh_base = [
            "ssh",
            "-b", str(config["host_ip"]),
            "-o", f"BindInterface={config['host_iface']}",
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=10",
            "-o", "StrictHostKeyChecking=accept-new",
        ]
        return worker_ip, int(port), destination, ssh_base

    def _remote(self, config: Mapping[str, object], command: Sequence[object],
                *, check: bool = True):
        _, _, destination, ssh_base = self._worker_parts(config)
        remote_command = shlex.join([os.fspath(item) for item in command])
        return self._run([*ssh_base, destination, remote_command], check=check)

    def _remote_build(self, config: Mapping[str, object], command: Sequence[object]):
        return self._remote(config, ["python3", "-c", REMOTE_BUILD_GUARD_CODE, *command])

    def _rsync(self, config: Mapping[str, object], source: Path, destination_path: str,
               *, directory: bool = False, exclude: Sequence[str] = ()) -> None:
        _, _, destination, ssh_base = self._worker_parts(config)
        command = ["rsync", "-a", "--protect-args"]
        for pattern in exclude:
            command.extend(("--exclude", pattern))
        if directory:
            command.append("--delete")
        command.extend(("-e", shlex.join(ssh_base)))
        source_text = f"{source}/" if directory else os.fspath(source)
        destination_text = f"{destination}:{destination_path}{'/' if directory else ''}"
        self._run([*command, source_text, destination_text])

    @staticmethod
    def _validate_version(output: str, identity: UpstreamIdentity) -> None:
        lowered = output.lower()
        release_number = re.search(r"\bb(\d+)", identity.release_tag.lower())
        if identity.source_commit[:7].lower() not in lowered:
            raise RuntimeError("Built llama-server version does not match the installed source commit")
        if release_number and not re.search(rf"\b(?:b)?{re.escape(release_number.group(1))}\b", lowered):
            raise RuntimeError("Built llama-server version does not match the installed b-number")

    def build_host(self, source: Path, flags: Sequence[str], identity: UpstreamIdentity) -> Path:
        build_dir = source / "build"
        self._run(["cmake", "-S", source, "-B", build_dir, "-G", "Unix Makefiles", *flags])
        self._run(["cmake", "--build", build_dir, "--target", "llama-server", "-j", "4"])
        binary = source / "build/bin/llama-server"
        rpc_library = source / "build/bin/libggml-rpc.so"
        if not binary.is_file() or not os.access(binary, os.X_OK) or not rpc_library.is_file():
            raise RuntimeError("Host build did not produce executable llama-server and libggml-rpc.so")
        version = self._run([binary, "--version"])
        self._validate_version((version.stdout or "") + (version.stderr or ""), identity)
        linkage = self._run(["ldd", binary]).stdout or ""
        if "libggml-rpc.so" not in linkage or str(rpc_library.parent) not in linkage:
            raise RuntimeError("Built llama-server does not load its versioned patched RPC backend")
        return binary

    def stage_worker(self, source: Path, release_id: str, config: Mapping[str, object],
                     flags: Sequence[str], *, clean: bool = False,
                     expected_sha256: Optional[str] = None) -> str:
        if not re.fullmatch(r"[0-9a-f]{64}", release_id):
            raise ValueError("Worker release ID must be a SHA-256 digest")
        worker_base = Path(str(config["worker_home"])) / ".local/share/connect-dual-spark/fastload"
        release = worker_base / "releases" / release_id
        remote_source = release / "source"
        build_dir = remote_source / "build"
        backup = remote_source / f".build.before-repair-{os.getpid()}-{time.time_ns()}" if clean else None
        self._remote(config, ["mkdir", "-p", remote_source])
        preserved = bool(clean and self._remote(config, ["test", "-d", build_dir], check=False).returncode == 0)
        if preserved:
            self._remote(config, ["mv", build_dir, backup])
        try:
            self._rsync(
                config, source, os.fspath(remote_source), directory=True,
                exclude=("build/", ".git/", ".build.before-repair-*/"),
            )
            for relative in (RPC_SOURCE, Path("BUILD_INFO.txt"), Path("UNSLOTH_PREBUILT_INFO.json")):
                remote_hash = self._remote(config, ["sha256sum", remote_source / relative]).stdout.split()
                if not remote_hash or remote_hash[0] != _sha256(source / relative):
                    raise RuntimeError(f"Worker source identity mismatch for {relative}")
            self._remote_build(config, ["cmake", "-S", remote_source, "-B", build_dir, "-G", "Unix Makefiles", *flags])
            self._remote_build(config, ["cmake", "--build", build_dir, "--target", "ggml-rpc-server", "-j", "4"])
            worker_binary = release / WORKER_BINARY
            self._remote(config, ["test", "-x", worker_binary])
            hash_output = self._remote(config, ["sha256sum", worker_binary]).stdout.split()
            if not hash_output or not re.fullmatch(r"[0-9a-f]{64}", hash_output[0]):
                raise RuntimeError("Could not verify worker ggml-rpc-server")
            if expected_sha256 is not None and hash_output[0] != expected_sha256:
                raise RuntimeError("Clean worker rebuild differs from the verified release manifest")
        except Exception:
            if clean:
                self._remote(config, ["rm", "-rf", build_dir], check=False)
                if preserved:
                    self._remote(config, ["mv", backup, build_dir])
            raise
        if preserved:
            self._worker_repair_backups = getattr(self, "_worker_repair_backups", [])
            self._worker_repair_backups.append((config, backup))
        return hash_output[0]

    def cleanup_worker_repairs(self) -> None:
        """Drop old mapped worker builds only after a new process was verified."""
        pending = getattr(self, "_worker_repair_backups", [])
        for config, backup in pending:
            self._remote(config, ["rm", "-rf", backup], check=False)
        self._worker_repair_backups = []

    def restore_worker_repairs(self) -> None:
        """Put a preserved running build back before restarting the old service."""
        pending = getattr(self, "_worker_repair_backups", [])
        for config, backup in reversed(pending):
            build_dir = backup.parent / "build"
            self._remote(config, ["rm", "-rf", build_dir])
            self._remote(config, ["mv", backup, build_dir])
        self._worker_repair_backups = []

    def prune_worker_releases(self, config: Mapping[str, object], keep_ids) -> None:
        """Retain the selected release and one rollback release on the worker."""
        if any(not re.fullmatch(r"[0-9a-f]{64}", release_id) for release_id in keep_ids):
            raise ValueError("Cannot prune worker releases with an invalid keep ID")
        releases = Path(str(config["worker_home"])) / ".local/share/connect-dual-spark/fastload/releases"
        if self._remote(config, ["test", "-d", releases], check=False).returncode:
            return
        listing = self._remote(config, [
            "find", releases, "-mindepth", "1", "-maxdepth", "1", "-type", "d", "-printf", "%f\n",
        ])
        for name in (listing.stdout or "").splitlines():
            if re.fullmatch(r"[0-9a-f]{64}", name) and name not in keep_ids:
                self._remote(config, ["rm", "-rf", releases / name])

    def worker_current_build(self, config: Mapping[str, object]) -> Optional[str]:
        current = Path(str(config["worker_home"])) / ".local/share/connect-dual-spark/fastload/current-worker"
        result = self._remote(config, ["readlink", current], check=False)
        if result.returncode:
            return None
        target = (result.stdout or "").strip()
        return Path(target).name if target else None

    def worker_service_installed(self, config: Mapping[str, object]) -> bool:
        result = self._remote(
            config,
            ["systemctl", "show", "--property", "LoadState", "--value", config["worker_service"]],
            check=False,
        )
        return result.returncode == 0 and (result.stdout or "").strip() not in ("", "not-found")

    def worker_runtime_digest(self, config: Mapping[str, object], release_id: str) -> str:
        """Hash the worker's adjacent shared libraries and verify linker resolution."""
        binary_dir = (
            Path(str(config["worker_home"]))
            / ".local/share/connect-dual-spark/fastload/releases"
            / release_id / "source/build/bin"
        )
        script = r'''
from pathlib import Path
import hashlib, json, os, subprocess, sys
root = Path(sys.argv[1])
entries = {}
for path in sorted(root.glob("libggml*.so*")):
    if path.is_symlink():
        entries[path.name] = "link:" + os.readlink(path)
    elif path.is_file():
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        entries[path.name] = digest.hexdigest()
if "libggml-rpc.so" not in entries or "libggml-cuda.so" not in entries:
    raise SystemExit("worker RPC or CUDA library is missing")
for target in (root / "ggml-rpc-server", root / "libggml-rpc.so"):
    linked = subprocess.run(["ldd", str(target)], capture_output=True, text=True)
    if linked.returncode or "not found" in linked.stdout or "not found" in linked.stderr:
        raise SystemExit("worker shared library resolution failed")
print(hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest())
'''
        result = self._remote(config, ["python3", "-c", script, binary_dir])
        digest = (result.stdout or "").strip()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError("Could not verify worker shared library digest")
        return digest

    def worker_staged_matches(self, config: Mapping[str, object], release_id: str,
                              expected_sha256: str, expected_runtime_digest: Optional[str] = None) -> bool:
        binary = (
            Path(str(config["worker_home"]))
            / ".local/share/connect-dual-spark/fastload/releases"
            / release_id
            / WORKER_BINARY
        )
        if self._remote(config, ["test", "-x", binary], check=False).returncode:
            return False
        result = self._remote(config, ["sha256sum", binary], check=False)
        fields = (result.stdout or "").split()
        if result.returncode or not fields or fields[0] != expected_sha256:
            return False
        if expected_runtime_digest is None:
            return True
        try:
            return self.worker_runtime_digest(config, release_id) == expected_runtime_digest
        except (RuntimeError, OSError, ValueError):
            return False

    def worker_matches(self, config: Mapping[str, object], release_id: str,
                       expected_sha256: str, expected_runtime_digest: Optional[str] = None) -> bool:
        if self.worker_current_build(config) != release_id or not self.worker_service_installed(config):
            return False
        pid = self._main_pid(config)
        if pid <= 0:
            return False
        expected_binary = (
            Path(str(config["worker_home"]))
            / ".local/share/connect-dual-spark/fastload/releases"
            / release_id
            / WORKER_BINARY
        )
        executable = self._remote(config, ["readlink", "-f", f"/proc/{pid}/exe"], check=False)
        if executable.returncode or (executable.stdout or "").strip() != os.fspath(expected_binary):
            return False
        return self.worker_staged_matches(config, release_id, expected_sha256, expected_runtime_digest)

    def ensure_worker_launcher(self, config: Mapping[str, object]) -> bool:
        executable = Path(str(config["worker_exec_path"]))
        worker_target = (
            Path(str(config["worker_home"]))
            / ".local/share/connect-dual-spark/fastload/current-worker"
            / WORKER_BINARY
        )
        launcher = f"#!/bin/sh\nset -eu\nexec {shlex.quote(os.fspath(worker_target))} \"$@\"\n"
        with tempfile.TemporaryDirectory() as temporary_dir:
            local = Path(temporary_dir) / executable.name
            local.write_text(launcher, encoding="utf-8")
            local.chmod(0o700)
            remote_temporary = executable.parent / f".{executable.name}.new.{os.getpid()}"
            self._remote(config, ["mkdir", "-p", executable.parent])
            exists = self._remote(config, ["test", "-e", executable], check=False).returncode == 0
            backup = executable.with_name(executable.name + ".before-connect-dual-spark")
            if exists and self._remote(config, ["test", "-e", backup], check=False).returncode:
                self._remote(config, ["cp", "-p", executable, backup])
            self._rsync(config, local, os.fspath(remote_temporary))
            self._remote(config, ["chmod", "700", remote_temporary])
            self._remote(config, ["mv", "-f", remote_temporary, executable])
        return exists

    def restore_worker_launcher(self, config: Mapping[str, object]) -> None:
        executable = Path(str(config["worker_exec_path"]))
        backup = executable.with_name(executable.name + ".before-connect-dual-spark")
        temporary = executable.parent / f".{executable.name}.restore.{os.getpid()}"
        if self._remote(config, ["test", "-e", backup], check=False).returncode:
            raise RuntimeError("Preserved worker executable is missing; cannot roll back migration")
        self._remote(config, ["cp", "-p", backup, temporary])
        self._remote(config, ["mv", "-f", temporary, executable])

    def select_worker(self, config: Mapping[str, object], release_id: Optional[str]) -> None:
        worker_base = Path(str(config["worker_home"])) / ".local/share/connect-dual-spark/fastload"
        current = worker_base / "current-worker"
        if release_id is None:
            self._remote(config, ["rm", "-f", current])
            return
        temporary = worker_base / f".current-worker.{os.getpid()}.{time.time_ns()}"
        self._remote(config, ["mkdir", "-p", worker_base])
        self._remote(config, ["ln", "-s", f"releases/{release_id}", temporary])
        try:
            self._remote(config, ["mv", "-Tf", temporary, current])
        finally:
            self._remote(config, ["rm", "-f", temporary], check=False)

    def _main_pid(self, config: Mapping[str, object]) -> int:
        result = self._remote(
            config,
            ["systemctl", "show", "--property", "MainPID", "--value", config["worker_service"]],
        )
        try:
            return int((result.stdout or "").strip())
        except ValueError as exc:
            raise RuntimeError("Worker service returned an invalid MainPID") from exc

    def _wait_for_pid(self, config: Mapping[str, object], *, previous: int = 0) -> int:
        for _ in range(30):
            self._sleep(0.5)
            candidate = self._main_pid(config)
            if candidate > 0 and candidate != previous:
                return candidate
        raise RuntimeError("Worker service did not restart with a new MainPID")

    def _verify_process_owner(self, config: Mapping[str, object], pid: int) -> None:
        expected_uid = (self._remote(config, ["id", "-u", config["worker_user"]]).stdout or "").strip()
        process_uid = (self._remote(config, ["stat", "-c", "%u", f"/proc/{pid}"]).stdout or "").strip()
        if not expected_uid or process_uid != expected_uid:
            raise RuntimeError("Worker service MainPID is not owned by the configured worker user")

    def _verify_listener(self, config: Mapping[str, object]) -> None:
        worker_ip, port = str(config["rpc"]).rsplit(":", 1)
        expected_endpoint = f"{worker_ip}:{port}"
        for _ in range(20):
            listeners = (self._remote(config, ["ss", "-H", "-ltnp"]).stdout or "").splitlines()
            rpc_listeners = [
                line.split()[3] for line in listeners
                if len(line.split()) >= 4
                and line.split()[3].endswith(f":{port}")
                and "ggml-rpc-server" in line
            ]
            if rpc_listeners and all(address == expected_endpoint for address in rpc_listeners):
                return
            self._sleep(0.5)
        raise RuntimeError("Worker RPC server is not listening only on the configured CX7 address")

    def restart_and_verify_worker(self, config: Mapping[str, object], release_id: str,
                                  expected_sha256: Optional[str] = None,
                                  expected_runtime_digest: Optional[str] = None) -> None:
        old_pid = self._main_pid(config)
        if old_pid <= 0:
            raise RuntimeError("Worker service is not active; cannot restart it without root")
        self._verify_process_owner(config, old_pid)
        self._remote(config, ["kill", "-TERM", str(old_pid)])
        new_pid = self._wait_for_pid(config, previous=old_pid)
        self._verify_process_owner(config, new_pid)

        expected_binary = (
            Path(str(config["worker_home"]))
            / ".local/share/connect-dual-spark/fastload/releases"
            / release_id
            / WORKER_BINARY
        )
        actual_binary = (self._remote(config, ["readlink", "-f", f"/proc/{new_pid}/exe"]).stdout or "").strip()
        if actual_binary != os.fspath(expected_binary):
            raise RuntimeError("Worker service restarted with the wrong executable")
        if expected_sha256 is not None:
            actual_hash = self._remote(config, ["sha256sum", expected_binary]).stdout.split()
            if not actual_hash or actual_hash[0] != expected_sha256:
                raise RuntimeError("Restarted worker executable hash does not match the staged build")
        if expected_runtime_digest is not None and self.worker_runtime_digest(config, release_id) != expected_runtime_digest:
            raise RuntimeError("Restarted worker shared libraries differ from the staged build")

        self._verify_listener(config)

    def restart_and_verify_legacy_worker(self, config: Mapping[str, object]) -> None:
        executable = os.fspath(Path(str(config["worker_exec_path"])))
        pid = self._main_pid(config)
        if pid > 0:
            self._verify_process_owner(config, pid)
            actual = self._remote(config, ["readlink", "-f", f"/proc/{pid}/exe"], check=False)
            if actual.returncode or (actual.stdout or "").strip() != executable:
                self._remote(config, ["kill", "-TERM", str(pid)])
                pid = self._wait_for_pid(config, previous=pid)
        else:
            pid = self._wait_for_pid(config)
        self._verify_process_owner(config, pid)
        actual = (self._remote(config, ["readlink", "-f", f"/proc/{pid}/exe"]).stdout or "").strip()
        if actual != executable:
            raise RuntimeError("Worker rollback restarted with the wrong legacy executable")
        self._verify_listener(config)


def _stderr_progress(message: str) -> None:
    print(f"fastload: {message}", file=sys.stderr, flush=True)


class FastloadManager:
    def __init__(self, base_dir: Optional[Path] = None, *, runner=None,
                 model_active: Optional[Callable[[], bool]] = None,
                 progress: Optional[Callable[[str], None]] = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else Path(__file__).resolve().parent
        self.fastload_root = self.base_dir / "fastload"
        self.releases_dir = self.fastload_root / "releases"
        self.current_link = self.fastload_root / "current"
        self.lock_path = self.fastload_root / ".refresh.lock"
        self.selection_lock_path = self.fastload_root / ".selection.lock"
        self.guard_path = self.base_dir / "llama-server-wrapper.py"
        self.runner = runner if runner is not None else CommandRunner()
        self._model_active = model_active if model_active is not None else self._default_model_active
        self._progress = progress if progress is not None else _stderr_progress

    def _default_model_active(self) -> bool:
        completed = subprocess.run(
            ["pgrep", "-x", "llama-server"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return completed.returncode == 0

    def _manifest(self) -> Optional[dict[str, object]]:
        try:
            value = json.loads((self.current_link / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    @staticmethod
    def _expected_release(root: Path, identity: UpstreamIdentity):
        rpc_text = (root / RPC_SOURCE).read_text(encoding="utf-8")
        patched = patch_rpc_source(rpc_text)
        patch_digest = hashlib.sha256(patched.encode("utf-8")).hexdigest()
        return build_id(identity, patch_digest, CMAKE_FLAGS), patch_digest, patched

    @staticmethod
    def _manifest_record_matches(manifest: Mapping[str, object], identity: UpstreamIdentity,
                                 release_id: str, patch_digest: str,
                                 config: Mapping[str, object], host_binary: Path, host_rpc: Path) -> bool:
        return (
            manifest.get("build_id") == release_id
            and manifest.get("patch_digest") == patch_digest
            and manifest.get("cmake_flags") == list(CMAKE_FLAGS)
            and manifest.get("worker_service") == config["worker_service"]
            and manifest_matches(manifest, identity, {"host": host_binary, "host_rpc": host_rpc})
        )

    def _current_matches(self, config: Mapping[str, object], root: Path,
                         identity: UpstreamIdentity) -> bool:
        manifest = self._manifest()
        if manifest is None or manifest.get("upstream_identity") != asdict(identity):
            return False
        release_id, patch_digest, _patched = self._expected_release(root, identity)
        if not self._manifest_record_matches(
            manifest, identity, release_id, patch_digest, config,
            self.current_link / HOST_BINARY, self.current_link / HOST_RPC_LIBRARY,
        ):
            return False
        worker_hash = manifest.get("worker_binary_sha256")
        worker_runtime = manifest.get("worker_runtime_digest")
        return (
            isinstance(worker_hash, str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", worker_hash))
            and isinstance(worker_runtime, str)
            and bool(re.fullmatch(r"[0-9a-f]{64}", worker_runtime))
            and self.runner.worker_matches(config, release_id, worker_hash, worker_runtime)
        )

    def _lock(self):
        self.fastload_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        handle = self.lock_path.open("a+")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return handle

    @contextmanager
    def _promotion_gate(self):
        """Never switch the worker while a guarded model holds its release."""
        self.fastload_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.selection_lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                yield False
                return
            yield True
        finally:
            os.close(descriptor)

    def status(self, config: Mapping[str, object], *, install_root: Optional[Path] = None) -> dict[str, object]:
        checked = _validated_config(config, self.base_dir)
        root = Path(install_root) if install_root is not None else Path(str(checked["upstream_root"]))
        try:
            identity = read_upstream_identity(root)
        except ValueError as exc:
            return {"state": "degraded", "message": str(exc), "current_build_id": None}
        manifest = self._manifest()
        current_id = manifest.get("build_id") if manifest else None
        try:
            self._expected_release(root, identity)
            current = self._current_matches(checked, root, identity)
        except (RuntimeError, ValueError) as exc:
            return {
                "state": "degraded",
                "message": str(exc),
                "current_build_id": current_id,
                "upstream_identity": asdict(identity),
            }
        if current:
            return {
                "state": "current",
                "message": "fastload matches the installed Unsloth source",
                "current_build_id": current_id,
                "upstream_identity": asdict(identity),
            }
        return {
            "state": "stale" if manifest else "missing",
            "message": "fastload does not match the installed Unsloth source",
            "current_build_id": current_id,
            "upstream_identity": asdict(identity),
        }

    def ensure(self, config: Mapping[str, object], *, update_hook: bool = False,
               install_root: Optional[Path] = None) -> RefreshResult:
        return self._run_refresh(config, install_root=install_root, update_hook=update_hook)

    def refresh(self, config: Mapping[str, object], *, update_hook: bool = False,
                install_root: Optional[Path] = None) -> RefreshResult:
        return self._run_refresh(config, install_root=install_root, update_hook=update_hook)

    def _run_refresh(self, config: Mapping[str, object], *, install_root: Optional[Path],
                     update_hook: bool) -> RefreshResult:
        del update_hook  # It identifies the caller; safety rules are identical for every caller.
        checked = _validated_config(config, self.base_dir)
        root = Path(install_root) if install_root is not None else Path(str(checked["upstream_root"]))
        with self._lock():
            # An official update replaces the whole tree. Restore the guarded
            # entry point before any slow build or active-model deferral.
            self.repair_guard(checked, root)
            identity = read_upstream_identity(root)
            if self._current_matches(checked, root, identity):
                self.repair_guard(checked, root)
                manifest = self._manifest() or {}
                return RefreshResult(
                    "current",
                    str(manifest.get("build_id", "")),
                    False,
                    "fastload already matches the installed Unsloth source",
                )
            return self._stage_and_promote(checked, root, identity)

    def _prepare_release(self, config: Mapping[str, object], root: Path,
                         identity: UpstreamIdentity, release_id: str,
                         patch_digest: str, patched: str):
        release = self.releases_dir / release_id
        existing_manifest = self._read_release_manifest(release)
        if existing_manifest is not None and self._manifest_record_matches(
            existing_manifest,
            identity,
            release_id,
            patch_digest,
            config,
            release / HOST_BINARY,
            release / HOST_RPC_LIBRARY,
        ):
            worker_hash = existing_manifest.get("worker_binary_sha256")
            worker_runtime = existing_manifest.get("worker_runtime_digest")
            if (
                isinstance(worker_hash, str)
                and re.fullmatch(r"[0-9a-f]{64}", worker_hash)
                and isinstance(worker_runtime, str)
                and re.fullmatch(r"[0-9a-f]{64}", worker_runtime)
                and _sha256(release / "source" / RPC_SOURCE) == patch_digest
            ):
                return release_id, release, worker_hash

        if (
            release.exists()
            and self.current_link.is_symlink()
            and self.current_link.resolve() == release.resolve()
        ):
            raise RuntimeError(
                "Selected fastload release failed manifest verification; refusing to overwrite it in place"
            )
        if release.exists():
            shutil.rmtree(release)
        self.releases_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = release / "source"
        self._progress(f"copying installed source for release {release_id[:12]}")

        def ignore(directory, names):
            ignored = {name for name in names if name in ("build", ".git")}
            if Path(directory) == root:
                ignored.update(
                    name for name in names
                    if name == "llama-server" or name.startswith("llama-server.before-connect-dual-spark")
                )
            return ignored

        shutil.copytree(
            root,
            source,
            symlinks=True,
            ignore=ignore,
        )
        copied_hashes = (
            _sha256(source / "BUILD_INFO.txt"),
            _sha256(source / "UNSLOTH_PREBUILT_INFO.json"),
            _sha256(source / RPC_SOURCE),
        )
        expected_hashes = (
            identity.build_info_sha256,
            identity.prebuilt_info_sha256,
            identity.rpc_source_sha256,
        )
        if copied_hashes != expected_hashes or read_upstream_identity(root) != identity:
            raise ValueError("Installed Unsloth tree changed while staging fastload source")
        (source / RPC_SOURCE).write_text(patched, encoding="utf-8")
        self._progress("building versioned host llama-server (this can take several minutes)")
        host_binary = self.runner.build_host(source, CMAKE_FLAGS, identity)
        if Path(host_binary) != release / HOST_BINARY:
            raise RuntimeError("Host builder returned a binary outside the versioned release")
        self._progress("syncing source and building versioned worker ggml-rpc-server")
        worker_hash = self.runner.stage_worker(source, release_id, config, CMAKE_FLAGS)
        worker_runtime = self.runner.worker_runtime_digest(config, release_id)
        manifest = {
            "build_id": release_id,
            "upstream_identity": asdict(identity),
            "patch_digest": patch_digest,
            "cmake_flags": list(CMAKE_FLAGS),
            "binaries": {
                "host": _sha256(host_binary),
                "host_rpc": _sha256(release / HOST_RPC_LIBRARY),
            },
            "worker_binary_sha256": worker_hash,
            "worker_runtime_digest": worker_runtime,
            "worker_service": config["worker_service"],
        }
        _atomic_json(release / MANIFEST, manifest)
        return release_id, release, worker_hash

    @staticmethod
    def _read_release_manifest(release: Path) -> Optional[dict[str, object]]:
        try:
            value = json.loads((release / MANIFEST).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return value if isinstance(value, dict) else None

    def _stage_and_promote(self, config: Mapping[str, object], root: Path,
                           identity: UpstreamIdentity) -> RefreshResult:
        release_id, patch_digest, patched = self._expected_release(root, identity)
        if self._model_active():
            self._progress("active llama-server detected; deferring refresh before changing releases")
            return self._deferred(release_id)
        keep = {release_id}
        if self.current_link.is_symlink() and re.fullmatch(r"[0-9a-f]{64}", self.current_link.readlink().name):
            keep.add(self.current_link.readlink().name)
        try:
            selected_worker = self.runner.worker_current_build(config)
            if selected_worker is not None and re.fullmatch(r"[0-9a-f]{64}", selected_worker):
                keep.add(selected_worker)
            self._prune_host_releases(keep)
            self.runner.prune_worker_releases(config, keep)
        except (OSError, RuntimeError, ValueError) as exc:
            self._progress(f"old release cleanup deferred: {exc}")
        release_id, _release, worker_hash = self._prepare_release(
            config, root, identity, release_id, patch_digest, patched
        )
        worker_runtime = self._read_release_manifest(_release).get("worker_runtime_digest")
        if not isinstance(worker_runtime, str) or not re.fullmatch(r"[0-9a-f]{64}", worker_runtime):
            raise RuntimeError("Worker shared library manifest is missing")
        if self._model_active():
            return self._deferred(release_id)

        with self._promotion_gate() as selected:
            if not selected or self._model_active():
                self._progress("a model holds the selected pair; deferring promotion")
                return self._deferred(release_id)
            return self._promote_under_gate(config, root, release_id, worker_hash, worker_runtime)

    def _promote_under_gate(self, config: Mapping[str, object], root: Path,
                            release_id: str, worker_hash: str, worker_runtime: str) -> RefreshResult:
        """Caller holds the exclusive selection gate until both nodes agree."""
        old_host = self.current_link.readlink() if self.current_link.is_symlink() else None
        old_worker = None
        service_installed = False
        legacy_launcher = False
        worker_selection_attempted = False
        try:
            if not self.runner.worker_staged_matches(config, release_id, worker_hash, worker_runtime):
                self._progress("rebuilding a missing or changed worker release under the selection gate")
                rebuilt = self.runner.stage_worker(
                    self.releases_dir / release_id / "source", release_id, config,
                    CMAKE_FLAGS, clean=True, expected_sha256=worker_hash,
                )
                if rebuilt != worker_hash:
                    raise RuntimeError("Rebuilt worker binary differs from the verified release manifest")
                if self.runner.worker_runtime_digest(config, release_id) != worker_runtime:
                    raise RuntimeError("Rebuilt worker shared libraries differ from the verified release manifest")

            old_worker = self.runner.worker_current_build(config)
            if self._model_active():
                self.runner.restore_worker_repairs()
                return self._deferred(release_id)
            service_installed = self.runner.worker_service_installed(config)
            self._progress("promoting the verified worker before switching the host")
            legacy_launcher = self.runner.ensure_worker_launcher(config)
            worker_selection_attempted = True
            self.runner.select_worker(config, release_id)
            if service_installed:
                self.runner.restart_and_verify_worker(config, release_id, worker_hash, worker_runtime)
            _atomic_symlink(self.current_link, Path("releases") / release_id)
            self.repair_guard(config, root)
            self.runner.cleanup_worker_repairs()
        except Exception:
            self._restore_host(old_host)
            try:
                self.runner.restore_worker_repairs()
            except Exception as rollback_error:
                raise RuntimeError("Fastload promotion failed and preserved worker build could not be restored") from rollback_error
            if worker_selection_attempted:
                self.runner.select_worker(config, old_worker)
            if worker_selection_attempted and old_worker is not None and service_installed:
                try:
                    self.runner.restart_and_verify_worker(config, old_worker, None)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Fastload promotion failed and worker rollback could not be verified"
                    ) from rollback_error
            elif legacy_launcher and service_installed:
                try:
                    self.runner.restore_worker_launcher(config)
                    if worker_selection_attempted:
                        self.runner.restart_and_verify_legacy_worker(config)
                except Exception as rollback_error:
                    raise RuntimeError(
                        "Fastload promotion failed and legacy worker rollback could not be verified"
                    ) from rollback_error
            raise
        keep = {release_id}
        if old_host is not None and re.fullmatch(r"[0-9a-f]{64}", old_host.name):
            keep.add(old_host.name)
        if old_worker is not None and re.fullmatch(r"[0-9a-f]{64}", old_worker):
            keep.add(old_worker)
        try:
            self._prune_host_releases(keep)
            self.runner.prune_worker_releases(config, keep)
        except (OSError, RuntimeError, ValueError) as exc:
            self._progress(f"release cleanup deferred: {exc}")
        return RefreshResult(
            "promoted",
            release_id,
            True,
            "new version-matched fastload host and worker pair selected",
        )

    def _prune_host_releases(self, keep_ids) -> None:
        if not self.releases_dir.is_dir():
            return
        for release in self.releases_dir.iterdir():
            if (
                re.fullmatch(r"[0-9a-f]{64}", release.name)
                and release.name not in keep_ids
                and release.is_dir()
                and not release.is_symlink()
            ):
                shutil.rmtree(release)

    @staticmethod
    def _deferred(release_id: str) -> RefreshResult:
        return RefreshResult(
            "deferred",
            release_id,
            True,
            "new fastload pair is staged; an active model deferred promotion",
        )

    def _restore_host(self, target: Optional[Path]) -> None:
        if target is None:
            self.current_link.unlink(missing_ok=True)
        else:
            _atomic_symlink(self.current_link, target)

    def repair_guard(self, config: Mapping[str, object], install_root: Path) -> bool:
        del config
        root = Path(install_root)
        if not root.is_dir() or root.is_symlink():
            raise RuntimeError("Official Unsloth install root is missing or externally linked")
        if not self.guard_path.is_file():
            raise RuntimeError(f"External llama-server guard is missing: {self.guard_path}")
        link = root / "llama-server"
        if link.is_symlink() and link.resolve() == self.guard_path.resolve():
            return False
        backup = root / "llama-server.before-connect-dual-spark"
        if (link.exists() or link.is_symlink()) and not (backup.exists() or backup.is_symlink()):
            if link.is_symlink():
                backup.symlink_to(os.readlink(link))
            elif link.is_file():
                shutil.copy2(link, backup)
        _atomic_symlink(link, self.guard_path)
        return True


def _read_config(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read fastload guard config {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"Fastload guard config must contain a JSON object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("ensure", "refresh", "status"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--config", type=Path, default=None)
        subparser.add_argument("--install-root", type=Path, default=None)
    return parser


def main(argv: Optional[Sequence[str]] = None, *, manager_factory=FastloadManager) -> int:
    arguments = _parser().parse_args(argv)
    config_path = arguments.config or Path(__file__).with_name("llama-server-wrapper.json")
    try:
        config = _read_config(config_path)
        manager = manager_factory(config_path.resolve().parent)
        if arguments.command == "status":
            output = manager.status(config, install_root=arguments.install_root)
            print(json.dumps(output, sort_keys=True))
            return 0 if output.get("state") == "current" else 3
        method = manager.ensure if arguments.command == "ensure" else manager.refresh
        result = method(config, install_root=arguments.install_root)
        print(json.dumps(asdict(result), sort_keys=True))
        if arguments.command == "ensure" and result.state not in ("current", "promoted"):
            return 3
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"fastload {arguments.command} failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
