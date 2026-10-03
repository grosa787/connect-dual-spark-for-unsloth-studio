import json
import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dual_spark.llama_wrapper import (
    GUARD_REVISION, connectx_cable_present, enforced_command, local_command,
    main, reject_placement_overrides, require_peer, route_matches_connectx,
    sanitize_device_env, sanitize_local_env, validate_saved_pair,
)


class LlamaWrapperTests(unittest.TestCase):
    def test_model_launch_enforces_remote_rpc_and_two_nonzero_splits(self):
        original = ["-m", "/models/model.gguf", "--rpc", "192.168.1.3:50053", "-c", "4096"]
        command = enforced_command("/opt/llama-server", original, "10.100.32.2:50053")
        self.assertNotIn("192.168.1.3:50053", command)
        self.assertEqual(command.count("--rpc"), 1)
        self.assertEqual(command[:5], ["/opt/llama-server", "-m", "/models/model.gguf", "-c", "4096"])
        self.assertEqual(command[-10:], [
            "--rpc", "10.100.32.2:50053", "--device", "CUDA0,RPC0", "--split-mode", "layer",
            "--tensor-split", "1,1", "--n-gpu-layers", "all",
        ])

    def test_conflicting_api_device_choice_is_overridden_last(self):
        for chosen_device in ("CUDA0", "none"):
            with self.subTest(chosen_device=chosen_device):
                args = ["-m", "/models/model.gguf", "--device", chosen_device]
                command = enforced_command("/opt/llama-server", args, "10.100.32.2:50053")
                self.assertNotIn(chosen_device, command[:4])
                self.assertEqual(command.count("--device"), 1)
                self.assertEqual(command[-10:][3], "CUDA0,RPC0")

    def test_old_management_rpc_and_split_flags_are_removed_before_backend_init(self):
        command = enforced_command("/opt/llama-server", [
            "--rpc", "192.168.150.49:50052", "--rpc=192.168.150.49:50052",
            "--device", "CUDA0,RPC0", "-ts", "1,0", "-sm", "none", "-ngl", "0",
            "-m", "/models/model.gguf",
        ], "10.100.32.2:50053")
        self.assertNotIn("192.168.150.49:50052", " ".join(command))
        self.assertEqual(command.count("--rpc"), 1)
        self.assertEqual(command.count("--device"), 1)
        self.assertEqual(command[:3], ["/opt/llama-server", "-m", "/models/model.gguf"])

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

    def test_local_mode_removes_stale_rpc_and_leaves_memory_fit_to_llama(self):
        args = [
            "-m", "/models/model.gguf", "--fit", "on", "--rpc", "10.100.32.2:50053",
            "--device", "CUDA0,RPC0", "--tensor-split", "1,1", "-c", "4096",
        ]
        self.assertEqual(local_command("/opt/llama-server", args), [
            "/opt/llama-server", "-m", "/models/model.gguf", "--fit", "on", "-c", "4096",
        ])
        environment = {
            "LLAMA_ARG_RPC": "10.100.32.2:50053",
            "LLAMA_ARG_TENSOR_SPLIT": "1,1",
            "LLAMA_ARG_DEVICE": "CUDA0,RPC0",
            "CUDA_VISIBLE_DEVICES": "0",
            "OTHER": "keep",
        }
        sanitize_local_env(environment)
        self.assertEqual(environment, {"CUDA_VISIBLE_DEVICES": "0", "OTHER": "keep"})
        self.assertEqual(
            local_command("/opt/llama-server", ["--rpc", "10.100.32.2:50053", "--device", "CUDA0,RPC0", "--list-devices"]),
            ["/opt/llama-server", "--list-devices"],
        )

    def test_any_connected_connectx_keeps_pair_mode(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            drivers = root / "drivers"
            (drivers / "mlx5_core").mkdir(parents=True)
            (drivers / "igc").mkdir()
            for name, driver, carrier in (
                ("cx7a", "mlx5_core", "0"),
                ("cx7b", "mlx5_core", "0"),
                ("management", "igc", "1"),
            ):
                iface = root / name
                (iface / "device").mkdir(parents=True)
                (iface / "device/driver").symlink_to(drivers / driver)
                (iface / "carrier").write_text(carrier)
            self.assertFalse(connectx_cable_present(root))
            (root / "cx7b/carrier").write_text("1")
            self.assertTrue(connectx_cable_present(root))

    def test_hotplugged_connectx_can_disappear_without_cable(self):
        with tempfile.TemporaryDirectory() as temp:
            self.assertFalse(connectx_cable_present(Path(temp)))
        with self.assertRaisesRegex(RuntimeError, "saved pair"):
            validate_saved_pair({"binary": "/opt/llama-server"})
        old_config = {"binary": "/opt/llama-server", "host_ip": "10.100.32.1", "host_iface": "cx7a", "rpc": "10.100.32.2:50053"}
        validate_saved_pair(old_config)
        validate_saved_pair({**old_config, "guard_revision": GUARD_REVISION})
        with self.assertRaisesRegex(RuntimeError, "saved pair"):
            validate_saved_pair({**old_config, "guard_revision": 0})

    def test_standalone_launch_ignores_old_peer_and_executes_local_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "llama-server-real"
            binary.write_text("binary")
            config = root / "guard.json"
            config.write_text(json.dumps({"binary": str(binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1", "host_iface": "enp1s0f0np0"}))
            with patch("dual_spark.llama_wrapper.connectx_cable_present", return_value=False), \
                 patch("dual_spark.llama_wrapper.os.execv") as execute, \
                 patch.dict(os.environ, {"LLAMA_ARG_RPC": "10.100.32.2:50053", "LLAMA_ARG_TENSOR_SPLIT": "1,1"}, clear=False):
                main(["-m", "/models/model.gguf", "--rpc", "10.100.32.2:50053"], config_path=config)
                self.assertNotIn("LLAMA_ARG_RPC", os.environ)
                self.assertNotIn("LLAMA_ARG_TENSOR_SPLIT", os.environ)
            execute.assert_called_once_with(str(binary), [str(binary), "-m", "/models/model.gguf"])

    def test_connected_but_unreachable_worker_does_not_fall_back(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "llama-server-real"
            binary.write_text("binary")
            config = root / "guard.json"
            config.write_text(json.dumps({"binary": str(binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1", "host_iface": "enp1s0f0np0"}))
            with patch("dual_spark.llama_wrapper.connectx_cable_present", return_value=True), \
                 patch("dual_spark.llama_wrapper.require_peer", side_effect=OSError("offline")), \
                 patch("dual_spark.llama_wrapper.os.execv") as execute:
                with self.assertRaisesRegex(OSError, "offline"):
                    main(["-m", "/models/model.gguf"], config_path=config)
            execute.assert_not_called()

    def test_cable_reappearing_before_exec_aborts_local_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "llama-server-real"
            binary.write_text("binary")
            config = root / "guard.json"
            config.write_text(json.dumps({"binary": str(binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1", "host_iface": "enp1s0f0np0"}))
            with patch("dual_spark.llama_wrapper.connectx_cable_present", side_effect=[False, True]), \
                 patch("dual_spark.llama_wrapper.os.execv") as execute:
                with self.assertRaisesRegex(RuntimeError, "reconnected"):
                    main(["-m", "/models/model.gguf"], config_path=config)
            execute.assert_not_called()

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
