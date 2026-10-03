"""Installation operations. Every cross-node command uses the selected CX7 IP."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import socket
import subprocess
import tempfile
import time
from urllib import request

from .configuration import bashrc_with_rpc, rpc_command, studio_unit
from .probe import ClusterProbe
from .system import CommandFailure, remote_cmd, remote_ssh


RPC_PORT = 50053
STUDIO_PORT = 8888
MODEL = "unsloth/Qwen3-0.6B-GGUF:UD-Q4_K_XL"


def rpc_launcher_script(peer, port=RPC_PORT):
    binary = f"{peer.worker_home}/.local/share/connect-dual-spark/llama-src/build/bin/ggml-rpc-server"
    args = rpc_command(binary, peer.worker_ip, port)
    return "#!/usr/bin/env bash\nset -Eeuo pipefail\nexec " + shlex.join(args) + "\n"


def smoke_command(binary, peer, rpc_port=RPC_PORT, smoke_port=18765):
    return [
        binary, "--hf-repo", MODEL, "--rpc", f"{peer.worker_ip}:{rpc_port}",
        "--split-mode", "layer", "--tensor-split", "1,1", "--n-gpu-layers", "99",
        "--ctx-size", "512", "--host", "127.0.0.1", "--port", str(smoke_port),
        "--no-webui", "--parallel", "1",
    ]


def smoke_log_proves_rdma(log_text, peer):
    remote_buffers = re.findall(
        r"RPC\d+\[" + re.escape(peer.worker_ip) + r":\d+\] model buffer size\s*=\s*([\d.]+)",
        log_text,
        re.IGNORECASE,
    )
    return (
        bool(remote_buffers)
        and max(float(n) for n in remote_buffers) > 0
        and "RDMA activated:" in log_text
        and "RDMA activate failed" not in log_text
    )


def _tcp_open(source, target, port, timeout=1):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        sock.bind((source, 0))
        return sock.connect_ex((target, port)) == 0


class Installer:
    def __init__(self, runner):
        self.runner = runner
        self.peer = None
        self.home = Path.home()
        self.studio = self.home / ".unsloth/studio/unsloth_studio/bin/unsloth"
        self.source = self.home / ".local/share/connect-dual-spark/llama-src"
        self.server = self.source / "build/bin/llama-server"
        self.unit = self.home / ".config/systemd/user/connect-dual-spark-studio.service"
        self.bootstrap = False

    def bootstrap_prerequisites(self):
        packages = {
            "ip": "iproute2", "ethtool": "ethtool", "ssh": "openssh-client",
            "rsync": "rsync", "curl": "curl", "git": "git", "xdg-open": "xdg-utils",
        }
        missing = sorted({package for command, package in packages.items() if not shutil.which(command)})
        if not missing:
            return
        if not shutil.which("sudo") or not shutil.which("apt-get"):
            raise RuntimeError("Missing base tools and cannot install them without sudo and apt-get")
        print("    Installing missing base tools: " + ", ".join(missing))
        apt = "set -e; log=$(mktemp); trap 'rm -f \"$log\"' EXIT; if ! (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y " + shlex.join(missing) + ") >\"$log\" 2>&1; then tail -n 30 \"$log\"; exit 1; fi"
        self.runner.run_interactive(["sudo", "bash", "-c", apt], label="Install base network tools")

    def preflight(self):
        import platform
        if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
            raise RuntimeError("Requires Ubuntu ARM64 on the primary DGX Spark")
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        if "ID=ubuntu" not in release:
            raise RuntimeError("Requires Ubuntu on both DGX Sparks")
        if self.bootstrap:
            self.bootstrap_prerequisites()
        for cmd in ("ip", "ethtool", "ssh", "rsync", "curl", "gnome-terminal", "nvidia-smi"):
            if not shutil.which(cmd):
                raise RuntimeError(f"Missing {cmd}; install the Connect Dual Spark .deb package")
        gpu = self.runner.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
        if "GB10" not in gpu:
            raise RuntimeError("Primary machine is not an NVIDIA DGX Spark (GB10 GPU absent)")

    def detect_cluster(self):
        self.preflight()
        self.peer = ClusterProbe(self.runner.run).detect()
        peer = self.peer
        print(f"    CX7 {peer.host_iface}: {peer.host_ip} → {peer.worker_ip} ({peer.speed_mbps // 1000} Gb/s)")
        worker = self.runner.run(remote_ssh(peer, "uname -m; nvidia-smi --query-gpu=name --format=csv,noheader; . /etc/os-release; echo $ID"))
        lines = worker.splitlines()
        if len(lines) < 3 or lines[0] != "aarch64" or "GB10" not in lines[1] or lines[-1] != "ubuntu":
            raise RuntimeError("Second machine must be an Ubuntu ARM64 DGX Spark with GB10")

    def install_studio(self):
        if not self.studio.is_file():
            with tempfile.TemporaryDirectory(prefix="connect-dual-spark-") as temp:
                installer = Path(temp) / "unsloth-install.sh"
                self.runner.run_task(["curl", "-fL", "--retry", "3", "--output", str(installer), "https://unsloth.ai/install.sh"], label="Download official Unsloth installer", timeout=180)
                env = os.environ.copy()
                env["UNSLOTH_SKIP_AUTOSTART"] = "1"
                self.runner.run_task(["bash", str(installer)], label="Install Unsloth Studio", timeout=3600, env=env)
        else:
            print("    Unsloth Studio is already installed")
        if not self.studio.is_file():
            raise RuntimeError("Official Unsloth install did not provide Studio")
        host_check = "dpkg-query -W cmake ninja-build build-essential git libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev >/dev/null 2>&1"
        try:
            self.runner.run(["bash", "-c", host_check])
        except CommandFailure:
            print("    Installing host build packages (sudo may ask for its password)")
            apt = "set -e; log=$(mktemp); trap 'rm -f \"$log\"' EXIT; if ! (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y cmake ninja-build build-essential git libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev) >\"$log\" 2>&1; then tail -n 30 \"$log\"; exit 1; fi"
            self.runner.run_interactive(["sudo", "bash", "-c", apt], label="Install host build packages")
        if not (self.source / "CMakeLists.txt").is_file():
            self.source.parent.mkdir(parents=True, exist_ok=True)
            self.runner.run_task(["git", "clone", "--depth", "1", "https://github.com/unslothai/llama.cpp", str(self.source)], label="Fetch matching llama.cpp source", timeout=1200)
        if not self.server.is_file():
            configure = ["cmake", "-S", str(self.source), "-B", str(self.source / "build"), "-G", "Ninja", "-DGGML_CUDA=ON", "-DGGML_RPC=ON", "-DGGML_RPC_RDMA=ON", "-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc"]
            self.runner.run_task(configure, label="Configure host CUDA/RPC/RDMA", timeout=1200)
            self.runner.run_task(["cmake", "--build", str(self.source / "build"), "--target", "llama-server", "-j", "4"], label="Build host llama-server", timeout=3600)
        if not self.server.is_file():
            raise RuntimeError("Host llama.cpp server build did not produce a binary")

    def _worker(self, command, *, timeout=60):
        return self.runner.run(remote_ssh(self.peer, command), timeout=timeout)

    def sync_and_build_rpc(self):
        peer = self.peer
        check = "command -v cmake && command -v ninja && command -v rsync && test -x /usr/local/cuda/bin/nvcc && dpkg-query -W cmake ninja-build build-essential git rsync libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev >/dev/null 2>&1"
        try:
            self._worker(check)
        except CommandFailure:
            print("    Installing build packages on the second Spark (sudo may ask for its password)")
            apt = "set -e; log=$(mktemp); trap 'rm -f \"$log\"' EXIT; if ! (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y cmake ninja-build build-essential git rsync libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev) >\"$log\" 2>&1; then tail -n 30 \"$log\"; exit 1; fi"
            self.runner.run_interactive(remote_ssh(peer, "sudo bash -c " + shlex.quote(apt), tty=True), label="Install worker build packages")
        base = f"{peer.worker_home}/.local/share/connect-dual-spark"
        dest = f"{base}/llama-src"
        self._worker(remote_cmd("mkdir", "-p", dest))
        ssh_transport = shlex.join(["ssh", "-b", peer.host_ip, "-o", f"BindInterface={peer.host_iface}", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"])
        self.runner.run_task([
            "rsync", "-ac", "--delete", "--exclude=build/", "--exclude=.git/", "-e", ssh_transport,
            f"{self.source}/", f"{peer.worker_user}@{peer.worker_ip}:{dest}/",
        ], label="Sync exact llama.cpp source over ConnectX-7", timeout=1200)
        delta = self.runner.run([
            "rsync", "-nrc", "--delete", "--itemize-changes", "--exclude=build/", "--exclude=.git/", "-e", ssh_transport,
            f"{self.source}/", f"{peer.worker_user}@{peer.worker_ip}:{dest}/",
        ], timeout=1200)
        if delta.strip():
            raise RuntimeError("llama.cpp source differs after synchronization: " + delta[:300])
        source_hash = self.runner.run(["sha256sum", str(self.source / "CMakeLists.txt")]).split()[0]
        remote_hash = self._worker(remote_cmd("sha256sum", f"{dest}/CMakeLists.txt")).split()[0]
        if source_hash != remote_hash:
            raise RuntimeError("Source checksum differs between Sparks")
        configure = remote_cmd("cmake", "-S", dest, "-B", f"{dest}/build", "-G", "Ninja", "-DGGML_CUDA=ON", "-DGGML_RPC=ON", "-DGGML_RPC_RDMA=ON", "-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc")
        self.runner.run_task(remote_ssh(peer, configure), label="Configure worker CUDA/RPC/RDMA", timeout=1200)
        self.runner.run_task(remote_ssh(peer, remote_cmd("cmake", "--build", f"{dest}/build", "--target", "ggml-rpc-server", "-j", "4")), label="Build worker RPC server", timeout=3600)
        self._worker(remote_cmd("test", "-x", f"{dest}/build/bin/ggml-rpc-server"))

    def _rpc_pid(self):
        peer = self.peer
        output = self._worker("pgrep -af '[g]gml-rpc-server' || true")
        expected = f"{peer.worker_home}/.local/share/connect-dual-spark/llama-src/build/bin/ggml-rpc-server"
        return any(expected in line and f"--host {peer.worker_ip}" in line and f"--port {RPC_PORT}" in line for line in output.splitlines())

    def start_rpc(self):
        peer = self.peer
        if _tcp_open(peer.host_ip, peer.worker_ip, RPC_PORT):
            if not self._rpc_pid():
                raise RuntimeError("RPC port is occupied by an unknown process on the second Spark")
            print("    Worker RPC already runs on the selected ConnectX-7 address")
            return
        remote_script = f"{peer.worker_home}/.local/share/connect-dual-spark/run-rpc.sh"
        script = rpc_launcher_script(peer)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as tmp:
            tmp.write(script)
            local_script = tmp.name
        try:
            ssh_transport = shlex.join(["ssh", "-b", peer.host_ip, "-o", f"BindInterface={peer.host_iface}", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"])
            self.runner.run_task(["rsync", "-a", "-e", ssh_transport, local_script, f"{peer.worker_user}@{peer.worker_ip}:{remote_script}"], label="Copy worker RPC launcher", timeout=60)
        finally:
            Path(local_script).unlink(missing_ok=True)
        self._worker(remote_cmd("chmod", "700", remote_script))
        ssh = remote_ssh(peer, remote_cmd("bash", remote_script), tty=True)
        shell = """\n"$@"\nstatus=$?\nprintf '\\nWorker RPC stopped (code %s). Press Enter to close.\\n' "$status"\nread -r _\nexit "$status"\n"""
        subprocess.Popen(["gnome-terminal", "--title=Connect-Dual-Spark-RPC", "--", "bash", "-c", shell, "connect-dual-spark-rpc", *ssh], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(30):
            if _tcp_open(peer.host_ip, peer.worker_ip, RPC_PORT):
                print("    Worker RPC is listening in its visible terminal")
                return
            time.sleep(1)
        raise RuntimeError("Worker RPC did not start; inspect the Connect-Dual-Spark-RPC terminal")

    def smoke_test(self):
        if self.runner.run(["bash", "-c", "pgrep -af '[l]lama-server' || true"]).strip():
            raise RuntimeError("Another llama-server is running. Stop its model before the temporary RPC smoke test")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = smoke_command(str(self.server), self.peer, RPC_PORT, port)
        opener = request.build_opener(request.ProxyHandler({}))
        with tempfile.TemporaryDirectory(prefix="connect-dual-spark-smoke-") as temp:
            log_path = Path(temp) / "smoke.log"
            with log_path.open("w+", encoding="utf-8") as log:
                proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 900
                    while time.monotonic() < deadline:
                        if proc.poll() is not None:
                            raise RuntimeError("Tiny GGUF server exited: " + log_path.read_text(errors="replace")[-3000:])
                        try:
                            with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                                if response.status == 200:
                                    break
                        except Exception:
                            pass
                        time.sleep(2)
                    else:
                        raise RuntimeError("Tiny GGUF did not become healthy within 15 minutes")
                    payload = json.dumps({"prompt": "Reply with the word READY.", "n_predict": 8, "temperature": 0}).encode()
                    req = request.Request(f"http://127.0.0.1:{port}/completion", data=payload, headers={"Content-Type": "application/json"})
                    with opener.open(req, timeout=120) as response:
                        result = json.load(response)
                    if not result.get("content", "").strip():
                        raise RuntimeError("Tiny GGUF returned an empty completion")
                    log.flush()
                    evidence = log_path.read_text(errors="replace")
                    if not smoke_log_proves_rdma(evidence, self.peer):
                        raise RuntimeError("Tiny GGUF did not prove remote weights over active RDMA; inspect the log for TCP fallback")
                    print("    Tiny GGUF completed an inference with remote weights over RDMA")
                finally:
                    proc.terminate()
                    try:
                        proc.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait(timeout=5)
                    self.runner._record(command, log_path.read_text(errors="replace")[-8000:])

    def configure_studio(self):
        endpoint = f"{self.peer.worker_ip}:{RPC_PORT}"
        bashrc = self.home / ".bashrc"
        previous = bashrc.read_text(encoding="utf-8") if bashrc.exists() else ""
        bashrc.write_text(bashrc_with_rpc(previous, self.peer.worker_ip, RPC_PORT, str(self.source)), encoding="utf-8")
        environment_dir = self.home / ".config/environment.d"
        environment_dir.mkdir(parents=True, exist_ok=True)
        environment_file = environment_dir / "90-connect-dual-spark.conf"
        environment_file.write_text(f"LLAMA_ARG_RPC={endpoint}\nUNSLOTH_LLAMA_CPP_PATH={self.source}\n", encoding="utf-8")
        environment_file.chmod(0o600)
        self.runner.run(["systemctl", "--user", "set-environment", f"LLAMA_ARG_RPC={endpoint}", f"UNSLOTH_LLAMA_CPP_PATH={self.source}"])
        self.unit.parent.mkdir(parents=True, exist_ok=True)
        self.unit.write_text(studio_unit(self.peer.worker_ip, RPC_PORT, str(self.studio), str(self.source)), encoding="utf-8")
        self.runner.run(["systemctl", "--user", "daemon-reload"])
        self.runner.run(["systemctl", "--user", "enable", self.unit.name])

    def verify_installation(self):
        peer = ClusterProbe(self.runner.run).detect()
        if peer.worker_ip != self.peer.worker_ip or peer.host_ip != self.peer.host_ip:
            raise RuntimeError("ConnectX-7 route changed after installation")
        if not _tcp_open(peer.host_ip, peer.worker_ip, RPC_PORT) or not self._rpc_pid():
            raise RuntimeError("Worker RPC is no longer listening on ConnectX-7")
        if not self.studio.is_file() or not self.server.is_file():
            raise RuntimeError("Unsloth Studio or llama.cpp server is missing")
        unit = self.unit.read_text(encoding="utf-8")
        if f"LLAMA_ARG_RPC={peer.worker_ip}:{RPC_PORT}" not in unit:
            raise RuntimeError("Studio RPC configuration differs from discovered peer")
        environment = (self.home / ".config/environment.d/90-connect-dual-spark.conf").read_text(encoding="utf-8")
        if f"LLAMA_ARG_RPC={peer.worker_ip}:{RPC_PORT}" not in environment or f"UNSLOTH_LLAMA_CPP_PATH={self.source}" not in environment:
            raise RuntimeError("Desktop login RPC configuration differs from discovered peer")

    def perform(self, stage):
        getattr(self, stage)()

    def offer_studio(self):
        answer = input("Все проверки пройдены. Запустить Unsloth Studio сейчас? [Y/n] ").strip().lower()
        if answer not in ("", "y", "yes", "д", "да"):
            print("    Studio готова к запуску: connect-dual-spark studio")
            return False
        return self.launch_studio()

    def launch_studio(self):
        try:
            active = self.runner.run(["systemctl", "--user", "is-active", self.unit.name]).strip() == "active"
        except CommandFailure:
            active = False
        if active:
            pid = int(self.runner.run(["systemctl", "--user", "show", "-p", "MainPID", "--value", self.unit.name]).strip())
            if pid <= 0:
                raise RuntimeError("Existing Studio service has no process")
            process_environment = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
            required = {
                f"LLAMA_ARG_RPC={self.peer.worker_ip}:{RPC_PORT}".encode(),
                f"UNSLOTH_LLAMA_CPP_PATH={self.source}".encode(),
            }
            if not required.issubset(set(process_environment)):
                raise RuntimeError("Existing Studio service has outdated RPC settings; stop it before launching the configured service")
        else:
            if _tcp_open("127.0.0.1", "127.0.0.1", STUDIO_PORT):
                raise RuntimeError("Port 8888 is occupied by another Studio or HTTP process; stop it before launching the configured service")
            self.runner.run(["systemctl", "--user", "start", self.unit.name])
        opener = request.build_opener(request.ProxyHandler({}))
        for _ in range(30):
            try:
                if self.runner.run(["systemctl", "--user", "is-active", self.unit.name]).strip() != "active":
                    time.sleep(1)
                    continue
                with opener.open(f"http://127.0.0.1:{STUDIO_PORT}/api/health", timeout=2) as response:
                    if response.status == 200 and json.load(response).get("service") == "Unsloth UI Backend":
                        break
            except Exception:
                time.sleep(1)
        else:
            raise RuntimeError("Studio service did not become ready on localhost:8888")
        subprocess.Popen(["xdg-open", f"http://127.0.0.1:{STUDIO_PORT}/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def check(self):
        self.detect_cluster()
        return True

    def status(self):
        self.detect_cluster()
        print(f"    Studio: {'installed' if self.studio.is_file() else 'missing'}")
        print(f"    llama.cpp: {'installed' if self.server.is_file() else 'missing'}")
        print(f"    Worker RPC: {'listening' if _tcp_open(self.peer.host_ip, self.peer.worker_ip, RPC_PORT) else 'offline'}")
        print(f"    Studio unit: {'configured' if self.unit.is_file() else 'missing'}")
