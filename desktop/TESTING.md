**English** | [Русский](TESTING.ru.md) · [App instructions](README.md)

# Spark Link verification

## Spark Link 1.4.0: real three-device qualification

138 CLI and 58 desktop tests; real three-GPU Q8/F16 KV at configured 1048576 context; text and vision; all 12 directed jumbo-packet checks; third-worker restart and automatic return from two to three devices; six-tab/four-language native UI. [Evidence and limitations](../docs/third-spark-2026-10-31.md).

## Spark Link 1.3.0 verification

138 CLI tests and all 49 desktop checks passed across the isolated/system runtimes. Triangle editing, preserved pair ports, three cable tabs, camera fit/reset, all four languages, compact layouts and hide/show rendering passed on real ARM64 Qt. [Triangle/detail report](../docs/triangle-and-detail-2026-10-31.md).

## Spark Link 1.2.0 verification (2026-10-31)

- 138 CLI tests passed. The desktop suite ran 42 tests: 40 passed in the Qt runtime; the two PyYAML-dependent tests passed separately under Ubuntu system Python (five network tests in that run).
- Real ARM64 Qt: six pages, four languages, camera presets and popup, mixed/upright devices, port drafts, pending third-device scene and 1000×700 layout.
- Hide/show regression reproduced with missing chassis. Retaining scene-graph nodes while allowing graphics/context cache release fixes the visual check; manual mesh re-upload was rejected after a Qt render-image crash under gdb.
- Installed 1.2.0 `.run`: isolated Qt imports, hidden start, IPC reopen with visible chassis, hide, Studio HTTP 200 and independent RPC available. Sample RSS: 399.2 / 404.9 / 401.0 MiB (hidden start / visible / hidden again), higher than the old simpler scene.
- Generation study: ordinary Mistral versus n-gram and DSpark, identical main weights/F16 KV and controlled requests. [Measurements and quality limits](../docs/design-and-generation-2026-10-31.md). Normal Studio launch settings remain unchanged.

## Historical verification — Spark Link 1.1.1

Verified on 2026-10-31 with the available Ubuntu 24.04 ARM64 DGX Spark pair.

The [startup/capacity report](../docs/startup-and-mistral-2026-10-31.md) and [validation JSON](../docs/startup-mistral-validation-2026-10-31.json) cover 1.1.1: **138 CLI tests and 41 desktop tests**, alignment-safe asynchronous RPC loading, actual Q8 text/vision controls, a matched minimal-context Mistral control and a fully processed 106240-token Mistral prompt. The two desktop netplan tests were additionally run with Ubuntu system Python. Native six-tab/four-language interaction and the installed menu launcher passed again after installing 1.1.1. The remaining bullets below retain the earlier release checks as historical coverage.

The later [runtime update report](../docs/runtime-update-2026-10-31.md) records the successful Unsloth 2026.10.11 / llama.cpp b11985 rebuild, actual Studio Q8 text/vision requests at configured context 1048576, per-device weights/KV buffers and final unloaded state. It also records a real failed-download rollback, supplementing the isolated rollback fixtures below.

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
- The published GitHub installer was also executed with a separately supplied `--archive` tar.gz; extraction and offline wheel installation succeeded. GitHub's uploaded-asset digests match the published SHA256SUMS. The full download path began successfully but was stopped because this Spark's GitHub transfer was around 60 KB/s; the identical archive was transferred over the local network for installation testing.
- The actual generated `.desktop` passed `desktop-file-validate` and was launched with `gio launch` in an Xvfb display; a native Spark Link window appeared. The desktop shortcut has `metadata::trusted=true`.
- The independent standard-library memory gateway delegates to the preserved custom Q8 43:57 launcher SHA-256 `cddb6aec3304021e2a759cca302ed952c95b809eb422b59f6e4561859e4da59e`; inference does not require the GUI runtime. Studio/RPC remain running.

## Practical limits

The new port-changing administrative transaction is covered by validation and rollback tests, but a physical cable relocation was not performed during this release check. Applying a different port requires the cable to be moved and sudo authentication on the affected devices.

The three-node topology and argument construction are tested in software. Three physical Spark systems are **not** available yet. Multi-worker inference, first-time third-device setup and physical three-node routing must be qualified after the third device is connected. The UI and documentation mark this mode experimental. There is no hot migration of an active model.

Application rendering and menu activation were checked in a virtual X11 display because the primary Spark was at its graphical login screen. The application is installed in the user's menu/desktop for their normal graphical session.

Power-cut, internet-disconnection and live first-password onboarding of a previously unknown third Spark were not physically tested. Recovery/rollback behavior is tested with isolated interrupted-update fixtures; real-pair recovery was a no-op check. Running distributed inference cannot continue through loss of an essential worker. A protected, unlocked GNOME keyring is required for unattended privileged recovery; ordinary RPC service boot does not require the GUI or a stored password.

[Installation](../docs/images/en/install.png) · [Updates](../docs/images/en/updates.png) · [Journal](../docs/images/en/journal.png) · [Onboarding](../docs/images/en/onboarding.png)
