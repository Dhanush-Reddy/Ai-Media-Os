# ADR 0002: Database-Backed MVP Job Queue

## Status

Accepted

## Context

Milestone 2 needs reliable local background work without paid services or external queue infrastructure. The MVP is single-machine, SQLite-backed, and resource constrained.

## Decision

Use the existing SQLite database as the job queue. Jobs are claimed through a short transaction that starts with `BEGIN IMMEDIATE`, selects eligible work by status, due time, priority, and creation time, checks resource capacity and dependencies, then performs a conditional update from `READY` to `RUNNING`.

Jobs store worker identity, heartbeat time, lease expiration, retry timing, failure diagnostics, cancellation requests, pause timestamps, and dependency blockage information.

## Rationale

A database-backed queue keeps the MVP local-first, simple to inspect, easy to test, and free of Redis, Celery, or cloud infrastructure. SQLite WAL mode is enough for the initial single-laptop workflow when workers keep claim transactions short.

Resource classes exist because the target laptop has limited CPU, RAM, and GPU capacity. In particular, only one `GPU_HEAVY` job should run by default.

## Concurrency Limitations

SQLite supports many readers but serializes writes. `BEGIN IMMEDIATE` prevents two workers from successfully claiming the same job, but it also means concurrent claim attempts wait or fail while another writer holds the lock. Workers should keep claim transactions short and do expensive work only after the claim commits.

## Alternatives Considered

- Redis or Celery: strong queue tooling, but unnecessary infrastructure for the local MVP.
- PostgreSQL row locking: better concurrent queue semantics, but adds setup and operational complexity too early.
- Filesystem locks: simple, but harder to query, migrate, inspect, and relate to project/version metadata.

## Future Reconsideration

Consider PostgreSQL or Redis later if the system needs multiple machines, high worker concurrency, remote workers, dashboard-driven queue controls under load, or substantially higher throughput than SQLite can comfortably provide.
