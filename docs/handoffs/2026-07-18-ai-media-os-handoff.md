# AI Media OS Detailed Engineering Handoff

> 2026-07-18 update: the measured reference style is now represented by the validated
> `reference_minimal_character_motion_v1` timeline preset. See
> `docs/architecture/reference-minimal-character-motion-profile.md`. It fingerprints 1080x1920,
> 30 fps, 48 kHz delivery intent, short phrase captions, measured visual-beat timing, motion
> vocabulary, avoidance rules, and original-character rights constraints. The current compositor
> still lacks executable pose/icon layers and reports that limitation as
> `reference_profile_layer_gap`; it must not be described as a full reference-style match yet.

**Handoff date:** 2026-07-18  
**Repository:** `Dhanush-Reddy/Ai-Media-Os`  
**Local repository:** `C:\Users\gspra\OneDrive\Desktop\Dhanush\Ai-Media-Os`  
**Current branch:** `feature/milestone-9d-motion-timeline`  
**Current HEAD:** `2134bf5 Fix Chatterbox V3 local runtime`  
**Remote branch tip:** `origin/feature/milestone-9d-motion-timeline` currently points to `5487c65`  
**Stable baseline tag:** `v0.9.4` at `b834091`  
**Primary project:** AI & Future, short-form pilot  
**Milestone 9D status:** In progress; timing foundation works, trigger-driven compositing does not yet work

This document is the authoritative handoff for the current local work. It is intentionally detailed
because a future engineer or Codex task must be able to continue without relying on chat history.

---

## 1. Executive Summary

AI Media OS is a local-first Python application for producing monetization-aware YouTube content.
The current product pipeline can already perform:

```text
research
  -> approved script
  -> approved scene plan
  -> generated/reviewed images
  -> generated/reviewed narration
  -> production timeline
  -> local FFmpeg render
  -> metadata and thumbnail foundations
  -> safety and publishing-gate checks
```

Real local providers are available for:

* Ollama text generation and image evaluation.
* ComfyUI image generation.
* Piper narration.
* Chatterbox Multilingual V3 narration.
* WhisperX forced alignment of narration to known script text.

The current creative objective is not another slideshow with zoom/pan. The target is a vertical,
faceless editorial short that uses a recurring host character, timed pose changes, transparent icon
overlays, real text overlays, and compact animation events synchronized to narration words.

The first fully specified animation is Scene 1, the "Tuesday Fall-Apart" hook:

```text
Narration:
An AI agent can look brilliant in a demo, then fall apart on its first real Tuesday.

At "AI":
  Pop in an AI icon above the host's right shoulder.

At "brilliant":
  Add sparkle/halo emphasis and show BRILLIANT IN A DEMO.

At "then":
  Hard-cut the host from arms_crossed to facepalm/pointing pose.

At "fall":
  Instantly remove the AI icon/sparkle and pop/tumble broken gears into frame.

At "Tuesday":
  Show a Tuesday calendar with a red X and FALL APART ON TUESDAY.
```

Word timing now works locally through WhisperX. The remaining major gap is that the compositor does
not consume those triggers as overlay/pose animation instructions. It currently uses the trigger-
independent `visual_beats` only for zoom pulses.

There is also an immediate selected-input mismatch: the successful WhisperX alignment references an
older Scene 1 narration revision, while the latest approved timeline selected a newer active
narration revision. The latest timeline and render therefore contain no alignment reference or word
triggers. This must be corrected before implementing or testing trigger-driven compositing.

---

## 2. Product Direction and Constraints

### Primary business goal

Generate revenue from one high-quality AI & Future YouTube channel before expanding into a general
multi-channel autonomous platform.

### Content formats

The product is expected to support two formats:

1. Short vertical videos, 9:16, currently the first priority.
2. Long horizontal videos, 16:9, after the short format reaches acceptable quality.

The desired production rate is approximately five to six short videos per week per channel. That
requires aggressive reuse of validated providers, character references, prompt templates, animation
presets, and cached assets without sacrificing quality.

### Target machine

* Windows laptop.
* NVIDIA RTX 4050 Laptop GPU.
* 16 GB RAM.
* Local-first execution.
* Zero recurring software cost initially.
* Sequential GPU-heavy processing.

### Permanent engineering constraints

* Python-first.
* SQLite and Alembic.
* Local filesystem storage.
* Provider-neutral application services.
* Cache-first and fingerprinted generation.
* Important content and assets are revisioned.
* Approved outputs are never overwritten.
* Human approval remains for creative quality and publishing.
* No arbitrary internet image reuse.
* Copyright, provenance, model-license, and monetization risk must remain visible.
* No YouTube auto-upload yet.
* No Telegram, analytics, Shorts scheduling, Redis, Celery, Docker, React, Node, or cloud backend yet.

---

## 3. Milestone History

Completed and merged before the current branch:

* Milestone 1: SQLite/Alembic foundation.
* Milestone 2: Database-backed queue.
* Milestone 3: Content versioning, approvals, prompt metadata, cache, storage.
* Milestone 4: Manual local research pipeline.
* Milestone 4.5: Minimal operations dashboard.
* Milestone 5: Script generation and scene planning.
* Milestone 6: Image and voice provider foundation.
* Milestone 7: Video composition / first local render.
* Milestone 8: Thumbnail and metadata foundation.
* Milestone 8.5: Content safety and rights engine.
* Milestone 9A-9C foundations: local Ollama, ComfyUI, real TTS/provider smoke work.
* Model-license provenance remediation and replacement Piper voice.

Current branch commits not yet merged into `main`:

```text
2134bf5 Fix Chatterbox V3 local runtime
b59a79f Add Chatterbox multilingual voice provider
2215897 Add production timeline foundation
```

Current uncommitted work extends Milestone 9D with:

* Better faceless editorial image prompts.
* Sequential short-production orchestration and staged image review.
* Ollama vision image evaluation.
* Dashboard usability work.
* Timeline and FFmpeg motion improvements.
* CLI approval ergonomics.
* WhisperX narration alignment and word triggers.

Milestone 9D is not complete because the final renderer still cannot execute layered animation
events or within-scene pose cuts.

---

## 4. Git and Working-Tree State

### Branch

```text
feature/milestone-9d-motion-timeline
```

Do not switch to `main`, reset, clean, or discard files. The working tree contains substantial
uncommitted work accumulated across the current pilot.

### Remote status

The local branch is ahead of its remote. The remote branch currently points to the merged-main
baseline `5487c65`, while local HEAD is `2134bf5` plus many uncommitted changes.

### Modified tracked files

```text
.env.example
.gitignore
README.md
docs/MVP_SCOPE.md
docs/architecture/production-timeline-engine.md
docs/architecture/video-composition.md
src/ai_media_os/application/assets.py
src/ai_media_os/application/timelines.py
src/ai_media_os/cli.py
src/ai_media_os/dashboard/progress.py
src/ai_media_os/dashboard/queries.py
src/ai_media_os/dashboard/view_models.py
src/ai_media_os/domain/enums.py
src/ai_media_os/infrastructure/settings.py
src/ai_media_os/media/production_timeline.py
src/ai_media_os/providers/ollama.py
src/ai_media_os/providers/video_composition.py
src/ai_media_os/schemas/production_timeline.py
src/ai_media_os/static/css/app.css
src/ai_media_os/templates/base.html
src/ai_media_os/templates/dashboard/approvals.html
src/ai_media_os/templates/dashboard/assets.html
src/ai_media_os/templates/dashboard/metadata.html
src/ai_media_os/templates/dashboard/project_detail.html
src/ai_media_os/templates/dashboard/projects.html
src/ai_media_os/templates/dashboard/renders.html
src/ai_media_os/templates/dashboard/research.html
src/ai_media_os/templates/dashboard/safety.html
src/ai_media_os/templates/dashboard/scenes.html
src/ai_media_os/templates/dashboard/script.html
src/ai_media_os/templates/dashboard/thumbnail.html
src/ai_media_os/templates/dashboard/timeline.html
tests/integration/test_job_queue_migrations.py
tests/unit/test_asset_pipeline.py
tests/unit/test_dashboard.py
tests/unit/test_production_timeline.py
tests/unit/test_settings.py
```

### Important untracked implementation files

```text
alembic/versions/0014_narration_alignment.py
docs/architecture/narration-word-alignment.md
docs/architecture/offline-image-evaluation.md
docs/architecture/remote-approval-access.md
docs/runbooks/local-production-and-approval-commands.md
docs/runbooks/offline-narration-alignment.md
scripts/keep-awake-on-ac-and-internet.ps1
scripts/review-latest-approval.ps1
scripts/run-short-production.ps1
src/ai_media_os/application/narration_alignment.py
src/ai_media_os/providers/narration_alignment.py
src/ai_media_os/providers/ollama_vision.py
src/ai_media_os/providers/whisperx_alignment.py
src/ai_media_os/providers/whisperx_alignment_worker.py
src/ai_media_os/schemas/image_evaluation.py
src/ai_media_os/schemas/narration_alignment.py
src/ai_media_os/templates/dashboard/fragments/project_nav.html
tests/unit/test_cli_reviews.py
tests/unit/test_narration_alignment.py
tests/unit/test_ollama_vision.py
```

### Untracked clutter that must be handled carefully

* A file named `--project-id` exists at the repository root. It was likely created by an earlier
  malformed PowerShell command. Inspect it before deleting it.
* `.pytest-tmp-*` directories were created by repository-local Pytest runs. Windows denied deletion
  because of their ACLs. They are test output, not source, but do not run `git clean` because it
  would also remove legitimate untracked implementation files.
* `data/reports/image-evaluations/` contains local evaluation reports. These are generated project
  data and should not be committed unless an audit explicitly requires selected fixtures.

### Safe first commands for the next engineer

```powershell
git branch --show-current
git log --oneline --decorate -10
git status --short
git diff --check
```

Do not use `git reset --hard`, `git checkout --`, or `git clean`.

---

## 5. Current Pilot Project Identity

### Channel

```text
Channel ID: c9716dbc-c7c0-483e-ac32-5901e2c3ec53
Channel slug: ai-future
Channel name: AI & Future
```

### Project

```text
Project ID: e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f
Working title: Why AI Agents Fail in Production
Status: draft
```

### Approved selected content

```text
Approved script version:
  ID: 99afddfe-c597-4cfd-926c-57956a27b2d4
  Version: 3

Approved scene plan:
  ID: 880b21be-6836-409a-b0c1-f1caab2cc156
  Version: 1

Scene count: 18
```

### Scene 1

```text
Scene ID: 1393f90f-a0a8-4420-8711-ca5a6e93f0d9
Narration: An AI agent can look brilliant in a demo, then fall apart on its first real Tuesday.
```

### Other scene IDs

```text
02 1459598c-ffcc-411b-9d48-cc0b1910b7bf
03 761b63a4-c68d-4005-963c-5e1f8c6eeb1d
04 758adbd2-f55d-4794-ad33-c3c9c8c281be
05 b229a16e-4bd3-4ffb-afc3-41b5f47e32f3
06 7ba59be2-3697-4118-849a-b1f5c8f3698b
07 5b8c3749-fd5b-483f-8535-bfb8b1da2e57
08 ed690bc1-ac66-4dfc-ac0e-b2604ce064dc
09 c7772cbd-e2ac-42a8-ae86-f04e7957d380
10 c6232567-d4ff-477c-9f9c-4c2ec181b137
11 21dee36a-ec24-45ff-a840-3af6cdbf8f60
12 e84afbdf-dbdc-4ced-8023-98edbafe0245
13 eb471781-6544-442c-bc1c-74d1b99bc24f
14 c4efce3d-9559-408d-afe8-68d18f42f441
15 276de614-7f75-4919-9f75-8596e6f7be79
16 005e396e-4ecb-4c10-afcd-fa75a2bcffe0
17 8a65cb37-6205-415c-b774-238bfed3b5c3
18 0bc8caf5-a441-4631-8ac9-1374e88eb7d4
```

---

## 6. Current Local Provider Setup

### Chatterbox

Machine-local root:

```text
C:\AI-Models\Chatterbox\
```

Observed directories:

```text
.venv
multilingual-v3
samples
voices
```

The provider runs in an isolated Python environment and records the Chatterbox runtime/source
revision in asset metadata. The application main environment does not import Chatterbox's heavy
dependencies.

Important configuration variables:

```text
AI_MEDIA_OS_CHATTERBOX_PYTHON_PATH
AI_MEDIA_OS_CHATTERBOX_MODEL_PATH
AI_MEDIA_OS_CHATTERBOX_REFERENCE_AUDIO_PATH
AI_MEDIA_OS_CHATTERBOX_DEVICE
AI_MEDIA_OS_CHATTERBOX_REQUEST_TIMEOUT_SECONDS
AI_MEDIA_OS_CHATTERBOX_EXAGGERATION
AI_MEDIA_OS_CHATTERBOX_CFG_WEIGHT
AI_MEDIA_OS_CHATTERBOX_EXPECTED_RUNTIME_VERSION
AI_MEDIA_OS_CHATTERBOX_SOURCE_REVISION
```

### WhisperX

Machine-local root:

```text
C:\AI-Models\WhisperX\
```

Observed directories:

```text
models
venv
```

WhisperX was manually installed and its health check returned:

```text
READY    whisperx    WhisperX offline alignment is ready.
```

That `READY` result depended on environment variables set in the user's PowerShell session. A new
PowerShell or Codex subprocess does not inherit those values automatically. The next task should
either set them again or persist correct paths in the local `.env` file, which is gitignored.

Expected current-session configuration:

```powershell
$env:AI_MEDIA_OS_WHISPERX_PYTHON_PATH = "C:\AI-Models\WhisperX\venv\Scripts\python.exe"
$env:AI_MEDIA_OS_WHISPERX_MODEL_PATH = "C:\AI-Models\WhisperX\models\wav2vec2-en"
$env:AI_MEDIA_OS_WHISPERX_DEVICE = "cpu"
$env:AI_MEDIA_OS_WHISPERX_COMPUTE_TYPE = "int8"
$env:AI_MEDIA_OS_WHISPERX_EXPECTED_RUNTIME_VERSION = "3.4.2"
```

The main application does not install or download WhisperX. The isolated worker sets offline flags
and requires the model directory to exist. An empty model path is explicitly rejected; an earlier
bug incorrectly interpreted an empty `Path` as `.` and treated the repository as a model directory.

### ComfyUI

The current image provider uses local ComfyUI. The model previously reported as producing the best
quality is:

```text
z_image_turbo_bf16.safetensors
```

The generation flow should remain text-free for images. All readable labels should be rendered by
the compositor using real fonts. Diffusion-generated text is unreliable and was visibly malformed
in earlier samples.

### Ollama

Ollama is installed locally. The image evaluation model used during the pilot is:

```text
qwen3-vl:4b
```

Ollama vision evaluation is advisory. It checks scene relevance, composition, perceived sharpness,
character presence/consistency when possible, artifact risk, and text artifacts. It is not a legal,
creative, or final human-quality guarantee.

---

## 7. Implemented Narration Alignment Foundation

### Files

```text
src/ai_media_os/schemas/narration_alignment.py
src/ai_media_os/providers/narration_alignment.py
src/ai_media_os/providers/whisperx_alignment.py
src/ai_media_os/providers/whisperx_alignment_worker.py
src/ai_media_os/application/narration_alignment.py
alembic/versions/0014_narration_alignment.py
tests/unit/test_narration_alignment.py
docs/architecture/narration-word-alignment.md
docs/runbooks/offline-narration-alignment.md
```

### Persistence

A new immutable content type exists:

```text
narration_alignment
```

Migration `0014_narration_alignment` updates the `content_versions.content_type` check constraint.
Downgrade preserves alignment rows in `migration_backup_0014_narration_alignment`, maps them to a
historical supported type, verifies row counts, and restores them on re-upgrade.

### Provider contract

`NarrationAlignmentProvider` is provider-neutral. It accepts:

* Audio path and hash.
* Known approved transcript.
* Language.
* Audio duration.
* Timeout.
* Optional cancellation file.
* Provider settings.

It returns:

* Ordered word timings.
* Per-word confidence when available.
* Provider/model/runtime identity.
* Provider settings hash.
* Metadata.

### Providers

* `FakeNarrationAlignmentProvider` distributes words deterministically. It never inspects audio and
  is always stored as `WARN`, `auto_usable=false`.
* `WhisperXNarrationAlignmentProvider` runs an isolated worker using an explicitly configured local
  Python runtime and local model bundle. It does not download models.

### Deterministic verification

An alignment is automatically usable only if:

* The source asset is `scene_narration`.
* The source narration asset is approved.
* The file exists inside configured storage.
* The file SHA-256 matches the asset record.
* The normalized aligned words exactly match the persisted scene narration.
* Word timestamps are monotonic and within audio bounds.
* Requested trigger words exist at the requested occurrence.
* Trigger order is valid.
* Average confidence meets the configured threshold, default `0.75`.
* Each trigger confidence meets the configured threshold, default `0.65`.
* Provider/model/model-bundle/settings/audio/transcript/triggers/FPS all contribute to the
  fingerprint.

### CLI

```text
check-alignment-provider
align-narration
show-narration-alignment
list-narration-alignments
```

### Timeline integration

`TimelineScene` now supports:

```text
narration_alignment_version_id
narration_alignment_hash
word_triggers[]
```

Timeline generation only embeds an alignment when all of these match:

* Project.
* Scene.
* Selected narration asset ID.
* Selected narration asset hash.
* `verification.auto_usable == true`.

This selected-input check is correct and is why the current active mismatch did not silently reuse
stale timings.

---

## 8. Successful Alignment Report

Two alignment versions exist for Scene 1:

```text
Version 1
ID: 4e7f75bb-917a-4721-ae92-101e5ffabd27
Provider: fake_alignment
Decision: WARN
Auto usable: false

Version 2
ID: e5b1660d-a7de-4876-ba99-3f76ae3a9f17
Provider: whisperx
Model: wav2vec2-en
Model version: whisperx-3.4.2
Decision: PASS
Auto usable: true
```

The successful alignment references:

```text
Narration asset ID: 3f2f3bac-f0c7-40ea-8ffe-66c67c707db1
Asset revision: 3
Active: false
File: projects/e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f/audio/scene_001/narration_v004.wav
Duration: 6.34 seconds
Hash: 7cfdd824e5573493a7ea50e9c09233e0764683414995a2458c1f3f85b2f4c0b6
Review: approved
```

Measured trigger timings at 30 FPS:

| Trigger | Word | Start | Frame | Confidence |
|---|---|---:|---:|---:|
| `ai_icon` | AI | 0.463 s | 14 | 0.696 |
| `sparkle` | brilliant | 2.315 s | 69 | 1.000 |
| `pose_cut` | then | 3.583 s | 107 | 0.874 |
| `fall_apart` | fall | 3.784 s | 114 | 0.960 |
| `tuesday_card` | Tuesday | 5.273 s | 158 | 0.843 |

Average confidence:

```text
0.9410588235294117
```

The report warning says the final word exceeded the recorded duration and was clamped. The result
still passed because the final timestamp was safely clamped to the asset duration and all other
checks passed.

---

## 9. Critical Active-Narration Mismatch

The active approved Scene 1 narration is now:

```text
Narration asset ID: 8e3fb19a-5155-4adf-a14e-1ef0aa75f1a0
Asset revision: 4
Active: true
File: projects/e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f/audio/scene_001/narration_v005.wav
Duration: 10.42 seconds
Hash: a14c075e14db276197f36d676395ce511e1b0e99b7b5306ad5c96d5633c92bcb
Provider: chatterbox
Model version: multilingual-v3-runtime-0.1.7-source-65b184371927
Review: approved
```

The passing alignment belongs to the inactive 6.34-second `narration_v004.wav`. It cannot be reused
for the active 10.42-second `narration_v005.wav`.

Consequences:

* Production timeline v5 selected narration asset `8e3f...`.
* Production timeline v5 has `narration_alignment_version_id: null` for Scene 1.
* Production timeline v5 has `word_triggers: []` for Scene 1.
* Render v5 does not use the measured word triggers.
* The trigger frames shown above are not valid for the 10.42-second narration.

This is the first operational blocker. Align the active narration and generate a new timeline
revision before making compositor changes or evaluating trigger synchronization.

---

## 10. Current Timeline and Render State

### Content versions

```text
Production timeline v1: 0a193b5e-1295-40a7-9f6a-1872639a3270, superseded
Production timeline v2: 3d86b2ae-0555-43c3-8f13-420354f31e97, superseded
Production timeline v3: 684806e8-79e8-434b-b283-bab3a0ecc94c, superseded
Production timeline v4: ca5d5e21-9a0c-4cde-b338-422605b7c93d, superseded
Production timeline v5: 097609f2-d9a3-4d4e-b5c5-bce0d0734b16, approved
```

Timeline v5:

```text
Format: short_vertical
Resolution: 1080x1920
FPS: 30
Style: faceless_editorial
Scene count: 18
Motion: beat_punch
Scene 1 duration: 10.42 seconds
Scene 1 active narration: 8e3fb19a-5155-4adf-a14e-1ef0aa75f1a0
Scene 1 alignment: null
Scene 1 triggers: empty
```

### Render versions

```text
Render v1: c5e76a46-730e-4fd7-91e5-2ce0583456b4, changes_requested
Render v2: 3e74bd7e-cb97-4aac-81bf-19780701a4d8, rendered
Render v3: c44bfea8-7fc1-4218-8584-ec25ca73867d, approved
Render v4: f34f1136-28b6-42bf-93cb-9328097f033d, changes_requested
Render v5: 91c369b4-13a3-4e3d-8d1d-b4538501f55c, rendered
```

Latest render details:

```text
ID: 91c369b4-13a3-4e3d-8d1d-b4538501f55c
Version: 5
Status: rendered, not approved
Path: data/projects/e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f/renders/production_v005.mp4
Hash: b9111312a38d8995be56e4a6727df0b520ebe77e447e9f56579a61586d94f1f5
File size: 15,952,272 bytes
File verification: OK
```

Do not approve render v5 as proof of trigger animation. It has no Scene 1 alignment triggers.

### Packaging and gate state for this pilot

At handoff time:

```text
Metadata versions: none listed for this project
Thumbnail assets: none listed for this project
Latest safety report: NONE
```

This means the current pilot is not ready for a publishing gate even after the motion work is done.

---

## 11. What the Current Renderer Actually Does

Implemented in `src/ai_media_os/providers/video_composition.py`:

* Scales/crops one selected image to the output frame.
* Applies output FPS.
* Supports static, zoom, pan, subtle float, parallax push, and beat-punch camera motion.
* Burns ASS/SRT subtitles through FFmpeg.
* Supports cuts and simple fades/crossfades.
* Concatenates scene video/audio segments.
* Produces H.264/AAC MP4 output.

For short vertical timelines, `beat_punch` generates small zoom pulses at `visual_beat_times_seconds`.
Those visual beats come from subtitle cue boundaries, not WhisperX word triggers.

The current renderer does not:

* Render all `TimelineLayer` objects as independent composited layers.
* Accept multiple host-pose assets inside one scene.
* Overlay transparent icons or illustrations.
* Execute `word_triggers`.
* Switch host pose at an exact word.
* Perform 0 -> 1.15 -> 1.0 overshoot scale over seven frames.
* Instantly remove an overlay at a word boundary.
* Rotate/tumble an icon into place.
* Animate text presets such as line reveal or scale bounce.
* Perform true parallax from separately generated foreground/background layers.

This is the central Milestone 9D gap.

---

## 12. Target Animation Contract

The next implementation should introduce an explicit event/action schema instead of encoding
behavior only in trigger names. Trigger names are labels; they are not sufficient compositor
instructions.

Recommended conceptual schema:

```json
{
  "trigger_name": "fall_apart",
  "source_alignment_version_id": "...",
  "timestamp_seconds": 3.784,
  "frame": 114,
  "actions": [
    {
      "action": "hide_layer",
      "target": "ai_icon",
      "duration_frames": 0
    },
    {
      "action": "hide_layer",
      "target": "sparkle",
      "duration_frames": 0
    },
    {
      "action": "show_layer",
      "target": "broken_gears",
      "animation": "overshoot_scale",
      "duration_frames": 7,
      "rotation_start_degrees": -15,
      "rotation_end_degrees": 0
    }
  ]
}
```

Recommended reusable action types:

```text
show_layer
hide_layer
replace_layer_asset
set_text
overshoot_scale
fade_in
fade_out
slide_in
rotate_in
hover_y
hard_cut
camera_punch
```

Recommended overshoot preset at 30 FPS:

```text
Trigger frame + 0: scale 0.00, opacity 1.00
Trigger frame + 4: scale 1.15, opacity 1.00
Trigger frame + 7: scale 1.00, opacity 1.00
```

The event schema must be strict Pydantic with `extra="forbid"`, deterministic serialization, and
frame/timestamp validation.

---

## 13. Required Scene 1 Assets

The target animation cannot be produced from one full-frame diffusion image. Scene 1 needs separate
assets, ideally transparent PNGs:

```text
host_arms_crossed.png
host_facepalm.png or host_pointing_forward.png
ai_icon.png
sparkle.png
broken_gears.png
tuesday_calendar_red_x.png
```

Background can remain a generated full-frame image or be a simple designed background.

Requirements:

* Host poses must use the same recurring character, outfit, colors, face, proportions, and line
  style.
* Icons should be simple, readable, and original.
* Generated assets must contain no text.
* `BRILLIANT IN A DEMO` and `FALL APART ON TUESDAY` must be rendered with real fonts.
* Transparent alpha must be validated.
* Every asset must be versioned, hashed, reviewed, and linked to the scene.
* Rejected staged assets should be deleted only through the existing explicit review/staging policy.
* Approved assets must be persisted and never overwritten.

The existing `AssetRole` model may need new roles or a role-plus-layer-key metadata convention. Do
not weaken the unique active scene/role invariant. If multiple overlays share a broad role, add a
stable layer key/revision invariant instead of bypassing uniqueness.

---

## 14. Recommended Rendering Approach

Stay Python-first and reuse FFmpeg for this milestone. Do not introduce React/Node/Remotion unless
the FFmpeg implementation is proven untenable and the architecture decision is explicitly changed.

Recommended FFmpeg strategy:

1. Resolve and hash-verify all selected layer assets before planning the render.
2. Build one deterministic `filter_complex` graph per scene.
3. Use transparent PNG inputs looped for scene duration.
4. Scale and position each layer from normalized timeline coordinates.
5. Use `enable='between(t,start,end)'` for visibility windows.
6. Use frame-based expressions for overshoot scale and rotation.
7. Use `overlay` chains ordered by `z_index`.
8. Use `drawtext` or generated ASS overlays for readable OST.
9. Keep subtitles as a separate final overlay.
10. Compose each scene to an intermediate MP4 with normalized audio/video settings.
11. Concatenate scenes using the existing safe concat flow.

Do not interpolate timing from transcript length after a passing alignment exists. Trigger events
must use the selected alignment document and exact selected narration hash.

---

## 15. Exact Immediate Recovery Flow

Run this before modifying the compositor. Use the same PowerShell session or set the WhisperX
variables again.

### 15.1 Set identifiers

```powershell
$PYTHON = ".\.venv\Scripts\python.exe"
$PROJECT_ID = "e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f"
$SCENE_ID = "1393f90f-a0a8-4420-8711-ca5a6e93f0d9"
$ACTIVE_NARRATION_ID = "8e3fb19a-5155-4adf-a14e-1ef0aa75f1a0"
```

### 15.2 Configure WhisperX for the terminal

```powershell
$env:AI_MEDIA_OS_WHISPERX_PYTHON_PATH = "C:\AI-Models\WhisperX\venv\Scripts\python.exe"
$env:AI_MEDIA_OS_WHISPERX_MODEL_PATH = "C:\AI-Models\WhisperX\models\wav2vec2-en"
$env:AI_MEDIA_OS_WHISPERX_DEVICE = "cpu"
$env:AI_MEDIA_OS_WHISPERX_COMPUTE_TYPE = "int8"
$env:AI_MEDIA_OS_WHISPERX_EXPECTED_RUNTIME_VERSION = "3.4.2"
```

### 15.3 Verify provider and active narration

```powershell
& $PYTHON -m ai_media_os.cli check-alignment-provider --provider whisperx
& $PYTHON -m ai_media_os.cli verify-audio-asset $ACTIVE_NARRATION_ID
```

Both must pass.

### 15.4 Align the active narration

```powershell
& $PYTHON -m ai_media_os.cli align-narration $ACTIVE_NARRATION_ID `
  --provider whisperx `
  --language en `
  --frame-rate 30 `
  --trigger "ai_icon=AI" `
  --trigger "sparkle=brilliant" `
  --trigger "pose_cut=then" `
  --trigger "fall_apart=fall" `
  --trigger "tuesday_card=Tuesday"
```

Required result:

```text
pass    auto_usable=true
```

### 15.5 Inspect the new report

```powershell
& $PYTHON -m ai_media_os.cli show-narration-alignment `
  --project-id $PROJECT_ID `
  --scene-id $SCENE_ID
```

Confirm:

```text
narration_asset_id == 8e3fb19a-5155-4adf-a14e-1ef0aa75f1a0
narration_asset_hash == a14c075e14db276197f36d676395ce511e1b0e99b7b5306ad5c96d5633c92bcb
decision == pass
auto_usable == true
```

### 15.6 Generate a new timeline revision

```powershell
$TIMELINE_ID = (
  & $PYTHON -m ai_media_os.cli generate-timeline `
    --project-id $PROJECT_ID `
    --video-format short_vertical `
    --style-profile faceless_editorial `
    --frame-rate 30
).Trim()

$TIMELINE_ID
```

Expected: a new timeline after v5 because the alignment content hash changes the fingerprint.

### 15.7 Prove selected-input linkage

```powershell
& $PYTHON -m ai_media_os.cli show-timeline --timeline-version-id $TIMELINE_ID
```

For Scene 1, confirm:

```text
narration_asset_id == 8e3fb19a-5155-4adf-a14e-1ef0aa75f1a0
narration_alignment_version_id is not null
narration_alignment_hash is not null
word_triggers contains all five triggers
```

### 15.8 Validate but do not treat current renderer as final

```powershell
& $PYTHON -m ai_media_os.cli validate-timeline --timeline-version-id $TIMELINE_ID
```

Only request timeline approval after the event/action compositor is implemented and the timeline
contains actual overlay/pose layers. Otherwise the new render will still only show camera pulses.

---

## 16. CLI Approval and Render Reference

After compositor implementation and visual review:

```powershell
$APPROVAL_ID = (
  & $PYTHON -m ai_media_os.cli approve-timeline `
    --timeline-version-id $TIMELINE_ID
).Trim()

& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID
```

Interactive choices:

```text
1 = Approve
2 = Reject
3 = Request changes
```

Render:

```powershell
$RENDER_ID = (
  & $PYTHON -m ai_media_os.cli render-timeline `
    --timeline-version-id $TIMELINE_ID
).Trim()

& $PYTHON -m ai_media_os.cli verify-render --render-id $RENDER_ID
& $PYTHON -m ai_media_os.cli list-renders --project-id $PROJECT_ID
```

Review:

```powershell
& $PYTHON -m ai_media_os.cli review-render $RENDER_ID
```

Never approve through raw SQL or direct ORM mutation.

---

## 17. Image Generation and Evaluation Work

### Creative direction

The desired visual style is a mature, crisp, illustrated faceless explainer:

* One recurring host character.
* Strong subject hierarchy.
* Character occupies roughly 60-70 percent of the frame when used as host.
* Text-free generated images.
* Simple backgrounds and clear props.
* Controlled direct-address, demonstration, reaction, close-up, and prop-based shots.
* No random decorative futuristic hardware unrelated to the narration.
* No fake labels or diffusion-generated words.
* 1080x1920 minimum for shorts; upscale/4K processing only when it improves actual detail.

### Local short-production script

```text
scripts/run-short-production.ps1
```

The script was developed to:

* Process scenes sequentially.
* Show generation/evaluation progress.
* Reuse already generated valid assets.
* Stage images in a temporary project review area.
* Send one image at a time for review.
* Persist approved images to final project storage.
* Delete rejected staged images under the explicit review flow.
* Run Ollama image evaluation.

### Ollama vision reliability fixes

Earlier failures included:

* Prompt exceeding the model's 4096-token context.
* Invalid or empty JSON responses.
* PowerShell treating a successful CLI result as an unknown exit code.
* Evaluation reports printed but not recognized as written.

The provider now has stricter parsing/repair and shorter context behavior. Tests are in:

```text
tests/unit/test_ollama_vision.py
```

Advisory output includes:

* Scene relevance score.
* Composition score.
* Perceived sharpness score.
* Character consistency score when reference comparison is available.
* Artifact risk score.
* Text artifact detection.
* Strengths, issues, recommendation.

Do not let an Ollama `PASS` automatically replace human visual review until real false-positive and
false-negative rates are measured on the channel's own samples.

---

## 18. Narration Quality Direction

The user accepted Chatterbox audio as better than earlier voices but wants more natural emotion and
less generated-sounding pitch behavior.

Current controls:

```text
reference audio
voice name
language
exaggeration
cfg weight
seed
```

Typical pilot command used:

```powershell
& $PYTHON -m ai_media_os.cli generate-scene-narration `
  --scene-id $SCENE_ID `
  --provider chatterbox `
  --reference-audio "C:\AI-Models\Chatterbox\voices\shorts-narrator.wav" `
  --voice shorts-narrator `
  --language en `
  --exaggeration 0.6 `
  --cfg-weight 0.4 `
  --seed 2
```

Timing automation does not judge emotional quality. WhisperX verifies transcript/timing structure,
not naturalness, clipping, pronunciation quality, or acting. Human listening remains required for
the final selected narration until a separate, validated audio-quality evaluator is added.

---

## 19. Dashboard and Approval Work

The dashboard was revised to be more understandable for a new user:

* Shared project navigation fragment.
* Clearer project progress and next action.
* More consistent page structure.
* Friendlier approvals/assets/renders/timeline views.
* Project/channel list output includes headings, creation dates, and a `LATEST` tag.
* CLI review commands can use numbered choices instead of long status strings.

Useful runbook:

```text
docs/runbooks/local-production-and-approval-commands.md
```

Useful helper:

```text
scripts/review-latest-approval.ps1
```

The dashboard remains localhost-only. Netlify-hosted frontend approval and Telegram are explicitly
deferred until the production flow is stable. Do not expose the current dashboard publicly because
it has no remote authentication/security boundary.

---

## 20. Verification Results

Before the final health-check message improvement:

```text
Full Pytest: 279 passed, 1 skipped
Ruff check: passed
Ruff format --check: passed
Mypy: passed, 92 source files
Alembic upgrade head: passed
Alembic downgrade -1: passed
Alembic upgrade head: passed
Alembic check: passed
git diff --check: passed
```

After fixing WhisperX empty model-path validation and exact health diagnostics:

```text
Focused narration alignment tests: 6 passed
Ruff focused check: passed
Mypy: passed, 92 source files
```

The full suite was not rerun after that last narrow health-diagnostic change. The next engineer
should rerun it before committing.

Pytest's normal global temp directory had Windows ACL problems. Full verification succeeded with a
repository-local `--basetemp`, but those directories later became difficult to delete. Prefer a
known writable temp root and add a safe ignore pattern before future runs.

Recommended full verification:

```powershell
.\.venv\Scripts\python.exe -m pytest --basetemp .codex-test-tmp-final
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
git diff --check
```

---

## 21. Tests Added or Extended

### Narration alignment

`tests/unit/test_narration_alignment.py` covers:

* Deterministic fake alignment persistence.
* Fake alignment never becoming production-usable.
* Idempotent replay.
* Approved narration requirement.
* File-hash requirement.
* Transcript mismatch blocking.
* Missing trigger blocking.
* Explicit local WhisperX runtime/model health.
* Empty model path/repository path rejection.
* CLI parsing for offline model and trigger options.
* Final-word timestamp clamp behavior.

### Timeline

`tests/unit/test_production_timeline.py` covers:

* Valid and idempotent timelines.
* Short vertical format.
* Faceless editorial profile.
* Visual beats and subtitle constraints.
* Selected script/scene-plan/asset validation.
* Production timeline approvals.
* Embedding only verified alignment matching selected narration.
* Production render behavior.

### Migration

`tests/integration/test_job_queue_migrations.py` includes the narration-alignment preservation cycle
and adjusts the production-timeline migration test to target the correct earlier revision now that
`0014` is head.

### Image evaluation and production assets

```text
tests/unit/test_ollama_vision.py
tests/unit/test_asset_pipeline.py
```

These cover image evaluation parsing/recovery, generated asset reuse, staged review, revision
preservation, and relevant provider behavior.

---

## 22. Known Risks and Technical Debt

### Critical

1. The active narration is not aligned; current v5 timeline/render have no word triggers.
2. The compositor does not execute word triggers or layer animation actions.
3. Scene animation currently remains one image plus camera motion.
4. Metadata, thumbnail, and safety report are absent for the current pilot package.

### High

1. Only Scene 1 has an attempted real alignment. Other scenes still use proportional subtitle cue
   timing and no word-level triggers.
2. Trigger schema contains timing but not explicit animation actions.
3. Character identity depends mostly on prompts and selected outputs; there is no validated
   reference-conditioning/LoRA consistency pipeline yet.
4. Current visual assets include many historical revisions. Active selection must always be explicit
   and hash-bound.
5. External WhisperX environment variables are session-local unless added to `.env`.

### Medium

1. Image sharpness evaluation is advisory and not calibrated against human review.
2. Chatterbox emotional delivery has no automatic quality evaluator.
3. Current production timeline docs describe layer schemas more broadly than the FFmpeg compositor
   actually renders; keep documentation explicit about this limitation.
4. Test temp directories and accidental root file clutter need controlled cleanup.
5. The branch contains multiple cohesive feature areas in one dirty worktree, increasing review and
   merge-conflict risk.

### Deferred intentionally

* Telegram.
* Netlify remote approval frontend.
* YouTube publishing.
* Analytics.
* Shorts scheduling/automation.
* Real plagiarism/copyright APIs.
* OCR.
* Cloud services.
* Redis/Celery/Docker.
* React/Node.

---

## 23. Recommended Next Engineering Sequence

Do these one at a time.

### Task 1: Correct selected alignment

Align active Scene 1 narration `8e3f...`, verify `PASS`, generate a new timeline, and prove the
alignment is embedded. Do not render yet.

### Task 2: Add explicit timeline event/action schema

Add strict versioned animation events tied to verified trigger names/frames. Keep existing timelines
backward compatible.

### Task 3: Add Scene 1 layer assets

Create/import and review host poses and transparent icons. Record hashes, revisions, roles/layer
keys, provider metadata, and provenance.

### Task 4: Implement FFmpeg layered scene compositor

Render independent layers, frame-based visibility, overshoot scale, pose replacement, rotation, and
real-font text overlays.

### Task 5: Render only Scene 1 as a fast pilot

Do not repeatedly render all 18 scenes while developing the animation engine. Add or use a scene-
range pilot command so iteration takes seconds instead of minutes.

### Task 6: Human acceptance test

Check exact sync, visual clarity, host consistency, text readability, and motion quality. Reject if it
still reads as a moving slideshow.

### Task 7: Generalize presets

Once Scene 1 passes, generalize events into reusable short-form templates for setup, contrast,
reveal, list item, correction, and CTA scenes.

### Task 8: Complete package and gate

Generate/review metadata and thumbnail, rerun safety/provenance checks, and create the publishing
gate report. Publishing remains manual.

### Task 9: Stabilize Git

After full verification, inspect every untracked/modified file, separate generated data from source,
commit intentionally, push the branch, and open/update the PR. Do not blindly `git add .` before
removing or ignoring local test/report clutter.

---

## 24. Definition of Milestone 9D Complete

Milestone 9D should be considered complete only when all of the following are true:

* Active selected narration is aligned and hash-linked.
* Scene 1 timeline contains verified trigger events.
* Separate host/icon/text layers are represented explicitly.
* FFmpeg executes the events at the measured frames.
* The setup/punchline contrast is visible without reading implementation notes.
* Rendered text is crisp and readable.
* Host identity is consistent between poses.
* Narration is natural enough for production after human listening.
* A short vertical pilot renders and verifies successfully.
* Timeline and render are approved through application services.
* Full tests, Ruff, formatting, Mypy, and Alembic checks pass.
* Source changes are committed and pushed without generated model/project data.
* Metadata/thumbnail/safety are either completed for the pilot or explicitly recorded as the next
  packaging step.

Current state does not meet this definition.

---

## 25. Do Not Do These Things

* Do not reuse alignment `e5b1660d...` for active narration `8e3fb19a...`.
* Do not approve render v5 as evidence of trigger animation.
* Do not silently make fake alignment production-usable.
* Do not render diffusion-generated text as final on-screen copy.
* Do not overwrite approved assets or renders.
* Do not bypass approvals with SQL or direct ORM updates.
* Do not delete project data or historical revisions.
* Do not run `git clean` in the current dirty worktree.
* Do not auto-download models from application code.
* Do not add Remotion/React/Node without an explicit architecture decision.
* Do not begin Telegram, Netlify remote approval, publishing, analytics, or Shorts automation.
* Do not claim the local safety engine guarantees legal or platform compliance.

---

## 26. Key Files to Read First

Permanent context:

```text
AGENTS.md
README.md
docs/MASTER_PLAN.md
docs/MVP_SCOPE.md
```

Current architecture:

```text
docs/architecture/production-timeline-engine.md
docs/architecture/video-composition.md
docs/architecture/narration-word-alignment.md
docs/architecture/offline-image-evaluation.md
docs/architecture/chatterbox-multilingual-voice.md
docs/architecture/content-safety-rights-engine.md
```

Current runbooks:

```text
docs/runbooks/local-production-and-approval-commands.md
docs/runbooks/offline-narration-alignment.md
```

Core implementation:

```text
src/ai_media_os/application/timelines.py
src/ai_media_os/application/narration_alignment.py
src/ai_media_os/application/assets.py
src/ai_media_os/providers/video_composition.py
src/ai_media_os/providers/whisperx_alignment.py
src/ai_media_os/providers/whisperx_alignment_worker.py
src/ai_media_os/providers/ollama_vision.py
src/ai_media_os/schemas/production_timeline.py
src/ai_media_os/schemas/narration_alignment.py
src/ai_media_os/media/production_timeline.py
src/ai_media_os/cli.py
```

Tests:

```text
tests/unit/test_narration_alignment.py
tests/unit/test_production_timeline.py
tests/unit/test_ollama_vision.py
tests/unit/test_asset_pipeline.py
tests/integration/test_job_queue_migrations.py
```

---

## 27. Short Handoff Prompt for the Next Codex Task

```text
Continue AI Media OS on feature/milestone-9d-motion-timeline.

Read AGENTS.md and docs/handoffs/2026-07-18-ai-media-os-handoff.md first.
Do not reset or clean the dirty worktree.

Immediate objective:
1. Configure the existing local WhisperX runtime for the current terminal.
2. Align active Scene 1 narration asset 8e3fb19a-5155-4adf-a14e-1ef0aa75f1a0.
3. Require PASS and auto_usable=true.
4. Generate a new short_vertical faceless_editorial timeline.
5. Prove the new timeline embeds the active narration alignment and all five word triggers.
6. Do not approve/render it yet.
7. Then implement a strict trigger-action schema and FFmpeg layered compositor for the Tuesday
   Fall-Apart Scene 1 pilot.

Target events:
- AI: pop AI icon.
- brilliant: sparkle plus BRILLIANT IN A DEMO.
- then: hard host pose cut.
- fall: instantly remove AI/sparkle and tumble broken gears in.
- Tuesday: calendar red X plus FALL APART ON TUESDAY.

Use separate reviewed transparent assets and real-font compositor text.
Do not use diffusion-generated text.
Do not start Telegram, Netlify remote access, YouTube publishing, analytics, or Shorts automation.
Run focused tests continuously and the full quality/migration suite before committing.
```

---

## 28. Final State Statement

The system has moved beyond a basic local generation demo: it has real provider integrations,
versioned assets, approvals, safe storage, local rendering, image evaluation, and real word-level
narration alignment. The data required for word-synchronized animation exists and is validated.

However, the currently selected active narration has not yet been aligned, and the current FFmpeg
composer does not execute layered animation events. The latest rendered video is therefore still a
high-quality moving-image timeline rather than the intended character-led animated short.

The next work should remain narrowly focused on selected-input correction and one excellent,
word-synchronized Scene 1 animation pilot. Do not broaden scope until that scene looks genuinely
production-worthy.
