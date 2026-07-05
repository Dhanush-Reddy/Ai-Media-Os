"""Optional LangGraph workflow adapter.

The adapter keeps LangGraph imports isolated from the rest of the application. This proof of concept
delegates persistence and transitions to the same repository-backed workflow core used by the simple
orchestrator because LangGraph is optional and not required for normal installs.
"""

from importlib.util import find_spec

from sqlalchemy.orm import Session

from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.workflows.simple_orchestrator import SimpleWorkflowOrchestrator


class LangGraphWorkflowOrchestrator(SimpleWorkflowOrchestrator):
    """LangGraph-shaped adapter around the existing workflow service boundary."""

    def __init__(self, session: Session, settings: AppSettings | None = None) -> None:
        super().__init__(session, settings)
        self.langgraph_available = find_spec("langgraph") is not None
