# ADR 0001: MVP Foundation Architecture

## Status

Accepted

## Context

AI Media OS must first help produce one high-quality, monetization-safe YouTube channel with zero recurring software cost. The MVP runs locally on a laptop with an RTX 4050 Laptop GPU and 16 GB RAM, uses manual publishing, and must preserve approved content versions.

## Decision

Use Python as the primary implementation language, SQLite as the initial database, a modular monolith architecture, and local filesystem storage for large media files.

## Rationale

Python fits the media and AI tooling ecosystem, keeps the implementation approachable, and works well with FastAPI, Pydantic, SQLAlchemy, Alembic, Pytest, Ruff, and Mypy.

SQLite is used initially because it has no server process, no recurring cost, simple backup behavior, and enough reliability for a single-machine MVP when WAL mode, foreign keys, and migrations are enabled.

A modular monolith is preferred because the MVP needs clear boundaries without distributed-system overhead. Domain, application, infrastructure, providers, workers, media, schemas, storage, and utility modules can evolve independently while remaining easy to test locally.

Large media files are stored on the filesystem instead of inside the database because videos, images, audio, captions, thumbnails, and exports are better handled as files. SQLite stores metadata, paths, hashes, statuses, and relationships, while the filesystem stores heavy binary assets.

## Alternatives Considered

- Node.js or TypeScript: strong for web applications, but less aligned with local AI and media workflows.
- PostgreSQL: production-grade and scalable, but adds operational cost and setup complexity before the first channel is validated.
- Microservices: useful later for scaling, but premature for a local-first MVP.
- Storing media blobs in SQLite: simple in theory, but would make the database large, slower to back up selectively, and harder to inspect or move.

## Consequences

- The MVP remains local-first, low-cost, and easy to run.
- Schema changes must go through Alembic migrations.
- Filesystem paths must remain project-relative and configurable.
- If future production usage requires concurrent multi-user access or remote workers, the database layer can migrate to PostgreSQL behind SQLAlchemy without changing domain concepts.
