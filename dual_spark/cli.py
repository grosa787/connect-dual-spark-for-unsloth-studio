"""One-command desktop and terminal entry point."""

import argparse
import sys

from .operations import Installer
from .system import CommandFailure, Runner
from .workflow import SetupWorkflow


LABELS = {
    "detect_cluster": "Проверка двух Spark и ConnectX-7",
    "install_studio": "Установка Unsloth Studio",
    "sync_and_build_rpc": "Синхронизация и сборка RPC на втором Spark",
    "start_rpc": "Автозапуск RPC на втором Spark и просмотр журнала",
    "smoke_test": "Пробный запуск небольшой GGUF-модели",
    "configure_studio": "Настройка Unsloth Studio",
    "verify_installation": "Итоговая проверка",
}


class DisplaySetup:
    def __init__(self, installer):
        self.installer = installer

    def perform(self, stage):
        print(f"\n▶ {LABELS[stage]}", flush=True)
        self.installer.perform(stage)
        print("  ✓ Готово", flush=True)

    def offer_studio(self):
        return self.installer.offer_studio()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="connect-dual-spark", description="Connect two DGX Sparks for Unsloth Studio")
    parser.add_argument("command", choices=("install", "check", "start-rpc", "status", "studio"), nargs="?", default="install")
    parser.add_argument("--verbose", action="store_true", help="show task output as it completes")
    args = parser.parse_args(argv)
    runner = Runner(verbose=args.verbose)
    installer = Installer(runner)
    print("Connect Dual Spark for Unsloth Studio")
    print(f"Журнал: {runner.log_path}")
    try:
        if args.command == "install":
            installer.bootstrap = True
            SetupWorkflow(DisplaySetup(installer)).run()
        elif args.command == "check":
            installer.check()
            print("✓ ConnectX-7, маршрут и SSH работают")
        elif args.command == "start-rpc":
            installer.detect_cluster()
            installer.start_rpc()
            print("✓ RPC запущен")
        elif args.command == "studio":
            installer.detect_cluster()
            installer.verify_installation()
            installer.launch_studio()
            print("✓ Studio запущена")
        else:
            installer.status()
    except (CommandFailure, RuntimeError, OSError, ValueError) as exc:
        print(f"\n✗ {exc}\nЖурнал: {runner.log_path}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
