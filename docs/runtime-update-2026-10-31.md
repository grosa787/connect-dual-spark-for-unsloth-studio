**English** | [Русский](runtime-update-2026-10-31.ru.md) · [App instructions](../desktop/README.md)

# Runtime update — 31 October 2026

Updated and verified on the available two-device Ubuntu 24.04 ARM64 DGX Spark pair. Studio, RPC and the refresh watcher are active and enabled at boot. The test model was unloaded afterward.

| Component | Before | Updated installation |
| --- | --- | --- |
| Unsloth / unsloth_zoo | 2026.10.9 | 2026.10.11 |
| Unsloth llama.cpp | b11876-mix-ec42614 | b11985-mix-c116c32 |
| Source commit | 468ad5824c4afb245338f0ede29ef31680ba59c7 | 6f4cc4d72556554a7c137de536e2fbd93fd7f907 |
| Isolated Node / npm | 24.18.0 / 11.16.0 | 24.22.1 / 11.19.1 |
| PyTorch | 2.10.0+cu130 | 2.10.0+cu130 |

The official `unsloth studio update` installs Unsloth's compatible mixed llama.cpp branch. Fastload then copies that exact source, applies the existing opt-in RPC hash-cache bypass, builds CUDA/RDMA host and worker runtimes, verifies manifests and promotes the pair. The original Q8 43:57 / 1048576-context launcher and Spark Link memory gateway are preserved.

## Hardware verification

- Selected fastload pair: `b59492e60c9cb513b24176170f9ab83aa72b4cd0264d6c6df403d556bac5962e`. Both devices built the same source with GCC 13.3.0 and NVCC 13.0.88; CUDA and RDMA are enabled. Host/worker manifests and the running worker executable were verified.
- The small cached Qwen model completed inference on both devices through the independent standard-library memory gateway, with saved 45:55 placement and 512-token context overriding stale 8192 launch arguments.
- The original `unsloth/DeepSeek-V4-Flash-Vision-Exp-GGUF`, `UD-Q8_K_XL`, loaded through the actual Studio API in **165.2 seconds**. Studio reported context **1048576** and **4 parallel slots**; launcher arguments retained `CUDA0,RPC0`, `43,57`, and direct RPC over ConnectX-7. The log confirmed RDMA activation and all 44 layers offloaded to GPU.

| Observed allocation | First Spark | Second Spark |
| --- | ---: | ---: |
| GPU model buffers | 67303.34 MiB (65.73 GiB) | 86052.51 MiB (84.04 GiB) |
| Logged KV buffers, summed | 11833 MiB (11.56 GiB) | 15816 MiB (15.45 GiB) |
| OS available memory while loaded, approximately | 27 GiB | 11 GiB |

Layer boundaries make actual buffer proportions approximate. Available memory includes reclaimable cache; it differs from the bare `free` column. The primary retains the larger headroom.

The Studio OpenAI-compatible chat route returned **`4`** for `2+2`, then **`Red`** for a synthetic solid-red image. Both were successful HTTP requests. Studio health remained HTTP 200. The model was unloaded through Studio's API and no `llama-server` process remained; available memory returned to about 114/116 GiB. Test memory policies were removed.

The existing **132 CLI + 40 desktop tests** passed, with the two Ubuntu netplan tests run separately on system Python. The original launcher delegate SHA-256 remains `cddb6aec3304021e2a759cca302ed952c95b809eb422b59f6e4561859e4da59e`. The update-pending marker is cleared and user linger remains enabled.

These checks cover short text/image requests and allocation for the configured context. They do not benchmark a million-token prompt, qualify three-device inference, or simulate power loss during generation. [Machine-readable result](runtime-validation-2026-10-31.json).

The first attempt stalled downloading Node from nodejs.org on the Spark. Stopping that attempt exercised automatic rollback to the previous runtime and fastload pair. The retry used the official Node archive downloaded on the control computer and served temporarily on Spark loopback, with its SHA-256 checked against the pin shipped by Unsloth. No checksum validation was disabled. The temporary source is not a permanent runtime dependency.

The setup reported no compatible torchcodec wheel for ARM64/Python 3.13 with this Torch version; TorchCodec audio decoding remains unavailable. This does not qualify audio/video decoding or training functionality.

## Update an existing installation

In Spark Link, unload models in Studio, then choose **Updates → Update Studio and RPC**. The app creates its local rollback snapshot before the official updater and matching RPC rebuild.

For the independent two-device CLI:

```bash
connect-dual-spark --lang en update-unsloth
connect-dual-spark --lang en status
connect-dual-spark --lang en check
```

CLI and app manage the same runtime; run one update at a time. A first installation still uses the [standard app instructions](../desktop/README.md) or [CLI instructions](../README.md).
