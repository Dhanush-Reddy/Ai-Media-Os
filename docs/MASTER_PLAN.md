# AI Media OS — Master Plan

**Version:** v0.1
**Status:** Planning
**Primary Goal:** Build a revenue-generating AI-assisted media pipeline that can eventually evolve into a reusable AI Media Operating System.

---

## 1. Vision

Build an AI-powered Content Operating System capable of creating, managing, and scaling multiple faceless media channels.

The long-term system should support:

* YouTube long-form videos
* YouTube Shorts
* Instagram Reels
* TikTok videos
* Blog articles
* Podcasts
* LinkedIn content
* X/Twitter content
* Newsletters
* Future social platforms

The system should generate multiple content formats from a single source of research and content.

This is not only a YouTube automation tool.

It is a reusable content production platform.

---

## 2. Primary Business Goal

The first priority is revenue.

Initial target:

* Generate ₹30,000–₹40,000 per month
* Start with one YouTube channel
* Reinvest early revenue into better models, APIs, hardware, storage, and automation
* Reduce manual involvement gradually
* Expand into multiple channels only after the first pipeline works consistently

The first success metric is not full automation.

The first success metric is:

> Can the system repeatedly produce content that real viewers voluntarily watch?

---

## 3. Current Constraints

### Budget

* No additional software budget
* No paid API credits
* No subscriptions beyond existing ChatGPT Plus
* No credit card dependency
* Target zero recurring cost for the first three to four months

### Hardware

* Lenovo laptop
* RTX 4050 Laptop GPU
* 16 GB RAM
* Local storage

### Current Software

* ChatGPT Plus
* Local development tools
* No production API access

---

## 4. Product Philosophy

Most creators think:

> I want multiple YouTube channels.

The AI Media OS approach is:

> I want one reusable AI Content Engine.

Channels should be configurations.

The engine should remain shared.

Channel-specific differences should include:

* Brand name
* Logo
* Intro
* Outro
* Voice
* Fonts
* Colors
* Prompt templates
* Thumbnail style
* Pacing
* Audience profile
* Content rules
* Publishing schedule

The rest of the pipeline should remain reusable.

---

## 5. Planned Channels

### Channel 1 — AI & Future

Topics:

* AI news
* AI models
* AI tools
* AI tutorials
* AI companies
* Product launches
* Research explained
* AI hardware
* Industry changes

Style:

* Fast-paced
* Modern
* Simple
* Highly visual
* Documentary-inspired
* Clear explanations

This is the first channel to be launched.

---

### Channel 2 — Gadgets & Chips

Topics:

* NVIDIA
* AMD
* Intel
* Apple Silicon
* Qualcomm
* CPUs
* GPUs
* Smartphones
* AI hardware
* Future gadgets

Style:

* Fast explanations
* Motion graphics
* Cartoon-inspired visual storytelling
* Strong pacing
* Short, high-retention segments

---

### Channel 3 — Cars & Bikes

Primary market:

* India

Topics:

* Vehicle launches
* Leaks
* EVs
* Royal Enfield
* Tata Motors
* Mahindra
* Hyundai
* Kia
* Comparisons
* Ownership tips
* Maintenance
* Buying advice

Content mix:

* Mostly Shorts
* Occasional long-form videos

---

### Channel 4 — Fitness Stories

Requirements:

* No copyrighted characters
* Use original AI-generated characters
* Maintain character consistency
* Build reusable intellectual property

Possible recurring characters:

* Panda
* Lion
* Tiger
* Robot
* Viking
* Bear

Style:

* Story-driven transformations
* Motivation
* Fitness education
* Character-based storytelling

---

### Channel 5 — Interesting Facts

Topics:

* Space
* Science
* Engineering
* Psychology
* Technology
* History
* Unusual discoveries
* Human behavior

Viewer reaction target:

> I never knew that.

---

## 6. Long-Term Content Targets

Each mature channel may eventually produce:

* 2 long-form videos per week
* 3–4 Shorts per week

Long-term combined target:

* Approximately 32 long videos per month
* Approximately 50–60 Shorts per month

These targets should not apply during the MVP stage.

---

## 7. Core Engineering Principles

The platform must be:

* Provider agnostic
* Local first
* Queue driven
* Cache first
* Configuration driven
* Modular
* Replaceable
* Retry safe
* Versioned
* Observable
* Copyright aware
* Monetization aware
* Resource aware
* Automation friendly

Avoid unnecessary complexity before the first working video.

---

## 8. High-Level Architecture

```text
Dashboard
    ↓
Project Manager
    ↓
Content Planner
    ↓
Job Queue
    ↓
AI Kernel
    ↓
Agents and Providers
    ↓
Video Pipeline
    ↓
Approval System
    ↓
Publishing
    ↓
Analytics
```

---

## 9. AI Kernel

The AI Kernel provides a common interface for all AI providers.

The application must not depend directly on one AI company or model.

Example interface:

```python
class TextGenerationProvider:
    def generate(self, prompt: str, **options) -> str:
        ...
```

Possible provider categories:

```text
providers/
├── local/
├── free/
└── paid/
```

Provider implementations may include:

* Local language models
* Free online providers
* Future paid APIs
* Manual provider
* Browser-assisted provider

The provider can change without rewriting the business logic.

---

## 10. Multi-Agent Pipeline

```text
Topic
    ↓
Research Agent
    ↓
Source Classifier
    ↓
Fact Extraction
    ↓
Claim Verification
    ↓
Script Agent
    ↓
Fact Checker
    ↓
Scene Planner
    ↓
Storyboard Generator
    ↓
Image Prompt Generator
    ↓
Image Generator
    ↓
Voice Generator
    ↓
Timeline Builder
    ↓
Video Composer
    ↓
Subtitle Generator
    ↓
Thumbnail Generator
    ↓
Shorts Generator
    ↓
Approval Queue
    ↓
Publishing Queue
```

Agents should be logical modules.

They do not always need separate AI models.

---

## 11. Queue System

Everything that takes time should become a job.

Example:

```text
Generate Script
    ↓
READY
    ↓
RUNNING
    ↓
COMPLETED
    ↓
Generate Scene Plan
```

Recommended job states:

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

A job waiting for approval should not block unrelated work.

The system should continue processing other videos while one video waits for human review.

---

## 12. Human Approval System

Human involvement is allowed and expected during the initial phase.

Recommended approval points:

* Topic approval
* Script approval
* Thumbnail approval
* Final video approval
* Publishing approval

The following should normally remain automatic:

* Scene splitting
* Image prompt creation
* Subtitle generation
* Timeline creation
* Metadata generation
* Cache checks
* File organization

The first approval interface should be a private Telegram bot.

The bot may send:

* Topic options
* Research summaries
* Scripts
* Voice previews
* Thumbnail previews
* Final video previews
* Error alerts
* Publishing reminders

Possible actions:

```text
Approve
Reject
Request Changes
Pause
Regenerate
Select Option
```

The system must never automatically publish a video because the user failed to respond.

---

## 13. Content Versioning

Important content must be immutable and versioned.

Example:

```text
Research v1
Research v2
Script v1
Script v2 — Approved
Scene Plan v1
Thumbnail A
Thumbnail B — Approved
Final Render v1
```

Approved content should never be overwritten.

Revisions must create a new version.

Each version should store:

* Version number
* Creation timestamp
* Provider
* Model
* Prompt version
* Input references
* Parent version
* Approval state
* Feedback
* Output path
* Content hash

---

## 14. Caching Strategy

Cache everything that is expensive or reusable.

Cache categories:

* Search results
* Extracted web pages
* Research briefs
* Claims
* Scripts
* Scene plans
* Image prompts
* Images
* Voice clips
* Music
* Captions
* Thumbnails
* Final videos
* Shorts
* Analytics reports

Recommended cache key inputs:

```text
Provider
Model
Model version
Prompt
Prompt version
Settings
Seed
Input asset hashes
```

Example:

```python
cache_key = sha256(
    provider
    + model
    + model_version
    + prompt
    + settings
    + input_hashes
)
```

Never regenerate an identical result unnecessarily.

---

## 15. Research System

The research system should not rely only on the top search results.

Sources should be classified by authority.

### Tier 1 — Primary Sources

* Official company announcements
* Official documentation
* Government websites
* Regulatory filings
* Research papers
* Official GitHub repositories
* Product release notes

### Tier 2 — Strong Secondary Sources

* Established technology publications
* Reputable financial publications
* Major newspapers
* Specialist industry publications

### Tier 3 — Discovery Sources

* Reddit
* Hacker News
* Forums
* Social media
* Small blogs
* YouTube discussions

Tier 3 sources may be used for discovery and public opinion.

Important factual claims should be verified through Tier 1 or Tier 2 sources.

Recommended research flow:

```text
Topic
    ↓
Generate Search Queries
    ↓
Collect Candidate Sources
    ↓
Remove Duplicates
    ↓
Classify Source Types
    ↓
Rank by Authority, Relevance and Recency
    ↓
Extract Information
    ↓
Create Claim Table
    ↓
Verify Important Claims
    ↓
Build Research Brief
```

---

## 16. Claim Tracking

Important claims should be stored separately from the script.

Example:

```json
{
  "claim": "Company X launched Product Y on July 1, 2026.",
  "importance": "high",
  "confidence": 0.97,
  "status": "verified",
  "sources": [
    {
      "type": "official_announcement",
      "url": "https://example.com",
      "published_at": "2026-07-01"
    }
  ]
}
```

The fact checker should map script claims to supporting evidence.

Unsupported high-risk claims should be removed or flagged.

---

## 17. Scene Planning

Do not convert a script directly into a video.

Use:

```text
Script
    ↓
Scene Splitter
    ↓
Scene JSON
    ↓
Asset Generation
    ↓
Timeline
    ↓
Video
```

A scene may contain:

```json
{
  "scene_number": 1,
  "narration": "Example narration.",
  "duration_seconds": 6.5,
  "visual_type": "generated_image",
  "image_prompt": "A cinematic AI data center...",
  "camera_motion": "slow_zoom_in",
  "transition": "crossfade",
  "sound_effect": null,
  "caption_style": "emphasis",
  "source_references": []
}
```

Scene JSON should be validated using a strict schema.

---

## 18. Video Style

The default video format should use:

* Generated images
* Licensed or original media
* Ken Burns movement
* Zoom and pan
* Motion graphics
* Transitions
* Captions
* Voice-over
* Sound effects
* Background music
* Charts
* Diagrams
* Screenshots used carefully

Expensive AI video generation should not be required for every scene.

---

## 19. Video Pipeline

```text
Approved Script
    ↓
Scene Plan
    ↓
Image Prompts
    ↓
Image Generation
    ↓
Voice Generation
    ↓
Audio Alignment
    ↓
Timeline Creation
    ↓
FFmpeg Composition
    ↓
Subtitle Rendering
    ↓
Quality Checks
    ↓
Final Preview
    ↓
Approval
```

---

## 20. Shorts Pipeline

```text
Long Video
    ↓
Detect Strong Segments
    ↓
Select Highlights
    ↓
Reframe to 9:16
    ↓
Add Captions
    ↓
Add Hook
    ↓
Export Short
```

One long video should eventually produce two or more Shorts.

The Shorts pipeline should support:

* Automatic highlight suggestions
* Manual segment selection
* Caption templates
* Face or object tracking
* 9:16 reframing
* Hook generation

---

## 21. Image Generation

Current implementation: Milestone 9B provides an optional local ComfyUI adapter for one fixed
text-to-image workflow. Fake generation remains the default; installation, checkpoints, and
advanced workflows remain manual/deferred. See `docs/architecture/comfyui-image-provider.md`.

Recommended local strategy:

* Use ComfyUI as the workflow engine
* Use a dependable lightweight model for most scenes
* Use higher-quality workflows only for priority scenes
* Add optional upscaling
* Reuse visual assets
* Store seeds and workflow metadata
* Avoid regenerating approved images

Possible workflow types:

* Standard scene generation
* Thumbnail generation
* Product visualization
* Background generation
* Character consistency
* Upscaling
* Inpainting
* Style consistency

The exact model should remain configurable.

---

## 22. Voice Generation

Current implementation: Milestone 9C provides optional offline Piper narration with one asset per
scene, pronunciation preparation, deterministic WAV verification/normalization, cache reuse, human
review, and approved-only render selection. Fake voice remains the default. Kokoro and advanced
alignment remain future options. See `docs/architecture/local-tts-provider.md` and
`docs/architecture/narration-pipeline.md`.

The initial voice pipeline should be local.

Possible local providers:

* Kokoro
* Piper
* Other open-source local TTS providers

The system should support provider replacement.

Recommended workflow:

```text
Raw Script
    ↓
Text Cleanup
    ↓
Pronunciation Rules
    ↓
Pause and Emphasis Processing
    ↓
Paragraph Segmentation
    ↓
TTS Generation
    ↓
Silence Adjustment
    ↓
Loudness Normalization
    ↓
Music Ducking
```

Narration should be generated in smaller segments instead of one complete file.

This allows cheap corrections.

---

## 23. Thumbnail Strategy

Use a hybrid process.

Template layer:

* Brand colors
* Fonts
* Text placement
* Safe zones
* Logo placement
* Contrast rules

AI-generated layer:

* Main visual
* Background
* Concept image
* Product image
* Technology illustration

Do not depend on an image model to generate final thumbnail text.

Typography should be added programmatically.

Each video may generate three concepts:

* Curiosity
* Conflict
* Scale or surprise

The best two should be sent for approval.

---

## 24. Asset Library

Reusable assets should include:

* Logos
* Intros
* Outros
* Music
* Sound effects
* Backgrounds
* Icons
* Character sheets
* Charts
* Lower thirds
* Transition elements
* Thumbnail components
* Brand templates

Every asset should store:

* Source
* Creator
* License
* Commercial-use status
* Attribution requirement
* Download date
* Original URL
* File hash
* Modification history

Possible asset safety states:

```text
SAFE
ATTRIBUTION_REQUIRED
EDITORIAL_ONLY
UNKNOWN
BLOCKED
```

Only safe assets should automatically enter final monetized content.

---

## 25. Copyright and Monetization Safety

Copyright safety is a core requirement.

Prefer:

* Self-generated visuals
* Original narration
* Original scripts
* Original charts
* Original diagrams
* Public-domain media
* Commercial-use licensed media
* Properly attributed media where required
* Original or licensed music

Avoid:

* Random image search downloads
* Copyrighted characters
* Unlicensed music
* Reused compilations
* Minimal-effort slide shows
* Unsupported clips
* Content copied from other creators
* Automated publishing without review

Every final video should provide original value through:

* Analysis
* Explanation
* Structure
* Commentary
* Editing
* Narration
* Visual transformation

### Content Safety and Rights Engine

A local rules-based Content Safety and Rights Engine is implemented to reduce risks around copyright claims, reused-content monetization rejection, unlicensed assets, misleading metadata, missing attribution, and unsafe publishing. It creates findings and publishing-gate reports without making legal or platform-compliance guarantees.

The engine must treat rights safety and originality risk as separate checks. It should preserve evidence, block unsafe assets, produce a content safety report, and require human review where risk cannot be resolved automatically.

Detailed architecture note: `docs/architecture/content-safety-rights-engine.md`.

---

## 26. Analytics

Store:

* Video title
* Thumbnail version
* Script prompt version
* Video duration
* Hook style
* Publish date
* Impressions
* Click-through rate
* Views
* Average view duration
* Retention
* Likes
* Comments
* Subscribers gained
* Traffic sources

The initial system should recommend improvements rather than automatically changing prompts.

Example:

```text
Observation:
Videos with introductions longer than 25 seconds lost viewers quickly.

Recommendation:
Keep future introductions between 12 and 18 seconds.
```

Automatic optimization should be delayed until enough data exists.

---

## 27. Knowledge and Research Memory

Do not build a full knowledge graph initially.

Start with lightweight research memory.

Store:

* Entity
* Topic
* Claim
* Source
* Publication date
* Last verified date
* Confidence
* Expiration date

Possible later upgrades:

* Vector search
* Entity linking
* Contradiction detection
* Knowledge graph
* Self-updating fact database

---

## 28. Local Resource Scheduling

The laptop has limited GPU and RAM.

The queue should classify jobs by resource needs.

Example:

```yaml
resources:
  gpu_heavy:
    max_concurrent: 1

  gpu_light:
    max_concurrent: 1

  cpu_heavy:
    max_concurrent: 2

  network:
    max_concurrent: 3
```

Suggested priority:

```text
1. User-requested preview
2. Approved final render
3. Voice generation
4. Image generation
5. Background experiments
```

Overnight jobs may include:

* Image generation
* Upscaling
* Final rendering
* Subtitle alignment
* Shorts extraction

---

## 29. Recommended Initial Technology Stack

### Backend

* Python
* FastAPI
* Pydantic
* SQLAlchemy
* Alembic

### Database

* SQLite
* WAL mode
* Migration-ready design

### Queue

* Database-backed job queue
* One or more Python workers
* CPU and GPU resource categories

### Media

* FFmpeg
* FFprobe

### Images

* ComfyUI
* Configurable local image models

### Voice

* Configurable local TTS provider

### Approval

* Telegram bot

### Storage

* Local filesystem
* Content-addressed cache
* Structured project directories

### Dashboard

* Minimal web dashboard later
* Do not prioritize dashboard before end-to-end content generation

---

## 30. Development Roadmap

### Phase 1 — Revenue-First MVP

* One AI & Future channel
* One long-form video per week
* Two or three Shorts per long video
* Local generation
* Manual review
* Manual publishing
* Copyright tracking
* No paid APIs

### Phase 2 — Reliability

* Job queue
* Retries
* Dependencies
* Versioning
* Cache
* Resource locks
* Failure recovery
* Structured logs

### Phase 3 — Mobile Approval

* Telegram topic approval
* Script approval
* Thumbnail approval
* Final video approval
* Error notifications

### Phase 4 — Shorts

* Highlight detection
* 9:16 conversion
* Captions
* Hook generation
* Reframing

### Phase 5 — Publishing and Analytics

* Metadata generation
* Upload checklist
* Content Safety and Rights Engine
* Assisted publishing
* Analytics storage
* Weekly recommendations

### Phase 6 — Multi-Channel Platform

* Channel configuration files
* Provider plugins
* Additional niches
* Shared asset library
* Research memory
* Advanced analytics

---

## 31. First Channel Strategy

The first channel is AI & Future.

Initial production target:

* One long-form video per week
* Two or three Shorts from each long-form video
* One or two thumbnail options
* Human approval before publishing

The system should first prove that it can create one polished video consistently.

Only then should production volume increase.

---

## 32. Non-Goals for the First Version

The first version will not include:

* Five active channels
* Fully autonomous publishing
* Distributed cloud workers
* Paid APIs
* Advanced knowledge graphs
* Autonomous prompt optimization
* Complex user accounts
* SaaS billing
* Mobile application
* Enterprise dashboards
* Real-time collaboration
* AI video generation for every scene
* Fully automatic copyright decisions

---

## 33. Main Product Principle

Do not build five separate systems.

Build one reusable pipeline.

Do not optimize for maximum automation first.

Optimize for:

* Quality
* Reliability
* Viewer value
* Monetization safety
* Repeatability
* Low cost

The channels prove that the system works.

The long-term asset is the AI Media Operating System.
