**English** | [Русский](mistral-million-context-2026-10-31.ru.md)

# Mistral 1M-context startup repair — Spark Link 1.4.1

The existing Mistral Large 4 UD-IQ1_S model now loads through the normal Studio API on the real three-Spark cluster with **1048576 context, F16 KV, high reasoning and the compatible DSpark draft**. Text and vision checks passed. The model was left loaded for use.

## Cause

The first failure exhausted compute-buffer memory: a third-worker allocation of 69.32 GiB failed, followed by a 18.98 GiB non-pipelined retry. Reducing microbatch alone still requested 63.20 / 15.85 GiB. The model's shared KV map reuses layer 35 in later layers; attention weights of seven consumers were placed on the other RPC GPU. Whole-cache cross-backend copies and scheduler pipelining inflated the workspace at a million tokens.

The retry then failed earlier in the generic memory guard. That estimator assumes weights and KV grow linearly with requested split percentages and reserves 24 GiB on the primary. Those assumptions do not describe this model's layer/KV sharing and validated tight-memory layout.

## Repair

- Keep the exact six existing weight shards, configured context 1048576, F16 K/V and high reasoning.
- Requested layer split **27:34:39**, preserving more primary headroom.
- Place `blk.(47|51|55|59|63|67|71).attn_*` on `RPC0[10.100.32.2:50053]`, with their shared KV source. FFN weights remain distributed. This changes placement, not weights or mathematical precision. Explicit tensor placement also disables the main model's memory-heavy pipeline scheduling.
- Batch 128, microbatch 16, **one parallel slot**, Flash Attention on, automatic fitting off. Extra RAM prompt-cache copies and context checkpoints are disabled. The active model's million-token KV cache is retained.
- Disable RPC graph retention for this model process only. Worker services and other models retain their settings.
- Apply a locally calibrated launch profile before the generic linear estimate. It checks the exact model header/shard sizes, host runtime hash, RPC manifests, device ordering, endpoints and measured per-node memory requirements plus a 4 GiB reserve. Changed runtime/model or insufficient RAM fails before allocation. User-created explicit memory policies retain priority.

The calibrated profile is local configuration on this cluster, not an unsafe universal preset for other hardware or quantizations. Its code is bundled in the independent model runtime and the desktop installer; closing the GUI does not remove the fix.

## Validation

The main model's third-worker compute buffer is now approximately **2.35 GiB**. Target cache allocation remains **83840 MiB (81.875 GiB)**, plus the small draft cache. The native 1M capacity was not reduced.

Direct validation processed an 1836-token filler/math input and returned `4`; a synthetic red image returned `Red`, both with high reasoning. A subsequent **normal Studio load**, requested with four slots, launched the validated one-slot layout and passed text/vision again. This checks context allocation and real requests, not a fully populated million-token input or an extensive quality benchmark.

A numeric continuation smoke generated 128 tokens at about 12.2 tokens/s in the balanced layout. This artificial workload is not a general chat-speed claim. Smaller microbatches and one slot trade prefill/concurrency for memory headroom.

138 CLI tests and all 65 desktop checks passed across the isolated/system runtimes, including profile binding, changed-runtime rejection, precision preservation, insufficient-memory rejection and prevention of uncalibrated CPU offload. The three-device services remained active. No CUDA driver, model weights or KV quantization was changed.

The remaining practical limits are explicit: all three configured Sparks are required for this 1M/F16 model; other large applications can reduce available RAM below its measured budget; engine/model updates require recalibration. An explicit manual memory policy can override automatic profile selection.

## Update the application

```bash
curl -fsSL https://raw.githubusercontent.com/grosa787/connect-dual-spark-for-unsloth-studio/main/desktop/install-desktop.sh | bash
```

Manual download: `bash "$HOME/Downloads/Spark-Link-1.4.1-arm64.run"`. [Application instructions](../desktop/README.md).
