# Video Composition

Milestone 7 adds the local preview render foundation for existing scene plans and generated or imported scene assets.

Implemented capabilities:

- Provider-neutral `VideoComposerProvider` interface.
- `LocalFFmpegVideoComposer` for local MP4 composition when FFmpeg is installed.
- `FakeVideoComposer` for deterministic tests without FFmpeg.
- Render planning from an approved scene plan and per-scene visual/narration assets.
- Render metadata on `Render` records: scene plan, provider, dimensions, FPS, format, input hashes, settings, output hash, errors, and completion timestamps.
- Render verification for safe project-relative MP4 paths, non-empty files, MP4 header check, and hash validation.
- CLI commands for planning, composing, verifying, listing, and reviewing renders.
- Queue handlers for render planning, composition, verification, and review.
- Dashboard render list, detail page, and safe local MP4 preview route.

The composer expects one image asset and one narration asset per scene. The planner validates that files exist under configured storage and match the stored asset hash before creating or reusing a render plan.

## Local demo flow

For an existing project with an approved scene plan and generated scene assets:

```powershell
$PROJECT_ID = "existing-project-id"
$SCENE_PLAN_VERSION_ID = "approved-scene-plan-version-id"

python -m ai_media_os.cli plan-render --project-id $PROJECT_ID --scene-plan-version-id $SCENE_PLAN_VERSION_ID
python -m ai_media_os.cli compose-video --project-id $PROJECT_ID
python -m ai_media_os.cli list-renders --project-id $PROJECT_ID
python -m ai_media_os.cli verify-render --project-id $PROJECT_ID
python -m ai_media_os.web
```

Open `http://127.0.0.1:8000/projects/{project_id}/renders` to inspect the generated preview render.

`compose-video` requires FFmpeg to be installed and available as `ffmpeg`, or configured through `AI_MEDIA_OS_FFMPEG_PATH`. FFprobe is optional for duration probing and can be configured with `AI_MEDIA_OS_FFPROBE_PATH`.

If FFmpeg is missing, the service fails clearly and records the render error instead of silently creating a fake production render.

## Faceless editorial profile

The optional `faceless_editorial` profile adapts retention patterns common to illustrated
faceless explainers without copying a reference creator's character, logo, artwork, or exact
sequence.

Image generation uses one original recurring AI analyst character with a stable outfit and
color palette. Prompts require a single focal point, a subject occupying roughly 60 to 70
percent of the frame, crisp cel-shaded edges, simple backgrounds, and varied direct-address,
demonstration, close-up, reaction, and prop-based shots. Generated images remain text-free;
captions and occasional headlines are composed with real fonts during video rendering.

```powershell
python -m ai_media_os.cli generate-scene-image `
  --scene-id <scene-id> `
  --provider comfyui `
  --visual-style faceless_editorial

python -m ai_media_os.cli generate-timeline `
  --project-id <project-id> `
  --style-profile faceless_editorial
```

The matching timeline profile favors hard cuts, controlled punch-ins, subtle float motion,
shorter caption lines, and only a few headline moments. It does not guarantee character
identity consistency from a text-only diffusion model. Production should first generate a
small pilot set; reference-image conditioning or a character LoRA can be evaluated later if
text-only consistency is insufficient.

Use `--video-format short_vertical` with this profile to produce a validated 1080x1920
timeline. Short narration is split into compact visual beats, and the FFmpeg composer applies
deterministic camera emphasis at those beat boundaries.

## Known limitations

- Subtitles and selected headline text are burned in with real fonts for production timelines.
- Thumbnail packaging and Content Safety are implemented by later stages, not by the composition service.
- No publishing, analytics, Shorts automation, or Telegram.
- Composition still uses one active image and narration asset per scene.
- Multi-pose character animation and within-scene asset cuts are not implemented.
