# ADR 0017: Isolate Chatterbox Multilingual Behind The Voice Provider Contract

## Status

Accepted

## Context

Piper provides inexpensive, predictable local narration but has limited expressiveness. The channel
may need multilingual dialogue and character-specific delivery. Chatterbox Multilingual V3 provides
speaker conditioning and expressive controls, but its pinned machine-learning dependencies are much
heavier than the core application and its model/reference rights require separate review.

ADR 0016 is reserved by the concurrent production-timeline work, so this decision uses 0017.

## Decision

Add Chatterbox as an optional `VoiceGenerationProvider`. Invoke a repository-owned worker script
with a separately configured Python executable and manually downloaded local model directory. Force
offline model loading, validate WAV output, use typed failures and bounded subprocess execution, and
store model/reference hashes without public filesystem paths.

Keep `fake_voice` as the default and Piper as the lightweight alternative. Chatterbox assets remain
pending human review with unknown rights until model provenance and reference-voice consent are
recorded. Queue execution requires `GPU_HEAVY`.

## Alternatives

* Install Chatterbox into the core environment. Rejected because its pinned Torch, Transformers,
  Diffusers, Gradio, and audio stack would enlarge and destabilize the application dependency set.
* Call the public Gradio demo. Rejected because it introduces network availability, privacy, and
  reproducibility dependencies.
* Replace Piper. Rejected because Chatterbox is heavier and does not remove the need for a simple
  deterministic narrator.
* Build a separate TTS service. Deferred because a local subprocess boundary is sufficient.

## Consequences

Users manage a second Python environment and model files manually. Generation is slower and uses the
single GPU-heavy slot. Speaker-reference consent becomes a required production review concern.
Provider isolation preserves the existing application environment and permits future replacement
without changing asset, cache, approval, render, or safety services.
