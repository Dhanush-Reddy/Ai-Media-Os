# ADR 0008: Image and Voice Provider Foundation

## Status

Accepted

## Context

After script and scene planning, the MVP needs per-scene visual and narration assets. The project still requires zero recurring software cost, local-first execution, provider neutrality, cache reuse, human review, and no real rendering pipeline yet.

## Decision

Implement provider-neutral image and voice interfaces with deterministic fake providers and manual import services. Store planned, generated, imported, and reviewed assets in the existing `Asset` table with additional role/status/model metadata. Use the existing content-addressed cache for deterministic fake generation. Expose assets through CLI, queue handlers, and the local dashboard.

Real ComfyUI and local TTS adapters are explicit future boundaries, not runtime dependencies in this milestone.

## Alternatives Considered

- Real ComfyUI now: deferred because Milestone 6 only needs the provider boundary and local fake workflow.
- Real TTS now: deferred because model choice and installation should be approved separately.
- New asset table: rejected because the existing `Asset` model already owns scene-to-file metadata.
- Skipping cache until real providers: rejected because fake providers let cache behavior be tested cheaply.

## Consequences

Milestone 6 can generate and review deterministic placeholder images and narration clips without paid APIs or GPU/TTS setup. Later providers can replace fake generation without changing the asset planning and review workflow. Asset quality is intentionally placeholder-level until real local providers are added.
