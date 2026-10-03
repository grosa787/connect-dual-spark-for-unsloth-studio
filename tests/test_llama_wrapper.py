import json
import os
import fcntl
import subprocess
import sys
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dual_spark.llama_wrapper import (
    GUARD_REVISION, connectx_cable_present, enforced_command, local_command,
    main, paired_launch_lock, reject_placement_overrides, require_peer, route_matches_connectx,
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

    def test_fastload_replaces_all_load_modes_with_direct_io(self):
        for args in (
            ["--load-mode", "mmap", "-m", "/models/model.gguf"],
            ["--load-mode=mmap+mlock", "-m", "/models/model.gguf"],
            ["-lm", "none", "-m", "/models/model.gguf"],
        ):
            with self.subTest(args=args):
                command = enforced_command("/opt/llama-server", args, "10.100.32.2:50053", fastload=True)
                self.assertEqual(command.count("--load-mode"), 1)
                self.assertEqual(command[-2:], ["--load-mode", "dio"])
                self.assertNotIn("mmap", " ".join(command))
                self.assertNotIn("-lm", command)

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

    def test_fastload_config_validates_worker_and_upstream_paths(self):
        config = {
            "binary": "/home/spark/.local/share/connect-dual-spark/fastload/current/source/build/bin/llama-server",
            "host_ip": "10.100.32.1", "host_iface": "enp1s0f0np0", "rpc": "10.100.32.2:50053",
            "guard_revision": GUARD_REVISION,
            "upstream_root": "/home/spark/.unsloth/llama.cpp", "worker_user": "spark2",
            "worker_home": "/home/spark2",
            "worker_exec_path": "/home/spark2/.local/share/connect-dual-spark/worker-rpc-launcher",
            "worker_service": "connect-dual-spark-rpc.service",
        }
        validate_saved_pair(config)
        with self.assertRaisesRegex(RuntimeError, "worker"):
            validate_saved_pair({**config, "worker_exec_path": "/tmp/unmanaged"})
        with self.assertRaisesRegex(RuntimeError, "worker"):
            validate_saved_pair({**config, "worker_user": "spark2; rm -rf /"})

    def test_connected_fastload_ensures_current_version_and_sanitizes_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "fastload/current/source/build/bin/llama-server"
            binary.parent.mkdir(parents=True)
            binary.write_text("binary")
            manager = root / "fastload_manager.py"
            manager.write_text("manager")
            config = root / "llama-server-wrapper.json"
            config.write_text(json.dumps({
                "binary": str(binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1",
                "host_iface": "enp1s0f0np0", "guard_revision": GUARD_REVISION,
                "upstream_root": str(root / "official"), "worker_user": "spark2", "worker_home": "/home/spark2",
                "worker_exec_path": "/home/spark2/.local/share/connect-dual-spark/worker-rpc-launcher",
                "worker_service": "connect-dual-spark-rpc.service",
            }))
            with patch("dual_spark.llama_wrapper.connectx_cable_present", return_value=True), \
                 patch("dual_spark.llama_wrapper.require_peer"), \
                 patch("dual_spark.llama_wrapper.subprocess.run", return_value=SimpleNamespace(returncode=0)) as run, \
                 patch("dual_spark.llama_wrapper.os.execv") as execute, \
                 patch.dict(os.environ, {"LLAMA_ARG_LOAD_MODE": "mmap", "GGML_RPC_NO_RDMA": "1"}, clear=False):
                main(["-m", "/models/model.gguf", "--load-mode=mmap"], config_path=config)
                self.assertEqual(os.environ["GGML_RPC_NO_HASH_CACHE"], "1")
                self.assertNotIn("GGML_RPC_NO_RDMA", os.environ)
                self.assertNotIn("LLAMA_ARG_LOAD_MODE", os.environ)
            self.assertEqual(run.call_args_list[0].args[0][-3:], ["ensure", "--config", str(config)])
            self.assertEqual(run.call_args_list[1].args[0][-3:], ["status", "--config", str(config)])
            command = execute.call_args.args[1]
            self.assertEqual(command[-2:], ["--load-mode", "dio"])
            self.assertEqual(command.count("--rpc"), 1)

    def test_guard_holds_shared_lock_through_exec_boundary(self):
        with tempfile.TemporaryDirectory() as temp:
            lock_path = Path(temp) / "fastload/.selection.lock"
            with paired_launch_lock(lock_path) as descriptor:
                self.assertTrue(os.get_inheritable(descriptor))
                with lock_path.open("a+") as updater:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(updater.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_executed_model_process_keeps_refresh_lock_until_exit(self):
        with tempfile.TemporaryDirectory() as temp:
            lock_path = Path(temp) / "fastload/.selection.lock"
            child = """
import os
from pathlib import Path
import sys
from dual_spark.llama_wrapper import paired_launch_lock
with paired_launch_lock(Path(sys.argv[1])):
    print('locked', flush=True)
    os.execv(sys.executable, [sys.executable, '-c', 'import time; time.sleep(0.8)'])
"""
            proc = subprocess.Popen([sys.executable, "-c", child, str(lock_path)], stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(proc.stdout.readline().strip(), "locked")
                with lock_path.open("a+") as updater:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(updater.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertEqual(proc.wait(timeout=3), 0)
                with lock_path.open("a+") as updater:
                    fcntl.flock(updater.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()

    def test_stale_version_between_ensure_and_launch_is_rechecked(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "fastload/current/source/build/bin/llama-server"
            binary.parent.mkdir(parents=True)
            binary.write_text("binary")
            (root / "fastload_manager.py").write_text("manager")
            config = root / "llama-server-wrapper.json"
            config.write_text(json.dumps({
                "binary": str(binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1",
                "host_iface": "enp1s0f0np0", "guard_revision": GUARD_REVISION,
                "upstream_root": str(root / "official"), "worker_user": "spark2", "worker_home": "/home/spark2",
                "worker_exec_path": "/home/spark2/.local/share/connect-dual-spark/worker-rpc-launcher",
                "worker_service": "connect-dual-spark-rpc.service",
            }))
            results = [SimpleNamespace(returncode=n) for n in (0, 3, 0, 0)]
            with patch("dual_spark.llama_wrapper.connectx_cable_present", return_value=True), \
                 patch("dual_spark.llama_wrapper.require_peer"), \
                 patch("dual_spark.llama_wrapper.subprocess.run", side_effect=results) as run, \
                 patch("dual_spark.llama_wrapper.os.execv") as execute:
                main(["-m", "/models/model.gguf"], config_path=config)
            self.assertEqual(run.call_count, 4)
            execute.assert_called_once()

    def test_route_is_rechecked_after_a_slow_refresh_before_exec(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "fastload/current/source/build/bin/llama-server"
            binary.parent.mkdir(parents=True)
            binary.write_text("binary")
            (root / "fastload_manager.py").write_text("manager")
            config = root / "llama-server-wrapper.json"
            config.write_text(json.dumps({
                "binary": str(binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1",
                "host_iface": "enp1s0f0np0", "guard_revision": GUARD_REVISION,
                "upstream_root": str(root / "official"), "worker_user": "spark2", "worker_home": "/home/spark2",
                "worker_exec_path": "/home/spark2/.local/share/connect-dual-spark/worker-rpc-launcher",
                "worker_service": "connect-dual-spark-rpc.service",
            }))
            with patch("dual_spark.llama_wrapper.connectx_cable_present", return_value=True), \
                 patch("dual_spark.llama_wrapper.require_peer", side_effect=[None, RuntimeError("route changed")]) as route, \
                 patch("dual_spark.llama_wrapper.subprocess.run", return_value=SimpleNamespace(returncode=0)), \
                 patch("dual_spark.llama_wrapper.os.execv") as execute:
                with self.assertRaisesRegex(RuntimeError, "route changed"):
                    main(["-m", "/models/model.gguf"], config_path=config)
            self.assertEqual(route.call_count, 2)
            execute.assert_not_called()

    def test_config_replacement_during_refresh_cannot_launch_old_endpoint(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            binary = root / "fastload/current/source/build/bin/llama-server"
            binary.parent.mkdir(parents=True)
            binary.write_text("binary")
            (root / "fastload_manager.py").write_text("manager")
            config = root / "llama-server-wrapper.json"
            saved = {
                "binary": str(binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1",
                "host_iface": "enp1s0f0np0", "guard_revision": GUARD_REVISION,
                "upstream_root": str(root / "official"), "worker_user": "spark2", "worker_home": "/home/spark2",
                "worker_exec_path": "/home/spark2/.local/share/connect-dual-spark/worker-rpc-launcher",
                "worker_service": "connect-dual-spark-rpc.service",
            }
            config.write_text(json.dumps(saved))
            calls = []

            def refresh(command, **kwargs):
                calls.append(command)
                if len(calls) == 1:
                    config.write_text(json.dumps({**saved, "rpc": "10.100.32.3:50053"}))
                return SimpleNamespace(returncode=0)

            with patch("dual_spark.llama_wrapper.connectx_cable_present", return_value=True), \
                 patch("dual_spark.llama_wrapper.require_peer"), \
                 patch("dual_spark.llama_wrapper.subprocess.run", side_effect=refresh), \
                 patch("dual_spark.llama_wrapper.os.execv") as execute:
                main(["-m", "/models/model.gguf"], config_path=config)
            self.assertGreaterEqual(len(calls), 3)
            self.assertIn("10.100.32.3:50053", execute.call_args.args[1])
            self.assertNotIn("10.100.32.2:50053", execute.call_args.args[1])

    def test_standalone_after_update_uses_new_official_binary(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            old_binary = root / "fastload/current/source/build/bin/llama-server"
            old_binary.parent.mkdir(parents=True)
            old_binary.write_text("old")
            official = root / "official"
            new_binary = official / "build/bin/llama-server"
            new_binary.parent.mkdir(parents=True)
            new_binary.write_text("new")
            config = root / "llama-server-wrapper.json"
            config.write_text(json.dumps({
                "binary": str(old_binary), "rpc": "10.100.32.2:50053", "host_ip": "10.100.32.1",
                "host_iface": "enp1s0f0np0", "guard_revision": GUARD_REVISION,
                "upstream_root": str(official), "worker_user": "spark2", "worker_home": "/home/spark2",
                "worker_exec_path": "/home/spark2/.local/share/connect-dual-spark/worker-rpc-launcher",
                "worker_service": "connect-dual-spark-rpc.service",
            }))
            with patch("dual_spark.llama_wrapper.connectx_cable_present", return_value=False), \
                 patch("dual_spark.llama_wrapper.subprocess.run") as run, \
                 patch("dual_spark.llama_wrapper.os.execv") as execute, \
                 patch.dict(os.environ, {"GGML_RPC_NO_HASH_CACHE": "1"}, clear=False):
                main(["-m", "/models/model.gguf", "--rpc", "10.100.32.2:50053"], config_path=config)
                self.assertNotIn("GGML_RPC_NO_HASH_CACHE", os.environ)
            run.assert_not_called()
            execute.assert_called_once_with(str(new_binary), [str(new_binary), "-m", "/models/model.gguf"])

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
