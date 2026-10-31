**English** | [Русский](startup-and-mistral-2026-10-31.ru.md) · [App installation](../desktop/README.md)

# Lossless RPC loading and Mistral capacity

Hardware: the existing two DGX Spark GB10 systems, direct ConnectX-7/RDMA, Ubuntu ARM64. Runtime: Unsloth 2026.10.11 and Unsloth llama.cpp b11985-mix-c116c32, source `6f4cc4d72556554a7c137de536e2fbd93fd7f907`.

## Shared loading improvement

The RPC backend advertised asynchronous execution and events but no host staging buffer. This made the native model loader fall back to synchronous whole-tensor reads/uploads for the remote device. The patch exposes an alignment-safe CPU host staging type. The native loader can then overlap aligned DirectIO reads with uploads using its existing bounded ring of four staging buffers and event barriers.

This is in the common GGUF/RPC device interface, with **no model-name or architecture filter**. It keeps the previous RPC weight-hash bypass, DirectIO and RDMA. It changes no weights, quantization, tensor serialization, sampling, KV precision or mathematical operations. Warmup remains enabled; readiness gains are not obtained by moving initialization to the first request. Standalone CUDA loading already has its own asynchronous path; other inference frameworks are outside this patch.

| Matched Studio Q8 setup | Readiness |
| --- | ---: |
| Before asynchronous RPC staging | 165.2 s |
| Alignment-safe experimental library | 98.1 s |
| Alignment-safe managed pair | 96.3 s |

The Q8 comparisons use the same cached DeepSeek-V4-Flash-Vision-Exp UD-Q8_K_XL, configured context 1048576, four slots, 43:57 split and F16 KV. Both the text answer `4` and synthetic image answer `Red` were reproduced through Studio. Model and KV allocations were unchanged. The final managed comparison is about **42% faster**; this is a measurement on this pair, not a fixed speedup guarantee for every model. Earlier unpadded prototypes were superseded by the alignment-safe implementation.

### Alignment regression caught before release

An intermediate adapter used plain CPU buffers without reserving alignment slack. On the actual Spark the base was 64 bytes into a page, so DirectIO's aligned read could extend **4032 bytes beyond the reported allocation**. Some early loads happened to succeed, but a later Q8 control crashed. Studio then retried without Flash Attention, which exceeded the 1M-context memory budget and caused a worker OOM restart. Services and memory recovered; no model file was modified. That intermediate adapter was not published as a release.

The corrected staging type reserves unused virtual padding for the loader's aligned base adjustment, while preserving the original CPU allocator. C++ regression checks cover 512/4096/65536-byte alignments, overflow rejection, and allocator isolation. On hardware, a full 64-MiB DirectIO chunk read through the actual RPC staging allocator matched the original file checksum. The later Q8 text/vision control passed with the corrected allocator. Final controls also reject an automatic no-FlashAttention fallback rather than allowing that memory-heavy retry during a 1M test.

The matched Mistral control used the same context 512, one slot, F16 KV, 46:54 layer split and batch settings before/after: **208.213 → 110.678 seconds**, about **47% faster**. Two final 128-token decoding runs measured **7.158 and 7.182 tokens/s**; the generated strings matched the original runs byte for byte. Small Qwen deterministic continuations matched as well.

Other options were evaluated against the requested goal: disabling warmup or lazily reading weights can defer work into the first request; larger mmap/mlock caches compete with unified model memory; lower-precision KV or another weight quant would change the quality conditions; a speculative draft targets decoding and consumes extra memory. These were not used as a shortcut in the controlled startup comparison. The first build of a new runtime is a separate, one-time CUDA/RPC compilation step; readiness timings exclude that build. This pair has already completed the build.

## Downloaded Mistral

`unsloth/Mistral-Large-4-1T-A52B-GGUF`, **UD-IQ1_S**, complete revision `1eb4373d37e76f6e7b4b8efa20e1b1ca40b3b964`, six shards, **217.007 GiB**. Another cached revision contains only the metadata shard; that is not a complete second model.

The downloaded quantization was retained. This does not claim equivalence to the original unquantized model: it is a comparison against the user's existing IQ1 weights. K/V were kept at **F16**, one serving slot, Flash Attention, batch 128, ubatch 64, no RAM prompt cache or context checkpoints, no context shifting.

At minimal context **512**, two 128-token continuation runs measured **7.191 and 7.100 tokens/s** (about **7.15 tokens/s**). This is batch-one raw decoding, not reasoning-completion latency or a multi-user throughput benchmark.

### Why 50:50 was wrong for this model

Tensor split is applied at layer boundaries. The first 36 blocks contain 111.684 GiB of weights, the last 36 only 103.387 GiB. A nominal 50:50 attempt exhausted primary headroom during allocation and was stopped by the watchdog. The tested **46:54 layer split** produced:

| Buffer | First Spark | Second Spark |
| --- | ---: | ---: |
| GPU model weights | 108528.49 MiB (105.98 GiB) | 112688.73 MiB (110.05 GiB) |
| Input embedding on primary CPU | 984.38 MiB | — |

All 73 offloadable layers, including output, were on GPU. The actual GPU weight proportions are approximately 49:51; the layer-split numbers are not exact byte percentages.

## A separate low-memory option

Long-prefill testing exposed additional memory growth: RPC retains up to 1024 serialized computation graphs per device. This cache is **not the KV cache**. Many changing graph shapes during prompt processing can retain substantial CPU memory.

The opt-in environment variable `GGML_RPC_NO_GRAPH_CACHE=1` on the client selects the existing protocol's UID-zero, uncached-graph path. It copies the graph descriptor and changes only its wire UID; the caller's graph and tensor data are untouched. The server already supports this path, so no new wire format or cache-size negotiation is introduced. Ordinary graph reuse remains enabled by default.

For the extreme Mistral memory experiments, CUDA graph capture was also disabled with `GGML_CUDA_DISABLE_GRAPHS=1` on both host and worker. This is a separate model-memory experiment, not a global loading-speed setting. Worker mode changes were reversible and backed up; a temporary flag under `/run/lock` prevents the experimental setting surviving a reboot.

### Largest fully validated profile

On the final alignment-safe managed build, **106496 context tokens** were fully qualified with one slot and unchanged F16 KV. The test processed **106240 actual input tokens from an empty KV state** (`cache_n=0`) and generated 83 further tokens without context shifting or truncation. Prefill took **603.45 seconds**, **176.06 tokens/s**; decoding after the long prompt was **6.35 tokens/s**. The synthetic prompt is repetitive filler plus a final arithmetic instruction, not a coding-quality benchmark. A separate chat-format check reused the filled prefix and returned final `content: "4"`, with reasoning in its own field; this cached check is not counted as another full prefill.

| Final long-context result | First Spark | Second Spark |
| --- | ---: | ---: |
| F16 KV allocation | 4628 MiB | 3887 MiB |
| Minimum sampled OS available RAM | 2.294 GiB | 1.831 GiB |
| Additional swap during this validated run | under 1 MiB | 0 |

The pair already had old swap pages before the test; their presence is not described as new model paging. Higher-context attempts were stopped at a **1.5 GiB per-node reserve** or the additional-swap threshold. In particular, 114688 on the final safe build left only about 1.32 GiB on the worker during warmup and was stopped. **106496 is the largest fully tested stable profile here**, not a claim of an exact mathematical limit for every OS/service state. These extreme text-only settings are separate from ordinary GUI reserve defaults, and Mistral vision was not qualified at this memory ceiling.

The tested command parameters are `--tensor-split 46,54 --split-mode layer --n-gpu-layers all --load-mode dio --fit off -c 106496 --parallel 1 --flash-attn on --cache-type-k f16 --cache-type-v f16 -b 128 -ub 64 --cache-ram 0 --ctx-checkpoints 0 --no-context-shift`. The client also needs `GGML_RPC_NO_HASH_CACHE=1`, `GGML_RPC_NO_GRAPH_CACHE=1`, and the low-memory CUDA-graph setting described above on both devices. This is an experimental capacity profile, not an automatically imported GUI preset. The benchmark/controller scripts and JSON results are retained under `~/.cache/spark-runtime-update` on the primary Spark for repeating this exact experiment. [Machine-readable results](startup-mistral-validation-2026-10-31.json).

### Physical capacity

At context 65536 the measured F16 KV totals 5240 MiB: 2848 MiB primary and 2392 MiB worker. At the native 1048576 window that scales to **81.875 GiB**. Model tensors plus that KV alone need about **298.87 GiB**, before the OS, runtime and compute buffers; the pair exposes about 243 GiB of RAM. A fully resident 1M window for this downloaded Mistral cannot be obtained merely by accelerating I/O. No lower-precision KV, additional weight quantization or RoPE extension was used.

## Installation and update behavior

The change is distributed in **CLI 0.6.1** and **Spark Link 1.1.1**. App installation updates the independent fastload helpers and patch assets atomically with previous-version backups, while preserving custom launchers, model placement rules and credentials. The ordinary versioned build/promote transaction still verifies host/worker source and binary identities and retains rollback.

Final checks: **138 CLI + 41 desktop tests**, actual saved-policy inference, all six native tabs in four languages, and installed desktop-menu activation passed. The final selected build is `43e6caad6164ca8ad0d2a1bc6299a92f19c16df00a159781babd58e45dd01871`. The custom launcher delegate hash remained unchanged. Models were unloaded after the experiments; Studio is healthy (HTTP 200), RPC and the refresh watcher are active/enabled, default worker CUDA-graph mode was restored, and the temporary experiment receipt was removed.

[Download Spark Link](https://github.com/grosa787/connect-dual-spark-for-unsloth-studio/releases/tag/desktop-v1.1.1) · [Download CLI](https://github.com/grosa787/connect-dual-spark-for-unsloth-studio/releases/tag/v0.6.1)
