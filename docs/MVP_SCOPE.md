# AI Media OS — MVP Scope

**Version:** v0.1
**Status:** Approved for initial development
**Primary Objective:** Produce one complete, high-quality, monetization-safe YouTube video using a local-first pipeline.

---

## 1. MVP Goal

The MVP must prove that the system can take a topic and produce a reviewable YouTube video package.

The package should include:

* Research brief
* Verified claims
* Script
* Scene plan
* Generated or approved visuals
* Voice-over
* Captions
* Thumbnail options
* Final video
* YouTube metadata
* Copyright and source report

The MVP does not need to be fully autonomous.

Human review is expected.

---

## 2. Business Priority

The main priority is revenue generation.

The MVP should support the launch of the first channel:

> AI & Future

The first channel should target:

* One long-form video per week
* Two or three Shorts generated from each completed long video
* Manual publishing
* Human approval before release

---

## 3. MVP Constraints

* Zero recurring software cost
* No paid APIs
* Local-first execution
* RTX 4050 Laptop GPU
* 16 GB RAM
* Python-first implementation
* SQLite database
* Local filesystem storage
* Manual publishing
* Telegram approval added after the first end-to-end pipeline works
* No distributed infrastructure
* No unnecessary dashboard complexity

---

## 4. MVP Success Criteria

The MVP is successful when it can:

1. Create a new video project.
2. Accept a topic manually.
3. Store project data in SQLite.
4. collect or import research sources.
5. Extract useful research notes.
6. Store claims with supporting sources.
7. Produce a script version.
8. Allow the script to be approved or revised.
9. Convert the approved script into validated scene JSON.
10. Generate or attach visual assets for each scene.
11. Generate local voice-over.
12. Build a synchronized timeline.
13. Add subtitles.
14. Render a complete video using FFmpeg.
15. Generate at least two thumbnail options.
16. Export title, description, chapters and tags.
17. Export a source and licensing report.
18. Avoid regenerating identical cached outputs.
19. Recover safely from failed jobs.
20. Preserve approved versions.

---

## 5. MVP Workflow

```text
Create Project
    ↓
Enter Topic
    ↓
Collect Research
    ↓
Create Research Brief
    ↓
Create Claim Table
    ↓
Generate Script
    ↓
Human Approval
    ↓
Create Scene Plan
    ↓
Generate or Attach Visuals
    ↓
Generate Voice
    ↓
Build Timeline
    ↓
Generate Captions
    ↓
Render Preview
    ↓
Generate Thumbnails
    ↓
Human Approval
    ↓
Render Final Video
    ↓
Export Metadata and Copyright Report
    ↓
Manual Upload
```

---

## 6. MVP Approval Points

Required approvals:

* Script
* Thumbnail
* Final video
* Publishing

Optional approval:

* Topic
* Research brief
* Voice selection

Automatic stages:

* Scene splitting
* Cache checking
* Caption generation
* Timeline generation
* File organization
* Metadata draft generation
* Source report generation

The system must never publish automatically during the MVP.

---

## 7. Initial Repository Structure

```text
ai-media-os/
├── AGENTS.md
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── docs/
│   ├── MASTER_PLAN.md
│   ├── MVP_SCOPE.md
│   ├── architecture/
│   └── decisions/
├── src/
│   └── ai_media_os/
│       ├── __init__.py
│       ├── api/
│       ├── application/
│       ├── domain/
│       ├── infrastructure/
│       ├── providers/
│       ├── workers/
│       ├── media/
│       ├── schemas/
│       ├── storage/
│       └── utils/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── data/
│   ├── database/
│   ├── cache/
│   ├── projects/
│   ├── assets/
│   ├── exports/
│   └── logs/
├── prompts/
│   ├── research/
│   ├── script/
│   ├── fact_check/
│   ├── scene_planning/
│   ├── thumbnails/
│   └── metadata/
└── scripts/
```

---

## 8. Initial Technical Stack

### Core

* Python 3.12 or a stable compatible version
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic
* SQLite in WAL mode

### Testing

* Pytest
* Pytest-cov
* Ruff
* Mypy

### Media

* FFmpeg
* FFprobe

### Local Providers

* ComfyUI for image workflows
* Local TTS provider
* Local or manually assisted text-generation provider

### Approval

* CLI approval first
* Telegram approval after core pipeline reliability

---

## 9. Initial Domain Entities

### Channel

Represents a media channel configuration.

Fields:

* id
* name
* slug
* niche
* language
* status
* brand configuration
* content configuration
* created_at
* updated_at

---

### VideoProject

Represents one long-form content project.

Fields:

* id
* channel_id
* title
* working_title
* topic
* description
* status
* target_duration_seconds
* priority
* created_at
* updated_at

---

### ContentVersion

Stores versioned text or structured content.

Possible types:

* research_brief
* script
* scene_plan
* metadata
* fact_check_report

Fields:

* id
* video_project_id
* content_type
* version_number
* parent_version_id
* content
* content_format
* prompt_version
* provider
* model
* status
* content_hash
* created_at

---

### Approval

Stores approval decisions.

Fields:

* id
* video_project_id
* content_version_id
* approval_type
* status
* reviewer
* feedback
* requested_at
* responded_at

Possible statuses:

* pending
* approved
* rejected
* changes_requested
* expired

---

### Source

Stores a research source.

Fields:

* id
* video_project_id
* url
* title
* publisher
* source_type
* authority_tier
* publication_date
* retrieved_at
* content_hash
* local_snapshot_path
* status

---

### Claim

Stores a factual claim.

Fields:

* id
* video_project_id
* claim_text
* importance
* confidence
* verification_status
* valid_until
* created_at
* updated_at

---

### ClaimSource

Links claims to sources.

Fields:

* id
* claim_id
* source_id
* support_type
* quoted_excerpt
* source_location

---

### Scene

Stores one scene from the approved scene plan.

Fields:

* id
* video_project_id
* scene_plan_version_id
* scene_number
* narration
* duration_seconds
* visual_type
* image_prompt
* camera_motion
* transition
* caption_style
* status

---

### Asset

Stores all media assets.

Fields:

* id
* video_project_id
* scene_id
* asset_type
* file_path
* mime_type
* provider
* model
* prompt
* seed
* width
* height
* duration_seconds
* content_hash
* license_status
* source_url
* created_at

Possible asset types:

* image
* audio
* music
* sound_effect
* subtitle
* thumbnail
* video
* chart
* screenshot

---

### Job

Represents background work.

Fields:

* id
* video_project_id
* job_type
* status
* priority
* payload
* result
* attempts
* max_attempts
* dependency_count
* resource_class
* scheduled_at
* started_at
* completed_at
* error_message
* created_at
* updated_at

---

### JobDependency

Links jobs.

Fields:

* id
* job_id
* depends_on_job_id

---

### CacheEntry

Stores reusable generated results.

Fields:

* id
* cache_key
* provider
* model
* operation
* input_hash
* output_hash
* output_path
* metadata
* created_at
* last_used_at

---

### PromptTemplate

Stores prompt versions.

Fields:

* id
* name
* category
* version
* template_text
* status
* created_at

---

### Render

Stores video render attempts.

Fields:

* id
* video_project_id
* render_type
* version_number
* status
* output_path
* duration_seconds
* resolution
* file_size
* created_at

Possible render types:

* preview
* final
* short
* thumbnail_preview

---

## 10. Job States

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

State transitions must be validated.

A completed job should not return to running.

A failed job may become retrying if attempts remain.

A waiting-for-approval job should not consume worker resources.

---

## 11. Resource Classes

```text
CPU_LIGHT
CPU_HEAVY
GPU_LIGHT
GPU_HEAVY
NETWORK
MANUAL
```

Initial limits:

```yaml
CPU_LIGHT: 3
CPU_HEAVY: 2
GPU_LIGHT: 1
GPU_HEAVY: 1
NETWORK: 3
MANUAL: 0
```

`MANUAL` jobs wait for human action.

---

## 12. Scene JSON Schema

Example:

```json
{
  "project_id": "project-id",
  "script_version": 2,
  "scenes": [
    {
      "scene_number": 1,
      "narration": "Artificial intelligence is changing faster than most people realize.",
      "duration_seconds": 6.5,
      "visual_type": "generated_image",
      "visual_description": "A cinematic global network of AI data centers",
      "image_prompt": "Cinematic documentary image of futuristic AI data centers connected across the globe, realistic, highly detailed, dramatic lighting, 16:9",
      "negative_prompt": "text, watermark, logo, distorted objects",
      "camera_motion": "slow_zoom_in",
      "transition": "fade",
      "sound_effect": null,
      "caption_style": "standard",
      "source_claim_ids": []
    }
  ]
}
```

Scene plans must fail validation when:

* Scene numbers are duplicated
* Duration is zero or negative
* Narration is empty
* Unsupported visual types are used
* Required fields are missing

---

## 13. File Storage Structure

```text
data/projects/{project_id}/
├── project.json
├── research/
│   ├── sources/
│   ├── snapshots/
│   └── briefs/
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

Generated files should use predictable names.

Example:

```text
script_v001.md
scene_plan_v001.json
voice_scene_001_v001.wav
thumbnail_option_a_v001.png
preview_v001.mp4
final_v001.mp4
```

---

## 14. Caching Rules

Before generation:

1. Normalize inputs.
2. Calculate cache key.
3. Check for a valid cache entry.
4. Reuse the result when available.
5. Generate only when missing.
6. Save result and metadata.
7. Update last-used timestamp.

Approved outputs should never be silently replaced by a cache hit from different inputs.

---

## 15. Prompt Versioning

Prompts should be stored in files during the MVP.

Example:

```text
prompts/script/long_form_v001.md
prompts/research/brief_v001.md
prompts/scene_planning/documentary_v001.md
```

Each generated output must store:

* Prompt name
* Prompt version
* Provider
* Model
* Generation settings

Prompts should be treated like source code.

---

## 16. Copyright Requirements

Each external asset must have:

* Source URL
* Creator where known
* License
* Commercial-use status
* Attribution requirement
* Retrieval date
* Local file hash

Possible statuses:

```text
SAFE
ATTRIBUTION_REQUIRED
EDITORIAL_ONLY
UNKNOWN
BLOCKED
```

Rules:

* `SAFE` assets may enter final renders.
* `ATTRIBUTION_REQUIRED` assets may enter only when attribution is included.
* `EDITORIAL_ONLY` assets require manual review.
* `UNKNOWN` assets must not enter final renders automatically.
* `BLOCKED` assets must never enter final renders.

---

## 17. MVP Milestones

### Milestone 1 — Project Foundation

Deliverables:

* Repository structure
* Python project setup
* Configuration system
* Structured logging
* SQLite connection
* Database migrations
* Initial domain models
* Tests

Do not add AI integrations yet.

---

### Milestone 2 — Job Queue

Deliverables:

* Job model
* Dependency model
* Job claiming
* Retry logic
* State transition validation
* Resource-class locking
* Worker heartbeat
* Failure recovery
* Tests

---

### Milestone 3 — Content Versioning and Cache

Deliverables:

* Content versions
* Approval records
* Prompt version metadata
* Content hashing
* Cache entries
* Reuse logic
* Tests

---

### Milestone 3 Review - Audit Content Versioning and Cache

Status: planned as the next task before Milestone 4.

Deliverables:

* Audit completed Milestone 3 implementation against `AGENTS.md`, `docs/MASTER_PLAN.md`, `docs/MVP_SCOPE.md`, and `docs/decisions/0003-content-versioning-approval-cache.md`
* Verify content-version immutability, approval consistency, prompt-template versioning, deterministic hashing, filesystem security, cache integrity, migrations, and test coverage
* Add or improve tests only where confirmed coverage is missing
* Fix only confirmed Milestone 3 defects
* Run the full verification command set, including pytest, Ruff, Mypy, Alembic upgrade/downgrade/upgrade, and `alembic check`

Detailed task checklist: `docs/tasks/milestone-3-audit.md`.

Do not begin Milestone 4 during this review.

---

### Milestone 4 — Research Pipeline

Deliverables:

* Manual URL import
* Source storage
* Source classification
* Text extraction
* Research brief generation interface
* Claim tracking
* Fact-check report
* Source report

Online search automation may be added later.

---

### Milestone 5 — Script and Scene Planning

Deliverables:

* Script-generation provider interface
* Script versions
* CLI approval
* Scene-plan schema
* Scene-plan validation
* Scene storage

---

### Milestone 6 — Image and Voice Providers

Deliverables:

* Image-provider interface
* ComfyUI adapter
* TTS-provider interface
* Local TTS adapter
* Per-scene audio generation
* Asset metadata
* Cache integration

---

### Milestone 7 — Video Composition

Deliverables:

* Timeline schema
* Audio alignment
* FFmpeg composition
* Basic motion effects
* Transitions
* Subtitle generation
* Preview rendering
* Final rendering
* Quality checks

---

### Milestone 8 — Thumbnail and Metadata

Deliverables:

* Thumbnail templates
* AI visual integration
* Programmatic typography
* Title suggestions
* Description
* Chapters
* Tags
* Upload checklist

---

### Milestone 8.5 - Content Safety and Rights Engine

Deliverables:

* Asset rights metadata and license-proof storage
* Rights statuses for safe, attribution-required, editorial-review, unknown, and blocked assets
* Script similarity and source-concentration checks
* Reused-content and originality risk report
* High-risk claim, AI-disclosure, trademark, thumbnail, generated-image, music, audio, and voice safety checks
* Content safety report exported with each final video package
* Publishing gate that blocks unsafe or incomplete packages until human review resolves them

Detailed architecture note: `docs/architecture/content-safety-rights-engine.md`.

Do not implement this as one large feature. Build it in small stages after the earlier content pipeline milestones provide the required inputs.

---

### Milestone 9 — Telegram Approval

Deliverables:

* Private Telegram bot
* Approval messages
* Script preview
* Thumbnail selection
* Final-video notification
* Feedback capture
* Error alerts

---

### Milestone 10 — Shorts

Deliverables:

* Highlight suggestions
* Segment selection
* 9:16 conversion
* Caption rendering
* Reframing
* Short export

---

## 18. Explicit Non-Goals

Do not build the following during early milestones:

* SaaS product
* User registration
* Billing
* Multiple organizations
* Distributed cloud architecture
* Kubernetes
* Microservices
* Five production channels
* Fully automatic uploading
* Complex React dashboard
* Advanced knowledge graph
* Self-training models
* Automatic prompt rewriting
* Paid provider integrations
* Mobile application

---

## 19. Quality Requirements

The codebase must include:

* Type hints
* Clear module boundaries
* Structured logs
* Useful errors
* Unit tests
* Integration tests for important workflows
* Database migrations
* Configuration through environment variables
* No hardcoded secrets
* No hardcoded absolute file paths
* No silent exception handling
* No untracked external assets
* No overwriting approved versions

---

## 20. First Codex Task

Codex should begin with the following task:

```text
Read AGENTS.md, docs/MASTER_PLAN.md and docs/MVP_SCOPE.md.

Do not implement the full platform.

Complete only Milestone 1:

1. Propose the repository structure.
2. Create the Python project configuration.
3. Add environment-based settings.
4. Add structured logging.
5. Configure SQLite in WAL mode.
6. Define the initial SQLAlchemy models.
7. Configure Alembic.
8. Create the first migration.
9. Add unit tests for model creation and database initialization.
10. Add a concise architecture decision record.

Do not add Telegram, ComfyUI, local language models, TTS, FFmpeg rendering or a web dashboard yet.

After implementation, run tests and report:
- Files created
- Commands run
- Test results
- Assumptions
- Remaining work
```
