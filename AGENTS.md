# AGENTS.md

This file contains permanent instructions for AI coding agents working on the AI Media OS repository.

Read this file before making any changes.

Also read:

* `docs/MASTER_PLAN.md`
* `docs/MVP_SCOPE.md`

---

## 1. Primary Goal

The primary business goal is to generate revenue from one high-quality YouTube channel before building a fully autonomous multi-channel platform.

The first channel is:

> AI & Future

Do not prioritize platform complexity over content quality and revenue validation.

---

## 2. Core Constraints

* Zero recurring software cost initially
* No paid APIs unless explicitly approved
* Local-first execution
* Target hardware is an RTX 4050 Laptop GPU with 16 GB RAM
* Python-first implementation
* SQLite initially
* Local filesystem storage
* Manual publishing initially
* Human approval is required for important decisions
* Copyright and monetization safety are mandatory

---

## 3. Development Philosophy

Build the smallest useful system.

Work in small, testable milestones.

Do not implement the entire platform in one task.

Avoid speculative infrastructure.

Do not add components merely because they may be useful later.

Prefer:

* Simple modules
* Clear interfaces
* Replaceable providers
* Explicit state
* Reliable recovery
* Strong tests
* Good documentation

Avoid:

* Premature microservices
* Kubernetes
* Distributed systems
* Unnecessary Redis usage
* Unnecessary message brokers
* Heavy dashboards
* Complex abstractions without current use
* Paid service dependencies

---

## 4. Required Engineering Principles

The codebase must be:

* Provider agnostic
* Queue driven
* Cache first
* Versioned
* Configuration driven
* Modular
* Typed
* Testable
* Observable
* Retry safe
* Resource aware
* Copyright aware

---

## 5. Coding Standards

Use:

* Python type hints
* Pydantic for validated schemas and settings
* SQLAlchemy for persistence
* Alembic for migrations
* Pytest for testing
* Ruff for linting and formatting
* Mypy for static type checking where practical
* Structured logging

Requirements:

* Use descriptive names.
* Keep functions focused.
* Prefer composition over inheritance.
* Avoid global mutable state.
* Do not use broad `except Exception` blocks without re-raising or logging context.
* Do not silently ignore errors.
* Do not hardcode secrets.
* Do not hardcode machine-specific absolute paths.
* Do not mix domain logic with provider-specific code.
* Do not overwrite approved content.
* Do not delete user-generated project data without an explicit command.

---

## 6. Architecture Boundaries

Recommended layers:

```text
domain
application
infrastructure
providers
workers
api
media
schemas
storage
utils
```

### Domain

Contains:

* Entities
* Value objects
* Enums
* Domain rules
* State-transition rules

The domain layer must not depend directly on:

* FastAPI
* Telegram
* ComfyUI
* FFmpeg
* SQLAlchemy sessions
* External APIs

### Application

Contains:

* Use cases
* Service orchestration
* Job creation
* Approval flow
* Version creation
* Cache coordination

### Infrastructure

Contains:

* Database
* Repositories
* File storage
* Logging
* Configuration
* Queue persistence

### Providers

Contains adapters for:

* Text generation
* Search
* Research extraction
* Image generation
* Voice generation
* Messaging
* Publishing

Business logic must depend on provider interfaces, not specific providers.

### Workers

Contains:

* Job claiming
* Execution
* Retries
* Heartbeats
* Resource locks
* Failure handling

### Media

Contains:

* Timeline generation
* Audio processing
* Subtitle processing
* FFmpeg composition
* Thumbnail composition

---

## 7. Provider Rules

Every replaceable external capability must have an interface.

Examples:

```python
class TextGenerationProvider:
    def generate(self, prompt: str, **options) -> str:
        ...
```

```python
class ImageGenerationProvider:
    def generate(self, prompt: str, **options) -> GeneratedAsset:
        ...
```

```python
class VoiceGenerationProvider:
    def synthesize(self, text: str, **options) -> GeneratedAsset:
        ...
```

```python
class SearchProvider:
    def search(self, query: str, limit: int) -> list[SearchResult]:
        ...
```

Do not call provider-specific code directly from domain or application services.

---

## 8. Database Rules

Use SQLite initially.

Enable:

* WAL mode
* Foreign keys
* Safe transaction boundaries

All schema changes must use Alembic migrations.

Do not rely only on automatic table creation in production code.

Store timestamps in UTC.

Use immutable identifiers.

Prefer UUIDs unless a simpler identifier is clearly justified.

Important content must be versioned.

---

## 9. Versioning Rules

Never overwrite:

* Approved research briefs
* Approved scripts
* Approved scene plans
* Approved thumbnails
* Approved final renders

A revision must create a new record.

Each version should store:

* Version number
* Parent version
* Prompt version
* Provider
* Model
* Input hashes
* Output hash
* Creation timestamp
* Approval status

---

## 10. Queue Rules

Everything expensive or asynchronous should become a job.

Supported states:

```text
PENDING
READY
RUNNING
WAITING_FOR_DEPENDENCY
WAITING_FOR_APPROVAL
RETRYING
COMPLETED
FAILED
CANCELLED
PAUSED
```

Rules:

* Validate state transitions.
* Use atomic job claiming.
* Prevent two workers from claiming the same job.
* Store attempt counts.
* Store failure reasons.
* Use retry limits.
* Waiting jobs must not consume worker resources.
* Jobs with incomplete dependencies must not run.
* Completed jobs must not run again unless a new job is created.
* Failed jobs must preserve diagnostic information.

---

## 11. Resource Scheduling Rules

Jobs must declare a resource class.

Supported classes:

```text
CPU_LIGHT
CPU_HEAVY
GPU_LIGHT
GPU_HEAVY
NETWORK
MANUAL
```

Only one GPU-heavy job should run at a time on the target laptop.

Do not assume unlimited RAM or VRAM.

Prefer sequential GPU processing.

---

## 12. Cache Rules

Before expensive generation:

1. Normalize inputs.
2. Calculate a deterministic cache key.
3. Check for an existing valid result.
4. Reuse the result when safe.
5. Generate only when missing.
6. Store generation metadata.
7. Store file hashes.
8. Update usage timestamps.

Cache keys should consider:

* Provider
* Model
* Model version
* Prompt
* Prompt version
* Settings
* Seed
* Input file hashes

Do not reuse results when important inputs differ.

---

## 13. File Storage Rules

Use project-relative configurable paths.

Recommended project structure:

```text
data/projects/{project_id}/
├── research/
├── scripts/
├── scenes/
├── images/
├── audio/
├── captions/
├── thumbnails/
├── renders/
├── metadata/
└── reports/
```

Use predictable versioned filenames.

Do not store large binary files directly in SQLite.

Store paths and metadata in the database.

---

## 14. Copyright Rules

Copyright and monetization safety are mandatory.

Every external asset must store:

* Source URL
* Creator where known
* License
* Commercial-use status
* Attribution requirement
* Retrieval timestamp
* File hash

Supported safety states:

```text
SAFE
ATTRIBUTION_REQUIRED
EDITORIAL_ONLY
UNKNOWN
BLOCKED
```

Rules:

* Do not automatically place `UNKNOWN` assets into final videos.
* Never use `BLOCKED` assets.
* Include required attribution.
* Prefer original and generated assets.
* Do not download and use arbitrary search-result images without licensing checks.

---

## 15. Approval Rules

Required approvals during the MVP:

* Script
* Thumbnail
* Final video
* Publishing

Publishing must remain manual unless explicitly changed in the project scope.

Lack of user response must not cause automatic publishing.

Approval feedback must be stored.

A request for changes must create a new content version.

---

## 16. Testing Requirements

Every milestone must include tests.

At minimum, test:

* Database initialization
* Model constraints
* State transitions
* Job claiming
* Retry logic
* Dependencies
* Cache-key generation
* Content versioning
* Approval behavior
* Scene-schema validation
* File-path generation

Tests should not require paid services.

External providers should be mocked or replaced with fake providers.

---

## 17. Documentation Requirements

When making a meaningful architectural decision:

* Create or update an architecture decision record in `docs/decisions/`.
* Explain the decision.
* Explain alternatives considered.
* Explain consequences.

Keep documentation concise and current.

Do not allow documentation to describe behavior that the code does not implement.

---

## 18. Security Rules

* Never commit secrets.
* Use environment variables.
* Provide `.env.example`.
* Do not log API keys, tokens or passwords.
* Validate external file paths.
* Prevent path traversal.
* Sanitize subprocess arguments.
* Do not construct unsafe shell commands.
* Use subprocess argument arrays where possible.
* Treat downloaded content as untrusted.

---

## 19. Command Execution Rules

Before completing a task:

* Run relevant tests.
* Run linting.
* Run formatting checks.
* Run type checks when configured.
* Report failures honestly.
* Do not claim success when commands fail.

When adding dependencies:

* Explain why they are required.
* Prefer maintained, lightweight dependencies.
* Avoid introducing overlapping libraries.

---

## 20. Scope Control

Before implementing a feature, verify that it belongs to the current milestone.

Do not implement future milestones unless they are required for the current task.

Examples:

* Do not build Telegram during database setup.
* Do not build a React dashboard during queue development.
* Do not add Redis while a database-backed queue is sufficient.
* Do not add paid API integrations during local provider work.
* Do not build multi-channel scheduling before one channel works.

---

## 21. Required Task Completion Report

At the end of each coding task, report:

* Summary of changes
* Files created
* Files modified
* Commands run
* Tests run
* Test results
* Architectural decisions
* Assumptions
* Known limitations
* Recommended next task

Do not report internal chain-of-thought reasoning.

Provide concise engineering explanations.

---

## 22. AI Provider

The autonomous reviewer uses NVIDIA NIM.

Required GitHub secret:

* `NVIDIA_API_KEY`

Optional GitHub variables:

* `NVIDIA_BASE_URL`
* `NVIDIA_MODEL`

The reviewer must fail closed when the API is unavailable, the response cannot
be parsed, the response schema is invalid, or the model does not return an
explicit approval decision.

---

## 23. Initial Task

The first implementation task is Milestone 1 only.

Complete:

1. Repository structure
2. Python project configuration
3. Environment-based settings
4. Structured logging
5. SQLite configuration with WAL mode
6. Initial SQLAlchemy models
7. Alembic setup
8. Initial migration
9. Unit tests
10. Architecture decision record

Do not implement:

* Telegram
* ComfyUI
* TTS
* Local language models
* FFmpeg rendering
* Dashboard
* Shorts
* Publishing
* Analytics
