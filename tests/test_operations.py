import unittest
from unittest.mock import patch
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace

from dual_spark.operations import Installer, smoke_command, smoke_log_proves_rdma
from dual_spark.probe import Peer


class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.peer = Peer(
            host_ip="10.100.32.1",
            host_iface="enp1s0f0np0",
            worker_ip="10.100.32.2",
            worker_iface="enp1s0f0np0",
            worker_user="spark2",
            worker_home="/home/spark2",
            hostname="spark-793d",
            speed_mbps=200000,
        )

    def test_smoke_uses_the_guarded_studio_binary(self):
        command = smoke_command("/home/spark/.unsloth/llama.cpp/llama-server", 18765)
        self.assertNotIn("--rpc", command)
        self.assertIn("unsloth/Qwen3-0.6B-GGUF:UD-Q4_K_XL", command)
        self.assertEqual(command[0], "/home/spark/.unsloth/llama.cpp/llama-server")
        self.assertIn("127.0.0.1", command)
        self.assertEqual(command[-2:], ["--verbosity", "4"])

    def test_smoke_requires_remote_weights_and_activated_rdma(self):
        weights = "RPC0[10.100.32.2:50053] model buffer size = 400.00 MiB"
        self.assertFalse(smoke_log_proves_rdma(weights, self.peer))
        self.assertFalse(smoke_log_proves_rdma(weights + "\nRDMA activate failed, staying on TCP", self.peer))
        self.assertFalse(smoke_log_proves_rdma("RDMA activated: qpn=1->2\n" + weights, self.peer))
        self.assertTrue(smoke_log_proves_rdma(
            "RDMA activated: qpn=1->2\n"
            "Connect Dual Spark: RPC hash cache disabled by GGML_RPC_NO_HASH_CACHE\n"
            "load_tensors: loading model tensors (load_mode = dio)\n" + weights,
            self.peer,
        ))

    def test_fastload_guard_config_tracks_new_official_source_and_worker_launcher(self):
        installer = Installer(object())
        installer.peer = self.peer
        config = installer._llama_guard_config(installer.server)
        self.assertEqual(config["upstream_root"], str(installer.home / ".unsloth/llama.cpp"))
        self.assertEqual(config["worker_user"], "spark2")
        self.assertEqual(config["worker_home"], "/home/spark2")
        self.assertEqual(config["worker_exec_path"], "/home/spark2/.local/share/connect-dual-spark/worker-rpc-launcher")
        self.assertEqual(config["worker_service"], "connect-dual-spark-rpc.service")
        self.assertEqual(config["binary"], str(installer.home / ".local/share/connect-dual-spark/fastload/current/source/build/bin/llama-server"))

    def test_studio_config_pins_managed_root_guard_and_update_repair(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            commands = []

            class Runner:
                def run(self, args, **kwargs):
                    commands.append(args)
                    return "inactive\n" if args[:3] == ["systemctl", "--user", "is-active"] else ""

            installer = Installer(Runner())
            installer.home = home
            installer.peer = self.peer
            installer.upstream = home / ".unsloth/llama.cpp"
            installer.guard_link = installer.upstream / "llama-server"
            installer.source = home / ".local/share/connect-dual-spark/llama-src"
            installer.unit = home / ".config/systemd/user/connect-dual-spark-studio.service"
            installer.configure_studio()

            environment = (home / ".config/environment.d/90-connect-dual-spark.conf").read_text()
            self.assertIn(f"LLAMA_SERVER_PATH={installer.guard_link}", environment)
            self.assertIn(f"UNSLOTH_LLAMA_CPP_PATH={installer.upstream}", environment)
            self.assertIn(f"UNSLOTH_LLAMA_INSTALLER={home / '.local/share/connect-dual-spark/update_proxy.py'}", environment)
            self.assertIn("--host 0.0.0.0", installer.unit.read_text())
            self.assertTrue((installer.unit.parent / "connect-dual-spark-refresh.path").is_file())
            self.assertTrue((installer.unit.parent / "connect-dual-spark-refresh.service").is_file())
            self.assertIn(["systemctl", "--user", "enable", "--now", "connect-dual-spark-refresh.path"], commands)

    def test_existing_owned_worker_service_executable_is_reused_for_migration(self):
        installer = Installer(object())
        installer.peer = self.peer
        old = "/home/spark2/dgx-cluster/llama-rpc-build/bin/ggml-rpc-server"
        unit = (
            "[Service]\nUser=spark2\nRestart=always\n"
            f"ExecStart={old} --host 10.100.32.2 --port 50053 --cache\n"
        )
        with patch.object(installer, "_worker", side_effect=[unit, ""]):
            self.assertEqual(installer._existing_rpc_exec_path(), old)
        self.assertIsNone(installer._existing_rpc_exec_path_from_text(
            unit.replace("User=spark2", "User=root"), Path("/home/spark2")
        ))

    def test_upgrade_publishes_guard_config_before_switching_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            official = home / ".unsloth/llama.cpp"
            official.mkdir(parents=True)
            installer = Installer(object())
            installer.home = home
            installer.upstream = official
            installer.guard_link = official / "llama-server"
            installer.source = home / ".local/share/connect-dual-spark/llama-src"
            installer.server = home / ".local/share/connect-dual-spark/fastload/current/source/build/bin/llama-server"
            installer.peer = self.peer

            class AssertConfigManager:
                def __init__(self, base):
                    pass

                def refresh(self, config):
                    saved = json.loads(installer._llama_wrapper_path().with_suffix(".json").read_text())
                    self_test.assertEqual(saved, config)
                    self_test.assertEqual(installer.guard_link.resolve(), installer._llama_wrapper_path().resolve())
                    installer.server.parent.mkdir(parents=True)
                    installer.server.write_text("ready")
                    return SimpleNamespace(state="promoted", build_id="a" * 64)

            self_test = self
            with patch.object(installer, "_host_model_active", return_value=False), \
                 patch.object(installer, "_worker", return_value=""), \
                 patch("dual_spark.operations.FastloadManager", AssertConfigManager):
                installer.sync_and_build_rpc()

    def test_managed_unsloth_update_stops_studio_then_refreshes_and_restarts(self):
        events = []

        class Runner:
            def run(self, args, **kwargs):
                events.append(("run", args))
                if args[:3] == ["systemctl", "--user", "is-active"]:
                    return "active\n"
                return ""

            def run_task(self, args, **kwargs):
                events.append(("update", args))

        installer = Installer(Runner())
        with patch.object(installer, "_host_model_active", return_value=False), \
             patch.object(installer, "detect_cluster", side_effect=lambda: events.append(("detect",))), \
             patch.object(installer, "refresh", side_effect=lambda: events.append(("refresh",))):
            installer.update_unsloth()
        labels = [event[0] for event in events]
        self.assertLess(labels.index("detect"), labels.index("update"))
        self.assertLess(labels.index("update"), labels.index("refresh"))
        self.assertIn(("run", ["systemctl", "--user", "stop", installer.unit.name]), events)
        self.assertIn(("run", ["systemctl", "--user", "start", installer.unit.name]), events)

    def test_managed_unsloth_update_never_stops_active_model(self):
        installer = Installer(object())
        with patch.object(installer, "_host_model_active", return_value=True), \
             patch.object(installer, "detect_cluster") as detect:
            with self.assertRaisesRegex(RuntimeError, "active model"):
                installer.update_unsloth()
        detect.assert_not_called()

    def test_does_not_accept_an_unrelated_studio_on_port_8888(self):
        class Runner:
            def run(self, args, **kwargs):
                if args[:3] == ["systemctl", "--user", "is-active"]:
                    return "inactive\n"
                raise AssertionError("must not start a service while another process owns its port")

        installer = Installer(Runner())
        with patch("builtins.input", return_value="y"), patch("dual_spark.operations._tcp_open", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "8888"):
                installer.offer_studio()

    def test_one_file_install_bootstraps_missing_network_tools(self):
        seen = []

        class Runner:
            def run_interactive(self, args, **kwargs):
                seen.append(args)

        installer = Installer(Runner())
        with patch("dual_spark.operations.shutil.which", side_effect=lambda command: None if command in ("ethtool", "rsync") else "/usr/bin/" + command):
            installer.bootstrap_prerequisites()
        self.assertEqual(len(seen), 1)
        self.assertIn("ethtool", " ".join(seen[0]))
        self.assertIn("rsync", " ".join(seen[0]))

    def test_rpc_install_enables_system_service_and_terminal_only_shows_logs(self):
        calls = {"tasks": [], "interactive": [], "terminal": []}

        class Runner:
            def run_task(self, args, **kwargs):
                calls["tasks"].append(args)

            def run_interactive(self, args, **kwargs):
                calls["interactive"].append(args)

        installer = Installer(Runner())
        installer.peer = self.peer
        with patch.object(installer, "_rpc_service_dropins", return_value=""), \
             patch.object(installer, "_rpc_service_state", side_effect=[False, True]), \
             patch.object(installer, "_host_model_active", return_value=False), \
             patch("dual_spark.operations._tcp_open", side_effect=[False, True]), \
             patch("dual_spark.operations.subprocess.Popen", side_effect=lambda args, **kwargs: calls["terminal"].append(args)):
            installer.start_rpc()
        command = " ".join(calls["interactive"][0])
        self.assertIn("systemctl enable connect-dual-spark-rpc.service", command)
        self.assertIn("systemctl restart connect-dual-spark-rpc.service", command)
        self.assertIn("journalctl", " ".join(calls["terminal"][0]))
        self.assertNotIn("ggml-rpc-server", " ".join(calls["terminal"][0]))

    def test_active_rpc_service_can_be_enabled_without_disconnect(self):
        commands = []

        class Runner:
            def run_task(self, args, **kwargs):
                pass

            def run_interactive(self, args, **kwargs):
                commands.append(" ".join(args))

        installer = Installer(Runner())
        installer.peer = self.peer
        with patch.object(installer, "_rpc_service_dropins", return_value=""), \
             patch.object(installer, "_rpc_service_state", side_effect=[False, True]), \
             patch.object(installer, "_rpc_service_owned", return_value=True), \
             patch.object(installer, "_rpc_runtime_correct", return_value=True), \
             patch.object(installer, "_show_rpc_logs"), \
             patch("dual_spark.operations._tcp_open", return_value=True):
            installer.start_rpc()
        self.assertIn("systemctl enable connect-dual-spark-rpc.service", commands[0])
        self.assertNotIn("systemctl restart", commands[0])

    def test_active_model_defers_stale_worker_binary_restart(self):
        commands = []

        class Runner:
            def run_task(self, args, **kwargs):
                pass

            def run_interactive(self, args, **kwargs):
                commands.append(" ".join(args))

        installer = Installer(Runner())
        installer.peer = self.peer
        with patch.object(installer, "_rpc_service_dropins", return_value=""), \
             patch.object(installer, "_rpc_service_state", return_value=False), \
             patch.object(installer, "_rpc_service_owned", return_value=True), \
             patch.object(installer, "_rpc_runtime_correct", return_value=False), \
             patch.object(installer, "_host_model_active", return_value=True), \
             patch("dual_spark.operations._tcp_open", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "unload the current model"):
                installer.start_rpc()
        self.assertIn("systemctl enable connect-dual-spark-rpc.service", commands[0])
        self.assertNotIn("systemctl restart", commands[0])

    def test_existing_systemd_override_is_reported_before_install(self):
        class Runner:
            def run_task(self, *args, **kwargs):
                raise AssertionError("must not change a service with an unknown override")

        installer = Installer(Runner())
        installer.peer = self.peer
        with patch.object(installer, "_rpc_service_dropins", return_value="/etc/systemd/system/connect-dual-spark-rpc.service.d/custom.conf"):
            with self.assertRaisesRegex(RuntimeError, "override"):
                installer.start_rpc()

    def test_ready_rpc_requires_boot_enablement_and_exact_runtime(self):
        installer = Installer(object())
        installer.peer = self.peer
        binary = installer._rpc_binary()
        selected = "/home/spark2/.local/share/connect-dual-spark/fastload/current-worker/source/build/bin/ggml-rpc-server"
        running = "/home/spark2/.local/share/connect-dual-spark/fastload/releases/current/source/build/bin/ggml-rpc-server"
        properties = (
            "NeedDaemonReload=yes\nDropInPaths=\n"
            "FragmentPath=/etc/systemd/system/connect-dual-spark-rpc.service\n"
            "Restart=always\nUser=spark2\n"
        )

        def output(command):
            if "cat /etc/systemd/system" in command:
                return installer._rpc_unit_text()
            if "is-enabled" in command:
                return "enabled\n"
            if "is-active" in command:
                return "active\n"
            if "MainPID" in command:
                return "123\n"
            if "ss -H" in command:
                return 'LISTEN 0 1 10.100.32.2:50053 0.0.0.0:* users:(("ggml-rpc-server",pid=123,fd=3))\n'
            if "readlink" in command and "/proc/" in command:
                return running + "\n"
            if "readlink" in command and "current-worker" in command:
                return running + "\n"
            if "python3 -c" in command:
                return json.dumps([selected, "--host", "10.100.32.2", "--port", "50053", "--cache"])
            if "systemctl show" in command:
                return properties
            raise AssertionError(command)

        with patch.object(installer, "_worker", side_effect=output):
            self.assertTrue(installer._rpc_service_state())

        def stale(command):
            if "is-enabled" in command:
                return "disabled\n"
            return output(command)

        with patch.object(installer, "_worker", side_effect=stale):
            self.assertFalse(installer._rpc_service_state())

    def test_installs_default_and_managed_llama_server_guards(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            default = home / ".unsloth/llama.cpp"
            managed = home / ".local/share/connect-dual-spark/llama-src"
            (default / "build/bin").mkdir(parents=True)
            (managed / "build/bin").mkdir(parents=True)
            binary = managed / "build/bin/llama-server"
            binary.write_text("binary")
            (default / "llama-server").symlink_to("build/bin/llama-server")

            installer = Installer(object())
            installer.home = home
            installer.upstream = default
            installer.guard_link = default / "llama-server"
            installer.source = managed
            installer.server = binary
            installer.peer = self.peer
            installer.install_llama_guard()
            self.assertTrue(installer._llama_guard_ready())
            installer.peer = None
            self.assertTrue(installer._llama_guard_ready())
            installer.peer = self.peer

            wrapper = home / ".local/share/connect-dual-spark/llama-server-wrapper.py"
            self.assertEqual((default / "llama-server").resolve(), wrapper.resolve())
            self.assertEqual((managed / "llama-server").resolve(), wrapper.resolve())
            self.assertEqual((default / "llama-server.before-connect-dual-spark").readlink(), Path("build/bin/llama-server"))
            config = json.loads(wrapper.with_suffix(".json").read_text())
            self.assertEqual(config["rpc"], "10.100.32.2:50053")
            self.assertEqual(config["binary"], str(binary))
            (default / "llama-server").unlink()
            (default / "llama-server").symlink_to("build/bin/llama-server")
            self.assertFalse(installer._llama_guard_ready())

    def test_fastload_guard_needs_only_official_tree_not_legacy_clone(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            official = home / ".unsloth/llama.cpp"
            (official / "build/bin").mkdir(parents=True)
            (official / "build/bin/llama-server").write_text("official")
            installer = Installer(object())
            installer.home = home
            installer.upstream = official
            installer.guard_link = official / "llama-server"
            installer.source = home / ".local/share/connect-dual-spark/llama-src"
            installer.server = home / ".local/share/connect-dual-spark/fastload/current/source/build/bin/llama-server"
            installer.server.parent.mkdir(parents=True)
            installer.server.write_text("fast")
            installer.peer = self.peer
            installer.install_llama_guard()
            self.assertTrue(installer._llama_guard_ready())
            self.assertEqual(installer.guard_link.resolve(), installer._llama_wrapper_path().resolve())
            self.assertTrue((installer._llama_wrapper_path().parent / "fastload_manager.py").is_file())
            (installer._llama_wrapper_path().parent / "fastload_manager.py").write_text("stale helper")
            self.assertFalse(installer._llama_guard_ready())

    def test_standalone_relinks_guard_after_official_tree_replacement(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            official = home / ".unsloth/llama.cpp"
            (official / "build/bin").mkdir(parents=True)
            (official / "build/bin/llama-server").write_text("version one")
            installer = Installer(object())
            installer.home = home
            installer.upstream = official
            installer.guard_link = official / "llama-server"
            installer.source = home / ".local/share/connect-dual-spark/llama-src"
            installer.server = home / ".local/share/connect-dual-spark/fastload/current/source/build/bin/llama-server"
            installer.server.parent.mkdir(parents=True)
            installer.server.write_text("fast")
            installer.studio = home / "unsloth"
            installer.studio.write_text("studio")
            installer.unit = home / "studio.service"
            installer.unit.write_text(f"Environment=LLAMA_SERVER_PATH={installer.guard_link}\n")
            installer.peer = self.peer
            installer.install_llama_guard()
            shutil.rmtree(official)
            (official / "build/bin").mkdir(parents=True)
            (official / "build/bin/llama-server").write_text("version two")
            installer.peer = None
            with patch.object(installer, "preflight"), \
                 patch("dual_spark.operations.connectx_cable_present", return_value=False):
                installer.verify_standalone()
            self.assertEqual(installer.guard_link.resolve(), installer._llama_wrapper_path().resolve())

    def test_status_reports_standalone_without_contacting_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            installer = Installer(object())
            installer.studio = Path(temp) / "unsloth"
            installer.server = Path(temp) / "llama-server"
            installer.studio.write_text("installed")
            installer.server.write_text("installed")
            output = StringIO()
            with patch.object(installer, "preflight"), \
                 patch.object(installer, "_llama_guard_ready", return_value=True), \
                 patch("dual_spark.operations.connectx_cable_present", return_value=False), \
                 redirect_stdout(output):
                installer.status()
            self.assertIn("Mode: standalone", output.getvalue())

    def test_status_does_not_call_fresh_unpaired_spark_standalone(self):
        installer = Installer(object())
        output = StringIO()
        with patch.object(installer, "preflight"), \
             patch.object(installer, "_llama_guard_ready", return_value=False), \
             patch("dual_spark.operations.connectx_cable_present", return_value=False), \
             redirect_stdout(output):
            installer.status()
        self.assertIn("unconfigured", output.getvalue())
        self.assertNotIn("Mode: standalone", output.getvalue())

    def test_standalone_studio_uses_saved_pair_without_contacting_worker(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            installer = Installer(object())
            installer.home = home
            installer.studio = home / "unsloth"
            installer.server = home / "llama-server-real"
            installer.unit = home / "studio.service"
            installer.studio.write_text("installed")
            installer.server.write_text("installed")
            wrapper = installer._llama_wrapper_path()
            wrapper.parent.mkdir(parents=True)
            wrapper.with_suffix(".json").write_text('{"rpc":"10.100.32.2:50053"}')
            installer.unit.write_text(f"Environment=LLAMA_SERVER_PATH={wrapper}\n")
            with patch.object(installer, "preflight"), \
                 patch.object(installer, "_llama_guard_ready", return_value=True), \
                 patch("dual_spark.operations.connectx_cable_present", return_value=False):
                installer.verify_standalone()

    def test_standalone_studio_refreshes_wrapper_after_package_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            default = home / ".unsloth/llama.cpp"
            managed = home / ".local/share/connect-dual-spark/llama-src"
            default.mkdir(parents=True)
            (default / "build/bin").mkdir(parents=True)
            (default / "build/bin/llama-server").write_text("official")
            managed.mkdir(parents=True)
            installer = Installer(object())
            installer.home = home
            installer.upstream = default
            installer.guard_link = default / "llama-server"
            installer.source = managed
            installer.server = managed / "build/bin/llama-server"
            installer.server.parent.mkdir(parents=True)
            installer.server.write_text("binary")
            installer.studio = home / "unsloth"
            installer.studio.write_text("installed")
            installer.unit = home / "studio.service"
            installer.peer = self.peer
            installer.install_llama_guard()
            wrapper = installer._llama_wrapper_path()
            installer.unit.write_text(f"Environment=LLAMA_SERVER_PATH={wrapper}\n")
            config_path = wrapper.with_suffix(".json")
            old_config = json.loads(config_path.read_text())
            old_config.pop("guard_revision")
            for key in ("upstream_root", "worker_user", "worker_home", "worker_exec_path", "worker_service"):
                old_config.pop(key)
            config_path.write_text(json.dumps(old_config))
            installer.peer = None
            self.assertFalse(installer._llama_guard_ready())
            installer.peer = self.peer
            wrapper.write_text("old wrapper")
            (default / "llama-server").unlink()
            (default / "llama-server").symlink_to("missing-old-runtime")
            installer.peer = None
            self.assertFalse(installer._llama_guard_ready())
            with patch.object(installer, "preflight"), \
                 patch("dual_spark.operations.connectx_cable_present", return_value=False):
                installer.verify_standalone()
            self.assertTrue(installer._llama_guard_ready())
            self.assertIn("guard_revision", json.loads(config_path.read_text()))

    def test_standalone_refresh_refuses_to_downgrade_newer_guard(self):
        with tempfile.TemporaryDirectory() as temp:
            home = Path(temp)
            default = home / ".unsloth/llama.cpp"
            managed = home / ".local/share/connect-dual-spark/llama-src"
            default.mkdir(parents=True)
            (default / "build/bin").mkdir(parents=True)
            (default / "build/bin/llama-server").write_text("official")
            managed.mkdir(parents=True)
            installer = Installer(object())
            installer.home = home
            installer.upstream = default
            installer.guard_link = default / "llama-server"
            installer.source = managed
            installer.server = managed / "build/bin/llama-server"
            installer.server.parent.mkdir(parents=True)
            installer.server.write_text("binary")
            installer.studio = home / "unsloth"
            installer.studio.write_text("installed")
            installer.unit = home / "studio.service"
            installer.peer = self.peer
            installer.install_llama_guard()
            wrapper = installer._llama_wrapper_path()
            installer.unit.write_text(f"Environment=LLAMA_SERVER_PATH={wrapper}\n")
            config_path = wrapper.with_suffix(".json")
            newer = json.loads(config_path.read_text())
            newer["guard_revision"] += 1
            config_path.write_text(json.dumps(newer))
            wrapper.write_text("newer wrapper")
            installer.peer = None
            with patch.object(installer, "preflight"), \
                 patch("dual_spark.operations.connectx_cable_present", return_value=False):
                with self.assertRaisesRegex(RuntimeError, "newer"):
                    installer.verify_standalone()
            self.assertEqual(wrapper.read_text(), "newer wrapper")


if __name__ == "__main__":
    unittest.main()
