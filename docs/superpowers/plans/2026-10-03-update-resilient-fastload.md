# Update resilient fastload implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the measured fast GGUF loading method and two Spark routing when Unsloth Studio or its managed llama.cpp is updated, including Studio's external API paths, and release it in the installer.

**Architecture:** A durable guard and updater outside the replaceable Unsloth tree build a versioned CUDA/RPC/RDMA `llama-server` from the current official installed source with an opt in RPC cache patch. The updater builds a matching worker RPC server from that same newly installed source and promotes host and worker only as a verified pair. Studio points at a guard link inside the official tree so its in-app updater remains available; the update proxy and repair watcher restore that link after replacement.

**Tech Stack:** Python 3 standard library, CMake/CUDA/`libibverbs`, SSH and rsync over discovered ConnectX-7, systemd user path/service plus existing worker system service, `unittest`.

**Spec:** `docs/superpowers/specs/2026-10-03-update-resilient-fastload-design.md`

## Global constraints

- Supported hardware remains Ubuntu ARM64 DGX Spark with a direct private ConnectX-7 pair; discover identities and addresses dynamically.
- No model run may be interrupted by background maintenance; current user activity takes priority.
- Do not silently run stale or mismatched host and worker versions after a managed update.
- Keep the existing paired 1:1 split, fail closed route, standalone fallback, and external API guard.
- Preserve the official new Unsloth install untouched; build and patch a version matched managed copy.
- Existing `.run` and `.deb` distribution formats, English and Russian documentation, and read only `check` remain.

## Review focus

1. Whole tree replacement while the guard link is open: repair link before the next load; concurrent updater calls serialize.
2. Patch no longer matches new source: use a clear degraded new version or fail without selecting old version.
3. Active model during background refresh: do not restart worker or overwrite current binaries.
4. Worker service root unit uses a user owned executable path: migrate safely without password prompts and verify the restarted PID's version.
5. Direct external API load without shell environment: canonical Studio process and guard link still select fastload.

### Task 1: Source identity and opt in RPC patch

**Files:** Create `dual_spark/fastload.py`, `dual_spark/patches/rpc-no-hash-cache.patch`, `tests/test_fastload.py`.

**Interfaces:** `read_upstream_identity(root: Path) -> UpstreamIdentity`; `patch_rpc_source(text: str) -> str`; `build_id(identity, patch_digest, cmake_flags) -> str`; `manifest_matches(manifest, identity, binaries) -> bool`.

- [ ] Write tests using an installed tree fixture for release/source/hash changes and a current RPC function fixture for one exact patch, already patched input, and drift. State the expected failures before implementing.
- [ ] Run `python3 -m unittest discover -s tests -p 'test_fastload.py' -v`; confirm those tests fail for missing behavior.
- [ ] Implement the identity, patch, and manifest pure functions. The patch adds `GGML_RPC_NO_HASH_CACHE` and a one time log marker, with its default behavior unchanged.
- [ ] Re-run the targeted tests and the full `python3 -m unittest discover -s tests -v`; commit the verified task.

### Task 2: Versioned host and worker refresh

**Files:** Create `dual_spark/fastload_manager.py`, `tests/test_fastload_manager.py`; modify `dual_spark/operations.py` and `tests/test_operations.py`.

**Interfaces:** `FastloadManager.ensure(config, *, update_hook=False)` checks current identity and stages only if changed; `refresh()` stages, validates, and atomically promotes both nodes; `status()` reports exact or degraded identity. The installer calls it after official Studio installation.

- [ ] Write failing tests for no-op refresh, changed official tree, patch mismatch, active model deferral, worker build failure, worker restart failure, and host promotion only after verified worker readiness.
- [ ] Run targeted tests and confirm expected red failures.
- [ ] Implement a file lock; copy the new official source into an immutable versioned directory, apply the opt in patch, build host CUDA/RPC/RDMA `llama-server`, rsync the same source and build worker CUDA/RPC/RDMA. Validate source hashes, library loading, manifest and version before atomic `current` selection.
- [ ] Install or migrate a durable worker executable at the service's existing user writable `ExecStart` path. Preserve the old executable and do not restart the service while a model is active. Restart by signalling its user owned PID; verify the newly selected executable and CX7 listener, and roll back on failure.
- [ ] Run targeted and full tests; commit the verified task.

### Task 3: Guard, external launch, and updater hooks

**Files:** Modify `dual_spark/llama_wrapper.py`, `dual_spark/configuration.py`, `dual_spark/operations.py`, `dual_spark/cli.py`, `dual_spark/workflow.py`, and their tests. Create `dual_spark/update_proxy.py` and `tests/test_update_proxy.py`.

**Interfaces:** The guard invokes `FastloadManager.ensure` before a paired model load; updater proxy forwards the bundled official installer and calls refresh only after a successful install; `connect-dual-spark refresh` reconciles CLI updates; background repair service invokes the same idempotent refresh.

- [ ] Write failing tests for connected `--load-mode` conflicts and environment cleanup, standalone preservation, updater proxy success/failure, and replaced guard link repair.
- [ ] Run targeted tests to observe the red state.
- [ ] Make the connected guard append one `--load-mode dio`, set `GGML_RPC_NO_HASH_CACHE=1`, and remove `GGML_RPC_NO_RDMA`; preserve help/device query and standalone semantics.
- [ ] Configure Studio's authoritative `LLAMA_SERVER_PATH` to its managed root guard link and `UNSLOTH_LLAMA_INSTALLER` to the proxy in user service, shell and `environment.d`. Install the external guard and link repair service/path unit, plus the current source identity manifest.
- [ ] Ensure the in-app updater still resolves its managed marker while external UI/API loads use the guard. Run targeted and full tests; commit.

### Task 4: Hardware rollout and package release

**Files:** Modify `README.md`, `README.ru.md`, `dual_spark/__init__.py`, packaging scripts as needed; create release notes.

- [ ] Update both guides with update behavior, first rebuild time, fallback/errors, external API scope, and the measured Q8 comparison. Bump the version to `0.6.0`.
- [ ] Run full unit tests, `compileall`, shell syntax checks, and `git diff --check` on macOS and Ubuntu ARM64.
- [ ] On the reference pair, preserve the user's running model; stage runtime files without restarting it. Once idle, validate a small GGUF through the new-source managed executable and the guard. Then time Vision Q8 through the guard and inspect RDMA, DirectIO, cache bypass marker, remote buffers, and completion.
- [ ] Simulate replacement of the official managed tree and verify repair/identity change; inspect the new worker service process and rollback path. Keep the original Studio binary intact.
- [ ] Build `.run` and `.deb` on ARM64, inspect their contents and checksums, commit and push `main`, publish a prerelease with both assets and `SHA256SUMS`.

## Completion gate

Review the spec requirement by requirement, run fresh tests and hardware checks, confirm the GitHub release assets and remote commit, and report any update scenario that cannot be guaranteed against future upstream changes.
