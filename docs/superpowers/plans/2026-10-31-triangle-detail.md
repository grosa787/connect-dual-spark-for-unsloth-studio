# Triangle cabling and hardware detail implementation plan

**Goal:** Make the three-Spark triangle explicit and easy to edit, refine controls,
and add authentic small hardware details without changing model runtime settings.

**Architecture:** Keep native Qt Quick 3D and the independent CLI. Pure topology
editing preserves K3 and swaps conflicting endpoints on the same device. Original
procedural meshes and static vector textures remain offline and reusable.

**Tech stack:** Python, PySide6 6.8, QML, original SVG materials.

Palette: chalk #f2f5ee, ink #203024, lime #b5e866, champagne #bdae87,
steel #939b96. Ubuntu Sans, existing type hierarchy. Layout: scene above a compact
cable selector; selected cable's two endpoints below. The physical triangle is
the focal point, rather than extra decoration.

- [x] Test triangle invariants, rejected open chains and atomic port swaps.
- [x] Test and implement cable curves that avoid three flat/upright chassis.
- [x] Refine cable editor, selected-cable feedback, button focus/disabled states.
- [x] Add connector latches, boot ribs, cage seams, fasteners, labels and lid grain.
- [x] Real ARM64 Qt checks: two/three devices, four languages, compact layout,
  physical port draft changes, repeated hide/show, installed background and menu.
- [ ] Install and publish 1.3.0 with Russian/English instructions and screenshots.

The real cluster still has two Spark devices. Three-node software/rendering
checks do not qualify a third physical device or live cable removal.
