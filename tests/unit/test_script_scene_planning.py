from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.research import ClaimService, SourceService
from ai_media_os.application.scenes import (
    ScenePlanningError,
    ScenePlanService,
    _split_visual_narration_segments,
)
from ai_media_os.application.scripts import ScriptGenerationService, ScriptPlanningError
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    JobStatus,
    SourceStatus,
    SourceType,
    VerificationStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Approval,
    Channel,
    ContentVersion,
    Scene,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.ollama import OllamaConnectionError
from ai_media_os.providers.text_generation import (
    LocalRuleBasedTextProvider,
    TextGenerationCancelledError,
    TextGenerationRequest,
    TextGenerationResult,
)
from ai_media_os.schemas.scene_plan import ScenePlanDocument
from ai_media_os.storage.filesystem import FileStorage
from ai_media_os.workers import script_scene_handlers as script_handlers
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workers.script_scene_handlers import (
    JOB_GENERATE_SCENE_PLAN,
    JOB_GENERATE_SCRIPT,
    script_scene_job_handlers,
)


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'script_scene.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
    )


@pytest.fixture()
def engine(settings: AppSettings) -> Generator[Engine]:
    database_engine = create_db_engine(settings)
    Base.metadata.create_all(database_engine)
    try:
        yield database_engine
    finally:
        Base.metadata.drop_all(database_engine)
        database_engine.dispose()


@pytest.fixture()
def session(engine: Engine) -> Generator[Session]:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as database_session:
        yield database_session


@pytest.fixture()
def project_id(session: Session, settings: AppSettings) -> str:
    channel = Channel(name="AI & Future", slug="ai-future-script", niche="AI")
    project = VideoProject(
        channel=channel,
        working_title="AI planning episode",
        topic="agentic AI planning systems",
        target_duration_seconds=420,
    )
    session.add(project)
    session.commit()
    source_service = SourceService(session, FileStorage(settings), settings)
    source = source_service.import_source(
        video_project_id=project.id,
        url="https://example.gov/agentic-ai",
        title="Agentic AI report",
        publisher="Example Gov",
        source_type=SourceType.GOVERNMENT,
        text="Agentic AI planning systems are being evaluated by enterprises.",
    ).source
    source_service.update_source_status(source.id, SourceStatus.APPROVED)
    claim_service = ClaimService(session)
    claim = claim_service.create_claim(
        video_project_id=project.id,
        claim_text="Agentic AI planning systems are being evaluated by enterprises.",
        importance=ClaimImportance.HIGH,
    )
    claim_service.link_source(
        claim_id=claim.id,
        source_id=source.id,
        support_type=ClaimSupportType.PRIMARY_EVIDENCE,
    )
    claim_service.update_verification_status(claim.id, VerificationStatus.VERIFIED)
    return project.id


def test_script_generation_requests_approval_and_is_idempotent(
    session: Session,
    project_id: str,
) -> None:
    service = ScriptGenerationService(session)
    first = service.generate_script(project_id)
    second = service.generate_script(project_id)

    assert second.id == first.id
    assert first.content_type == ContentType.SCRIPT
    assert first.status == VersionStatus.PENDING_APPROVAL
    approval = session.query(Approval).filter_by(content_version_id=first.id).one()
    assert approval.approval_type == ApprovalType.SCRIPT
    assert approval.status == ApprovalStatus.PENDING


def test_script_fingerprint_includes_provider_settings(
    session: Session,
    project_id: str,
) -> None:
    first = ScriptGenerationService(
        session, provider_settings={"profile": "concise"}
    ).generate_script(project_id)
    second = ScriptGenerationService(
        session, provider_settings={"profile": "documentary"}
    ).generate_script(project_id)

    assert second.id != first.id


def test_text_provider_has_typed_cancellation_failure() -> None:
    class Cancelled:
        is_cancelled = True

    with pytest.raises(TextGenerationCancelledError):
        LocalRuleBasedTextProvider().generate(
            TextGenerationRequest(prompt="test", cancellation_token=Cancelled())
        )


class StubTextProvider:
    provider_name = "ollama"
    model_name = "qwen3:8b"
    model_version = "qwen3:8b"
    prompt_version = "ollama-generate-v1"

    def __init__(self, text: str, *, model_name: str = "qwen3:8b") -> None:
        self.text = text
        self.model_name = model_name
        self.model_version = model_name
        self.provider_settings: dict[str, Any] = {"temperature": 0.4}
        self.requests: list[TextGenerationRequest] = []

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        self.requests.append(request)
        return TextGenerationResult(
            text=self.text,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            provider_settings={**self.provider_settings, **request.provider_settings},
        )


class FailingTextProvider(StubTextProvider):
    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        raise OllamaConnectionError("Could not connect to the local Ollama server.")


def test_mocked_ollama_script_generation_and_short_output_rejection(
    session: Session, project_id: str
) -> None:
    generated = "# Local Script\n\n" + ("AI planning systems need grounded evidence. " * 8)
    provider = StubTextProvider(generated)
    service = ScriptGenerationService(session, provider)
    first = service.generate_script(project_id)
    replay = service.generate_script(project_id)

    assert first.id == replay.id
    assert first.provider == "ollama"
    assert first.model == "qwen3:8b"
    assert provider.requests[0].system_prompt is not None
    assert provider.requests[0].target_words is not None
    approval = session.scalar(select(Approval).where(Approval.content_version_id == first.id))
    assert approval is not None
    ApprovalService(session).approve(approval.id, reviewer="test")
    approved_replay = service.generate_script(project_id)
    assert approved_replay.id == first.id
    assert approved_replay.status == VersionStatus.APPROVED
    with pytest.raises(ScriptPlanningError, match="too short"):
        ScriptGenerationService(
            session, StubTextProvider("too short", model_name="other:8b")
        ).generate_script(project_id)


def test_mocked_ollama_scene_plan_is_strict_and_atomic(
    session: Session, project_id: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    script = ScriptGenerationService(session).generate_script(project_id)
    approval = session.scalar(select(Approval).where(Approval.content_version_id == script.id))
    assert approval is not None
    ApprovalService(session).approve(approval.id, reviewer="test")
    document = ScenePlanDocument.model_validate(
        {
            "video_project_id": project_id,
            "script_content_version_id": script.id,
            "total_duration_seconds": 8,
            "scenes": [
                {
                    "scene_number": 1,
                    "start_seconds": 0,
                    "duration_seconds": 8,
                    "narration": "A grounded opening about agentic AI planning systems.",
                    "visual_type": "diagram",
                    "visual_description": "An original planning workflow diagram.",
                }
            ],
        }
    )
    service = ScenePlanService(session, StubTextProvider(document.model_dump_json()))
    version = service.generate_scene_plan(project_id, script_version_id=script.id)
    assert version.provider == "ollama"
    assert len(service.list_scenes(version.id)) == 1

    version_count = session.scalar(select(func.count()).select_from(ContentVersion))
    scene_count = session.scalar(select(func.count()).select_from(Scene))
    invalid_service = ScenePlanService(
        session, StubTextProvider("not-json", model_name="invalid:8b")
    )
    with pytest.raises(ScenePlanningError, match="invalid"):
        invalid_service.generate_scene_plan(project_id, script_version_id=script.id)
    assert session.scalar(select(func.count()).select_from(ContentVersion)) == version_count
    assert session.scalar(select(func.count()).select_from(Scene)) == scene_count

    failing_service = ScenePlanService(
        session, StubTextProvider(document.model_dump_json(), model_name="db-failure:8b")
    )

    def fail_scene_insert(*_args: object) -> None:
        raise RuntimeError("scene insert failed")

    monkeypatch.setattr(failing_service, "_replace_scenes", fail_scene_insert)
    with pytest.raises(RuntimeError, match="scene insert failed"):
        failing_service.generate_scene_plan(project_id, script_version_id=script.id)
    assert session.scalar(select(func.count()).select_from(ContentVersion)) == version_count
    assert session.scalar(select(func.count()).select_from(Scene)) == scene_count

    unavailable_service = ScenePlanService(
        session, FailingTextProvider("unused", model_name="offline:8b")
    )
    with pytest.raises(OllamaConnectionError):
        unavailable_service.generate_scene_plan(project_id, script_version_id=script.id)
    assert session.scalar(select(func.count()).select_from(ContentVersion)) == version_count
    assert session.scalar(select(func.count()).select_from(Scene)) == scene_count


def test_ollama_queue_failure_is_safe_and_retryable(
    session: Session,
    settings: AppSettings,
    project_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        script_handlers,
        "build_text_provider",
        lambda *_args: FailingTextProvider("unused"),
    )
    queue = QueueService(session, settings)
    job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_GENERATE_SCRIPT,
        payload={"provider": "ollama", "model": "qwen3:8b"},
    )
    worker = JobWorker(
        session,
        handlers=script_scene_job_handlers(),
        settings=settings,
        worker_id="ollama-failure-worker",
    )

    result = worker.run_once()
    session.refresh(job)
    assert result.failed is True
    assert job.status == JobStatus.RETRYING
    assert job.last_error_type == "OllamaConnectionError"
    assert job.last_error_message == "Could not connect to the local Ollama server."
    assert session.scalar(select(func.count()).where(ContentVersion.provider == "ollama")) == 0


def test_script_generation_requires_research_readiness(session: Session) -> None:
    channel = Channel(name="AI & Future Draft", slug="ai-future-draft", niche="AI")
    project = VideoProject(channel=channel, working_title="Draft", topic="AI rumor")
    session.add(project)
    session.commit()

    with pytest.raises(ScriptPlanningError):
        ScriptGenerationService(session).generate_script(project.id)


def test_fact_check_quality_and_scene_plan_flow(
    session: Session,
    project_id: str,
) -> None:
    script = ScriptGenerationService(session).generate_script(project_id)
    approval = session.query(Approval).filter_by(content_version_id=script.id).one()
    ApprovalService(session).approve(approval.id, reviewer="test")
    session.refresh(script)

    report = ScriptGenerationService(session).generate_fact_check_report(project_id)
    quality = ScriptGenerationService(session).evaluate_script_quality(project_id)
    scene_plan = ScenePlanService(session).generate_scene_plan(project_id)
    parsed = ScenePlanDocument.model_validate_json(scene_plan.content)
    scenes = ScenePlanService(session).list_scenes(scene_plan.id)

    assert script.status == VersionStatus.APPROVED
    assert report.content_type == ContentType.FACT_CHECK_REPORT
    assert quality.passed is True
    assert scene_plan.content_type == ContentType.SCENE_PLAN
    assert scene_plan.status == VersionStatus.PENDING_APPROVAL
    assert len(parsed.scenes) == len(scenes)
    assert scenes[0].start_seconds == 0
    assert scenes[0].visual_description


def test_scene_schema_rejects_nonsequential_scenes(project_id: str) -> None:
    with pytest.raises(ValueError):
        ScenePlanDocument.model_validate(
            {
                "video_project_id": project_id,
                "script_content_version_id": "script-id",
                "total_duration_seconds": 12,
                "scenes": [
                    {
                        "scene_number": 2,
                        "start_seconds": 0,
                        "duration_seconds": 12,
                        "narration": "Opening",
                        "visual_type": "generated_image",
                        "visual_description": "Opening visual",
                    }
                ],
            }
        )


def test_script_scene_worker_handlers(
    session: Session, settings: AppSettings, project_id: str
) -> None:
    queue = QueueService(session, settings)
    script_job = queue.create_job(video_project_id=project_id, job_type=JOB_GENERATE_SCRIPT)
    worker = JobWorker(
        session,
        handlers=script_scene_job_handlers(),
        settings=settings,
        worker_id="script-scene-worker",
    )

    assert worker.run_once().completed is True
    session.refresh(script_job)
    assert script_job.status == JobStatus.COMPLETED
    script_version_id = str(script_job.result["content_version_id"])
    approval = session.query(Approval).filter_by(content_version_id=script_version_id).one()
    ApprovalService(session).approve(approval.id, reviewer="test")

    scene_job = queue.create_job(video_project_id=project_id, job_type=JOB_GENERATE_SCENE_PLAN)
    assert worker.run_once().completed is True
    session.refresh(scene_job)
    assert scene_job.result is not None
    assert scene_job.result["scene_count"] > 0
    scene_version = session.get(ContentVersion, scene_job.result["content_version_id"])
    assert scene_version is not None
    assert scene_version.content_type == ContentType.SCENE_PLAN


def test_visual_narration_segments_create_distinct_short_shots() -> None:
    segments = _split_visual_narration_segments(
        "Coolant can be full, but it still needs to circulate. "
        "A blocked radiator traps heat inside the engine."
    )

    assert segments == [
        "Coolant can be full, but it still needs to circulate.",
        "A blocked radiator traps heat inside the engine.",
    ]


def test_rule_based_scene_timing_has_no_rounding_overlap(session: Session, project_id: str) -> None:
    script = ContentVersion(
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        version_number=99,
        content=(
            "A full coolant tank does not guarantee a cool engine. "
            "The liquid must keep moving and release its heat.\n\n"
            "If this small valve stays shut, hot coolant remains trapped inside the engine."
        ),
        content_format=ContentFormat.MARKDOWN,
        status=VersionStatus.APPROVED,
        content_hash="a" * 64,
    )
    session.add(script)
    session.flush()

    document = ScenePlanService(session)._build_scene_document(project_id, script, [])

    assert all(
        following.start_seconds >= round(current.start_seconds + current.duration_seconds, 2)
        for current, following in zip(document.scenes, document.scenes[1:], strict=False)
    )
