[English](README.md) | [Русский](README.ru.md)

# Connect Dual Spark for Unsloth Studio

Connect Dual Spark automatically discovers the direct ConnectX-7 link between exactly two NVIDIA DGX Spark systems, installs Unsloth Studio, and configures `llama.cpp` RPC on the second Spark. Inter-node model traffic is allowed only over the verified high-speed ConnectX-7 interface.

> **Pre-release status:** The project passes automated static and package-structure checks, but a complete clean installation has not yet been validated on a physical pair of DGX Spark systems. Treat version 0.4.0 as a pre-release and test it on the target hardware before production use.

## Requirements

- Exactly two NVIDIA DGX Spark systems running Ubuntu ARM64.
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
./scripts/build_run.sh 0.4.0
./dist/Connect-Dual-Spark-arm64.run --verify
```

The build script packages the current `dual_spark` module, removes Python caches, adds the embedded archive's SHA-256 digest, and creates `dist/Connect-Dual-Spark-arm64.run`. If the version argument is omitted, the package's current version is used.

## Build and install the `.deb` package

The Debian package targets the `arm64` architecture:

```bash
./scripts/build_deb.sh 0.4.0
sudo apt install ./dist/connect-dual-spark_0.4.0_arm64.deb
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
4. Install Unsloth Studio and build the local `llama-server` from the managed `unslothai/llama.cpp` clone on the primary Spark.
5. Synchronize the same source tree over ConnectX-7 and build `llama.cpp` RPC on the second Spark.
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
connect-dual-spark --lang en status
```

- `install` performs the complete setup and offers to launch Studio after all checks pass.
- `check` only verifies the environment, link, route, and SSH; it does not modify packages or configuration.
- `start-rpc` checks the RPC system service, starts it when necessary, and opens a log window.
- `studio` verifies the current ConnectX-7 link and RPC configuration, then starts the configured Studio service. Use it after installation, including from the terminal that ran the installer.
- `status` reports the link, RPC, and Studio configuration state.

`--lang en` forces English, `--lang ru` forces Russian, and `--lang auto` checks `CONNECT_DUAL_SPARK_LANG` before the system locale. The option works before or after the command, for example `connect-dual-spark status --lang ru`. If the option is omitted, auto selection is used. This setting localizes the installer's own prompts, progress, and status messages; diagnostics printed by operating-system commands or third-party tools may remain in English.

After a power cycle, RPC on the second Spark starts automatically as the system service `connect-dual-spark-rpc.service`, with `WantedBy=multi-user.target` and `Restart=always`. No user needs to log in on the second Spark. On the primary Spark, check the state with `connect-dual-spark status` and start Studio with `connect-dual-spark studio` when needed. If power was lost while a model was running, the model may need to be loaded again after connectivity returns.

Environment variables for ordinary new terminals are also saved in `.bashrc` and `environment.d`. Running `install` again checks and repairs the same managed configuration; it does not run `git pull` or update source versions automatically.

For GGUF model loads, the installer places a standalone guard at both the default Unsloth `llama-server` path (`~/.unsloth/llama.cpp/llama-server`) and the Connect Dual Spark managed path (`~/.local/share/connect-dual-spark/llama-src/llama-server`). This also protects Studio when it is started externally through its API and does not inherit `LLAMA_ARG_RPC`. Before starting a model, the guard requires the discovered ConnectX-7 route and the RPC worker at port `50053` to be reachable. A `--list-devices` probe includes both `CUDA0` and `RPC0`. For model loads, the guard places these options last in the final `llama.cpp` command, so they override conflicting earlier device choices:

```text
--rpc discovered-peer:50053 --device CUDA0,RPC0 --split-mode layer --tensor-split 1,1 --n-gpu-layers all
```

If the verified route or worker is unavailable, the guard refuses the model load instead of running the GGUF solely on the primary Spark. It also rejects `-ot` / `--override-tensor` placement overrides that could pin all weights to one device. Its scope is GGUF inference launched through `llama-server` at the default or managed paths above. An explicitly configured alternate binary or another backend bypasses this guard. If an Unsloth update replaces either guard symlink, rerun `connect-dual-spark install` to restore the guard before loading another model.

## ConnectX-7 route guarantee

The installer rejects addresses from Wi-Fi, ordinary Ethernet, and management networks. It selects only an active ConnectX-7 interface with a private IPv4 address and negotiated speed of at least 100 Gbit/s, then verifies both outbound and return routes.

RPC binds to the second Spark's ConnectX-7 address, and Studio receives exactly that address through `LLAMA_ARG_RPC`. The installer sets `UNSLOTH_LLAMA_CPP_PATH` to the locally built `llama.cpp` and `LLAMA_SERVER_PATH` to the guarded binary for the Studio service, shell, and `environment.d`. The guarded default and managed `llama-server` paths enforce the same endpoint even when those environment variables are absent. If the verified route disappears, installation, validation, or a guarded model load fails; model traffic does not automatically fall back to a slower network or to host-only execution. Internet downloads and other external traffic may continue to use the regular connection.

Do not expose the `llama.cpp` RPC protocol to a public or untrusted network. Keep the ConnectX-7 subnet isolated and do not publish the RPC port on management interfaces.

## Troubleshooting failed checks

Run `connect-dual-spark check` and fix the first reported error. Common causes are a QSFP cable that is not fully seated, incomplete cluster configuration in NVIDIA Sync, or passwordless SSH that does not work between the nodes. The installer intentionally does not ask for an address or username and stops if more than one eligible peer is found on the link.

## Official documentation

- [NVIDIA Sync Cluster Assistant](https://docs.nvidia.com/sync/latest/cluster-assistant.html)
- [`llama.cpp` RPC](https://github.com/ggml-org/llama.cpp/blob/master/tools/rpc/README.md)
- [Unsloth](https://github.com/unslothai/unsloth/blob/main/README.md)
