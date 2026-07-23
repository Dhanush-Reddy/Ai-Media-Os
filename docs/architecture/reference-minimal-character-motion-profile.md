# Reference Minimal Character Motion Profile

`reference_minimal_character_motion_v1` converts the measured reference-video style into a
validated short-form production contract. It is intended for original AI Media OS artwork. The
reference character, logo, forehead mark, and other identifiable branding are not reusable assets.

## Output contract

- 9:16, 1080x1920, 30 fps
- 48 kHz final audio target
- original recurring faceless host with a stable silhouette and design language
- flat, low-contrast blue-grey backgrounds
- no more than two primary subjects
- one-line, lower-center captions with at most six words per phrase
- meaningful visual beats every 0.8-2.0 seconds
- complete compositions held approximately 2.5-5.0 seconds
- pose changes, icon pops, short slides, fades, and restrained camera motion

The timing source was two unique reference videos. Three other uploads were duplicates and are not
counted as independent evidence. Retention rules are editorial heuristics, not measured audience
retention predictions.

## Current executable behavior

The profile is strict, versioned, and included in timeline fingerprints. Selecting it requires
`short_vertical`; generation otherwise fails. The current compositor executes:

- 1080x1920 output at 30 fps
- phrase captions and visual-beat timing
- deterministic beat punches, slow movement, cuts, and crossfades
- approved asset and narration selection by exact ID and hash
- subtitle rendering with real fonts

The validator emits `reference_profile_layer_gap` until a timeline contains executable character or
icon layers. The FFmpeg compositor now executes separately supplied background and transparent
character layers, including independent timing, directional entrances, character bobs, and reaction
motion. Automatic pose-pack generation and planning are still required before normal production
timelines use this layered path; existing one-image timelines remain flattened by design.

## Generate and inspect

```powershell
$PYTHON = ".\.venv\Scripts\python.exe"
$PROJECT_ID = "e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f"

& $PYTHON -m ai_media_os.cli generate-timeline `
  --project-id $PROJECT_ID `
  --video-format short_vertical `
  --style-profile reference_minimal_character_motion_v1

& $PYTHON -m ai_media_os.cli show-timeline --project-id $PROJECT_ID
```

Use the emitted timeline version ID with `validate-timeline`, then request approval and render only
after reviewing all findings.

## Next implementation slice

1. Align the active narration asset, not a historical narration revision.
2. Convert verified word triggers into semantic beats.
3. Introduce automatic generation and approval of transparent character, icon, and prop assets.
4. Add rotation and richer pose replacement planning to the existing layered compositor.
5. Implement the Scene 1 Tuesday contrast as the first acceptance fixture.
6. Compare the rendered MP4 against this profile using deterministic timing and motion checks.

Qwen/Ollama visual scores remain advisory. Actual retention can only be evaluated from published
viewer behavior.
