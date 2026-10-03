import io
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from dual_spark.update_proxy import find_official_installer, refresh_install_root, run_proxy


class UpdateProxyTests(unittest.TestCase):
    def _studio_spec(self, studio_directory):
        return SimpleNamespace(
            origin=str(studio_directory / "__init__.py"),
            submodule_search_locations=[str(studio_directory)],
        )

    def test_successful_install_is_forwarded_then_refreshed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            studio = root / "site-packages/studio"
            studio.mkdir(parents=True)
            installer = studio / "install_llama_prebuilt.py"
            installer.write_text("# official installer\n", encoding="utf-8")
            manager = root / "durable/fastload_manager.py"
            manager.parent.mkdir()
            manager.write_text("# manager\n", encoding="utf-8")
            environment = {"UNSLOTH_LLAMA_INSTALLER": "/durable/update_proxy.py", "KEEP": "yes"}
            standard_input = object()
            standard_output = object()
            standard_error = object()
            calls = []

            def process(command, **kwargs):
                calls.append((command, kwargs))
                return SimpleNamespace(returncode=0)

            result = run_proxy(
                ["--install-dir", "/home/spark/.unsloth/llama.cpp", "--llama-tag", "b7000"],
                find_spec=lambda name: self._studio_spec(studio),
                run_process=process,
                executable="/studio/venv/bin/python",
                environment=environment,
                stdin=standard_input,
                stdout=standard_output,
                stderr=standard_error,
                proxy_path=root / "durable/update_proxy.py",
                manager_path=manager,
            )

        self.assertEqual(result, 0)
        forwarded = {
            "env": environment,
            "stdin": standard_input,
            "stdout": standard_output,
            "stderr": standard_error,
            "check": False,
        }
        self.assertEqual(calls, [
            ([
                "/studio/venv/bin/python", str(installer),
                "--install-dir", "/home/spark/.unsloth/llama.cpp",
                "--llama-tag", "b7000",
            ], forwarded),
            ([
                "/studio/venv/bin/python", str(manager), "refresh",
                "--install-root", "/home/spark/.unsloth/llama.cpp",
            ], forwarded),
        ])

    def test_resolver_and_existing_install_checks_never_refresh(self):
        for special_argument in ("--resolve-prebuilt", "--check-existing-install"):
            with self.subTest(special_argument=special_argument), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                studio = root / "studio"
                studio.mkdir()
                installer = studio / "install_llama_prebuilt.py"
                installer.write_text("# official installer\n", encoding="utf-8")
                calls = []

                def process(command, **kwargs):
                    calls.append(command)
                    return SimpleNamespace(returncode=0)

                result = run_proxy(
                    [special_argument, "--install-dir=/managed/llama.cpp"],
                    find_spec=lambda name: self._studio_spec(studio),
                    run_process=process,
                    executable="python",
                    proxy_path=root / "update_proxy.py",
                    manager_path=root / "fastload_manager.py",
                )

            self.assertEqual(result, 0)
            self.assertEqual(calls, [["python", str(installer), special_argument, "--install-dir=/managed/llama.cpp"]])

    def test_official_installer_failure_is_returned_without_refresh(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            studio = root / "studio"
            studio.mkdir()
            installer = studio / "install_llama_prebuilt.py"
            installer.write_text("# official installer\n", encoding="utf-8")
            calls = []

            def process(command, **kwargs):
                calls.append(command)
                return SimpleNamespace(returncode=23)

            result = run_proxy(
                ["--install-dir", "/managed/llama.cpp"],
                find_spec=lambda name: self._studio_spec(studio),
                run_process=process,
                executable="python",
                proxy_path=root / "update_proxy.py",
                manager_path=root / "fastload_manager.py",
            )

        self.assertEqual(result, 23)
        self.assertEqual(calls, [["python", str(installer), "--install-dir", "/managed/llama.cpp"]])

    def test_refresh_failure_is_reported_and_returned(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            studio = root / "studio"
            studio.mkdir()
            installer = studio / "install_llama_prebuilt.py"
            installer.write_text("# official installer\n", encoding="utf-8")
            error = io.StringIO()
            results = iter((SimpleNamespace(returncode=0), SimpleNamespace(returncode=9)))

            result = run_proxy(
                ["--install-dir=/managed/llama.cpp"],
                find_spec=lambda name: self._studio_spec(studio),
                run_process=lambda command, **kwargs: next(results),
                executable="python",
                stderr=error,
                proxy_path=root / "update_proxy.py",
                manager_path=root / "fastload_manager.py",
            )

        self.assertEqual(result, 9)
        self.assertIn("fastload refresh failed", error.getvalue())
        self.assertIn("exit code 9", error.getvalue())

    def test_namespace_package_location_finds_official_installer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            studio = root / "namespace/studio"
            studio.mkdir(parents=True)
            installer = studio / "install_llama_prebuilt.py"
            installer.write_text("# official installer\n", encoding="utf-8")
            spec = SimpleNamespace(origin=None, submodule_search_locations=[str(studio)])

            found = find_official_installer(
                find_spec=lambda name: spec,
                proxy_path=root / "update_proxy.py",
            )

        self.assertEqual(found, installer)

    def test_regular_package_origin_finds_official_installer(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            studio = root / "site-packages/studio"
            studio.mkdir(parents=True)
            installer = studio / "install_llama_prebuilt.py"
            installer.write_text("# official installer\n", encoding="utf-8")
            spec = SimpleNamespace(
                origin=str(studio / "__init__.py"),
                submodule_search_locations=None,
            )

            found = find_official_installer(
                find_spec=lambda name: spec,
                proxy_path=root / "update_proxy.py",
            )

        self.assertEqual(found, installer)

    def test_missing_official_installer_reports_a_clear_error(self):
        error = io.StringIO()

        result = run_proxy(
            ["--resolve-prebuilt"],
            find_spec=lambda name: None,
            run_process=lambda command, **kwargs: self.fail("must not run"),
            executable="python",
            stderr=error,
        )

        self.assertEqual(result, 2)
        self.assertIn("cannot locate Studio's official installer", error.getvalue())

    def test_official_installer_cannot_resolve_back_to_proxy(self):
        with tempfile.TemporaryDirectory() as temp:
            studio = Path(temp) / "studio"
            studio.mkdir()
            proxy = studio / "install_llama_prebuilt.py"
            proxy.write_text("# proxy\n", encoding="utf-8")

            with self.assertRaisesRegex(RuntimeError, "refusing recursive updater proxy"):
                find_official_installer(
                    find_spec=lambda name: self._studio_spec(studio),
                    proxy_path=proxy,
                )

    def test_refresh_root_parses_both_install_dir_forms(self):
        self.assertEqual(refresh_install_root(["--install-dir", "/managed/a"]), Path("/managed/a"))
        self.assertEqual(refresh_install_root(["--install-dir=/managed/b"]), Path("/managed/b"))
        self.assertIsNone(refresh_install_root(["--llama-tag", "b7000"]))
        self.assertIsNone(refresh_install_root(["--resolve-prebuilt", "--install-dir", "/managed/a"]))

    def test_real_install_replaces_proxy_with_manager_for_watchdog_cancellation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            studio = root / "studio"
            studio.mkdir()
            (studio / "install_llama_prebuilt.py").write_text("# official\n")
            manager = root / "fastload_manager.py"
            calls = []

            class Replaced(Exception):
                pass

            def process(command, **kwargs):
                calls.append(("official", command))
                return SimpleNamespace(returncode=0)

            def replace(executable, command, environment):
                calls.append(("replace", executable, command, environment))
                raise Replaced()

            with self.assertRaises(Replaced):
                run_proxy(
                    ["--install-dir", "/managed/llama.cpp"],
                    find_spec=lambda name: self._studio_spec(studio),
                    run_process=process, replace_process=replace,
                    executable="/venv/python", environment={"KEEP": "yes"},
                    proxy_path=root / "update_proxy.py", manager_path=manager,
                )
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[1][0], "replace")
        self.assertEqual(calls[1][2], [
            "/venv/python", str(manager), "refresh", "--install-root", "/managed/llama.cpp",
        ])


if __name__ == "__main__":
    unittest.main()
