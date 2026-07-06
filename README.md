# AI Media OS

AI Media OS is a local-first foundation for producing one monetization-safe YouTube channel before expanding into broader automation.

The current implementation covers Milestones 1 through 6:

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

The next planned task is Milestone 7. Do not begin FFmpeg rendering, thumbnail generation, Telegram, publishing, analytics, Shorts, real ComfyUI, real TTS, automated search, scraping, or Content Safety implementation until explicitly scoped.

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

## Database

Create or update the local SQLite database with Alembic:

```bash
alembic upgrade head
```

The default database path is `data/database/ai_media_os.db`.

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

## Verification

```bash
pytest
ruff check .
ruff format --check .
mypy src
alembic upgrade head
```

## Scope

This repository intentionally does not yet include Telegram, real ComfyUI integration, real local TTS integration, local language models, FFmpeg rendering, publishing automation, analytics, automated web search, scraping, AI research generation, Redis, Celery, Docker, Kubernetes, React, Next.js, WebSockets, authentication, or a cloud deployment.

The planned Content Safety and Rights Engine is documented in `docs/architecture/content-safety-rights-engine.md`; it is not implemented yet.
