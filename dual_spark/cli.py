"""One-command desktop and terminal entry point."""

import argparse
import sys

from .language import current_language, msg, resolve_language, set_language
from .operations import Installer
from .system import CommandFailure, Runner
from .workflow import SetupWorkflow


LABELS = {
    "detect_cluster": ("Checking both Sparks and ConnectX-7", "Проверка двух Spark и ConnectX-7"),
    "install_studio": ("Installing Unsloth Studio", "Установка Unsloth Studio"),
    "sync_and_build_rpc": ("Syncing and building RPC on the second Spark", "Синхронизация и сборка RPC на втором Spark"),
    "start_rpc": ("Enabling worker RPC at boot and opening its log", "Автозапуск RPC на втором Spark и просмотр журнала"),
    "smoke_test": ("Testing a small GGUF model", "Пробный запуск небольшой GGUF-модели"),
    "configure_studio": ("Configuring Unsloth Studio", "Настройка Unsloth Studio"),
    "verify_installation": ("Final verification", "Итоговая проверка"),
}


class LocalizedArgumentParser(argparse.ArgumentParser):
    def format_help(self):
        help_text = super().format_help()
        return help_text.replace("usage:", msg("usage:", "использование:"), 1)

    def format_usage(self):
        usage = super().format_usage()
        return usage.replace("usage:", msg("usage:", "использование:"), 1)

    def error(self, message):
        if current_language() == "ru":
            for english, russian in (
                ("invalid choice:", "неверное значение:"),
                ("choose from", "выберите из"),
                ("expected one argument", "требуется одно значение"),
                ("unrecognized arguments:", "неизвестные аргументы:"),
                ("the following arguments are required:", "требуются аргументы:"),
                ("argument", "аргумент"),
            ):
                message = message.replace(english, russian)
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {msg('error', 'ошибка')}: {message}\n")


class DisplaySetup:
    def __init__(self, installer):
        self.installer = installer

    def perform(self, stage):
        print(f"\n▶ {msg(*LABELS[stage])}", flush=True)
        self.installer.perform(stage)
        print(msg("  ✓ Done", "  ✓ Готово"), flush=True)

    def offer_studio(self):
        return self.installer.offer_studio()


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    language_choice = "auto"
    for index, argument in enumerate(arguments):
        if argument == "--lang" and index + 1 < len(arguments):
            language_choice = arguments[index + 1]
        elif argument.startswith("--lang="):
            language_choice = argument.split("=", 1)[1]
    set_language(resolve_language(language_choice if language_choice in ("en", "ru", "auto") else "auto"))
    parser = LocalizedArgumentParser(prog="connect-dual-spark", add_help=False, description=msg("Connect two DGX Sparks for Unsloth Studio", "Подключить два DGX Spark для Unsloth Studio"))
    parser._positionals.title = msg("commands", "Команды")
    parser._optionals.title = msg("options", "Параметры")
    parser.add_argument("-h", "--help", action="help", help=msg("show this help message and exit", "показать справку и выйти"))
    parser.add_argument("command", choices=("install", "check", "start-rpc", "status", "studio"), nargs="?", default="install")
    parser.add_argument("--lang", choices=("en", "ru", "auto"), default="auto", help=msg("installer language (default: system locale)", "язык установщика (по умолчанию: язык системы)"))
    parser.add_argument("--verbose", action="store_true", help=msg("show task output as it completes", "показывать вывод задач по завершении"))
    args = parser.parse_args(argv)
    runner = Runner(verbose=args.verbose)
    installer = Installer(runner)
    print("Connect Dual Spark for Unsloth Studio")
    print(msg(f"Log: {runner.log_path}", f"Журнал: {runner.log_path}"))
    try:
        if args.command == "install":
            installer.bootstrap = True
            SetupWorkflow(DisplaySetup(installer)).run()
        elif args.command == "check":
            installer.check()
            print(msg("✓ ConnectX-7, routing, and SSH are ready", "✓ ConnectX-7, маршрут и SSH работают"))
        elif args.command == "start-rpc":
            installer.detect_cluster()
            installer.start_rpc()
            print(msg("✓ RPC is running", "✓ RPC запущен"))
        elif args.command == "studio":
            installer.detect_cluster()
            installer.verify_installation()
            installer.launch_studio()
            print(msg("✓ Studio is running", "✓ Studio запущена"))
        else:
            installer.status()
    except (CommandFailure, RuntimeError, OSError, ValueError) as exc:
        print(msg(f"\n✗ {exc}\nLog: {runner.log_path}", f"\n✗ {exc}\nЖурнал: {runner.log_path}"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
