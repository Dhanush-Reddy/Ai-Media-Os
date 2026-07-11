# Milestone 3 Audit Task

## Status

Completed before Milestone 4. Retained as a historical audit checklist.

## Scope

Review the completed Milestone 3 implementation against:

* `AGENTS.md`
* `docs/MASTER_PLAN.md`
* `docs/MVP_SCOPE.md`
* `docs/decisions/0003-content-versioning-approval-cache.md`

Do not add new features and do not begin Milestone 4. Audit only the existing Milestone 3 implementation.

## Audit Areas

Verify content versioning, approvals, prompt templates, deterministic hashing, filesystem security, cache integrity, database migrations, and tests.

Content versioning checks must include concurrent version creation, project-and-type scoped numbering, parent validation, cycle rejection, immutability through application services, transactional approval superseding, one active approved version per project and content type, rollback safety, deterministic history ordering, and preservation of input hashes, content hashes, prompt metadata, and provider metadata.

Approval checks must include append-only final decisions, new review records for new cycles, duplicate pending approvals, status consistency after partial failures, job transitions after valid approval only, useful blocked reasons for rejection or change requests, publishing approval without a content version, related-object validation for other approval types, and no automatic approval or publishing on expiration.

Prompt-template checks must include per-name version uniqueness, immutability, one active version per name, transactional active-version replacement, hashes calculated from exact stored template content, and no silent database mutation when source files change.

Hashing checks must cover UTF-8 text, Windows and Unix newlines, dictionary key ordering, list ordering, nested values, UUID, date, UTC-aware datetime, naive datetime, enum, decimal, path, boolean, null, and floating-point values. Unsupported values must fail clearly rather than using unstable string representations.

Filesystem checks must cover traversal rejection, absolute paths outside approved roots, Windows drive-letter paths, UNC paths, symlink or junction escapes, partial-overwrite prevention, temporary-file cleanup after failures, Windows atomic replacement, closed file handles before replacement, user-controlled extension safety, portable database paths, and OneDrive synchronization-related failure behavior without OneDrive-specific dependencies.

Cache checks must cover equivalent normalized requests, meaningful input differences, provider/model/model-version/operation/prompt-hash/prompt-version/settings/seed/input-hashes/workflow-version handling, missing outputs, corrupt outputs, expiry, unsafe paths, `last_used_at`, atomic write ordering, duplicate content reuse, shared-file invalidation safety, shared corruption detection, disappearing files during verification, and streaming file hashing.

Migration checks must confirm model metadata matches Alembic output, unique constraints, foreign keys, indexes, conservative cascades, approved historical records are not deleted accidentally, `0003` downgrade preserves earlier schema integrity, re-upgrade recreates expected schema, and `alembic check` reports no drift.

## Tests

Add or improve tests only where confirmed coverage is missing.

Prioritize concurrent version creation, concurrent prompt activation, concurrent version approval, transaction rollback during superseding, direct mutation limitation documentation, symlink or junction escape protection, Windows-style path traversal, atomic-write cleanup after simulated failure, cache corruption, cache file deletion during verification, duplicate-content reuse, shared-file invalidation safety, approval/job transaction rollback, naive datetime hashing behavior, and float hashing behavior.

Tests must remain local and must not require network access, Docker, PostgreSQL, Redis, GPU access, paid APIs, or external services.

## Verification Commands

Run:

```bash
pytest
ruff check .
ruff format --check .
mypy src
alembic upgrade head
alembic downgrade -1
alembic upgrade head
alembic check
```

Also run targeted concurrency and filesystem-security tests separately and report their results.

## Scope Restrictions

Do not add research collection, search providers, web extraction, AI providers, prompt rendering, scene planning, ComfyUI, TTS, FFmpeg, Telegram, publishing, analytics, Shorts, frontend, PostgreSQL, Redis, Celery, Docker, cloud storage, or cache cleanup workers.

Fix only confirmed Milestone 3 defects.

## Completion Report

Provide:

1. Issues found
2. Fixes applied
3. Files changed
4. Concurrency findings
5. Filesystem-security findings
6. Cache-integrity findings
7. Approval and versioning findings
8. Migration verification
9. Test results
10. Ruff results
11. Formatting results
12. Mypy results
13. Remaining limitations
14. Confirmation that no Milestone 4 features were added
