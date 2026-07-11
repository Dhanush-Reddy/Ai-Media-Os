# ADR 0013: Optional Local LLM Through Ollama

## Status

Accepted

## Context

The deterministic providers are reliable for tests and local demonstrations but cannot provide the
content quality expected from a real language model. The project requires a zero-recurring-cost,
local-first option that remains replaceable and does not weaken cache, approval, or safety rules.

## Decision

Add Ollama behind the existing text-generation provider contract. Keep fake/rules providers as the
default and require explicit configuration or CLI selection for Ollama. Use strict JSON schemas for
scene plans, metadata, and thumbnail concepts. Preserve typed provider failures and include model,
settings, prompt/schema versions, and source hashes in generation fingerprints.

Allow read-only LLM summaries of persisted safety reports. Deterministic safety findings and
publishing gates remain authoritative and cannot be modified by the LLM adapter.

Do not perform automatic health checks during provider construction. An eager network call would
break cache-first reuse when Ollama is offline. Health checks remain an explicit CLI operation.

## Alternatives Considered

* Replace fake providers globally. Rejected because tests and offline use must remain deterministic.
* Call Ollama directly from application services. Rejected because it couples business logic to one
  runtime.
* Add a cloud or paid LLM. Rejected because it conflicts with local-first and zero recurring cost.
* Let an LLM decide publishing safety. Rejected because safety gates must remain deterministic and
  auditable.

## Consequences

Users can opt into real local text generation without changing the default workflow. Ollama must be
installed and the selected model must be pulled separately. Synchronous generation consumes local
CPU/GPU and may time out, but failures remain retryable through the existing queue.
