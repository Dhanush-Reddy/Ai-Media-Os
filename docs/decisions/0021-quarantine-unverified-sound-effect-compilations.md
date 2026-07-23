# ADR 0021: Quarantine Unverified Sound-Effect Compilations

## Status

Accepted

## Decision

AI Media OS may cut and catalog a user-supplied sound-effect compilation for analysis, but clips with
unverified commercial-use rights are stored under `inputs/sfx-library/quarantine` with safety state
`UNKNOWN` and `auto_usable=false`.

Recognizable platform and game recordings are marked `BLOCKED` independently of the compilation's
license. A compilation uploader may not control those underlying recordings.

Each extracted clip records its source interval, category, scene tags, SHA-256 hash, source URL,
creator, license, commercial-use confirmation, and safety state. Licensed imports are stored under
`inputs/sfx-library/approved`; final rendering may select only clips marked safe and auto-usable.

## Consequences

- Reference compilations can be analyzed and segmented without losing provenance.
- Unknown or blocked recordings cannot accidentally enter monetized videos.
- Once permission is documented, safe clips can be re-imported reproducibly without manually
  finding timestamps again.
- A separate approved SFX source is still required before these clips can replace procedural effects
  in production renders.
