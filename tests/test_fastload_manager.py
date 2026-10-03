from __future__ import annotations

from contextlib import redirect_stdout
from dataclasses import asdict
import hashlib
import fcntl
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dual_spark.fastload import build_id, patch_rpc_source, read_upstream_identity
from dual_spark.fastload_manager import CMAKE_FLAGS, REMOTE_BUILD_GUARD_CODE, CommandRunner, FastloadManager, RefreshResult, main


RPC_FUNCTION = """static bool rpc_use_hash_cache(const ggml_tensor * tensor, size_t size) {
    return size > HASH_THRESHOLD && tensor->buffer->usage == GGML_BACKEND_BUFFER_USAGE_WEIGHTS;
}
"""


class InstalledTree:
    def __init__(self, root: Path) -> None:
        self.root = root

    def write(self, *, release: str = "b11160-test", commit: str = "1" * 40,
              rpc_source: str = RPC_FUNCTION) -> None:
        files = {
            "BUILD_INFO.txt": f"llama.cpp version: b11160\nsource commit: {commit}\n",
            "UNSLOTH_PREBUILT_INFO.json": json.dumps(
                {"release_tag": release, "source_commit": commit}
            ) + "\n",
            "ggml/src/ggml-rpc/ggml-rpc.cpp": rpc_source,
        }
        for relative, contents in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(contents, encoding="utf-8")
        binary_dir = self.root / "build/bin"
        binary_dir.mkdir(parents=True, exist_ok=True)
        (binary_dir / "llama-server").write_bytes(f"official-{release}".encode())
        (binary_dir / "libggml-rpc.so").write_bytes(f"rpc-{release}".encode())
        (self.root / "CMakeLists.txt").write_text("# fixture\n", encoding="utf-8")


class FakeRunner:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.worker_current: str | None = "old"
        self.fail_worker_build = False
        self.restart_failures = 0
        self.current_link: Path | None = None
        self.legacy_launcher = False
        self.service_installed = True
        self.worker_service_matches = True
        self.worker_staged_valid = True
        self.worker_runtime_valid = True
        self.runtime_mismatch_after_clean = False
        self.repair_pending = False

    def build_host(self, source: Path, flags, identity) -> Path:
        self.events.append(("build-host", identity.release_tag, tuple(flags)))
        binary_dir = source / "build/bin"
        binary_dir.mkdir(parents=True, exist_ok=True)
        binary = binary_dir / "llama-server"
        binary.write_bytes(f"host-{identity.release_tag}".encode())
        (binary_dir / "libggml-rpc.so").write_bytes(b"patched-rpc")
        binary.chmod(0o755)
        return binary

    def stage_worker(self, source: Path, release_id: str, config, flags, *, clean=False, expected_sha256=None) -> str:
        self.events.append(("build-worker", release_id, tuple(flags), clean))
        if self.fail_worker_build:
            raise RuntimeError("worker build failed")
        self.worker_staged_valid = True
        if clean:
            self.repair_pending = True
            if self.runtime_mismatch_after_clean:
                self.worker_runtime_valid = False
            return hashlib.sha256(b"old-worker").hexdigest()
        return hashlib.sha256(("worker-" + release_id).encode()).hexdigest()

    def worker_current_build(self, config) -> str | None:
        self.events.append(("worker-current", self.worker_current))
        return self.worker_current

    def worker_matches(self, config, release_id: str, expected_sha256: str, expected_runtime_digest=None) -> bool:
        self.events.append(("worker-matches", release_id))
        return (
            self.worker_service_matches and self.service_installed and self.worker_current == release_id
            and (expected_runtime_digest is None or (self.worker_runtime_valid and expected_runtime_digest == "d" * 64))
        )

    def worker_service_installed(self, config) -> bool:
        self.events.append(("service-installed", self.service_installed))
        return self.service_installed

    def worker_staged_matches(self, config, release_id, expected_sha256, expected_runtime_digest=None) -> bool:
        self.events.append(("worker-staged-matches", release_id))
        return self.worker_staged_valid and (expected_runtime_digest is None or self.worker_runtime_valid)

    def worker_runtime_digest(self, config, release_id) -> str:
        self.events.append(("worker-runtime-digest", release_id))
        return "d" * 64 if self.worker_runtime_valid else "e" * 64

    def ensure_worker_launcher(self, config) -> None:
        self.events.append(("install-launcher", config["worker_exec_path"]))
        return self.legacy_launcher

    def restore_worker_launcher(self, config) -> None:
        self.events.append(("restore-launcher", config["worker_exec_path"]))

    def restart_and_verify_legacy_worker(self, config) -> None:
        self.events.append(("verify-legacy-worker", config["worker_exec_path"]))

    def select_worker(self, config, release_id: str | None) -> None:
        self.events.append(("select-worker", release_id))
        self.worker_current = release_id

    def restart_and_verify_worker(self, config, release_id: str,
                                  expected_sha256: str | None = None,
                                  expected_runtime_digest: str | None = None) -> None:
        selected_host = None
        if self.current_link is not None and self.current_link.is_symlink():
            selected_host = self.current_link.readlink().name
        self.events.append(("verify-worker", release_id, selected_host))
        if self.restart_failures:
            self.restart_failures -= 1
            raise RuntimeError("worker did not restart")

    def cleanup_worker_repairs(self) -> None:
        self.events.append(("cleanup-worker-repairs",))
        self.repair_pending = False

    def restore_worker_repairs(self) -> None:
        self.events.append(("restore-worker-repairs",))
        self.repair_pending = False
        self.worker_runtime_valid = True

    def prune_worker_releases(self, config, keep_ids) -> None:
        self.events.append(("prune-worker", frozenset(keep_ids)))


class ManagerFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.official = InstalledTree(self.root / "official")
        self.official.write()
        self.base = self.root / "state"
        self.base.mkdir()
        self.guard = self.base / "llama-server-wrapper.py"
        self.guard.write_text("#!/usr/bin/python3\n", encoding="utf-8")
        self.runner = FakeRunner()
        self.config = {
            "binary": str(self.base / "fastload/current/source/build/bin/llama-server"),
            "host_ip": "10.100.32.1",
            "host_iface": "enp1s0f0np0",
            "rpc": "10.100.32.2:50053",
            "guard_revision": 2,
            "upstream_root": str(self.official.root),
            "worker_user": "spark",
            "worker_home": "/home/spark",
            "worker_exec_path": "/home/spark/.local/bin/connect-dual-spark-rpc",
            "worker_service": "connect-dual-spark-rpc.service",
        }
        self.manager = FastloadManager(
            self.base,
            runner=self.runner,
            model_active=lambda: False,
            progress=lambda message: None,
        )
        self.runner.current_link = self.manager.current_link

    def seed_current(self, identity=None, release_id: str | None = None) -> Path:
        identity = identity or read_upstream_identity(self.official.root)
        patched = patch_rpc_source(
            (self.official.root / "ggml/src/ggml-rpc/ggml-rpc.cpp").read_text(encoding="utf-8")
        )
        patch_digest = hashlib.sha256(patched.encode()).hexdigest()
        release_id = release_id or build_id(identity, patch_digest, CMAKE_FLAGS)
        release = self.base / "fastload/releases" / release_id
        binary = release / "source/build/bin/llama-server"
        binary.parent.mkdir(parents=True, exist_ok=True)
        binary.write_bytes(b"old-host")
        binary.chmod(0o755)
        rpc_library = binary.parent / "libggml-rpc.so"
        rpc_library.write_bytes(b"patched-rpc")
        patched_source = release / "source/ggml/src/ggml-rpc/ggml-rpc.cpp"
        patched_source.parent.mkdir(parents=True, exist_ok=True)
        patched_source.write_text(patched, encoding="utf-8")
        manifest = {
            "build_id": release_id,
            "upstream_identity": asdict(identity),
            "patch_digest": patch_digest,
            "cmake_flags": list(CMAKE_FLAGS),
            "binaries": {
                "host": hashlib.sha256(b"old-host").hexdigest(),
                "host_rpc": hashlib.sha256(b"patched-rpc").hexdigest(),
            },
            "worker_binary_sha256": hashlib.sha256(b"old-worker").hexdigest(),
            "worker_runtime_digest": "d" * 64,
            "worker_service": self.config["worker_service"],
        }
        (release / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        self.manager.fastload_root.mkdir(parents=True, exist_ok=True)
        self.manager.current_link.symlink_to(Path("releases") / release_id)
        self.runner.worker_current = release_id
        return release


class FastloadManagerTests(ManagerFixture):
    def test_worker_paths_reject_remote_shell_metacharacters(self):
        bad = dict(self.config)
        bad["worker_home"] = "/home/spark;touch"
        bad["worker_exec_path"] = "/home/spark;touch/.local/bin/rpc"

        with self.assertRaisesRegex(ValueError, "Worker paths"):
            self.manager.status(bad)

    def test_unchanged_verified_release_is_a_noop(self):
        old = self.seed_current()

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "current")
        self.assertFalse(result.changed)
        self.assertEqual(self.manager.current_link.readlink(), Path("releases") / old.name)
        self.assertNotIn("build-host", [event[0] for event in self.runner.events])

    def test_changed_official_tree_builds_and_promotes_a_new_pair(self):
        old_identity = read_upstream_identity(self.official.root)
        old = self.seed_current(old_identity)
        self.official.write(release="b11161-test", commit="2" * 40)

        result = self.manager.ensure(self.config)

        self.assertEqual(result.state, "promoted")
        self.assertTrue(result.changed)
        self.assertNotEqual(result.build_id, old.name)
        self.assertEqual(self.manager.current_link.readlink().name, result.build_id)
        manifest = json.loads((self.manager.current_link / "manifest.json").read_text())
        self.assertEqual(manifest["upstream_identity"]["release_tag"], "b11161-test")
        patched = self.manager.current_link / "source/ggml/src/ggml-rpc/ggml-rpc.cpp"
        self.assertIn("GGML_RPC_NO_HASH_CACHE", patched.read_text())

    def test_clean_install_can_resume_after_build_before_service_install(self):
        self.runner.worker_current = None
        self.runner.service_installed = False
        first = self.manager.refresh(self.config)
        self.assertEqual(first.state, "promoted")
        self.assertEqual(self.runner.worker_current, first.build_id)
        self.runner.events.clear()

        second = self.manager.refresh(self.config)

        self.assertIn(second.state, ("current", "promoted"))
        self.assertEqual(second.build_id, first.build_id)
        self.assertNotIn("build-host", [event[0] for event in self.runner.events])
        self.assertNotIn("build-worker", [event[0] for event in self.runner.events])

    def test_missing_worker_release_is_rebuilt_from_cached_host_source(self):
        current = self.seed_current()
        self.runner.worker_staged_valid = False
        self.runner.worker_service_matches = False

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "promoted")
        self.assertEqual(self.manager.current_link.readlink().name, current.name)
        events = [event[0] for event in self.runner.events]
        self.assertIn("build-worker", events)
        self.assertNotIn("build-host", events)
        self.assertTrue(any(event[0] == "build-worker" and event[3] for event in self.runner.events))

    def test_corrupt_selected_worker_is_not_rebuilt_while_model_holds_gate(self):
        self.seed_current()
        self.runner.worker_staged_valid = False
        self.runner.worker_service_matches = False
        selection = self.manager.fastload_root / ".selection.lock"
        selection.parent.mkdir(parents=True, exist_ok=True)
        with selection.open("a+") as model:
            fcntl.flock(model.fileno(), fcntl.LOCK_SH)
            result = self.manager.refresh(self.config)
        self.assertEqual(result.state, "deferred")
        self.assertNotIn("build-worker", [event[0] for event in self.runner.events])

    def test_changed_patched_rpc_library_never_reports_current(self):
        current = self.seed_current()
        self.assertEqual(self.manager.status(self.config)["state"], "current")
        (current / "source/build/bin/libggml-rpc.so").write_bytes(b"unpatched-rpc")

        status = self.manager.status(self.config)

        self.assertNotEqual(status["state"], "current")

    def test_changed_worker_dynamic_library_never_reports_current(self):
        self.seed_current()
        self.assertEqual(self.manager.status(self.config)["state"], "current")
        self.runner.worker_runtime_valid = False
        self.assertNotEqual(self.manager.status(self.config)["state"], "current")

    def test_future_rpc_source_drift_is_structured_degraded_status(self):
        self.official.write(rpc_source="static bool rpc_use_hash_cache_new() { return false; }\n")

        status = self.manager.status(self.config)

        self.assertEqual(status["state"], "degraded")
        self.assertIn("source drift", status["message"])

    def test_successful_promotion_keeps_current_and_previous_releases_only(self):
        previous = self.seed_current()
        abandoned = self.manager.releases_dir / ("f" * 64)
        abandoned.mkdir()
        self.official.write(release="b11161-test", commit="2" * 40)

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "promoted")
        self.assertTrue(previous.is_dir())
        self.assertTrue((self.manager.releases_dir / result.build_id).is_dir())
        self.assertFalse(abandoned.exists())
        self.assertIn(("prune-worker", frozenset({previous.name, result.build_id})), self.runner.events)

    def test_failed_release_from_older_update_is_pruned_before_next_failed_build(self):
        previous = self.seed_current()
        abandoned = self.manager.releases_dir / ("f" * 64)
        abandoned.mkdir()
        self.official.write(release="b11161-test", commit="2" * 40)
        self.runner.fail_worker_build = True

        with self.assertRaisesRegex(RuntimeError, "worker build failed"):
            self.manager.refresh(self.config)

        self.assertFalse(abandoned.exists())
        self.assertTrue(previous.is_dir())
        self.assertEqual(self.manager.current_link.readlink().name, previous.name)

    def test_replaced_official_link_is_repaired_while_model_defers_rebuild(self):
        self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)
        link = self.official.root / "llama-server"
        link.symlink_to("build/bin/llama-server")
        self.manager._model_active = lambda: True

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "deferred")
        self.assertEqual(link.resolve(), self.guard.resolve())
        self.assertNotIn("build-host", [event[0] for event in self.runner.events])

    def test_live_model_selection_lock_defers_promotion_but_repairs_guard(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)
        link = self.official.root / "llama-server"
        link.symlink_to("build/bin/llama-server")
        selection = self.manager.fastload_root / ".selection.lock"
        selection.parent.mkdir(parents=True, exist_ok=True)
        with selection.open("a+") as model:
            fcntl.flock(model.fileno(), fcntl.LOCK_SH)
            result = self.manager.refresh(self.config)
        self.assertEqual(result.state, "deferred")
        self.assertEqual(self.manager.current_link.readlink().name, old.name)
        self.assertEqual(link.resolve(), self.guard.resolve())
        self.assertNotIn("select-worker", [event[0] for event in self.runner.events])

    def test_patch_mismatch_leaves_the_current_release_selected(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40,
                            rpc_source="static bool rpc_use_hash_cache() { return true; }\n")

        with self.assertRaisesRegex(ValueError, "source drift"):
            self.manager.refresh(self.config)

        self.assertEqual(self.manager.current_link.readlink(), Path("releases") / old.name)
        self.assertEqual(self.runner.events, [])

    def test_active_model_defers_before_mutating_any_release(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)
        manager = FastloadManager(
            self.base,
            runner=self.runner,
            model_active=lambda: True,
            progress=lambda message: None,
        )

        result = manager.refresh(self.config)

        self.assertEqual(result.state, "deferred")
        self.assertEqual(manager.current_link.readlink(), Path("releases") / old.name)
        self.assertNotIn("build-host", [event[0] for event in self.runner.events])
        self.assertNotIn("build-worker", [event[0] for event in self.runner.events])
        self.assertNotIn("select-worker", [event[0] for event in self.runner.events])

    def test_current_manifest_must_match_patch_flags_and_build_id(self):
        current = self.seed_current()
        manifest_path = current / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["cmake_flags"] = ["-DGGML_CUDA=OFF"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaisesRegex(RuntimeError, "refusing to overwrite"):
            self.manager.refresh(self.config)

        self.assertEqual((current / "source/build/bin/llama-server").read_bytes(), b"old-host")
        self.assertNotIn("build-host", [event[0] for event in self.runner.events])

    def test_current_release_requires_matching_worker_selection_and_service(self):
        current = self.seed_current()
        self.runner.worker_current = "different-build"

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "promoted")
        self.assertEqual(self.runner.worker_current, current.name)
        self.assertIn("verify-worker", [event[0] for event in self.runner.events])

    def test_clean_install_selects_pair_before_root_service_is_installed(self):
        self.runner.worker_current = None
        self.runner.service_installed = False

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "promoted")
        self.assertEqual(self.runner.worker_current, result.build_id)
        self.assertNotIn("verify-worker", [event[0] for event in self.runner.events])

    def test_source_copy_excludes_the_managed_root_guard_link(self):
        managed_link = self.official.root / "llama-server"
        managed_link.symlink_to(self.guard)

        result = self.manager.refresh(self.config)

        copied_link = self.base / "fastload/releases" / result.build_id / "source/llama-server"
        self.assertFalse(copied_link.exists() or copied_link.is_symlink())

    def test_refresh_reports_build_and_promotion_progress(self):
        progress = []
        manager = FastloadManager(
            self.base,
            runner=self.runner,
            model_active=lambda: False,
            progress=progress.append,
        )

        manager.refresh(self.config)

        combined = "\n".join(progress).lower()
        self.assertIn("host", combined)
        self.assertIn("worker", combined)
        self.assertIn("promot", combined)

    def test_model_becoming_active_after_build_still_defers_worker_switch(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)
        activity = iter((False, True))
        manager = FastloadManager(
            self.base,
            runner=self.runner,
            model_active=lambda: next(activity),
            progress=lambda message: None,
        )

        result = manager.refresh(self.config)

        self.assertEqual(result.state, "deferred")
        self.assertEqual(manager.current_link.readlink(), Path("releases") / old.name)
        self.assertNotIn("select-worker", [event[0] for event in self.runner.events])

    def test_worker_build_failure_does_not_promote_host(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)
        self.runner.fail_worker_build = True

        with self.assertRaisesRegex(RuntimeError, "worker build failed"):
            self.manager.refresh(self.config)

        self.assertEqual(self.manager.current_link.readlink(), Path("releases") / old.name)
        self.assertNotIn("select-worker", [event[0] for event in self.runner.events])

    def test_worker_restart_failure_rolls_back_worker_and_host(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)
        self.runner.restart_failures = 1

        with self.assertRaisesRegex(RuntimeError, "worker did not restart"):
            self.manager.refresh(self.config)

        self.assertEqual(self.runner.worker_current, old.name)
        self.assertEqual(self.manager.current_link.readlink(), Path("releases") / old.name)
        selections = [event[1] for event in self.runner.events if event[0] == "select-worker"]
        self.assertEqual(selections[-1], old.name)
        self.assertEqual([e[1] for e in self.runner.events if e[0] == "verify-worker"][-1], old.name)

    def test_failed_same_release_clean_repair_restores_old_build_before_restart(self):
        old = self.seed_current()
        self.runner.worker_staged_valid = False
        self.runner.worker_service_matches = False
        self.runner.restart_failures = 1

        with self.assertRaisesRegex(RuntimeError, "worker did not restart"):
            self.manager.refresh(self.config)

        kinds = [event[0] for event in self.runner.events]
        self.assertIn("restore-worker-repairs", kinds)
        self.assertLess(kinds.index("restore-worker-repairs"), kinds.index("verify-worker", kinds.index("restore-worker-repairs")))
        self.assertEqual(self.manager.current_link.readlink().name, old.name)

    def test_same_release_runtime_mismatch_restores_old_build_without_switching(self):
        old = self.seed_current()
        self.runner.worker_staged_valid = False
        self.runner.worker_service_matches = False
        self.runner.runtime_mismatch_after_clean = True

        with self.assertRaisesRegex(RuntimeError, "shared libraries differ"):
            self.manager.refresh(self.config)

        kinds = [event[0] for event in self.runner.events]
        self.assertIn("restore-worker-repairs", kinds)
        self.assertNotIn("select-worker", kinds)
        self.assertEqual(self.manager.current_link.readlink().name, old.name)

    def test_model_appearing_during_clean_repair_restores_old_build_before_deferral(self):
        old = self.seed_current()
        self.runner.worker_staged_valid = False
        self.runner.worker_service_matches = False
        activity = iter((False, False, False, True))
        self.manager._model_active = lambda: next(activity, True)

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "deferred")
        self.assertIn("restore-worker-repairs", [event[0] for event in self.runner.events])
        self.assertEqual(self.manager.current_link.readlink().name, old.name)

    def test_first_promotion_failure_restores_preserved_legacy_worker(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)
        self.runner.worker_current = None
        self.runner.legacy_launcher = True
        self.runner.restart_failures = 1

        with self.assertRaisesRegex(RuntimeError, "worker did not restart"):
            self.manager.refresh(self.config)

        kinds = [event[0] for event in self.runner.events]
        self.assertIn("restore-launcher", kinds)
        self.assertIn("verify-legacy-worker", kinds)
        self.assertEqual(self.manager.current_link.readlink(), Path("releases") / old.name)

    def test_host_switch_happens_only_after_worker_readiness(self):
        old = self.seed_current()
        self.official.write(release="b11161-test", commit="2" * 40)

        result = self.manager.refresh(self.config)

        verification = next(event for event in self.runner.events if event[0] == "verify-worker")
        self.assertEqual(verification[1], result.build_id)
        self.assertEqual(verification[2], old.name)
        self.assertEqual(self.manager.current_link.readlink().name, result.build_id)

    def test_refresh_repairs_guard_link_after_official_tree_replacement(self):
        self.seed_current()
        managed_link = self.official.root / "llama-server"
        managed_link.symlink_to("build/bin/llama-server")

        result = self.manager.refresh(self.config)

        self.assertEqual(result.state, "current")
        self.assertTrue(managed_link.is_symlink())
        self.assertEqual(managed_link.resolve(), self.guard.resolve())


class CliTests(ManagerFixture):
    def test_ensure_returns_nonzero_when_stale_release_is_deferred(self):
        config_path = self.base / "llama-server-wrapper.json"
        config_path.write_text(json.dumps(self.config), encoding="utf-8")

        class DeferredManager:
            def __init__(self, base_dir):
                self.base_dir = base_dir

            def ensure(self, config, **kwargs):
                return RefreshResult("deferred", "new", True, "model active")

        with redirect_stdout(io.StringIO()):
            code = main(
                ["ensure", "--config", str(config_path)],
                manager_factory=DeferredManager,
            )

        self.assertEqual(code, 3)

    def test_refresh_accepts_install_root_override_and_deferred_is_success(self):
        config_path = self.base / "llama-server-wrapper.json"
        config_path.write_text(json.dumps(self.config), encoding="utf-8")
        seen = {}

        class DeferredManager:
            def __init__(self, base_dir):
                seen["base"] = base_dir

            def refresh(self, config, **kwargs):
                seen.update(kwargs)
                return RefreshResult("deferred", "new", True, "model active")

        override = self.root / "new-official"
        with redirect_stdout(io.StringIO()):
            code = main(
                ["refresh", "--config", str(config_path), "--install-root", str(override)],
                manager_factory=DeferredManager,
            )

        self.assertEqual(code, 0)
        self.assertEqual(seen["install_root"], override)
        self.assertEqual(seen["base"], self.base.resolve())


class WorkerListenerTests(unittest.TestCase):
    def test_missing_worker_library_requests_clean_repair(self):
        runner = CommandRunner()
        good_hash = "a" * 64
        responses = [
            SimpleNamespace(returncode=0, stdout=""),
            SimpleNamespace(returncode=0, stdout=good_hash + "  binary\n"),
        ]
        with patch.object(runner, "_remote", side_effect=responses), \
             patch.object(runner, "worker_runtime_digest", side_effect=RuntimeError("worker RPC library is missing")):
            self.assertFalse(runner.worker_staged_matches(
                {"worker_home": "/home/worker"}, "b" * 64, good_hash, "c" * 64,
            ))

    def test_protected_runner_preserves_successful_command_output(self):
        result = CommandRunner()._run([sys.executable, "-c", "print('ready')"])
        self.assertEqual(result.stdout.strip(), "ready")
        self.assertEqual(result.returncode, 0)

    def test_unrelated_legacy_management_rpc_port_does_not_fail_cx7_verification(self):
        runner = CommandRunner(sleep=lambda _: None)
        listeners = (
            'LISTEN 0 1 192.168.150.49:50052 0.0.0.0:* users:(("ggml-rpc-server",pid=10,fd=3))\n'
            'LISTEN 0 1 10.100.32.2:50053 0.0.0.0:* users:(("ggml-rpc-server",pid=11,fd=3))\n'
        )
        with patch.object(runner, "_remote", return_value=SimpleNamespace(stdout=listeners)):
            runner._verify_listener({"rpc": "10.100.32.2:50053"})

    def test_manager_death_stops_build_children_before_they_mutate_release(self):
        with tempfile.TemporaryDirectory() as temp:
            started = Path(temp) / "started"
            late = Path(temp) / "late"
            child_code = (
                "from pathlib import Path; import time; "
                f"Path({str(started)!r}).write_text('started'); "
                "time.sleep(1.2); "
                f"Path({str(late)!r}).write_text('late')"
            )
            manager_code = (
                "import sys; from dual_spark.fastload_manager import CommandRunner; "
                f"CommandRunner()._run([sys.executable, '-c', {child_code!r}])"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", manager_code], cwd=Path(__file__).resolve().parents[1],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            try:
                deadline = time.monotonic() + 5
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(started.exists())
                proc.kill()
                proc.wait(timeout=2)
                time.sleep(1.4)
                self.assertFalse(late.exists())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def test_remote_build_guard_kills_compiler_when_ssh_pipe_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            started = Path(temp) / "started"
            late = Path(temp) / "late"
            child_code = (
                "from pathlib import Path; import time; "
                f"Path({str(started)!r}).write_text('started'); "
                "time.sleep(1.2); "
                f"Path({str(late)!r}).write_text('late')"
            )
            proc = subprocess.Popen(
                [sys.executable, "-c", REMOTE_BUILD_GUARD_CODE, sys.executable, "-c", child_code],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
            try:
                deadline = time.monotonic() + 5
                while not started.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                self.assertTrue(started.exists())
                proc.stderr.close()
                proc.wait(timeout=3)
                time.sleep(1.4)
                self.assertFalse(late.exists())
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                proc.stdout.close()
                if not proc.stderr.closed:
                    proc.stderr.close()


if __name__ == "__main__":
    unittest.main()
