# Spark Link native application implementation plan

**Goal:** Deliver an independently installable Ubuntu ARM64 desktop application for managing Unsloth, RPC, dependencies, updates, and physical ConnectX-7 cabling.

**Architecture:** PySide6 / Qt Quick native window with a Qt Quick 3D device scene. A standard-library management layer validates topology, gathers real device state through SSH, and runs bundled CLI operations asynchronously. Network changes use explicit, narrowly validated administrative jobs and reject active models. The application bundles its own copy of the MIT CLI engine; neither installed artifact requires the other.

**Design:** Light mineral background #F2F5EE, white panels, ink #203024, muted #637264, lime #B5E866 and dark green #345B36. Ubuntu Sans / system sans. Quiet left navigation, central gold Spark models with selectable physical ports, right connection inspector. Five views: Overview, Cables, Installation, Updates, Journal. Labels and errors in Russian; physical port 0 is nearest RJ45 regardless of chassis rotation.

**Constraints:** Do not modify llama.cpp source or interrupt current model processes. Preserve installed model placement and the Q8 43:57 guard. Live topology changes require unloaded models and real carrier. No private keys or local credentials in distribution. A third device is visibly pending until actually reachable; no fabricated success or unsupported seamless failover. Hardware verification is limited to the two available Sparks.

## Task 1: Cluster and topology management
- [x] Add tests for two/three-node cabling, port conflicts, active-model refusal, configuration rollback, safe SSH target validation.
- [x] Implement topology model, read-only inventory, safe netplan helper and transactional apply job.
- [x] Implement install/update/check/RPC actions using bundled core while preserving installed custom guard.

## Task 2: Native interface
- [x] Implement native Qt Quick navigation, real state, operation feedback, journal, install/update controls.
- [x] Build rounded gold Spark geometry, perforated enclosure, physical port picking and cable scene.
- [x] Run app on ARM64, resolve QML/runtime errors, inspect screenshots and test controls.

## Task 3: Independent delivery
- [x] Build versioned tar archive and self-extracting run, bootstrap installer, desktop/menu entries, repair old launcher.
- [x] Document download-and-install and offline-archive install commands plus existing CLI commands in English/Russian.
- [x] Verify tests, archive installation from clean app directory, menu launch, real two-Spark inventory and no-op cabling apply.
- [x] Publish code and release artifacts on existing public GitHub repository and install native app on first Spark. Release: https://github.com/grosa787/connect-dual-spark-for-unsloth-studio/releases/tag/desktop-v1.0.0

## Review focus
Invalid topology cannot mutate networking; failed SSH cannot be green; active models block write jobs; failed updates restore service availability; external user guard survives app install/update; archived paths and desktop launchers handle spaces; three-node states distinguish prepared from verified hardware.
