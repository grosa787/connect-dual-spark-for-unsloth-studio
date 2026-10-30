# Verification — Spark Link 1.0.0

Verified on 2026-10-31 with the available Ubuntu 24.04 ARM64 DGX Spark pair.

- Existing CLI suite: **132 passed**.
- Desktop management suite on Ubuntu system Python: **13 passed**, including failed-netplan rollback and failed-updater service restoration. On the macOS development host, the two netplan/PyYAML tests are skipped; they were run on Ubuntu.
- Native Qt Quick / Qt Quick 3D test: all five tabs activated, two real Spark inventories loaded, third-device pending state, keyboard connector selection, draft selection retained across refresh, connection indicator rejects a mismatched draft, screenshots at 1240×820 and 1000×700. No QML loading/type errors.
- Real existing network: no-op apply of the existing port-0 configuration, direct routes and bidirectional ping checked; SSH and matching installed host/worker build confirmed. No administrative netplan mutation was needed because the actual addresses already matched the plan.
- Self-extracting release installed on the first Spark with its own isolated PySide6 runtime. Imports resolve to the application's bundled `spark_link` and `dual_spark`, not to an installed CLI.
- The published GitHub installer was also executed with a separately downloaded `--archive` tar.gz; extraction and offline wheel installation succeeded. GitHub's uploaded-asset digests match the published SHA256SUMS.
- The actual generated `.desktop` passed `desktop-file-validate` and was launched with `gio launch` in an Xvfb display; a native Spark Link window appeared. The desktop shortcut has `metadata::trusted=true`.
- The installed custom Q8 43:57 launcher SHA-256 remained `cddb6aec3304021e2a759cca302ed952c95b809eb422b59f6e4561859e4da59e`; the Studio/RPC services remain running.

## Practical limits

The new port-changing administrative transaction is covered by validation and rollback tests, but a physical cable relocation was not performed during this release check. Applying a different port requires the cable to be moved and sudo authentication on the affected devices.

The three-node topology and argument construction are tested in software. Three physical Spark systems are **not** available yet. Multi-worker inference, first-time third-device setup and physical three-node routing must be qualified after the third device is connected. The UI and documentation mark this mode experimental. There is no hot migration of an active model.

Application rendering and menu activation were checked in a virtual X11 display because the primary Spark was at its graphical login screen. The application is installed in the user's menu/desktop for their normal graphical session.
