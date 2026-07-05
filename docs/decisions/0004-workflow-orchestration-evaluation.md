# ADR 0004: Workflow Orchestration Evaluation

## Status

Accepted

## Context

AI Media OS has completed and audited Milestones 1, 2, and 3. The repository already has SQLite persistence, SQLAlchemy models, Alembic migrations, a database-backed queue, worker ownership and heartbeats, retry logic, resource-class scheduling, approval records, content versioning, prompt metadata, content-addressed cache, filesystem storage, and CLI commands.

The question is whether LangGraph should coordinate future logical content workflows.

## Decision

Add a small provider-neutral workflow orchestration proof of concept with:

* `WorkflowOrchestrator` protocol
* `SimpleWorkflowOrchestrator`
* `LangGraphWorkflowOrchestrator`
* Typed workflow events and workflow state
* Repository-backed workflow state tables
* Event idempotency records

Do not replace the existing queue, approval, versioning, cache, storage, or worker infrastructure.

LangGraph remains optional and isolated in the adapter package. Normal installs do not require it.

Recommendation: `ADOPT LATER`.

## Rationale

The simple orchestrator is enough for the current proof-of-concept workflow. It is explicit, easy to test with SQLite, and aligns with the existing Alembic-backed persistence model.

LangGraph may become useful later if workflows gain substantial branching, multiple resumable checkpoints, or complex agent coordination. At the current size, it does not clearly improve maintainability or reliability enough to justify making it a required dependency.

## Alternatives Considered

* Adopt LangGraph now as the primary workflow engine: rejected for now because it adds dependency and persistence complexity before the workflow is complex enough to benefit.
* Ignore LangGraph entirely: rejected because a small adapter boundary lets the project evaluate it later without rewiring application services.
* Use LangGraph-specific persistence immediately: deferred because it could conflict with the existing SQLAlchemy/Alembic source of truth.

## Consequences

* Workflow state survives process restart using the existing SQLite database.
* Events are idempotent by `workflow_id + event_id`.
* Existing jobs still control execution, retries, leases, dependencies, and resources.
* Existing approvals still control human review.
* LangGraph can be installed through the optional `workflow-langgraph` dependency group when a real graph implementation is worth testing.
* The current adapter delegates to the repository-backed transition core and does not require LangGraph at runtime.

## Limitations

The proof of concept does not implement real research, script generation, prompt rendering, scene planning, media generation, publishing, analytics, or Content Safety and Rights Engine behavior.

It also does not implement generalized distributed workflow recovery. It provides practical local idempotency and restart recovery for the proof-of-concept flow.
