# AI Media OS

AI Media OS is a local-first foundation for producing one monetization-safe YouTube channel before expanding into broader automation.

The current implementation covers Milestones 1 through 8.5 and optional local providers through Milestone 9C:

- Python project configuration
- Environment-based settings
- Structured logging setup
- SQLite database configuration with WAL mode and foreign-key enforcement
- Initial SQLAlchemy persistence models
- Alembic migration setup
- Unit tests for settings, database initialization, and model constraints
- Database-backed job creation, dependencies, claiming, heartbeats, retries, stale recovery, cancellation, pausing, and a minimal local CLI
- Immutable content-version services, approval records, prompt-template metadata, deterministic hashing, safe filesystem storage, and content-addressed cache lookup/write/verification
- Manual local research source import, canonical URL deduplication, UTF-8 source snapshots, duplicate-content detection, deterministic source classification, research notes, claim-source linking, claim verification rules, research briefs, source reports, readiness evaluation, queue handlers, and CLI commands
- Local FastAPI/Jinja operations dashboard for projects, research output, approvals, jobs, friendly status labels, derived progress, small HTMX-style polling fragments, and CSRF-protected form actions
- Local deterministic script generation, fact-check reports, strict scene-plan validation, scene storage, script/scene dashboard views, and queue-compatible handlers
- Provider-neutral image and voice interfaces, deterministic fake image and voice providers, manual image/audio import, per-scene asset planning, cache reuse, asset review statuses, asset dashboard visibility, and asset workflow/CLI handlers
- Provider-neutral video composition, local FFmpeg preview rendering when FFmpeg is installed, render planning and verification, render review statuses, render dashboard visibility, and render workflow/CLI handlers
- Strict YouTube metadata documents, deterministic fake metadata generation, thumbnail concept documents, deterministic fake thumbnail PNG generation, manual metadata/thumbnail import, thumbnail verification/review, dashboard metadata/thumbnail pages, and packaging workflow/CLI handlers
- Local rights records, deterministic claim/script/metadata/thumbnail checks, reused-content risk checks, AI disclosure decisions, persisted publishing-gate reports, and a dashboard safety view
- Atomic workflow transitions with persisted-evidence validation, approved-asset immutability, signature-checked atomic imports, approved asset planning defaults, and provider-complete script fingerprints
- Optional local Ollama text generation for scripts, scene plans, metadata, thumbnail concepts, and read-only safety summaries, with strict schemas and typed failures
- Optional local ComfyUI scene-image generation with local-only HTTP controls, fixed workflow injection, verified output storage, cache reuse, and pending human review
- Optional offline Piper narration with pronunciation preparation, verified/normalized WAV output, scene-level cache reuse, safe audio preview, and mandatory human approval before rendering

The optional providers do not change deterministic defaults. Telegram, publishing, analytics, Shorts, automated search, and scraping remain unstarted.

## Setup

Use Python 3.12 where available.

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -e ".[dev]"
```

Copy the example environment file if you want local overrides:

```bash
copy .env.example .env
```

Or use the local PowerShell launcher to install dependencies, migrate the database, create the
default channel/project, and start the dashboard:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1 -Setup -BootstrapProject
```

For Ollama after installing it and pulling the configured model:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1 -Provider ollama -Model qwen3:8b -BootstrapProject
```

## Database

Create or update the local SQLite database with Alembic:

```bash
alembic upgrade head
```

The default database path is `data/database/ai_media_os.db`.

## Start A Local Project

Create the channel and first video project without editing SQLite directly:

```powershell
$CHANNEL_ID = python -m ai_media_os.cli create-channel --name "AI & Future" --slug "ai-future" --niche "AI" --language en
$PROJECT_ID = python -m ai_media_os.cli create-project --channel-id $CHANNEL_ID --working-title "AI Reliability" --topic "Reliable local AI media workflows" --target-duration-seconds 420
python -m ai_media_os.cli list-channels
python -m ai_media_os.cli list-projects --channel-id $CHANNEL_ID
```

Continue the same project through the documented local stages below: import and approve research,
generate and approve a script and scene plan, plan/generate/review assets, compose and approve a
render, generate and approve metadata and a thumbnail, then run the publishing gate. Every stage
uses the same `$PROJECT_ID`; publishing remains manual.

## Dashboard

Run the local-only operations dashboard:

```bash
python -m ai_media_os.web
```

or:

```bash
ai-media-os dashboard
```

Default URL: `http://127.0.0.1:8000`

Do not expose the dashboard beyond localhost until authentication is added.

## Optional Local Ollama

The default text provider is still `fake`; no Ollama installation is required for tests or the
normal deterministic demo. To opt into local LLM generation:

```powershell
ollama pull qwen3:8b
ollama serve
python -m ai_media_os.cli check-llm-provider --provider ollama --model qwen3:8b
python -m ai_media_os.cli test-llm-generate --provider ollama --model qwen3:8b --prompt "Explain local AI in one sentence."
python -m ai_media_os.cli generate-script --project-id $PROJECT_ID --provider ollama --model qwen3:8b
python -m ai_media_os.cli generate-scene-plan --project-id $PROJECT_ID --provider ollama --model qwen3:8b
python -m ai_media_os.cli generate-metadata --project-id $PROJECT_ID --provider ollama --model qwen3:8b
python -m ai_media_os.cli generate-thumbnail-concept --project-id $PROJECT_ID --provider ollama --model qwen3:8b
```

See `docs/architecture/local-llm-ollama.md` for provider behavior and limitations.

## Optional Local ComfyUI

Install and start ComfyUI manually, add a compatible local checkpoint, and set
`AI_MEDIA_OS_COMFYUI_DEFAULT_CHECKPOINT`. No model or ComfyUI files are downloaded by this project.

```powershell
python -m ai_media_os.cli check-image-provider --provider comfyui --model your-checkpoint.safetensors
python -m ai_media_os.cli generate-scene-image --scene-id $SCENE_ID --provider comfyui --model your-checkpoint.safetensors --seed 42
python -m ai_media_os.cli verify-asset-file IMAGE_ASSET_ID
```

The server is restricted to localhost by default. Generated images are stored as pending-review,
synthetic assets and remain subject to the rights and publishing gate. See
`docs/architecture/comfyui-image-provider.md`.

## Optional Local Piper Narration

Install Piper and an ONNX voice model manually, then configure the executable, model, optional JSON
config, voice ID, language, and sample rate in `.env`.

```powershell
python -m ai_media_os.cli check-voice-provider --provider piper --model-path C:\models\voice.onnx --voice en_US-lessac-medium
python -m ai_media_os.cli generate-scene-narration --scene-id $SCENE_ID --provider piper --model-path C:\models\voice.onnx --voice en_US-lessac-medium --pronunciation "API=A P I"
python -m ai_media_os.cli generate-project-narration --project-id $PROJECT_ID --provider piper --model-path C:\models\voice.onnx --voice en_US-lessac-medium
python -m ai_media_os.cli list-narration-assets --project-id $PROJECT_ID
python -m ai_media_os.cli verify-audio-asset NARRATION_ASSET_ID
```

Narration is generated per scene, normalized, stored as pending review, and playable on the project
asset dashboard. Rendering always requires approved narration. See
`docs/architecture/local-tts-provider.md` and `docs/architecture/narration-pipeline.md`.

## Local Asset Demo

After a project has an approved scene plan and at least one stored scene, Milestone 6 can generate local fake media assets that are visible in the filesystem and dashboard.

Use PowerShell variables for the existing project and scene:

```powershell
$PROJECT_ID = "existing-project-id"
$SCENE_PLAN_VERSION_ID = "approved-scene-plan-version-id"
$SCENE_ID = "existing-scene-id"
```

Generate planned scene asset records:

```powershell
python -m ai_media_os.cli plan-scene-assets --project-id $PROJECT_ID --scene-plan-version-id $SCENE_PLAN_VERSION_ID
```

Generate one real PNG placeholder and one valid WAV narration placeholder using the fake providers:

```powershell
python -m ai_media_os.cli generate-scene-image --scene-id $SCENE_ID --width 1280 --height 720 --seed 42
python -m ai_media_os.cli generate-scene-voice --scene-id $SCENE_ID --voice-name ai-future-neutral --language en --seed 42
```

List and verify the generated assets:

```powershell
python -m ai_media_os.cli list-assets --project-id $PROJECT_ID
python -m ai_media_os.cli verify-asset-file IMAGE_ASSET_ID
python -m ai_media_os.cli verify-asset-file VOICE_ASSET_ID
```

These commands do not require real ComfyUI or real TTS. The fake image provider writes a viewable PNG under `data/projects/{project_id}/images/scene_001/visual_v001.png`.
The fake voice provider writes a valid WAV file under `data/projects/{project_id}/audio/scene_001/narration_v001.wav`.

Start the dashboard and open the project asset page:

```powershell
python -m ai_media_os.web
```

Then visit `http://127.0.0.1:8000/projects/{project_id}/assets`.

## Local Render Demo

After the local asset demo has produced one image and one narration asset for every scene in an approved scene plan, Milestone 7 can plan and compose a local preview render.

FFmpeg must be installed and available as `ffmpeg`, or configured with `AI_MEDIA_OS_FFMPEG_PATH`. FFprobe is optional and can be configured with `AI_MEDIA_OS_FFPROBE_PATH`.

```powershell
$PROJECT_ID = "existing-project-id"
$SCENE_PLAN_VERSION_ID = "approved-scene-plan-version-id"

python -m ai_media_os.cli plan-render --project-id $PROJECT_ID --scene-plan-version-id $SCENE_PLAN_VERSION_ID
python -m ai_media_os.cli compose-video --project-id $PROJECT_ID
python -m ai_media_os.cli list-renders --project-id $PROJECT_ID
python -m ai_media_os.cli verify-render --project-id $PROJECT_ID
python -m ai_media_os.web
```

The render output is written under `data/projects/{project_id}/renders/render_v001.mp4` and is visible at `http://127.0.0.1:8000/projects/{project_id}/renders`.

If FFmpeg is missing, `compose-video` fails with a clear message and stores the render error. Tests use a fake video composer, but production CLI composition does not silently create fake MP4 output.

## Local Metadata And Thumbnail Demo

After a project has an approved script, approved scene plan, and at least one rendered or approved render record, Milestone 8 can generate a reviewable YouTube metadata draft and a visible fake thumbnail PNG.

```powershell
$PROJECT_ID = "existing-project-id"
$RENDER_ID = "rendered-render-id"

python -m ai_media_os.cli generate-metadata --project-id $PROJECT_ID --render-id $RENDER_ID --keyword-hints "AI,Future"
python -m ai_media_os.cli list-metadata --project-id $PROJECT_ID
```

Use the generated metadata version ID to create a thumbnail concept and fake PNG thumbnail:

```powershell
$METADATA_VERSION_ID = "metadata-content-version-id"

python -m ai_media_os.cli generate-thumbnail-concept --project-id $PROJECT_ID --metadata-version-id $METADATA_VERSION_ID
python -m ai_media_os.cli generate-thumbnail --project-id $PROJECT_ID --metadata-version-id $METADATA_VERSION_ID --width 1280 --height 720 --seed 42
python -m ai_media_os.cli list-thumbnails --project-id $PROJECT_ID
python -m ai_media_os.cli verify-thumbnail-file THUMBNAIL_ASSET_ID
```

The fake thumbnail provider writes a real PNG under `data/projects/{project_id}/thumbnails/thumbnail_v001.png`. Start the dashboard and open:

```powershell
python -m ai_media_os.web
```

Then visit `http://127.0.0.1:8000/projects/{project_id}/metadata` and `http://127.0.0.1:8000/projects/{project_id}/thumbnail`.

## Local Safety And Publishing Gate Demo

After metadata and thumbnail are approved, Milestone 8.5 can run the local safety and rights checks and create a publishing-gate report.

```powershell
$PROJECT_ID = "existing-project-id"

python -m ai_media_os.cli check-asset-rights --project-id $PROJECT_ID
python -m ai_media_os.cli check-claims --project-id $PROJECT_ID
python -m ai_media_os.cli check-script-safety --project-id $PROJECT_ID
python -m ai_media_os.cli check-metadata-safety --project-id $PROJECT_ID
python -m ai_media_os.cli check-thumbnail-safety --project-id $PROJECT_ID
python -m ai_media_os.cli check-reused-content --project-id $PROJECT_ID
python -m ai_media_os.cli decide-ai-disclosure --project-id $PROJECT_ID
python -m ai_media_os.cli run-publishing-gate --project-id $PROJECT_ID
python -m ai_media_os.cli show-safety-report --project-id $PROJECT_ID
python -m ai_media_os.cli list-safety-findings --project-id $PROJECT_ID
```

Open `http://127.0.0.1:8000/projects/{project_id}/safety` to review the gate decision, findings, and rights records.

## Verification

```bash
pytest
ruff check .
ruff format --check .
mypy src
alembic upgrade head
```

## Scope

This repository intentionally does not include Telegram, voice cloning, cloud TTS, publishing automation, analytics, automated web search, scraping, AI research generation, Redis, Celery, Docker, Kubernetes, React, Next.js, WebSockets, authentication, or a cloud deployment. ComfyUI, Piper, checkpoints, and voice models must be installed separately.

The implemented local Content Safety and Rights Engine is documented in `docs/architecture/content-safety-rights-engine.md`. It provides risk-reduction checks, not legal advice or a platform-compliance guarantee.
