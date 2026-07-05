# ADR 0003: Content Versioning, Approvals, and Content-Addressed Cache

## Status

Accepted

## Context

Milestone 3 adds reusable infrastructure for immutable content versions, append-only approval records, deterministic hashing, prompt-template metadata, safe filesystem storage, and a content-addressed cache. The MVP remains local-first, SQLite-backed, and filesystem-backed.

## Decision

Content versions and prompt-template versions are immutable after creation except for administrative status changes. Revisions create new records with lineage instead of overwriting existing content.

Approval decisions are stored as records. A completed approval decision is not edited in place; a new review cycle creates a new approval request.

SHA-256 is the only content-addressing algorithm used in the MVP. Text and JSON-compatible values are canonicalized before hashing, and files are streamed in chunks.

Cache files are stored on the filesystem under `data/cache/sha256/<prefix>/<prefix>/<hash>`, while SQLite stores cache keys, metadata, hashes, validity status, and portable project-relative paths.

File writes use a temporary file in the target directory followed by an atomic replace. Cache lookup verifies that the path stays inside an approved storage root, the file exists, and the file hash matches the database record.

## Rationale

Immutable records protect approved scripts, scene plans, metadata, and reports from accidental overwrite. Append-only approval history preserves reviewer feedback and decision timing.

Filesystem storage keeps large or reusable outputs out of SQLite while still allowing the database to coordinate metadata, integrity checks, and cache reuse.

Content-addressed files allow multiple cache keys to point to the same output without duplicating bytes. Invalidating one cache entry does not delete a shared output file.

## Windows and OneDrive Considerations

Storage paths are handled with `pathlib`, validated against configured roots, and stored relative to the project data root where practical. Atomic replacement is used to reduce the chance of incomplete cache files on local and OneDrive-hosted folders.

## Direct Database Mutation Limitation

Milestone 3 enforces content-version and prompt-template immutability through application services and tests. Direct SQLAlchemy model mutation can still change immutable fields if future code bypasses those services and commits the session directly.

This is an accepted MVP limitation because the project is a local modular monolith and database triggers are intentionally deferred. Code that changes content versions or prompt templates must go through the application services. Reconsider database-level immutability protections if multiple writers, external tools, or untrusted plugins begin writing directly to the database.

## Future Reconsideration

An object store may be considered later if local disk capacity, multi-machine workers, or backup requirements outgrow filesystem storage. Multiple hash algorithms may be considered only if compatibility or migration needs justify the extra complexity.
