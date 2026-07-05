# AI Media OS

AI Media OS is a local-first foundation for producing one monetization-safe YouTube channel before expanding into broader automation.

The current implementation covers **Milestone 1: Project Foundation**, **Milestone 2: Database-Backed Job Queue**, and **Milestone 3: Content Versioning and Cache** only:

- Python project configuration
- Environment-based settings
- Structured logging setup
- SQLite database configuration with WAL mode and foreign-key enforcement
- Initial SQLAlchemy persistence models
- Alembic migration setup
- Unit tests for settings, database initialization, and model constraints
- Database-backed job creation, dependencies, claiming, heartbeats, retries, stale recovery, cancellation, pausing, and a minimal local CLI
- Immutable content-version services, approval records, prompt-template metadata, deterministic hashing, safe filesystem storage, and content-addressed cache lookup/write/verification

The next planned task is the Milestone 3 audit in `docs/tasks/milestone-3-audit.md`. Do not begin Milestone 4 until that audit is complete.

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

## Verification

```bash
pytest
ruff check .
ruff format --check .
mypy src
alembic upgrade head
```

## Scope

This repository intentionally does not yet include Telegram, ComfyUI, local language models, text-to-speech, FFmpeg rendering, content-addressed cache workflows, approval workflows, publishing automation, analytics, Redis, Celery, Docker, Kubernetes, or a frontend dashboard.

The planned Content Safety and Rights Engine is documented in `docs/architecture/content-safety-rights-engine.md`; it is not implemented yet.
