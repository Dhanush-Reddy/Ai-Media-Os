# ADR 0016: Versioned Motion Graphics Timeline Engine

## Status

Accepted

## Decision

Store production timelines as strict JSON `ContentVersion` documents and retain FFmpeg behind the existing video-composer provider boundary. Use validated preset enums instead of user-supplied filter expressions. Production renders remain versioned `Render` records and reference timeline identity and fingerprint through immutable render settings.

## Rationale

This reuses established versioning and approval semantics, avoids another persistence model, preserves local-first operation, and keeps deterministic rendering testable without FFmpeg through the fake composer.

## Alternatives

- A separate timeline table was rejected because the current document is naturally versioned and reviewed as one unit.
- A browser nonlinear editor was rejected as outside MVP scope.
- Raw FFmpeg filters were rejected because they weaken validation, portability, and subprocess safety.

## Consequences

Timeline revisions are append-only and approved versions remain immutable. The initial renderer implements a constrained production subset; additional presets and audio processing can expand behind the same validated schema without changing stored contracts.
