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

from .configuration import bashrc_with_rpc, rpc_command, rpc_system_unit, studio_unit
from .language import msg
from .probe import ClusterProbe
from .system import CommandFailure, remote_cmd, remote_ssh


RPC_PORT = 50053
RPC_SERVICE = "connect-dual-spark-rpc.service"
STUDIO_PORT = 8888
MODEL = "unsloth/Qwen3-0.6B-GGUF:UD-Q4_K_XL"


def smoke_command(binary, smoke_port=18765):
    return [
        binary, "--hf-repo", MODEL,
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
            raise RuntimeError(msg("Missing base tools and cannot install them without sudo and apt-get", "Не хватает системных утилит; установить их без sudo и apt-get невозможно"))
        print(msg("    Installing missing base tools: ", "    Установка недостающих системных утилит: ") + ", ".join(missing))
        apt = "set -e; log=$(mktemp); trap 'rm -f \"$log\"' EXIT; if ! (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y " + shlex.join(missing) + ") >\"$log\" 2>&1; then tail -n 30 \"$log\"; exit 1; fi"
        self.runner.run_interactive(["sudo", "bash", "-c", apt], label=msg("Install base network tools", "Установка сетевых утилит"))

    def preflight(self):
        import platform
        if platform.system() != "Linux" or platform.machine() not in ("aarch64", "arm64"):
            raise RuntimeError(msg("Requires Ubuntu ARM64 on the primary DGX Spark", "На основном DGX Spark требуется Ubuntu ARM64"))
        release = Path("/etc/os-release").read_text(encoding="utf-8")
        if "ID=ubuntu" not in release:
            raise RuntimeError(msg("Requires Ubuntu on both DGX Sparks", "На обоих DGX Spark требуется Ubuntu"))
        if self.bootstrap:
            self.bootstrap_prerequisites()
        for cmd in ("ip", "ethtool", "ssh", "rsync", "curl", "gnome-terminal", "nvidia-smi"):
            if not shutil.which(cmd):
                raise RuntimeError(msg(f"Missing {cmd}; install the Connect Dual Spark .deb package", f"Не найдена команда {cmd}; установите пакет Connect Dual Spark .deb"))
        gpu = self.runner.run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"])
        if "GB10" not in gpu:
            raise RuntimeError(msg("Primary machine is not an NVIDIA DGX Spark (GB10 GPU absent)", "Основной компьютер не является NVIDIA DGX Spark: GPU GB10 не найдена"))

    def detect_cluster(self):
        self.preflight()
        self.peer = ClusterProbe(self.runner.run).detect()
        peer = self.peer
        print(f"    CX7 {peer.host_iface}: {peer.host_ip} → {peer.worker_ip} ({peer.speed_mbps // 1000} Gb/s)")
        worker = self.runner.run(remote_ssh(peer, "uname -m; nvidia-smi --query-gpu=name --format=csv,noheader; . /etc/os-release; echo $ID"))
        lines = worker.splitlines()
        if len(lines) < 3 or lines[0] != "aarch64" or "GB10" not in lines[1] or lines[-1] != "ubuntu":
            raise RuntimeError(msg("Second machine must be an Ubuntu ARM64 DGX Spark with GB10", "Второй компьютер должен быть DGX Spark с Ubuntu ARM64 и GPU GB10"))

    def install_studio(self):
        if not self.studio.is_file():
            with tempfile.TemporaryDirectory(prefix="connect-dual-spark-") as temp:
                installer = Path(temp) / "unsloth-install.sh"
                self.runner.run_task(["curl", "-fL", "--retry", "3", "--output", str(installer), "https://unsloth.ai/install.sh"], label=msg("Download official Unsloth installer", "Загрузка установщика Unsloth"), timeout=180)
                env = os.environ.copy()
                env["UNSLOTH_SKIP_AUTOSTART"] = "1"
                self.runner.run_task(["bash", str(installer)], label=msg("Install Unsloth Studio", "Установка Unsloth Studio"), timeout=3600, env=env)
        else:
            print(msg("    Unsloth Studio is already installed", "    Unsloth Studio уже установлена"))
        if not self.studio.is_file():
            raise RuntimeError(msg("Official Unsloth install did not provide Studio", "Официальная установка Unsloth не создала Studio"))
        host_check = "dpkg-query -W cmake ninja-build build-essential git libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev >/dev/null 2>&1"
        try:
            self.runner.run(["bash", "-c", host_check])
        except CommandFailure:
            print(msg("    Installing host build packages (sudo may ask for its password)", "    Установка пакетов сборки на основном Spark (sudo может запросить пароль)"))
            apt = "set -e; log=$(mktemp); trap 'rm -f \"$log\"' EXIT; if ! (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y cmake ninja-build build-essential git libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev) >\"$log\" 2>&1; then tail -n 30 \"$log\"; exit 1; fi"
            self.runner.run_interactive(["sudo", "bash", "-c", apt], label=msg("Install host build packages", "Установка пакетов сборки на основном Spark"))
        if not (self.source / "CMakeLists.txt").is_file():
            self.source.parent.mkdir(parents=True, exist_ok=True)
            self.runner.run_task(["git", "clone", "--depth", "1", "https://github.com/unslothai/llama.cpp", str(self.source)], label=msg("Fetch matching llama.cpp source", "Загрузка исходников llama.cpp"), timeout=1200)
        if not self.server.is_file():
            configure = ["cmake", "-S", str(self.source), "-B", str(self.source / "build"), "-G", "Ninja", "-DGGML_CUDA=ON", "-DGGML_RPC=ON", "-DGGML_RPC_RDMA=ON", "-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc"]
            self.runner.run_task(configure, label=msg("Configure host CUDA/RPC/RDMA", "Настройка CUDA/RPC/RDMA на основном Spark"), timeout=1200)
            self.runner.run_task(["cmake", "--build", str(self.source / "build"), "--target", "llama-server", "-j", "4"], label=msg("Build host llama-server", "Сборка llama-server на основном Spark"), timeout=3600)
        if not self.server.is_file():
            raise RuntimeError(msg("Host llama.cpp server build did not produce a binary", "Сборка llama.cpp на основном Spark не создала исполняемый файл сервера"))

    def _worker(self, command, *, timeout=60):
        return self.runner.run(remote_ssh(self.peer, command), timeout=timeout)

    def _llama_wrapper_path(self):
        return self.home / ".local/share/connect-dual-spark/llama-server-wrapper.py"

    def _llama_guard_config(self, binary):
        return {
            "binary": str(binary),
            "host_ip": self.peer.host_ip,
            "host_iface": self.peer.host_iface,
            "rpc": f"{self.peer.worker_ip}:{RPC_PORT}",
        }

    def install_llama_guard(self, binary_override=None):
        """Guard both Studio's managed and default GGUF binary search paths."""
        binary = Path(binary_override) if binary_override else self.server
        if not binary.is_absolute() or not binary.is_file():
            raise RuntimeError(msg("Built llama-server binary is missing", "Собранный исполняемый файл llama-server не найден"))
        wrapper = self._llama_wrapper_path()
        wrapper.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        source = Path(__file__).with_name("llama_wrapper.py")
        with tempfile.NamedTemporaryFile(dir=wrapper.parent, delete=False) as tmp:
            temporary = Path(tmp.name)
        try:
            shutil.copyfile(source, temporary)
            temporary.chmod(0o700)
            os.replace(temporary, wrapper)
        finally:
            temporary.unlink(missing_ok=True)
        config = wrapper.with_suffix(".json")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=wrapper.parent, delete=False) as tmp:
            json.dump(self._llama_guard_config(binary), tmp)
            tmp.write("\n")
            temporary = Path(tmp.name)
        try:
            temporary.chmod(0o600)
            os.replace(temporary, config)
        finally:
            temporary.unlink(missing_ok=True)
        for root in (self.home / ".unsloth/llama.cpp", self.source):
            if not root.is_dir():
                continue
            link = root / "llama-server"
            if link.is_symlink() and link.resolve() == wrapper.resolve():
                continue
            if link.exists() or link.is_symlink():
                backup = root / "llama-server.before-connect-dual-spark"
                if backup.exists() or backup.is_symlink():
                    backup = root / f"llama-server.before-connect-dual-spark-{time.time_ns()}"
                if link.is_symlink():
                    backup.symlink_to(os.readlink(link))
                else:
                    shutil.copy2(link, backup)
            temporary_link = root / f".llama-server-connect-dual-spark-{os.getpid()}"
            temporary_link.unlink(missing_ok=True)
            temporary_link.symlink_to(wrapper)
            os.replace(temporary_link, link)

    def _llama_guard_ready(self):
        wrapper = self._llama_wrapper_path()
        try:
            config = json.loads(wrapper.with_suffix(".json").read_text(encoding="utf-8"))
            if config != self._llama_guard_config(self.server) or not wrapper.is_file():
                return False
            return all(
                (root / "llama-server").is_symlink()
                and (root / "llama-server").resolve() == wrapper.resolve()
                for root in (self.home / ".unsloth/llama.cpp", self.source)
            )
        except (OSError, ValueError, KeyError):
            return False

    def prepare_llama_guard(self):
        if self._host_model_active():
            raise RuntimeError(msg("Another llama-server is running; unload it before installing the dual-Spark guard", "Другой llama-server уже работает; выгрузите модель перед установкой защиты для двух Spark"))
        self.install_llama_guard()

    def sync_and_build_rpc(self):
        peer = self.peer
        check = "command -v cmake && command -v ninja && command -v rsync && test -x /usr/local/cuda/bin/nvcc && dpkg-query -W cmake ninja-build build-essential git rsync libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev >/dev/null 2>&1"
        try:
            self._worker(check)
        except CommandFailure:
            print(msg("    Installing build packages on the second Spark (sudo may ask for its password)", "    Установка пакетов сборки на втором Spark (sudo может запросить пароль)"))
            apt = "set -e; log=$(mktemp); trap 'rm -f \"$log\"' EXIT; if ! (apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y cmake ninja-build build-essential git rsync libibverbs-dev librdmacm-dev libnuma-dev libcurl4-openssl-dev) >\"$log\" 2>&1; then tail -n 30 \"$log\"; exit 1; fi"
            self.runner.run_interactive(remote_ssh(peer, "sudo bash -c " + shlex.quote(apt), tty=True), label=msg("Install worker build packages", "Установка пакетов сборки на втором Spark"))
        base = f"{peer.worker_home}/.local/share/connect-dual-spark"
        dest = f"{base}/llama-src"
        self._worker(remote_cmd("mkdir", "-p", dest))
        ssh_transport = shlex.join(["ssh", "-b", peer.host_ip, "-o", f"BindInterface={peer.host_iface}", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "-o", "StrictHostKeyChecking=accept-new"])
        self.runner.run_task([
            "rsync", "-ac", "--delete", "--exclude=build/", "--exclude=.git/", "-e", ssh_transport,
            f"{self.source}/", f"{peer.worker_user}@{peer.worker_ip}:{dest}/",
        ], label=msg("Sync exact llama.cpp source over ConnectX-7", "Синхронизация исходников llama.cpp через ConnectX-7"), timeout=1200)
        delta = self.runner.run([
            "rsync", "-nrc", "--delete", "--itemize-changes", "--exclude=build/", "--exclude=.git/", "-e", ssh_transport,
            f"{self.source}/", f"{peer.worker_user}@{peer.worker_ip}:{dest}/",
        ], timeout=1200)
        if delta.strip():
            raise RuntimeError(msg("llama.cpp source differs after synchronization: ", "Исходники llama.cpp различаются после синхронизации: ") + delta[:300])
        source_hash = self.runner.run(["sha256sum", str(self.source / "CMakeLists.txt")]).split()[0]
        remote_hash = self._worker(remote_cmd("sha256sum", f"{dest}/CMakeLists.txt")).split()[0]
        if source_hash != remote_hash:
            raise RuntimeError(msg("Source checksum differs between Sparks", "Контрольные суммы исходников на двух Spark различаются"))
        configure = remote_cmd("cmake", "-S", dest, "-B", f"{dest}/build", "-G", "Ninja", "-DGGML_CUDA=ON", "-DGGML_RPC=ON", "-DGGML_RPC_RDMA=ON", "-DCMAKE_CUDA_COMPILER=/usr/local/cuda/bin/nvcc")
        self.runner.run_task(remote_ssh(peer, configure), label=msg("Configure worker CUDA/RPC/RDMA", "Настройка CUDA/RPC/RDMA на втором Spark"), timeout=1200)
        self.runner.run_task(remote_ssh(peer, remote_cmd("cmake", "--build", f"{dest}/build", "--target", "ggml-rpc-server", "-j", "4")), label=msg("Build worker RPC server", "Сборка RPC-сервера на втором Spark"), timeout=3600)
        self._worker(remote_cmd("test", "-x", f"{dest}/build/bin/ggml-rpc-server"))

    def _rpc_binary(self):
        return f"{self.peer.worker_home}/.local/share/connect-dual-spark/llama-src/build/bin/ggml-rpc-server"

    def _rpc_unit_text(self):
        peer = self.peer
        return rpc_system_unit(peer.worker_user, peer.worker_home, self._rpc_binary(), peer.worker_ip, RPC_PORT)

    def _rpc_service_pid(self):
        try:
            if self._worker(remote_cmd("systemctl", "is-active", RPC_SERVICE)).strip() != "active":
                return None
            pid = int(self._worker(remote_cmd("systemctl", "show", "-p", "MainPID", "--value", RPC_SERVICE)).strip())
            return pid if pid > 0 else None
        except (CommandFailure, OSError, ValueError):
            return None

    def _rpc_service_owned(self):
        pid = self._rpc_service_pid()
        if pid is None:
            return False
        try:
            listeners = self._worker("ss -H -ltnp 'sport = :50053'")
        except CommandFailure:
            return False
        return any(
            f"{self.peer.worker_ip}:{RPC_PORT}" in line and f"pid={pid}," in line
            for line in listeners.splitlines()
        )

    def _rpc_runtime_correct(self):
        pid = self._rpc_service_pid()
        if pid is None:
            return False
        try:
            if self._worker(remote_cmd("readlink", f"/proc/{pid}/exe")).strip() != self._rpc_binary():
                return False
            script = f"import json; from pathlib import Path; p=Path('/proc/{pid}/cmdline').read_bytes(); print(json.dumps([x.decode() for x in p.split(bytes([0])) if x]))"
            argv = json.loads(self._worker(remote_cmd("python3", "-c", script)))
            return argv == rpc_command(self._rpc_binary(), self.peer.worker_ip, RPC_PORT)
        except (CommandFailure, OSError, ValueError):
            return False

    def _rpc_service_state(self):
        """Confirm boot enablement, effective systemd settings, and exact argv."""
        if not self._rpc_service_owned() or not self._rpc_runtime_correct():
            return False
        try:
            if self._worker(remote_cmd("cat", f"/etc/systemd/system/{RPC_SERVICE}")) != self._rpc_unit_text():
                return False
            if self._worker(remote_cmd("systemctl", "is-enabled", RPC_SERVICE)).strip() != "enabled":
                return False
            raw = self._worker(remote_cmd(
                "systemctl", "show", RPC_SERVICE,
                "-p", "NeedDaemonReload", "-p", "DropInPaths", "-p", "FragmentPath",
                "-p", "Restart", "-p", "User",
            ))
            properties = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
            return properties == {
                "NeedDaemonReload": "no", "DropInPaths": "",
                "FragmentPath": f"/etc/systemd/system/{RPC_SERVICE}",
                "Restart": "always", "User": self.peer.worker_user,
            }
        except (CommandFailure, OSError, ValueError):
            return False

    def _rpc_service_dropins(self):
        try:
            return self._worker(remote_cmd("systemctl", "show", RPC_SERVICE, "-p", "DropInPaths", "--value")).strip()
        except CommandFailure:
            return ""

    def _host_model_active(self):
        return bool(self.runner.run(["bash", "-c", "pgrep -af '[l]lama-server' || true"]).strip())

    def _show_rpc_logs(self):
        peer = self.peer
        ssh = remote_ssh(peer, remote_cmd("journalctl", "-u", RPC_SERVICE, "-n", "20", "-f", "--no-pager"), tty=True)
        shell = """\n"$@"\nstatus=$?\nprintf '\\nRPC log viewer stopped (code %s). Press Enter to close.\\n' "$status"\nread -r _\nexit "$status"\n"""
        subprocess.Popen(["gnome-terminal", "--title=Connect-Dual-Spark-RPC-Logs", "--", "bash", "-c", shell, "connect-dual-spark-rpc-logs", *ssh], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def start_rpc(self):
        peer = self.peer
        dropins = self._rpc_service_dropins()
        if dropins:
            raise RuntimeError(msg(f"Worker RPC has an existing systemd override ({dropins}); inspect it before installation", f"У службы RPC есть дополнительная настройка systemd ({dropins}); проверьте её перед установкой"))
        if self._rpc_service_state() and _tcp_open(peer.host_ip, peer.worker_ip, RPC_PORT):
            print(msg("    Worker RPC system service is already active and enabled at boot", "    Системная служба RPC уже работает и включена при загрузке"))
            self._show_rpc_logs()
            return
        port_open = _tcp_open(peer.host_ip, peer.worker_ip, RPC_PORT)
        owned = port_open and self._rpc_service_owned()
        if port_open and not owned:
            raise RuntimeError(msg("RPC port is occupied by an unmanaged process; stop the old terminal RPC before installing the boot service", "Порт RPC занят сторонним процессом; остановите старый RPC в терминале перед установкой службы автозапуска"))
        needs_restart = not (owned and self._rpc_runtime_correct())
        defer_restart = needs_restart and self._host_model_active()
        remote_unit = f"{peer.worker_home}/.local/share/connect-dual-spark/{RPC_SERVICE}"
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", delete=False) as tmp:
            tmp.write(self._rpc_unit_text())
            local_unit = tmp.name
        try:
            ssh_transport = shlex.join(["ssh", "-b", peer.host_ip, "-o", f"BindInterface={peer.host_iface}", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"])
            self.runner.run_task(["rsync", "-a", "-e", ssh_transport, local_unit, f"{peer.worker_user}@{peer.worker_ip}:{remote_unit}"], label=msg("Stage worker RPC system unit", "Подготовка системной службы RPC"), timeout=60)
        finally:
            Path(local_unit).unlink(missing_ok=True)
        install = (
            "set -e; "
            + remote_cmd("install", "-o", "root", "-g", "root", "-m", "0644", remote_unit, f"/etc/systemd/system/{RPC_SERVICE}")
            + "; systemctl daemon-reload; "
            + remote_cmd("systemctl", "enable", RPC_SERVICE)
        )
        if needs_restart and not defer_restart:
            install += "; " + remote_cmd("systemctl", "restart", RPC_SERVICE)
        self.runner.run_interactive(remote_ssh(peer, "sudo bash -c " + shlex.quote(install), tty=True), label=msg("Enable worker RPC at boot (sudo authorization)", "Включение RPC при загрузке второго Spark (sudo)"))
        if defer_restart:
            raise RuntimeError(msg("Worker RPC boot service is enabled, but its running binary needs a restart; unload the current model and run connect-dual-spark start-rpc", "Автозапуск службы RPC включён, но текущий процесс требует перезапуска; выгрузите модель и выполните connect-dual-spark start-rpc"))
        for _ in range(60):
            if self._rpc_service_state() and _tcp_open(peer.host_ip, peer.worker_ip, RPC_PORT):
                print(msg("    Worker RPC system service is active and enabled at boot", "    Системная служба RPC работает и включена при загрузке"))
                self._show_rpc_logs()
                return
            time.sleep(1)
        raise RuntimeError(msg("Worker RPC system service did not become reachable; inspect systemctl status connect-dual-spark-rpc.service on the second Spark", "Служба RPC не стала доступной; проверьте systemctl status connect-dual-spark-rpc.service на втором Spark"))

    def smoke_test(self):
        if self._host_model_active():
            raise RuntimeError(msg("Another llama-server is running. Stop its model before the temporary RPC smoke test", "Другой llama-server уже работает. Выгрузите его модель перед пробной проверкой RPC"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        command = smoke_command(str(self.home / ".unsloth/llama.cpp/llama-server"), port)
        opener = request.build_opener(request.ProxyHandler({}))
        with tempfile.TemporaryDirectory(prefix="connect-dual-spark-smoke-") as temp:
            log_path = Path(temp) / "smoke.log"
            with log_path.open("w+", encoding="utf-8") as log:
                proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                try:
                    deadline = time.monotonic() + 900
                    while time.monotonic() < deadline:
                        if proc.poll() is not None:
                            raise RuntimeError(msg("Tiny GGUF server exited: ", "Сервер пробной GGUF-модели завершился: ") + log_path.read_text(errors="replace")[-3000:])
                        try:
                            with opener.open(f"http://127.0.0.1:{port}/health", timeout=2) as response:
                                if response.status == 200:
                                    break
                        except Exception:
                            pass
                        time.sleep(2)
                    else:
                        raise RuntimeError(msg("Tiny GGUF did not become healthy within 15 minutes", "Пробная GGUF-модель не стала готовой за 15 минут"))
                    payload = json.dumps({"prompt": "Reply with the word READY.", "n_predict": 8, "temperature": 0}).encode()
                    req = request.Request(f"http://127.0.0.1:{port}/completion", data=payload, headers={"Content-Type": "application/json"})
                    with opener.open(req, timeout=120) as response:
                        result = json.load(response)
                    if not result.get("content", "").strip():
                        raise RuntimeError(msg("Tiny GGUF returned an empty completion", "Пробная GGUF-модель вернула пустой ответ"))
                    log.flush()
                    evidence = log_path.read_text(errors="replace")
                    if not smoke_log_proves_rdma(evidence, self.peer):
                        raise RuntimeError(msg("Tiny GGUF did not prove remote weights over active RDMA; inspect the log for TCP fallback", "Пробная GGUF-модель не подтвердила размещение весов на втором Spark через RDMA; проверьте журнал на переход к TCP"))
                    print(msg("    Tiny GGUF completed an inference with remote weights over RDMA", "    Пробная GGUF-модель выполнила запрос с удалёнными весами через RDMA"))
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
        wrapper = str(self._llama_wrapper_path())
        bashrc = self.home / ".bashrc"
        previous = bashrc.read_text(encoding="utf-8") if bashrc.exists() else ""
        bashrc.write_text(bashrc_with_rpc(previous, self.peer.worker_ip, RPC_PORT, str(self.source), wrapper), encoding="utf-8")
        environment_dir = self.home / ".config/environment.d"
        environment_dir.mkdir(parents=True, exist_ok=True)
        environment_file = environment_dir / "90-connect-dual-spark.conf"
        environment_file.write_text(f"LLAMA_ARG_RPC={endpoint}\nUNSLOTH_LLAMA_CPP_PATH={self.source}\nLLAMA_SERVER_PATH={wrapper}\n", encoding="utf-8")
        environment_file.chmod(0o600)
        self.runner.run(["systemctl", "--user", "set-environment", f"LLAMA_ARG_RPC={endpoint}", f"UNSLOTH_LLAMA_CPP_PATH={self.source}", f"LLAMA_SERVER_PATH={wrapper}"])
        self.unit.parent.mkdir(parents=True, exist_ok=True)
        self.unit.write_text(studio_unit(self.peer.worker_ip, RPC_PORT, str(self.studio), str(self.source), wrapper), encoding="utf-8")
        self.runner.run(["systemctl", "--user", "daemon-reload"])
        self.runner.run(["systemctl", "--user", "enable", self.unit.name])
        try:
            active = self.runner.run(["systemctl", "--user", "is-active", self.unit.name]).strip() == "active"
        except CommandFailure:
            active = False
        if active:
            if self._host_model_active():
                raise RuntimeError(msg("Unload the current model before updating the Studio service", "Выгрузите текущую модель перед обновлением службы Studio"))
            self.runner.run(["systemctl", "--user", "restart", self.unit.name])

    def verify_installation(self):
        peer = ClusterProbe(self.runner.run).detect()
        if peer.worker_ip != self.peer.worker_ip or peer.host_ip != self.peer.host_ip:
            raise RuntimeError(msg("ConnectX-7 route changed after installation", "Маршрут ConnectX-7 изменился после установки"))
        if not _tcp_open(peer.host_ip, peer.worker_ip, RPC_PORT) or not self._rpc_service_state():
            raise RuntimeError(msg("Worker RPC boot service is not active and reachable on ConnectX-7", "Служба RPC второго Spark не работает или недоступна через ConnectX-7"))
        if not self.studio.is_file() or not self.server.is_file():
            raise RuntimeError(msg("Unsloth Studio or llama.cpp server is missing", "Отсутствует Unsloth Studio или сервер llama.cpp"))
        if not self._llama_guard_ready():
            raise RuntimeError(msg("The llama-server dual-Spark guard is missing", "Не найдена защита запуска llama-server через два Spark"))
        unit = self.unit.read_text(encoding="utf-8")
        if f"LLAMA_ARG_RPC={peer.worker_ip}:{RPC_PORT}" not in unit:
            raise RuntimeError(msg("Studio RPC configuration differs from discovered peer", "Адрес RPC в настройках Studio не совпадает с обнаруженным вторым Spark"))
        if f"LLAMA_SERVER_PATH={self._llama_wrapper_path()}" not in unit:
            raise RuntimeError(msg("Studio is not pinned to the dual-Spark llama-server guard", "Studio не закреплена за обёрткой llama-server для двух Spark"))
        environment = (self.home / ".config/environment.d/90-connect-dual-spark.conf").read_text(encoding="utf-8")
        if f"LLAMA_ARG_RPC={peer.worker_ip}:{RPC_PORT}" not in environment or f"UNSLOTH_LLAMA_CPP_PATH={self.source}" not in environment or f"LLAMA_SERVER_PATH={self._llama_wrapper_path()}" not in environment:
            raise RuntimeError(msg("Desktop login RPC configuration differs from discovered peer", "Адрес RPC в настройках рабочего стола не совпадает с обнаруженным вторым Spark"))

    def perform(self, stage):
        getattr(self, stage)()

    def offer_studio(self):
        answer = input(msg("All checks passed. Start Unsloth Studio now? [Y/n] ", "Все проверки пройдены. Запустить Unsloth Studio сейчас? [Y/n] ")).strip().lower()
        if answer not in ("", "y", "yes", "д", "да"):
            print(msg("    Studio is ready: connect-dual-spark studio", "    Studio готова к запуску: connect-dual-spark studio"))
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
                raise RuntimeError(msg("Existing Studio service has no process", "У существующей службы Studio нет работающего процесса"))
            process_environment = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
            required = {
                f"LLAMA_ARG_RPC={self.peer.worker_ip}:{RPC_PORT}".encode(),
                f"UNSLOTH_LLAMA_CPP_PATH={self.source}".encode(),
                f"LLAMA_SERVER_PATH={self._llama_wrapper_path()}".encode(),
            }
            if not required.issubset(set(process_environment)):
                raise RuntimeError(msg("Existing Studio service has outdated RPC settings; stop it before launching the configured service", "У существующей службы Studio устаревшие настройки RPC; остановите её перед запуском настроенной службы"))
        else:
            if _tcp_open("127.0.0.1", "127.0.0.1", STUDIO_PORT):
                raise RuntimeError(msg("Port 8888 is occupied by another Studio or HTTP process; stop it before launching the configured service", "Порт 8888 занят другой Studio или HTTP-службой; остановите её перед запуском настроенной службы"))
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
            raise RuntimeError(msg("Studio service did not become ready on localhost:8888", "Служба Studio не стала доступной на localhost:8888"))
        subprocess.Popen(["xdg-open", f"http://127.0.0.1:{STUDIO_PORT}/"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True

    def check(self):
        self.detect_cluster()
        return True

    def status(self):
        self.detect_cluster()
        installed = msg("installed", "установлено")
        missing = msg("missing", "отсутствует")
        print(f"    Studio: {installed if self.studio.is_file() else missing}")
        print(f"    llama.cpp: {installed if self.server.is_file() else missing}")
        service_ready = self._rpc_service_state()
        listening = _tcp_open(self.peer.host_ip, self.peer.worker_ip, RPC_PORT)
        print(f"    {msg('Worker RPC boot service', 'Служба RPC при загрузке')}: {msg('enabled and active', 'включена и работает') if service_ready else msg('not ready', 'не готова')}")
        print(f"    {msg('Worker RPC CX7 listener', 'RPC на ConnectX-7')}: {msg('reachable', 'доступен') if listening else msg('offline', 'недоступен')}")
        print(f"    {msg('Studio unit', 'Служба Studio')}: {msg('configured', 'настроена') if self.unit.is_file() else missing}")
        print(f"    {msg('External Studio GGUF guard', 'Защита GGUF при внешнем запуске Studio')}: {msg('configured', 'настроена') if self._llama_guard_ready() else missing}")
