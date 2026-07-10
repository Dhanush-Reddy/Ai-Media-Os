# ADR 0011: Content Safety And Rights Engine

## Status

Accepted

## Context

Milestone 8 produces local metadata and thumbnail packaging. The next step is a local risk-reduction layer that evaluates asset rights, claim support, script and metadata safety, thumbnail risk, reused-content risk, AI disclosure, and publishing readiness before manual publishing.

The repository must stay local-first, zero recurring cost, and provider agnostic. It must not introduce real plagiarism APIs, copyright databases, YouTube upload automation, Telegram, or cloud services.

## Decision

Implement a rules-based Content Safety and Rights Engine backed by SQLite, immutable safety findings, rights records, and publishing-gate reports.

Use deterministic local checks for asset provenance, claim support, unsupported factual wording, local file-path leakage, repeated content, and synthetic-content disclosure. Store the publishing gate as a report content version and expose the results through the dashboard, CLI, and queue handlers.

Use the existing content-version architecture for safety reports and preserve historical safety data when a downgrade removes the new tables by backing up rows before dropping them.

## Alternatives Considered

* Add a real plagiarism or copyright API. Rejected because it adds recurring cost, network dependency, and unclear legal value for the MVP.
* Push safety checks into the publishing layer only. Rejected because the pipeline needs reusable reports and queue jobs before publishing.
* Treat rights and safety as ad hoc flags on assets. Rejected because the system needs versioned findings and explicit gate decisions.

## Consequences

The project now has a local publishing gate that can block or warn on rights and safety issues without claiming legal certainty. The implementation stays deterministic and testable, but it cannot prove that a video is safe in the legal or platform-policy sense.

