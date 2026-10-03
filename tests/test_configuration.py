import unittest

from dual_spark.configuration import bashrc_with_rpc, rpc_command, studio_unit


class ConfigurationTests(unittest.TestCase):
    def test_studio_has_one_private_rpc_default(self):
        unit = studio_unit("10.100.32.2", 50053, "/home/user/.unsloth/studio/unsloth_studio/bin/unsloth")
        self.assertIn("Environment=LLAMA_ARG_RPC=10.100.32.2:50053", unit)
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
        updated = bashrc_with_rpc(current, "10.100.32.2", 50053, source)
        self.assertIn("export LLAMA_ARG_RPC=10.100.32.2:50053", updated)
        self.assertIn(f"export UNSLOTH_LLAMA_CPP_PATH={source}", updated)
        self.assertEqual(updated, bashrc_with_rpc(updated, "10.100.32.2", 50053, source))
        self.assertIn("export PATH=$HOME/bin:$PATH", updated)


if __name__ == "__main__":
    unittest.main()
