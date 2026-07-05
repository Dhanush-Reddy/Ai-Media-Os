# Workflow Orchestration Evaluation

## Status

Proof of concept complete.

## Goal

Evaluate whether LangGraph should become an optional workflow orchestration layer for AI Media OS without replacing the existing SQLite, SQLAlchemy, Alembic, database-backed queue, workers, retries, resource scheduling, approvals, content versioning, cache, filesystem storage, or CLI.

The intended boundary is:

```text
LangGraph or simple orchestrator
    ->
Logical workflow coordination
    ->
Application services
    ->
Existing job queue
    ->
Workers and providers
```

## Proof-of-Concept Workflow

The proof of concept models only:

```text
START
    ->
RESEARCH
    ->
SCRIPT
    ->
WAIT_FOR_SCRIPT_APPROVAL
        APPROVED -> COMPLETE
        CHANGES_REQUESTED -> SCRIPT_REVISION -> WAIT_FOR_SCRIPT_APPROVAL
        REJECTED -> REJECTED
```

It uses fake job types and existing content-version and approval records. It does not implement real research, script generation, prompt rendering, scene planning, AI providers, publishing, or media generation.

## Interface

The orchestration boundary is provider-neutral:

```python
class WorkflowOrchestrator(Protocol):
    def start(self, project_id: UUID) -> str: ...
    def resume(self, workflow_id: str, event: WorkflowEvent) -> WorkflowState: ...
    def get_state(self, workflow_id: str) -> WorkflowState: ...
```

The application can use `SimpleWorkflowOrchestrator` or `LangGraphWorkflowOrchestrator` through the same interface.

## Persistence

Workflow state is persisted in SQLite through SQLAlchemy models and Alembic migration `0004_workflow_orchestration_evaluation`.

Tables:

* `workflow_instances`
* `workflow_event_records`

The state stores IDs and references only. Large content remains in existing tables and filesystem storage.

This approach was chosen over LangGraph-specific persistence because it keeps the proof of concept aligned with the existing SQLite/Alembic architecture and avoids introducing a second persistence model for a small evaluation.

## Human Approval

The workflow pauses at `WAIT_FOR_SCRIPT_APPROVAL` after script completion creates an existing `Approval` record. A later `SCRIPT_APPROVED`, `SCRIPT_CHANGES_REQUESTED`, or `SCRIPT_REJECTED` event resumes the workflow.

The integration test reconstructs the orchestrator with a new SQLAlchemy session before sending approval, demonstrating restart recovery.

## Idempotency

Processed workflow events are stored by `workflow_id + event_id`.

Replaying the same processed event returns the existing state and does not create duplicate jobs or approvals. Terminal workflows return their terminal state without creating new work.

This is practical idempotency, not generalized distributed workflow recovery.

## Simple Orchestrator Evaluation

* Lines of code: moderate, mostly explicit transition handling.
* State transitions: clear `match` branch per event.
* Ease of understanding: high; transitions are visible in one service.
* Persistence complexity: low; uses SQLAlchemy models and Alembic.
* Testing complexity: low; temporary SQLite databases are enough.
* Human approval handling: direct use of existing approval service.
* Restart recovery: works through persisted workflow state.
* Dependency footprint: none beyond existing stack.

## LangGraph Adapter Evaluation

* Lines of code: currently minimal because the adapter delegates to the same persisted transition core.
* State transitions: not yet materially improved by graph syntax for this small workflow.
* Ease of understanding: no clear improvement at the current workflow size.
* Persistence complexity: LangGraph persistence would add another persistence concept unless carefully adapted.
* Testing complexity: would increase if real LangGraph graph/checkpointer behavior becomes part of normal tests.
* Human approval handling: still needs existing approval records and explicit resume events.
* Restart recovery: best handled through existing repository-backed state for now.
* Dependency footprint: optional only through `workflow-langgraph`; normal installs do not need it.

## Recommendation

`ADOPT LATER`

LangGraph may become useful once workflows include branching, multiple resumable human checkpoints, richer agent coordination, and reusable graph tooling. For the current MVP proof of concept, the simple persisted orchestrator is easier to understand, cheaper to test, and better aligned with the existing infrastructure.

Do not make LangGraph a required dependency yet. Keep it isolated behind the adapter boundary and revisit after Milestone 4 or later workflow complexity proves that graph semantics reduce maintenance burden.

## Non-Goals Confirmed

This evaluation did not implement Milestone 4, the Content Safety and Rights Engine, real research collection, web extraction, AI text generation, prompt rendering, scene planning, image generation, TTS, FFmpeg, Telegram, publishing, analytics, Shorts, frontend, Docker, PostgreSQL, Redis, Celery, or cloud services.
