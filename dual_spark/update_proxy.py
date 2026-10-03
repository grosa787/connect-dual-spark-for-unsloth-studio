#!/usr/bin/python3
"""Forward Unsloth llama updates and reconcile the durable fastload pair."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys


READ_ONLY_FLAGS = {"--resolve-prebuilt", "--check-existing-install"}


def _studio_directories(spec):
    directories = []
    for location in spec.submodule_search_locations or ():
        directory = Path(location)
        if directory not in directories:
            directories.append(directory)
    if spec.origin and spec.origin not in ("built-in", "namespace"):
        directory = Path(spec.origin).parent
        if directory not in directories:
            directories.append(directory)
    return directories


def find_official_installer(*, find_spec=importlib.util.find_spec, proxy_path=Path(__file__)):
    """Locate Studio's bundled installer without following the proxy back to itself."""
    spec = find_spec("studio")
    if spec is None:
        raise RuntimeError("cannot locate Studio's official installer: Python package 'studio' was not found")

    proxy = Path(proxy_path).resolve()
    recursive_candidate = False
    for directory in _studio_directories(spec):
        candidate = directory / "install_llama_prebuilt.py"
        if not candidate.is_file():
            continue
        if candidate.resolve() == proxy:
            recursive_candidate = True
            continue
        return candidate

    if recursive_candidate:
        raise RuntimeError("refusing recursive updater proxy: Studio's installer resolves to this proxy")
    raise RuntimeError("cannot locate Studio's official installer: install_llama_prebuilt.py was not found")


def refresh_install_root(argv):
    """Return the installed root for a real installation, or None for read-only calls."""
    if any(argument.split("=", 1)[0] in READ_ONLY_FLAGS for argument in argv):
        return None

    install_root = None
    for index, argument in enumerate(argv):
        if argument == "--install-dir":
            if index + 1 < len(argv) and argv[index + 1]:
                install_root = Path(argv[index + 1])
        elif argument.startswith("--install-dir="):
            value = argument.split("=", 1)[1]
            if value:
                install_root = Path(value)
    return install_root


def _process_kwargs(environment, stdin, stdout, stderr):
    return {
        "env": environment,
        "stdin": stdin,
        "stdout": stdout,
        "stderr": stderr,
        "check": False,
    }


def _report_error(stream, message):
    target = sys.stderr if stream is None else stream
    target.write(message + "\n")
    target.flush()


def run_proxy(
    argv,
    *,
    find_spec=importlib.util.find_spec,
    run_process=subprocess.run,
    executable=sys.executable,
    environment=None,
    stdin=None,
    stdout=None,
    stderr=None,
    proxy_path=Path(__file__),
    manager_path=None,
    replace_process=None,
):
    """Run the official installer, then refresh fastload after a successful install."""
    try:
        installer = find_official_installer(find_spec=find_spec, proxy_path=proxy_path)
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        _report_error(stderr, "update proxy error: {}".format(exc))
        return 2

    forwarded = _process_kwargs(environment, stdin, stdout, stderr)
    try:
        installed = run_process([executable, str(installer), *argv], **forwarded)
    except OSError as exc:
        _report_error(stderr, "update proxy error: could not run Studio's official installer: {}".format(exc))
        return 2
    if installed.returncode:
        return installed.returncode

    install_root = refresh_install_root(argv)
    if install_root is None:
        return 0

    manager = Path(manager_path) if manager_path is not None else Path(proxy_path).with_name("fastload_manager.py")
    manager_command = [executable, str(manager), "refresh", "--install-root", str(install_root)]
    if replace_process is not None:
        try:
            # Keep the same PID that Studio's update watchdog can terminate.
            replace_process(executable, manager_command, dict(os.environ if environment is None else environment))
        except OSError as exc:
            _report_error(stderr, "fastload refresh failed after the official install: {}".format(exc))
            return 2
        _report_error(stderr, "fastload refresh failed: process replacement returned unexpectedly")
        return 2
    try:
        refreshed = run_process(
            manager_command,
            **forwarded,
        )
    except OSError as exc:
        _report_error(stderr, "fastload refresh failed after the official install: {}".format(exc))
        return 2
    if refreshed.returncode:
        _report_error(
            stderr,
            "fastload refresh failed after the official install (exit code {})".format(refreshed.returncode),
        )
        return refreshed.returncode
    return 0


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else argv
    return run_proxy(
        arguments,
        environment=os.environ,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
        replace_process=os.execvpe,
    )


if __name__ == "__main__":
    raise SystemExit(main())
