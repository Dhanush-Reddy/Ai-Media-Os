# AI Media OS

AI Media OS is a local-first foundation for producing one monetization-safe YouTube channel before expanding into broader automation.

The current implementation covers **Milestone 1: Project Foundation**, **Milestone 2: Database-Backed Job Queue**, **Milestone 3: Content Versioning and Cache**, **Milestone 4: Local Research Pipeline**, and **Milestone 4.5: Minimal Operations Dashboard**:

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

The next planned task is Milestone 5. Do not begin script generation, scene planning, image generation, TTS, FFmpeg rendering, Telegram, publishing, analytics, Shorts, automated search, scraping, AI generation, or Content Safety implementation until explicitly scoped.

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

## Verification

```bash
pytest
ruff check .
ruff format --check .
mypy src
alembic upgrade head
```

## Scope

This repository intentionally does not yet include Telegram, ComfyUI, local language models, text-to-speech, FFmpeg rendering, publishing automation, analytics, automated web search, scraping, AI research generation, Redis, Celery, Docker, Kubernetes, React, Next.js, WebSockets, authentication, or a cloud deployment.

The planned Content Safety and Rights Engine is documented in `docs/architecture/content-safety-rights-engine.md`; it is not implemented yet.
