# Verification — Spark Link 1.1.0

Verified on 2026-10-31 with the available Ubuntu 24.04 ARM64 DGX Spark pair.

- Existing CLI suite: **132 passed**.
- Desktop management suite: **40 tests**, 38 passed in the isolated Qt runtime and the two netplan/PyYAML tests passed separately using Ubuntu system Python. Includes unhealthy-update rollback, durable JSON recovery, offline model metadata, discovery topology/deduplication, per-worker manifests, allocation/context enforcement, model-specific policy removal and password stdin isolation.
- Native Qt Quick / Qt Quick 3D test: all six tabs in all four languages; two real Spark inventories; upright/mixed orientations persisted across reload; third-device pending state; keyboard connector selection; draft retained across polling; mismatched draft rejected; hidden-window resource release; 1240×820 and 1000×700 screenshots. No QML loading/type errors.
- Real HF metadata/GUI smoke: bounded Qwen3-0.6B GGUF metadata, declared 40960 context, variants, cache estimate, automatic/manual percentages and GiB, four populated layouts and four masked onboarding dialogs. This test does not submit real credentials or add hardware.
- Isolated GNOME Keyring session: dummy password/connection metadata stored, retrieved and deleted; backing keyring files do not contain the plaintext dummy secret. No real account password was read by QA.
- Real two-device inference: cached small Qwen GGUF, saved 45:55 policy and 512-token context overriding stale 8192 launch arguments, nonempty completion and simultaneous Studio health 200. Only the QA model process was terminated; its policy was removed afterward. No user model was loaded or unloaded.
- Noninteractive local recovery: matching installed source/build, unchanged fastload selection, Studio/RPC available without downloading software. Primary user `Linger=yes` confirmed.
- Installed background main loop: hidden startup, IPC reopening, hiding again, Studio/RPC still available. RSS approximately 347 MiB initially, 351 MiB visible and 286 MiB hidden after graphics release on the tested Spark/Xvfb session. This is a measured sample, not a memory ceiling.
- Real existing network: no-op apply of the existing port-0 configuration, direct routes and bidirectional ping checked; SSH and matching installed host/worker build confirmed. No administrative netplan mutation was needed because the actual addresses already matched the plan.
- Self-extracting release installed on the first Spark with its own isolated PySide6 runtime. Imports resolve to the application's bundled `spark_link` and `dual_spark`, not to an installed CLI.
- The published GitHub installer was also executed with a separately downloaded `--archive` tar.gz; extraction and offline wheel installation succeeded. GitHub's uploaded-asset digests match the published SHA256SUMS.
- The actual generated `.desktop` passed `desktop-file-validate` and was launched with `gio launch` in an Xvfb display; a native Spark Link window appeared. The desktop shortcut has `metadata::trusted=true`.
- The independent standard-library memory gateway delegates to the preserved custom Q8 43:57 launcher SHA-256 `cddb6aec3304021e2a759cca302ed952c95b809eb422b59f6e4561859e4da59e`; inference does not require the GUI runtime. Studio/RPC remain running.

## Practical limits

The new port-changing administrative transaction is covered by validation and rollback tests, but a physical cable relocation was not performed during this release check. Applying a different port requires the cable to be moved and sudo authentication on the affected devices.

The three-node topology and argument construction are tested in software. Three physical Spark systems are **not** available yet. Multi-worker inference, first-time third-device setup and physical three-node routing must be qualified after the third device is connected. The UI and documentation mark this mode experimental. There is no hot migration of an active model.

Application rendering and menu activation were checked in a virtual X11 display because the primary Spark was at its graphical login screen. The application is installed in the user's menu/desktop for their normal graphical session.

Power-cut, internet-disconnection and live first-password onboarding of a previously unknown third Spark were not physically tested. Recovery/rollback behavior is tested with isolated interrupted-update fixtures; real-pair recovery was a no-op check. Running distributed inference cannot continue through loss of an essential worker. A protected, unlocked GNOME keyring is required for unattended privileged recovery; ordinary RPC service boot does not require the GUI or a stored password.
