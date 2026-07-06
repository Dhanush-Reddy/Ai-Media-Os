# ADR 0007: Local Script and Scene Planning

## Status

Accepted

## Context

The MVP needs scripts and scene plans before image, voice, video, and publishing work can start.
The repository must remain local-first, provider-agnostic, queue-driven, versioned, and approval-gated.

## Decision

Implement Milestone 5 with deterministic local rules behind a text generation provider interface.
Scripts, fact-check reports, and scene plans are immutable content versions. Script and scene plan
outputs request human approval. Scene planning requires an approved script and persists validated
scene rows using a strict Pydantic schema.

## Alternatives Considered

- Paid hosted LLMs: rejected because the initial product constraint is zero recurring software cost.
- Direct provider calls inside services: rejected because application logic must stay provider-agnostic.
- Storing only scene-plan JSON: rejected because later media steps need queryable scene records.

## Consequences

The first implementation is predictable and testable, but creative quality is limited until a local
model provider is added. The schema and approval flow are ready for that provider swap.
