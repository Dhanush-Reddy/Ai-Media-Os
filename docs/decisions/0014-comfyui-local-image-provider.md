# ADR 0014: Optional Local Image Generation Through ComfyUI

## Status

Accepted

## Context

The fake image provider validates the asset pipeline but cannot produce production scene visuals.
The project needs a zero-recurring-cost local image runtime without coupling application services to
one model or weakening storage, cache, review, rights, and publishing-gate rules.

## Decision

Add ComfyUI behind `ImageGenerationProvider`, keep `fake_image` as the default, and require explicit
configuration or CLI selection. Use a version-controlled API workflow with a fixed node map. Permit
only local HTTP hosts by default, reject redirects and unsafe paths, and verify downloaded image
signatures and dimensions before atomic storage and cache insertion.

Persist provider, checkpoint, workflow, prompt, seed, dimensions, generation settings, synthetic
provenance, MIME, size, and hashes in the existing asset and cache records. New outputs require
human review; approved assets remain immutable and the deterministic safety/publishing gate remains
authoritative. Do not perform an eager health call during provider construction because valid cache
reuse must work while ComfyUI is offline.

## Alternatives Considered

* Call ComfyUI directly from asset services. Rejected because it breaks provider neutrality.
* Bundle or automatically install ComfyUI and checkpoints. Rejected for security, size, and scope.
* Use a cloud image API. Rejected because it conflicts with local-first and zero recurring cost.
* Mark generated assets rights-safe. Rejected because model and output rights require review.

## Consequences

Users can opt into real local scene images while deterministic fake/manual workflows remain intact.
They must install ComfyUI and a compatible checkpoint separately. Generation is synchronous within
a worker, consumes local GPU resources, and can time out. The initial workflow intentionally omits
advanced editing and consistency features.
