# ADR 0018: Staged Review Package and Optional Reference Project

## Status

Accepted

## Context

The full short-production runner needs to create a fresh project for each run, preserve the work for human review, and remain usable when a local metadata provider is temporarily unavailable. Reviewers also need a simple way to point a new run at approved work from an earlier project without making that reference mandatory.

## Decision

The regeneration runner now writes a per-run `review-package` folder under the production-runs report directory. The package stores the imported source script and resolved reference context so the run can be reviewed or amended after generation.

The image-evaluation path accepts an optional reference-project ID. When provided, the system resolves the newest approved image reference from that project and uses it for evaluation in the same way as an explicit reference asset.

If the Ollama metadata provider health check fails during a production run, the runner falls back to the fake metadata provider and continues instead of aborting the entire run.

## Rationale

Each run should have a visible, inspectable staging area without requiring users to search through internal logs.

Optional reference-project support makes it easier to reuse prior approved work while keeping the primary workflow explicit and local-first.

Failing closed on a temporary local metadata-provider outage blocks otherwise reviewable work. Falling back keeps the project moving while still logging the degraded path.

## Consequences

Reviewers gain a stable place to inspect the source script and reference context for a run.

The system remains conservative because approval is still required at the content and asset levels; the review package does not bypass human sign-off.

If users need strict Ollama-only metadata generation, that behavior should be reintroduced as an explicit opt-in guard rather than a silent default.
