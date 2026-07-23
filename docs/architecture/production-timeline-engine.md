# Production Timeline Engine

Verified local narration word timings can be embedded as `word_triggers`. See
`docs/architecture/narration-word-alignment.md`. Timings are accepted only when the alignment passes
deterministic checks and matches the selected narration asset hash.

Milestone 9D stores production timelines as immutable `production_timeline` content versions. A timeline references an approved script and scene plan plus exact active, approved asset IDs and hashes. Approved timelines are never modified; changed inputs create a new version.

The strict Pydantic document validates contiguous scene timing, unique scene placement, normalized frame-relative layer bounds, validated animation/motion/transition presets, subtitle timing, audio-mix settings, and sound-effect cues. Raw FFmpeg expressions are not accepted.

## Video formats

Timelines declare an explicit video format instead of relying on arbitrary dimensions:

- `long_horizontal`: existing 16:9 production behavior, defaulting to 1920x1080.
- `short_vertical`: retention-focused 9:16 production, defaulting to 1080x1920.

Short timelines split narration captions into visual beats of at most five words, use a
single caption line in the vertical safe area, and synchronize deterministic camera punches
to beat timestamps. The validator blocks incorrect aspect ratios, sub-1080x1920 short
outputs, multi-line short captions, and missing visual beats. Long-form optimization remains
deferred until the short-form pilot is approved.

```powershell
python -m ai_media_os.cli generate-timeline `
  --project-id <id> `
  --video-format short_vertical `
  --style-profile reference_minimal_character_motion_v1
```

The reference-derived preset is documented in
`docs/architecture/reference-minimal-character-motion-profile.md`. Its validated profile hash is
part of the timeline fingerprint. It currently enforces the output and caption contract while
reporting a warning for character/icon layer animation that the compositor does not execute yet.

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

When verified alignment matches the selected narration asset and hash, its word timings and triggers
are embedded. Otherwise timing remains narration-weighted. The compositor supports independent
background, character, prop, and overlay image layers with normalized placement, alpha, timing,
directional entrances, character motion, and story-event reactions. Existing one-image timelines use
the backward-compatible flat path. Automatic recurring-character pose-pack generation and approval
planning remain the next short-form increment. Music and SFX are represented and fingerprinted, but
a production pilot must supply separately licensed, approved assets before they can be mixed.
