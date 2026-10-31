# Spark hardware scene and generation study

Keep the existing native Qt app, lime accent, device discovery, network workflow,
model policy and independent CLI. No production model settings change during QA.

1. Rebuild the procedural DGX Spark shell at 150 × 150 × 50.5 mm, with a smooth
   champagne lid, porous front/rear panels, front grips, feet and recessed I/O.
   Keep physical QSFP identities stable and rotate cable anchors with the shell.
2. Refine navigation, inputs and scene lighting. Add accessible camera presets,
   zoom and port labels. Preserve resource release when the window is hidden.
3. Test ordinary and upright scenes, two/three-device drafts, four languages,
   keyboard input and compact layouts on the first Spark with real Qt rendering.
4. Compare generation with and without target-verified n-gram speculation using
   the same Mistral weights, F16 KV, context, split, seeds and six fixed requests.
   Record timing and exact output comparison; do not infer universal speedups.
5. Publish verified screenshots, measurements, installation artifacts and notes.

Hardware reference: https://docs.nvidia.com/dgx/dgx-spark/hardware.html
Speculation reference: https://github.com/ggml-org/llama.cpp/blob/master/docs/speculative.md

The scene is an original procedural illustration, not NVIDIA CAD. No imported
product photograph or third-party mesh is shipped.

The hide/show visual regression exposed Qt 6.8 resource teardown failures. The
final approach retains graph nodes and still permits graphics/context cache release.
An attempted manual mesh rebuild was rejected after a render-image crash under gdb.
