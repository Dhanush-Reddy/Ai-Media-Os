# ADR 0010: Local Metadata And Thumbnail Packaging

## Status

Accepted

## Context

After local render composition, the MVP needs a human-reviewable YouTube package: title/description/tags/chapters and at least one thumbnail candidate. The project must remain zero-cost, local-first, provider agnostic, and testable.

## Decision

Add packaging services that store metadata and thumbnail concepts as immutable content versions, and store generated/imported thumbnail files as assets.

Use strict Pydantic schemas for reviewable metadata and thumbnail concepts. Use deterministic fake providers for local demos and tests. The fake thumbnail provider writes a valid PNG file without adding a new image dependency.

Add small queue handlers and dashboard pages for metadata and thumbnail review. Extend workflow events from render verification to metadata generation, thumbnail concept generation, and Milestone 8 completion.

## Alternatives Considered

- Generate metadata directly in CLI commands without services. Rejected because it would bypass content versioning, approval rules, and queue handlers.
- Store thumbnail concepts only in asset metadata. Rejected because concepts need immutable reviewable versions before image generation.
- Add Pillow for PNG generation. Rejected for now because a tiny deterministic PNG writer is enough for fake local output and keeps dependencies smaller.

## Consequences

Milestone 8 now produces visible local thumbnail output and structured metadata without paid APIs. Future real providers can implement the same provider protocols. Content safety, real LLM metadata, and real thumbnail generation remain explicitly out of scope.
