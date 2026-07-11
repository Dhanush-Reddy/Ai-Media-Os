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

## Known limitations

- No subtitles or caption burn-in yet.
- Thumbnail packaging and Content Safety are implemented by later stages, not by the composition service.
- No publishing, analytics, Shorts, Telegram, real ComfyUI, or real TTS.
- Basic scene composition only: image plus narration per scene, concat into one MP4.
- Basic motion and transition hooks are deferred until FFmpeg is available for visual validation.
