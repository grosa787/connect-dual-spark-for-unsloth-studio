# Update resilient fastload design

## Intent and observed baseline

The user wants every GGUF load through their Unsloth Studio, including loads requested through its external API, to retain the two Spark ConnectX-7 placement and fast loading after either Studio or its managed `llama.cpp` is updated. A new Unsloth `llama.cpp` release must replace the old engine; keeping the benchmarked b11160 engine indefinitely does not meet the request. The desktop installer and GitHub release must include this behavior for other Ubuntu ARM64 DGX Spark pairs.

On the reference pair, DeepSeek V4 Flash Vision Q8 (150.75 GiB, 1,048,576 context, CUDA0/RPC0 split 1:1) reached health in 335.6 seconds with the stock TCP loader. RDMA alone took 335.5 seconds. `--load-mode dio` took 212.3 seconds on the stock engine. A same source build with the RPC client's weight cache hash lookup disabled by `GGML_RPC_NO_HASH_CACHE=1`, DirectIO, and RDMA took 112.3 seconds twice and 110.2 seconds through the Studio guard. Every completed run generated a response. The upstream cache path hashes large tensors byte by byte before asking the worker cache; bypassing it is the measured change.

## Supported scope

- Primary and worker are Ubuntu ARM64 DGX Sparks with a discovered private ConnectX-7 route and a working SSH identity from NVIDIA Sync. No fixed username, host IP, or interface name is shipped.
- All Studio GGUF loads pass through `LlamaCppBackend.load_model`, including UI loads and external OpenAI compatible auto switching. Its binary resolver honors `LLAMA_SERVER_PATH` first. An explicitly launched different binary or different inference backend is outside this integration.
- The managed Unsloth tree, normally `~/.unsloth/llama.cpp`, is replaced wholesale during an official prebuilt update. Nothing owned by Connect Dual Spark is stored only in that tree.
- Active models are never interrupted by background maintenance. A user initiated in-app llama update already unloads its model; Connect Dual Spark participates in that update transaction. CLI updates are reconciled after the official update completes.

## Runtime paths and update interception

The authoritative guard and fastload manager live in `~/.local/share/connect-dual-spark`, outside Unsloth's replacement trees. Studio receives `LLAMA_SERVER_PATH` pointing to a guard symlink **inside the current Unsloth managed root**. That path lets Studio's in-app updater find the managed install marker. The guard symlink points to the external, persistent guard. The project's Studio service, user manager environment, and shell configuration set this path; a repair service reinstalls the symlink if an update replaces the tree. Unsloth's in-app updater uses `UNSLOTH_LLAMA_INSTALLER`; Connect Dual Spark provides a proxy for the bundled official installer. The proxy forwards its arguments unchanged and, after a successful real install, synchronously reconciles fastload and restores the guard before reporting success. A lightweight path watcher and the guard's own version check cover CLI updates and missed events. The guard refuses a stale engine during reconciliation rather than silently running an old one.

The worker system service is installed once with an executable path owned by its normal user. That executable is a durable launcher pointing to a versioned worker build. On an existing supported unit whose executable is user writable, migration atomically replaces that executable with the launcher while preserving the old binary; it does not change the root owned unit. A completed refresh restarts the worker service only when no model uses it.

## Versioned fastload transaction

1. Read the official managed `BUILD_INFO.txt` and `UNSLOTH_PREBUILT_INFO.json`, plus hashes of the official `llama-server`, RPC library, and RPC source. Reject inconsistent, incomplete, or still changing trees; never select a release by a moving branch name when an installed source is available.
2. Lock one refresh at a time. If a verified manifest already matches the official tree, return without rebuilding. Otherwise copy the *new installed source* to a private staging directory and apply a narrow, opt in RPC client patch. The patch must match exactly once and must be verifiable; source drift is an explicit error.
3. Build a complete host `llama-server` with CUDA/RPC/RDMA from that exact newly installed source plus the client patch. The build lives in an immutable versioned directory so its shared-library runpath remains valid. Verify its version and source commit against Unsloth's new release metadata and verify that it loads the patched RPC backend. Only this managed copy is patched; Unsloth's new official binary and source remain intact.
4. Synchronize the same patched source over ConnectX-7 to a versioned worker directory and build a matching CUDA/RPC/RDMA server. The worker does not set the opt-in cache bypass variable, so its server behavior remains unchanged. Check source identity on both nodes.
5. After confirming no active host model, atomically select the worker version, restart its service through the user owned process, verify it listens only on the worker ConnectX-7 address, then atomically select the host version. A failed worker promotion restores the previous worker selection; no new host version is published. Keep previous versions for rollback.
6. The guard continues to enforce one private RPC endpoint, CUDA0/RPC0, 1:1 split, and fail closed routing. For a connected model load it removes conflicting load mode flags and environment, selects `--load-mode dio`, sets `GGML_RPC_NO_HASH_CACHE=1`, and permits RDMA negotiation. Standalone mode retains Unsloth's own fit and load mode choices.

The managed manifest records the official release/source identity, source and patch digests, build flags, host and worker executable identities, and the selected worker service. The guard checks it on every model launch; unchanged checks are cheap. If an upstream patch or binary ABI changes incompatibly, the new official version remains installed, the previous active model remains untouched, and new paired loads fail with a clear repair message. This avoids silently running an old engine or a mismatched RPC pair. Unknown future Unsloth changes cannot be guaranteed compatible without a Connect Dual Spark update.

## Checks and release gates

- Unit tests cover patch insertion and drift rejection; identity changes after an atomic tree replacement; no rebuild on an unchanged release; atomic promotion and rollback; connected DirectIO/cache bypass; standalone arguments; and a missed watcher event resolved by the guard.
- The in-app installer proxy forwards resolver/check requests without changing them and refreshes only after a successful install. Tests cover success, failure, and a concurrent model.
- An isolated fake managed tree update verifies that the guard path is restored and the new release identity is selected. Package inspection verifies all runtime files are in both `.run` and `.deb`.
- On ARM64 hardware, prove that the new-source host executable loads its patched RPC backend, RDMA activates, remote buffers are nonzero, and Q8 completes. Verify the external Studio request path still uses the guard. Compare to the approximately 110 second reference without treating one timing as a hard pass threshold.
- Publish a prerelease with updated English and Russian instructions. Explain the one time rebuild after an upstream update and the explicit failure behavior if upstream source changes beyond the supported patch.
