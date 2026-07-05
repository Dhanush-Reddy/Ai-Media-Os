from pathlib import Path
from uuid import UUID

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import Channel, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.workflows.langgraph_orchestrator import LangGraphWorkflowOrchestrator
from ai_media_os.workflows.models import WorkflowStage, WorkflowStatus


def test_langgraph_adapter_starts_with_repository_backed_state(tmp_path: Path) -> None:
    settings = AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'langgraph.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
    )
    engine: Engine = create_db_engine(settings)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        with session_factory() as session:
            assert isinstance(session, Session)
            channel = Channel(name="AI & Future", slug="ai-future-langgraph", niche="AI")
            project = VideoProject(channel=channel, working_title="LangGraph", topic="AI")
            session.add(project)
            session.commit()
            orchestrator = LangGraphWorkflowOrchestrator(session, settings)

            workflow_id = orchestrator.start(UUID(project.id))
            state = orchestrator.get_state(workflow_id)

            assert state.current_stage == WorkflowStage.RESEARCH
            assert state.status == WorkflowStatus.RUNNING
            assert "langgraph_available" not in state.metadata
            assert isinstance(orchestrator.langgraph_available, bool)
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()
