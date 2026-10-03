from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from dual_spark.fastload import (
    UpstreamIdentity,
    build_id,
    manifest_matches,
    patch_rpc_source,
    read_upstream_identity,
)


RPC_FUNCTION = """// the hash cache is meant for weights
static bool rpc_use_hash_cache(const ggml_tensor * tensor, size_t size) {
    return size > HASH_THRESHOLD && tensor->buffer->usage == GGML_BACKEND_BUFFER_USAGE_WEIGHTS;
}
"""


class InstalledTree:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.build_info = root / "BUILD_INFO.txt"
        self.prebuilt_info = root / "UNSLOTH_PREBUILT_INFO.json"
        self.rpc_source = root / "ggml/src/ggml-rpc/ggml-rpc.cpp"
        self.llama_server = root / "build/bin/llama-server"
        self.rpc_library = root / "build/bin/libggml-rpc.so"

    def write(
        self,
        *,
        release_tag: str = "b11160-mix-example",
        source_commit: str = "0123456789abcdef0123456789abcdef01234567",
        rpc_source: str = RPC_FUNCTION,
        llama_server: bytes = b"llama-server-v1",
        rpc_library: bytes = b"rpc-library-v1",
    ) -> None:
        for path in (
            self.build_info,
            self.prebuilt_info,
            self.rpc_source,
            self.llama_server,
            self.rpc_library,
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
        self.build_info.write_text(
            "llama.cpp version: b11160\n"
            f"source commit: {source_commit}\n",
            encoding="utf-8",
        )
        self.prebuilt_info.write_text(
            json.dumps(
                {
                    "release_tag": release_tag,
                    "source_commit": source_commit,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        self.rpc_source.write_text(rpc_source, encoding="utf-8")
        self.llama_server.write_bytes(llama_server)
        self.rpc_library.write_bytes(rpc_library)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class UpstreamIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.tree = InstalledTree(Path(self.tempdir.name))
        self.tree.write()

    def test_reads_release_source_and_every_installed_hash(self):
        identity = read_upstream_identity(self.tree.root)

        self.assertEqual(identity.release_tag, "b11160-mix-example")
        self.assertEqual(identity.source_commit, "0123456789abcdef0123456789abcdef01234567")
        self.assertEqual(identity.build_info_sha256, sha256(self.tree.build_info))
        self.assertEqual(identity.prebuilt_info_sha256, sha256(self.tree.prebuilt_info))
        self.assertEqual(identity.rpc_source_sha256, sha256(self.tree.rpc_source))
        self.assertEqual(identity.llama_server_sha256, sha256(self.tree.llama_server))
        self.assertEqual(identity.rpc_library_sha256, sha256(self.tree.rpc_library))
        self.assertEqual(json.loads(json.dumps(asdict(identity))), asdict(identity))

    def test_release_change_changes_identity(self):
        before = read_upstream_identity(self.tree.root)
        self.tree.write(release_tag="b11161-mix-example")

        self.assertNotEqual(read_upstream_identity(self.tree.root), before)

    def test_source_change_changes_identity(self):
        before = read_upstream_identity(self.tree.root)
        self.tree.write(source_commit="89abcdef0123456789abcdef0123456789abcdef")

        self.assertNotEqual(read_upstream_identity(self.tree.root), before)

    def test_binary_change_changes_identity(self):
        before = read_upstream_identity(self.tree.root)
        self.tree.llama_server.write_bytes(b"llama-server-v2")

        self.assertNotEqual(read_upstream_identity(self.tree.root), before)

    def test_rpc_library_change_changes_identity(self):
        before = read_upstream_identity(self.tree.root)
        self.tree.rpc_library.write_bytes(b"rpc-library-v2")

        self.assertNotEqual(read_upstream_identity(self.tree.root), before)

    def test_rejects_inconsistent_source_metadata(self):
        marker = json.loads(self.tree.prebuilt_info.read_text(encoding="utf-8"))
        marker["source_commit"] = "f" * 40
        self.tree.prebuilt_info.write_text(json.dumps(marker), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "source commit"):
            read_upstream_identity(self.tree.root)

    def test_rejects_missing_identity_or_payload_files(self):
        for path, expected in (
            (self.tree.build_info, "BUILD_INFO.txt"),
            (self.tree.prebuilt_info, "UNSLOTH_PREBUILT_INFO.json"),
            (self.tree.rpc_source, "ggml-rpc.cpp"),
            (self.tree.llama_server, "llama-server"),
            (self.tree.rpc_library, "libggml-rpc.so"),
        ):
            with self.subTest(path=path):
                saved = path.read_bytes()
                path.unlink()
                with self.assertRaisesRegex(ValueError, expected):
                    read_upstream_identity(self.tree.root)
                path.write_bytes(saved)


class RpcPatchTests(unittest.TestCase):
    def test_patches_the_current_function_once_and_preserves_default_return(self):
        patched = patch_rpc_source(RPC_FUNCTION)

        self.assertEqual(patched.count("GGML_RPC_NO_HASH_CACHE"), 2)
        self.assertEqual(patched.count("Connect Dual Spark: RPC hash cache disabled"), 1)
        self.assertIn('if (std::getenv("GGML_RPC_NO_HASH_CACHE")) {', patched)
        self.assertIn(
            "return size > HASH_THRESHOLD && tensor->buffer->usage == "
            "GGML_BACKEND_BUFFER_USAGE_WEIGHTS;",
            patched,
        )
        self.assertEqual(patch_rpc_source(RPC_FUNCTION + "\n// unrelated").rsplit("\n", 2)[-1], "// unrelated")

    def test_rejects_already_patched_input(self):
        with self.assertRaisesRegex(ValueError, "already patched"):
            patch_rpc_source(patch_rpc_source(RPC_FUNCTION))

    def test_rejects_source_drift(self):
        drifted = RPC_FUNCTION.replace("size > HASH_THRESHOLD", "size >= HASH_THRESHOLD")

        with self.assertRaisesRegex(ValueError, "source drift"):
            patch_rpc_source(drifted)

    def test_rejects_more_than_one_matching_function(self):
        with self.assertRaisesRegex(ValueError, "source drift"):
            patch_rpc_source(RPC_FUNCTION + RPC_FUNCTION)

    def test_patch_asset_applies_to_the_same_supported_source(self):
        patch_file = Path(__file__).parents[1] / "dual_spark/patches/rpc-no-hash-cache.patch"
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "ggml/src/ggml-rpc/ggml-rpc.cpp"
            source.parent.mkdir(parents=True)
            source.write_text(RPC_FUNCTION, encoding="utf-8")

            result = subprocess.run(
                ["patch", "-p1", "--batch", "--forward", "-i", str(patch_file)],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(source.read_text(encoding="utf-8"), patch_rpc_source(RPC_FUNCTION))


class BuildIdentityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = UpstreamIdentity(
            release_tag="b11160-mix-example",
            source_commit="0123456789abcdef0123456789abcdef01234567",
            build_info_sha256="1" * 64,
            prebuilt_info_sha256="2" * 64,
            rpc_source_sha256="3" * 64,
            llama_server_sha256="4" * 64,
            rpc_library_sha256="5" * 64,
        )

    def test_build_id_is_stable_and_covers_every_input(self):
        first = build_id(self.identity, "6" * 64, ["-DGGML_CUDA=ON", "-DGGML_RPC=ON"])

        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(
            first,
            build_id(self.identity, "6" * 64, ["-DGGML_CUDA=ON", "-DGGML_RPC=ON"]),
        )
        self.assertNotEqual(first, build_id(self.identity, "7" * 64, ["-DGGML_CUDA=ON", "-DGGML_RPC=ON"]))
        self.assertNotEqual(first, build_id(self.identity, "6" * 64, ["-DGGML_RPC=ON", "-DGGML_CUDA=ON"]))
        changed_identity = UpstreamIdentity(**(asdict(self.identity) | {"rpc_source_sha256": "8" * 64}))
        self.assertNotEqual(first, build_id(changed_identity, "6" * 64, ["-DGGML_CUDA=ON", "-DGGML_RPC=ON"]))

    def test_manifest_matches_exact_identity_and_current_binary_hashes(self):
        with tempfile.TemporaryDirectory() as tempdir:
            host = Path(tempdir) / "llama-server"
            worker = Path(tempdir) / "ggml-rpc-server"
            host.write_bytes(b"host")
            worker.write_bytes(b"worker")
            binaries = {"host": host, "worker": worker}
            manifest = {
                "upstream_identity": asdict(self.identity),
                "binaries": {name: sha256(path) for name, path in binaries.items()},
            }

            self.assertTrue(manifest_matches(manifest, self.identity, binaries))
            worker.write_bytes(b"changed worker")
            self.assertFalse(manifest_matches(manifest, self.identity, binaries))

    def test_manifest_rejects_malformed_or_different_records(self):
        with tempfile.TemporaryDirectory() as tempdir:
            binary = Path(tempdir) / "llama-server"
            binary.write_bytes(b"host")
            binaries = {"host": binary}
            good = {
                "upstream_identity": asdict(self.identity),
                "binaries": {"host": sha256(binary)},
            }

            self.assertFalse(manifest_matches({}, self.identity, binaries))
            self.assertFalse(manifest_matches({**good, "upstream_identity": {}}, self.identity, binaries))
            self.assertFalse(manifest_matches({**good, "binaries": {}}, self.identity, binaries))
            self.assertFalse(manifest_matches(good, self.identity, {**binaries, "extra": binary}))
            binary.unlink()
            self.assertFalse(manifest_matches(good, self.identity, binaries))


if __name__ == "__main__":
    unittest.main()
