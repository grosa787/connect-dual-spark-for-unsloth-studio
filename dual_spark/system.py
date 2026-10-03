"""Small subprocess boundary with a persistent installation log."""

from datetime import datetime
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time

from .language import msg


class CommandFailure(RuntimeError):
    pass


class Runner:
    def __init__(self, log_path=None, verbose=False):
        if log_path is None:
            state = Path.home() / ".local" / "state" / "connect-dual-spark"
            state.mkdir(mode=0o700, parents=True, exist_ok=True)
            log_path = state / ("setup-" + datetime.now().strftime("%Y%m%d-%H%M%S") + ".log")
        self.log_path = Path(log_path)
        self.log_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.verbose = verbose

    def _record(self, args, output=""):
        with self.log_path.open("a", encoding="utf-8") as log:
            log.write("\n$ " + shlex.join([str(arg) for arg in args]) + "\n")
            if output:
                log.write(output)
                if not output.endswith("\n"):
                    log.write("\n")

    def run(self, args, *, timeout=20, env=None, cwd=None):
        try:
            result = subprocess.run(
                [str(arg) for arg in args],
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
                cwd=cwd,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            self._record(args, str(exc))
            raise CommandFailure(msg(f"Could not run {args[0]}: {exc}", f"Не удалось запустить {args[0]}: {exc}")) from exc
        self._record(args, result.stdout + result.stderr)
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().splitlines()[-3:]
            raise CommandFailure(msg(
                f"{args[0]} exited with {result.returncode}: {' | '.join(detail)}",
                f"Команда {args[0]} завершилась с кодом {result.returncode}: {' | '.join(detail)}",
            ))
        return result.stdout

    def run_task(self, args, *, label, timeout=3600, env=None, cwd=None):
        args = [str(arg) for arg in args]
        self._record(args)
        start = time.monotonic()
        try:
            with self.log_path.open("a", encoding="utf-8") as log:
                proc = subprocess.Popen(
                    args,
                    stdin=sys.stdin,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    env=env,
                    cwd=cwd,
                )
                while proc.poll() is None:
                    elapsed = int(time.monotonic() - start)
                    if sys.stdout.isatty():
                        print(f"\r    {label} · {elapsed // 60:02d}:{elapsed % 60:02d}", end="", flush=True)
                    if elapsed > timeout:
                        proc.terminate()
                        try:
                            proc.wait(timeout=10)
                        except subprocess.TimeoutExpired:
                            proc.kill()
                        raise CommandFailure(msg(f"{label} timed out after {timeout}s", f"Превышено время ожидания задачи «{label}»: {timeout} с"))
                    time.sleep(1)
        except OSError as exc:
            raise CommandFailure(msg(f"Could not start {label}: {exc}", f"Не удалось начать задачу «{label}»: {exc}")) from exc
        if sys.stdout.isatty():
            print("\r" + " " * 72 + "\r", end="", flush=True)
        if proc.returncode:
            tail = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-12:]
            raise CommandFailure(msg(
                f"{label} failed (exit {proc.returncode}). Log: {self.log_path}\n",
                f"Задача «{label}» завершилась с ошибкой (код {proc.returncode}). Журнал: {self.log_path}\n",
            ) + "\n".join(tail))
        if self.verbose:
            print("\n".join(self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-8:]))

    def run_interactive(self, args, *, label):
        args = [str(arg) for arg in args]
        self._record(args)
        print(msg(
            f"    {label}: an operating-system authorization prompt may appear below.",
            f"    {label}: системный запрос прав доступа может появиться ниже.",
        ), flush=True)
        try:
            result = subprocess.run(args, stdin=sys.stdin)
        except OSError as exc:
            raise CommandFailure(msg(f"Could not run {label}: {exc}", f"Не удалось запустить задачу «{label}»: {exc}")) from exc
        if result.returncode:
            raise CommandFailure(msg(f"{label} failed (exit {result.returncode})", f"Задача «{label}» завершилась с ошибкой (код {result.returncode})"))


def remote_ssh(peer, command, *, tty=False):
    """Route every peer command through the selected ConnectX-7 source IP."""
    return [
        "ssh", "-tt" if tty else "-T", "-b", peer.host_ip,
        "-o", f"BindInterface={peer.host_iface}",
        "-o", "BatchMode=yes",
        "-o", "ConnectTimeout=10",
        "-o", "StrictHostKeyChecking=accept-new",
        peer.worker_ip, command,
    ]


def remote_cmd(*argv):
    return shlex.join([str(arg) for arg in argv])
