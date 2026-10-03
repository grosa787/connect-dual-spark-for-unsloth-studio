[English](README.md) | [Русский](README.ru.md)

# Connect Dual Spark for Unsloth Studio

Connect Dual Spark automatically discovers the direct ConnectX-7 link between exactly two NVIDIA DGX Spark systems, installs Unsloth Studio, and configures `llama.cpp` RPC on the second Spark. Inter-node model traffic is allowed only over the verified high-speed ConnectX-7 interface.

> **Pre-release status:** Version 0.6.0 has measured fastload results on the reference DGX Spark pair and passes automated checks, but a complete clean installation of this release still needs validation on physical hardware. Test the prerelease on the target pair before production use.

Standalone operation is available only after a successful installation and pairing of two Sparks. The initial installation still requires both systems and their direct ConnectX-7 link. Later, if every local ConnectX-7 interface has no carrier, the guarded `llama-server` can run on the primary Spark alone and lets Unsloth/`llama.cpp` fit the model to the available local memory. This does not guarantee that a model sized for two Sparks will fit on one.

## Requirements

- Exactly two NVIDIA DGX Spark systems running Ubuntu ARM64. Both are required for the initial installation and pairing.
- A physical QSFP cable between the ConnectX-7 ports on both systems.
- A cluster configured in advance with [NVIDIA Sync Cluster Assistant](https://docs.nvidia.com/sync/latest/cluster-assistant.html).
- Passwordless SSH between the nodes. The installer discovers the second Spark's address and user automatically; you do not enter them manually.
- Internet access to download Unsloth and the `llama.cpp` sources.
- A GNOME graphical session and GNOME Terminal for the installer and log viewer. The RPC worker itself runs as a system service, independently of any terminal window or user login.
- If Studio is already loading a model through `llama-server`, unload it first. The installer starts a separate small test model and does not interrupt an active session.

During installation, the operating system may request a `sudo` password or confirmation on the local or second Spark. This is separate system authorization; SSH between the nodes should not request a password.

The `.run` file installs missing basic networking tools through Ubuntu APT. You do not need to install the `.deb` package first.

## Quick start: one file from the desktop

Download the single `Connect-Dual-Spark-arm64.run` file from [GitHub Releases](https://github.com/grosa787/connect-dual-spark-for-unsloth-studio/releases) to the desktop of the primary DGX Spark. No adjacent source directory is required.

Optionally verify the embedded archive first:

```bash
bash "$(xdg-user-dir DESKTOP)/Connect-Dual-Spark-arm64.run" --verify
```

Start the installer in English explicitly:

```bash
bash "$(xdg-user-dir DESKTOP)/Connect-Dual-Spark-arm64.run" --lang en
```

To use Russian instead:

```bash
bash "$(xdg-user-dir DESKTOP)/Connect-Dual-Spark-arm64.run" --lang ru
```

`--lang auto` (also the default when omitted) checks `CONNECT_DUAL_SPARK_LANG=en` or `ru` first, then the system locale. Locales beginning with `ru` select Russian; all others select English. An explicit `--lang en` or `--lang ru` takes precedence. Setting `CONNECT_DUAL_SPARK_LANG=auto` leaves selection to the locale.

The file verifies its embedded checksum, extracts the Python modules into a private temporary directory, and opens GNOME Terminal. The temporary files are removed after the installer window closes. The `.run` file is built for Ubuntu ARM64 and contains no addresses, usernames, or credentials.

If GNOME Terminal or a graphical session is unavailable, the launcher reports a clear error. During installation, an additional window displays the RPC log; closing that window does not stop the service.

## Run from source for development

The `Connect-Dual-Spark.run` launcher must remain next to the `dual_spark` directory. From a cloned repository, run:

```bash
./Connect-Dual-Spark.run --lang en
```

It opens a separate GNOME Terminal window and runs the following command from the project root:

```bash
python3 -m dual_spark.cli --lang en install
```

The source launcher is intended for development and requires the adjacent `dual_spark` directory. The release file built below is self-contained.

## Build the self-contained `.run` release

```bash
./scripts/build_run.sh 0.6.0
./dist/Connect-Dual-Spark-arm64.run --verify
```

The build script packages the current `dual_spark` module, removes Python caches, adds the embedded archive's SHA-256 digest, and creates `dist/Connect-Dual-Spark-arm64.run`. If the version argument is omitted, the package's current version is used.

## Build and install the `.deb` package

The Debian package targets the `arm64` architecture:

```bash
./scripts/build_deb.sh 0.6.0
sudo apt install ./dist/connect-dual-spark_0.6.0_arm64.deb
```

After installation, launch **Connect Dual Spark** from the application menu or run:

```bash
connect-dual-spark --lang en install
```

## Installation stages

The terminal interface reports each stage in order:

1. Check the operating system, architecture, and required system commands.
2. Find the active ConnectX-7 interface and the only eligible second Spark.
3. Verify link speed, the direct route in both directions, and passwordless SSH.
4. Install Unsloth Studio and build a versioned fastload `llama-server` from the officially installed `llama.cpp` source on the primary Spark.
5. Synchronize that exact patched source over ConnectX-7 and build its matching versioned RPC worker on the second Spark.
6. Install the RPC system service so it starts at boot before any user login.
7. Guard Studio's default and managed `llama-server` paths, then run a small GGUF model through the guard with weights on the second Spark and confirm active RDMA.
8. Configure Studio and perform the final installation checks.

The installer offers to launch Unsloth Studio only after every stage succeeds. On failure, it stops with diagnostics and never switches RPC to another network interface.

## Commands and interface language

```bash
connect-dual-spark --lang en install
connect-dual-spark --lang en check
connect-dual-spark --lang en start-rpc
connect-dual-spark --lang en studio
connect-dual-spark --lang en refresh
connect-dual-spark --lang en update-unsloth
connect-dual-spark --lang en status
```

- `install` performs the complete setup and offers to launch Studio after all checks pass.
- `check` only verifies the environment, link, route, and SSH; it does not modify packages or configuration.
- `start-rpc` checks the RPC system service, starts it when necessary, and opens a log window.
- `studio` starts the configured Studio service after checking the paired link, or the saved standalone setup when no ConnectX-7 cable is active.
- `refresh` reconciles the fastload pair after a command-line Unsloth update or a missed background repair event.
- `update-unsloth` stops the managed Studio when no model is running, invokes Unsloth's official Studio updater, rebuilds the version-matched fastload pair, and restarts Studio.
- `status` reports whether the Spark is paired or standalone, along with RPC and Studio configuration state.

The `.deb` installs the `connect-dual-spark` command. With the single `.run` file, use the same command names after the file path, for example `bash "$(xdg-user-dir DESKTOP)/Connect-Dual-Spark-arm64.run" refresh` or `bash "$(xdg-user-dir DESKTOP)/Connect-Dual-Spark-arm64.run" update-unsloth`.

`--lang en` forces English, `--lang ru` forces Russian, and `--lang auto` checks `CONNECT_DUAL_SPARK_LANG` before the system locale. The option works before or after the command, for example `connect-dual-spark status --lang ru`. If the option is omitted, auto selection is used. This setting localizes the installer's own prompts, progress, and status messages; diagnostics printed by operating-system commands or third-party tools may remain in English.

After a power cycle, RPC on the second Spark starts automatically as the system service `connect-dual-spark-rpc.service`, with `WantedBy=multi-user.target` and `Restart=always`. No user needs to log in on the second Spark. On the primary Spark, check the state with `connect-dual-spark status` and start Studio with `connect-dual-spark studio` when needed. If power was lost while a model was running, the model may need to be loaded again after connectivity returns.

Environment variables for ordinary new terminals are also saved in `.bashrc` and `environment.d`. Running `install` again checks and repairs the same managed configuration; it does not run `git pull` or choose an unreleased source revision.

For GGUF model loads, the installer sets `LLAMA_SERVER_PATH` to a guard link in the current Unsloth managed root. The guard and versioned fastload releases live under `~/.local/share/connect-dual-spark`, outside the tree that an official Unsloth update replaces. Studio uses this guarded path for launches from its UI and its external OpenAI-compatible API. An explicitly configured different binary or another inference backend is outside this integration.

## Fast loading and Unsloth updates

In paired mode, the guard selects DirectIO (`--load-mode dio`), permits RDMA negotiation, and enables the opt-in `GGML_RPC_NO_HASH_CACHE=1` path in the patched host RPC client. It still enforces the verified private ConnectX-7 endpoint, `CUDA0,RPC0`, and the 1:1 tensor split. The worker does not enable the cache-bypass variable.

On the reference pair, DeepSeek V4 Flash Vision Q8 (150.75 GiB, 1,048,576 context, 1:1 split) reached health in 5 min 35.6 s with the stock TCP loader. RDMA alone measured 5 min 35.5 s and DirectIO alone 3 min 32.3 s. The combined DirectIO, host-side RPC hash bypass, and RDMA path measured 112.3 s twice and 110.2 s through the Studio guard. These results describe the tested system; they are a comparison, not a fixed pass threshold for other models or machines.

After Unsloth officially installs a new managed `llama.cpp`, Connect Dual Spark identifies that installed release and rebuilds both host and worker from its source. The builds are stored as a new versioned pair outside Unsloth's replaceable tree. The in-app llama updater runs the official installer first and then refreshes the pair synchronously. Updates performed from the command line are picked up by the repair service and checked again when the next paired model launches. The first paired launch after an update can therefore wait for a one-time host and worker build.

For a full Studio update, use `connect-dual-spark update-unsloth` after unloading the current model. Unsloth's own CLI updater requires its managed Studio process to be idle; this command stops and restarts that service around the official update. If you update directly with `unsloth studio update`, stop Studio first and run `connect-dual-spark refresh` before restarting it.

The current in-app llama updater has a 30-minute limit for the official download and both fastload builds together. If a slow download exceeds that limit, the UI may report a failed update after the official files were replaced. The guard refuses a stale pair; run `refresh` from the `.run` file or CLI to finish reconciliation. On the reference pair, the version-matched rebuild took about 12 minutes.

Background repair does not stop an active model. Promotion of a newly built pair waits until the model is no longer using the worker. If the upstream RPC source no longer matches the supported narrow patch, or the new host and worker cannot be verified as one pair, the new paired launch fails with a repair error instead of silently using the old fastload engine. Future upstream source changes can require a new Connect Dual Spark release.

After the initial two-Spark installation, the guard selects one of two runtime modes:

- If any local ConnectX-7 interface has carrier and the RPC worker at port `50053` is reachable through the verified route, a `--list-devices` probe includes both `CUDA0` and `RPC0`. Before model loads, the guard removes earlier RPC/device/split/load-mode options, including stale RPC endpoints on a slower network. It then adds only the verified ConnectX-7 endpoint and these final options for the forced 1:1 split, followed by `--load-mode dio`:

```text
--rpc discovered-peer:50053 --device CUDA0,RPC0 --split-mode layer --tensor-split 1,1 --n-gpu-layers all --load-mode dio
```

- If every local ConnectX-7 interface reports no carrier, or the [hot-plugged ConnectX-7 NICs are absent without a cable](https://forums.developer.nvidia.com/t/the-100g-network-interface-card-nic-is-not-visible-in-the-operating-system/367149), the guard enters standalone mode using the saved pair configuration. It removes stale RPC arguments, two-Spark device and split settings, and their related environment settings before starting the local `llama-server`. No 1:1 split is imposed; Unsloth/`llama.cpp` decides what fits in the primary Spark's local memory. An oversized model may still fail to load.

The mode is chosen when a model starts. Unload and reload after disconnecting a cable to switch an active paired model to local mode, or after reconnecting to distribute an active standalone model across both Sparks. After upgrading the package while disconnected, `connect-dual-spark studio` refreshes the saved guard before starting Studio; the first installation still requires both Sparks.

If any local ConnectX-7 interface has carrier but the verified route or RPC worker is unavailable, the guard fails closed and refuses the model load. This avoids silently running locally while the cable appears connected or sending model traffic over another network. In connected mode it also rejects `-ot` / `--override-tensor` placement overrides that could pin all weights to one device. If an update replaces the managed guard link, the repair service and launch-time check restore it before selecting the matching fastload pair.

## ConnectX-7 route guarantee

The installer rejects addresses from Wi-Fi, ordinary Ethernet, and management networks. It selects only an active ConnectX-7 interface with a private IPv4 address and negotiated speed of at least 100 Gbit/s, then verifies both outbound and return routes.

RPC binds to the second Spark's ConnectX-7 address, and Studio receives exactly that address through `LLAMA_ARG_RPC`. The installer sets `UNSLOTH_LLAMA_CPP_PATH` to the official managed source and `LLAMA_SERVER_PATH` to its guarded path for the Studio service, shell, and `environment.d`. The guard enforces the same verified endpoint even when a launch request supplies conflicting placement arguments. Installation and validation always require the verified two-Spark route. After installation, host-only execution is allowed only when every local ConnectX-7 interface has no carrier; if any has carrier, a missing verified route or worker remains an error. Model traffic never falls back to a slower network. Internet downloads and other external traffic may continue to use the regular connection.

Do not expose the `llama.cpp` RPC protocol to a public or untrusted network. Keep the ConnectX-7 subnet isolated and do not publish the RPC port on management interfaces.

Studio listens on port 8888 on all host interfaces so another laptop can reach its authenticated UI and API. Restrict that port to a trusted LAN or VPN with your firewall; do not forward it to the public Internet.

## Troubleshooting failed checks

Run `connect-dual-spark check` and fix the first reported error. Common causes are a QSFP cable that is not fully seated, incomplete cluster configuration in NVIDIA Sync, or passwordless SSH that does not work between the nodes. A fastload repair error after an Unsloth update can also mean that the new official RPC source has changed beyond the patch supported by this Connect Dual Spark release; update Connect Dual Spark before retrying the paired load. The installer intentionally does not ask for an address or username and stops if more than one eligible peer is found on the link.

## Official documentation

- [NVIDIA Sync Cluster Assistant](https://docs.nvidia.com/sync/latest/cluster-assistant.html)
- [`llama.cpp` RPC](https://github.com/ggml-org/llama.cpp/blob/master/tools/rpc/README.md)
- [Unsloth](https://github.com/unslothai/unsloth/blob/main/README.md)
