# ADR 0022: Layered 2D Cutout Animation

## Status

Accepted

## Decision

Short-form production will use layered 2D cutout animation for character-led scenes. Backgrounds,
characters, props, and overlays are separately approved assets with independent timing, bounds,
opacity, entrance, and motion presets. Existing one-image timelines retain the flat-image renderer
for reproducibility.

The first executable motion vocabulary includes background drift, two phase-offset character bobs,
reaction pops, and directional entrances. Pose changes use multiple character layers with
non-overlapping time windows rather than AI-generated frame-by-frame interpolation.

## Consequences

- Two characters can move independently while story action remains in the background.
- Transparent cutouts and reusable pose packs are required before a timeline can use this path.
- Character consistency becomes an asset-generation and approval requirement.
- Full-body continuous animation and lip synchronization remain outside this slice.
- The target RTX 4050 renders composition locally without requiring a video diffusion model.
- Local Markdown-script runs opt into this path through
  `scripts/start-layered-short-project.ps1`.
- Each project receives immutable copies of the approved original host, support-character,
  and story-effect pack; repeated registration reuses verified copies.
- Narration rules add the support character and story effect only when the scene meaning calls
  for them, while the host remains the visual anchor.
- Repeated-background validation excludes reusable cast and effect layers because character
  continuity is intentional; repeated story imagery still produces a warning.
- Reusable cast packs declare a compatible topic family. The initial technology cast is skipped
  for automotive, health, finance, and general projects instead of being overlaid meaninglessly.
- Scene-art prompts derive presenter wardrobe, palette, object inserts, and props from the project
  topic. A recurring presenter is used for continuity, but object-only scenes remain character-free.
- The first topic families are automotive, health, finance, technology, and a neutral general
  fallback. These are deterministic local prompt rules and can be expanded without changing the
  compositor.
