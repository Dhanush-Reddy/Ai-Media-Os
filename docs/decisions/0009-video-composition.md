# ADR 0009: Local Video Composition Foundation

## Status

Accepted

## Context

After image and voice assets exist, the MVP needs a reviewable local preview render. The project constraints still require zero recurring cost, local-first execution, provider neutrality, queue-driven work, safe filesystem paths, and no publishing automation.

## Decision

Implement a provider-neutral video composition boundary with a local FFmpeg provider. Render planning remains in the application layer and selects existing scene image and narration assets, validates file hashes, stores deterministic render fingerprints, and creates preview render records. Composition runs through `LocalFFmpegVideoComposer` when FFmpeg is available. Tests use `FakeVideoComposer` so CI and local verification do not require FFmpeg.

Expose render planning, composition, verification, listing, and review through CLI commands, queue handlers, and dashboard render pages.

## Alternatives Considered

- Require FFmpeg in all tests: rejected because local developer environments may not have FFmpeg installed.
- Generate fake MP4 files in production when FFmpeg is missing: rejected because that would hide a real runtime dependency.
- Add a full timeline/caption/motion engine now: deferred because the current milestone only needs the smallest useful local preview render foundation.
- Store rendered videos in SQLite: rejected because large binary files belong in local filesystem storage with hashes and metadata in SQLite.

## Consequences

Milestone 7 can plan and verify local render outputs and compose real MP4 previews on machines with FFmpeg installed. Missing FFmpeg produces a clear failure. Later milestones can add captions, thumbnails, richer timeline effects, and final render gates behind the same render metadata and provider boundary.
