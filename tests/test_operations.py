import unittest
from unittest.mock import patch

from dual_spark.operations import Installer, rpc_launcher_script, smoke_command, smoke_log_proves_rdma
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

    def test_rpc_launcher_uses_only_selected_peer_and_cache(self):
        script = rpc_launcher_script(self.peer, port=50053)
        self.assertIn("--host 10.100.32.2 --port 50053 --cache", script)
        self.assertNotIn("192.168.", script)
        self.assertNotIn("0.0.0.0", script)

    def test_smoke_model_forces_a_remote_weight_split(self):
        command = smoke_command(
            "/home/spark/.unsloth/llama.cpp/llama-server", self.peer, 50053, 18765
        )
        self.assertIn("--rpc", command)
        self.assertEqual(command[command.index("--rpc") + 1], "10.100.32.2:50053")
        self.assertEqual(command[command.index("--tensor-split") + 1], "1,1")
        self.assertIn("unsloth/Qwen3-0.6B-GGUF:UD-Q4_K_XL", command)
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


if __name__ == "__main__":
    unittest.main()
