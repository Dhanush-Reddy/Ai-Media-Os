# Production Timeline Engine

Milestone 9D stores production timelines as immutable `production_timeline` content versions. A timeline references an approved script and scene plan plus exact active, approved asset IDs and hashes. Approved timelines are never modified; changed inputs create a new version.

The strict Pydantic document validates contiguous scene timing, unique scene placement, normalized frame-relative layer bounds, validated animation/motion/transition presets, subtitle timing, audio-mix settings, and sound-effect cues. Raw FFmpeg expressions are not accepted.

Timeline fingerprints include ordered scenes, asset and narration hashes, subtitle/font settings, resolution, frame rate, motion, transitions, audio mix, schema version, and renderer configuration version. Volatile timestamps, job IDs, absolute paths, and temporary paths are excluded.

## Workflow

```text
approved scene plan and assets
  -> generate timeline
  -> deterministic validation
  -> timeline approval
  -> production render plan
  -> FFmpeg composition and verification
  -> production render approval
  -> existing safety and publishing gate
```

The local dashboard exposes `/projects/{project_id}/timeline`. CLI commands provide generation, display, validation, approval requests, subtitle export, rendering, and preset discovery.

## Limitations

Subtitle timing is scene and sentence/chunk based; word-level forced alignment is deferred. The first renderer uses deterministic per-scene motion and fades before concatenation. Music and SFX are represented and fingerprinted, but a production pilot must supply separately licensed, approved assets before they can be mixed.
