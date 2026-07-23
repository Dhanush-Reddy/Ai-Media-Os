# ADR 0020: Duration-Based Short Timing and Procedural Engagement Audio

## Status

Accepted

## Decision

The simple short-production launcher skips WhisperX and uses narration duration to distribute
caption cues. Those cues create an establish beat, intermediate emphasis beats, and a stronger final
reveal beat for every scene.

New short timelines enable `procedural_semantic_reactions_v3`. FFmpeg generates a soft major-seventh
pad and chooses restrained effects from caption meaning and visual-beat purpose: electrical pulses
for power language, digital ticks for data and compute, airflow sweeps for cooling, low impacts for
reveals, and transition whooshes for scene openings. Generic reveal chimes are not used. Gentle echo
and a final limiter keep the mix engaging without obscuring narration. The profile is stored in the
immutable timeline settings and fingerprint. Earlier profiles remain supported so approved
timelines stay reproducible.

WhisperX remains available through the advanced production runner when word-level timing is needed.

## Alternatives Considered

- Keep WhisperX mandatory. This added long processing time and repeatedly blocked otherwise usable
  productions.
- Download royalty-free music. This requires licensing records, attribution checks, and stable source
  files before it can be safely automated.
- Generate multiple images for every narration scene. This substantially increases GPU time and
  review work; subtitle-timed motion beats provide the first useful engagement improvement.

## Consequences

- Simple runs no longer require a WhisperX installation or alignment health check.
- Caption timing is approximate rather than word-accurate.
- Engagement audio is deterministic, local, and free of third-party copyright risk.
- Each scene still uses one approved source image, but it receives multiple timed motion beats and a
  distinct reveal moment.
