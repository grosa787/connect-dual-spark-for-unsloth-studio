import unittest
from unittest.mock import patch
import json
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import tempfile

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

    def test_smoke_requires_remote_weights_and_activated_rdma(self):
        weights = "RPC0[10.100.32.2:50053] model buffer size = 400.00 MiB"
        self.assertFalse(smoke_log_proves_rdma(weights, self.peer))
        self.assertFalse(smoke_log_proves_rdma(weights + "\nRDMA activate failed, staying on TCP", self.peer))
        self.assertTrue(smoke_log_proves_rdma("RDMA activated: qpn=1->2\n" + weights, self.peer))

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
        properties = (
            "NeedDaemonReload=no\nDropInPaths=\n"
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
            if "readlink" in command:
                return binary + "\n"
            if "python3 -c" in command:
                return json.dumps([binary, "--host", "10.100.32.2", "--port", "50053", "--cache"])
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
            managed.mkdir(parents=True)
            installer = Installer(object())
            installer.home = home
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
            managed.mkdir(parents=True)
            installer = Installer(object())
            installer.home = home
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
