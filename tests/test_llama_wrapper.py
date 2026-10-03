import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dual_spark.llama_wrapper import enforced_command, reject_placement_overrides, require_peer, route_matches_connectx, sanitize_device_env


class LlamaWrapperTests(unittest.TestCase):
    def test_model_launch_enforces_remote_rpc_and_two_nonzero_splits(self):
        original = ["-m", "/models/model.gguf", "--rpc", "192.168.1.3:50053", "-c", "4096"]
        command = enforced_command("/opt/llama-server", original, "10.100.32.2:50053")
        self.assertEqual(command[:1 + len(original)], ["/opt/llama-server", *original])
        self.assertEqual(command[-10:], [
            "--rpc", "10.100.32.2:50053", "--device", "CUDA0,RPC0", "--split-mode", "layer",
            "--tensor-split", "1,1", "--n-gpu-layers", "all",
        ])

    def test_conflicting_api_device_choice_is_overridden_last(self):
        for chosen_device in ("CUDA0", "none"):
            with self.subTest(chosen_device=chosen_device):
                args = ["-m", "/models/model.gguf", "--device", chosen_device]
                command = enforced_command("/opt/llama-server", args, "10.100.32.2:50053")
                self.assertEqual(command[command.index("--device") + 1], chosen_device)
                self.assertEqual(command[-10:][3], "CUDA0,RPC0")

    def test_device_probe_includes_the_rpc_peer(self):
        self.assertEqual(
            enforced_command("/opt/llama-server", ["--list-devices"], "10.100.32.2:50053"),
            ["/opt/llama-server", "--rpc", "10.100.32.2:50053", "--list-devices"],
        )
        self.assertEqual(
            enforced_command("/opt/llama-server", ["--device", "CUDA0", "--rpc", "192.168.1.3:50053", "--list-devices"], "10.100.32.2:50053"),
            ["/opt/llama-server", "--rpc", "10.100.32.2:50053", "--list-devices"],
        )

    def test_inherited_device_restrictions_are_removed(self):
        environment = {"LLAMA_ARG_DEVICE": "none", "CUDA_VISIBLE_DEVICES": "-1", "OTHER": "keep"}
        sanitize_device_env(environment)
        self.assertEqual(environment, {"OTHER": "keep"})

    def test_tensor_override_that_could_hide_rpc_is_rejected(self):
        for args, environment in (
            (["-ot", ".*=CUDA0"], {}),
            (["--override-tensor=.*=CPU"], {}),
            ([], {"LLAMA_ARG_OVERRIDE_TENSOR": ".*=CUDA0"}),
        ):
            with self.subTest(args=args, environment=environment):
                with self.assertRaisesRegex(RuntimeError, "tensor placement override"):
                    reject_placement_overrides(args, environment)

    def test_help_does_not_require_worker_connection(self):
        self.assertEqual(
            enforced_command("/opt/llama-server", ["--help"], "10.100.32.2:50053"),
            ["/opt/llama-server", "--help"],
        )

    def test_route_must_remain_on_discovered_connectx_interface(self):
        direct = json.dumps([{"dev": "enp1s0f0np0", "prefsrc": "10.100.32.1"}])
        lan = json.dumps([{"dev": "enP7s7", "prefsrc": "192.168.150.90"}])
        self.assertTrue(route_matches_connectx(direct, "enp1s0f0np0", "10.100.32.1"))
        self.assertFalse(route_matches_connectx(lan, "enp1s0f0np0", "10.100.32.1"))

    def test_reachability_uses_same_source_address_as_route_lookup(self):
        config = {"rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1", "host_iface": "enp1s0f0np0"}
        route = '[{"dev":"enp1s0f0np0","from":"10.100.32.1"}]'
        with patch("dual_spark.llama_wrapper.subprocess.run", return_value=SimpleNamespace(stdout=route)) as lookup, \
             patch("dual_spark.llama_wrapper.socket.socket") as socket_factory:
            require_peer(config)
        self.assertEqual(lookup.call_args.args[0], [
            "ip", "-j", "route", "get", "10.100.32.2", "from", "10.100.32.1",
        ])
        socket_factory.return_value.__enter__.return_value.bind.assert_called_once_with(("10.100.32.1", 0))


if __name__ == "__main__":
    unittest.main()
