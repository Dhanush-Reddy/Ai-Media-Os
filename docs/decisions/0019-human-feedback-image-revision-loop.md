# ADR 0019: Human-feedback image revision loop

## Status

Accepted.

## Decision

Rejecting a staged scene image during local production requests a reason and creates a new staged
revision for only that scene. The reason is stored in the rejected asset's review history and is
also added to the next generation prompt. Each retry uses a deterministic seed increment. Approved
assets remain immutable, other pending scene images are reused, and entering `STOP` ends the run.

## Alternatives considered

- Stop the complete run after rejection: rejected because it wastes completed local generation and
  makes human review unnecessarily expensive.
- Regenerate every project image: rejected because feedback normally concerns one scene and GPU work
  must remain sequential and resource-aware.
- Overwrite the rejected asset: rejected because review history and generated revisions must remain
  auditable.

## Consequences

Image review can continue until approval without restarting production. Rejected staged files are
still deleted, while their database records, feedback, seed, prompt, and revision relationships are
preserved. A user can explicitly stop instead of entering another revision cycle.
