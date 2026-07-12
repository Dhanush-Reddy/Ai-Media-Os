# ADR 0015: Piper As The First Local TTS Provider

## Status

Accepted

## Context

The deterministic fake voice validates storage and rendering but cannot provide understandable
production narration. The project needs an offline, zero-recurring-cost adapter that remains
optional and preserves verification, cache, review, safety, and approved-render rules.

## Decision

Implement Piper first behind `VoiceGenerationProvider`. Keep `fake_voice` as the default and require
manual Piper/model installation. Invoke Piper through a validated argument list with `shell=False`,
a timeout, managed temporary output, and sanitized errors. Verify and deterministically normalize
16-bit mono WAV before atomic storage or cache insertion.

Generate one narration asset per scene, preserve original/effective text, include all pronunciation,
pacing, model, and processing settings in fingerprints, and require human approval before rendering.
Use RMS dBFS normalization in this milestone and label it accurately rather than claiming full LUFS
compliance.

## Alternatives Considered

* Kokoro first. Deferred because current packaging/model choices add a larger and less stable local
  runtime boundary; it remains the preferred future naturalness option.
* Cloud TTS. Rejected because it conflicts with local-first and zero recurring cost.
* Invoke a command through a shell. Rejected because narration and paths are untrusted inputs.
* Synthesize an entire script as one file. Rejected because scene segmentation improves retry,
  review, cache reuse, synchronization, and pronunciation correction.

## Consequences

Users can opt into real offline narration with a manually installed Piper voice. Output quality
depends on that voice model. Pitch, true LUFS analysis, word alignment, voice cloning, streaming,
and multi-speaker narration remain outside this milestone.
