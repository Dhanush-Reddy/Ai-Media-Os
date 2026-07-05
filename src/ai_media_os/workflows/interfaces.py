"""Provider-neutral workflow orchestration interfaces."""

from typing import Protocol
from uuid import UUID

from ai_media_os.workflows.models import WorkflowEvent, WorkflowState


class WorkflowOrchestrator(Protocol):
    def start(self, project_id: UUID) -> str:
        """Start a workflow for an existing video project and return its workflow ID."""
        ...

    def resume(self, workflow_id: str, event: WorkflowEvent) -> WorkflowState:
        """Apply a workflow event and return the current state."""
        ...

    def get_state(self, workflow_id: str) -> WorkflowState:
        """Return a persisted workflow state."""
        ...
