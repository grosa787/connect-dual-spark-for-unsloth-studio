import unittest

from dual_spark.configuration import bashrc_with_rpc, rpc_command, rpc_system_unit, studio_unit


class ConfigurationTests(unittest.TestCase):
    def test_studio_has_one_private_rpc_default(self):
        unit = studio_unit(
            "10.100.32.2", 50053, "/home/user/.unsloth/studio/unsloth_studio/bin/unsloth",
            "/home/user/.local/share/connect-dual-spark/llama-src",
            "/home/user/.local/share/connect-dual-spark/llama-server-wrapper.py",
        )
        self.assertIn("Environment=LLAMA_ARG_RPC=10.100.32.2:50053", unit)
        self.assertIn("Environment=LLAMA_SERVER_PATH=/home/user/.local/share/connect-dual-spark/llama-server-wrapper.py", unit)
        self.assertEqual(unit.count("LLAMA_ARG_RPC"), 1)
        self.assertNotIn("192.168.", unit)

    def test_rpc_process_binds_only_connectx_and_uses_cache(self):
        cmd = rpc_command("/home/user/dgx-dual-spark/llama-rpc-build/bin/ggml-rpc-server", "10.100.32.2", 50053)
        self.assertEqual(cmd[-5:], ["--host", "10.100.32.2", "--port", "50053", "--cache"])
        with self.assertRaises(ValueError):
            rpc_command("/tmp/rpc", "0.0.0.0", 50053)

    def test_interactive_studio_restarts_keep_the_same_rpc_endpoint(self):
        current = "# existing shell settings\nexport PATH=$HOME/bin:$PATH\n"
        source = "/home/user/.local/share/connect-dual-spark/llama-src"
        wrapper = "/home/user/.local/share/connect-dual-spark/llama-server-wrapper.py"
        updated = bashrc_with_rpc(current, "10.100.32.2", 50053, source, wrapper)
        self.assertIn("export LLAMA_ARG_RPC=10.100.32.2:50053", updated)
        self.assertIn(f"export UNSLOTH_LLAMA_CPP_PATH={source}", updated)
        self.assertIn(f"export LLAMA_SERVER_PATH={wrapper}", updated)
        self.assertEqual(updated, bashrc_with_rpc(updated, "10.100.32.2", 50053, source, wrapper))
        self.assertIn("export PATH=$HOME/bin:$PATH", updated)

    def test_worker_rpc_starts_at_boot_without_user_login(self):
        binary = "/home/worker/.local/share/connect-dual-spark/llama-src/build/bin/ggml-rpc-server"
        unit = rpc_system_unit("worker", "/home/worker", binary, "10.100.32.2", 50053)
        self.assertIn("User=worker", unit)
        self.assertIn("WantedBy=multi-user.target", unit)
        self.assertIn("Restart=always", unit)
        self.assertIn("StartLimitIntervalSec=0", unit)
        self.assertIn(f"ExecStart={binary} --host 10.100.32.2 --port 50053 --cache", unit)
        self.assertNotIn("WantedBy=default.target", unit)
        self.assertNotIn("0.0.0.0", unit)


if __name__ == "__main__":
    unittest.main()
