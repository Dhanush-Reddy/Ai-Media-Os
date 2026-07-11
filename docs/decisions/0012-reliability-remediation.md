# ADR 0012: Reliability Remediation

## Status

Accepted

## Context

The local pipeline had several crash and replay gaps after Milestone 8.5. Workflow handlers
could commit jobs or approval decisions before workflow state and event records. Some transitions
trusted event payloads without checking persisted approvals, files, jobs, or publishing gates.
Generation fingerprints did not fully identify text-provider behavior, and scene asset planning
did not enforce one asset per scene and role in the database.

## Decision

Use one composable SQLite `BEGIN IMMEDIATE` write transaction for each workflow transition.
Nested application services flush into that transaction and only the outer owner commits. A
transition validates its persisted job, content version, approval, asset, render, or publishing
gate before changing workflow state.

Reject generation or import that would overwrite an approved scene asset. Plan scene assets from
an approved scene plan by default and enforce a unique non-null `(scene_id, asset_role)` invariant.
Manual media imports use signature validation and atomic writes.

Publishing gates evaluate the explicitly selected package inputs and persist a blocked report when
required inputs are absent. Text generation requests include provider/model versions, provider
settings, timeout and cancellation contracts, and typed provider failures. Script fingerprints
include those deterministic provider inputs.

## Downgrade Support

Released migrations are immutable. A new migration may add or remove constraints, but it must not
rewrite an older released migration. Downgrades that remove tables or columns containing project
data must preserve and verify that data before destructive schema operations. Constraint-only
downgrades restore the prior constraint or index shape without changing rows.

Historical multi-revision downgrade paths are tested from current head to documented milestone
boundaries and back to head. They are supported for local recovery and development, not as a
substitute for database backups. A newly discovered unsafe historical downgrade requires a
dedicated remediation migration or recovery tool and tests; it must not be silently patched by
changing an already released revision.

## Consequences

Workflow replay after a crash cannot expose a committed side effect without the corresponding
state and event record. Invalid event payloads no longer advance the workflow. Provider-setting
changes produce new script versions, approved assets remain immutable, and incomplete publishing
packages still produce auditable blocked reports.

SQLite remains the supported database. No distributed transaction coordinator, external queue,
real LLM provider, publishing automation, or cloud service is introduced.
