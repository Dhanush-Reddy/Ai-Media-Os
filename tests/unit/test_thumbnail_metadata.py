from collections.abc import Generator
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.packaging import MetadataService, PackagingError, ThumbnailService
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    AssetType,
    ContentFormat,
    ContentType,
    JobStatus,
    RenderStatus,
    RenderType,
    VersionStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Approval as ApprovalModel,
)
from ai_media_os.infrastructure.database.models import (
    Asset,
    Channel,
    ContentVersion,
    Render,
    Scene,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.ollama import OllamaStructuredOutputError
from ai_media_os.providers.ollama_content import (
    OllamaMetadataGenerationProvider,
    OllamaThumbnailConceptProvider,
)
from ai_media_os.providers.text_generation import TextGenerationRequest, TextGenerationResult
from ai_media_os.schemas.thumbnail import ThumbnailConceptDocument
from ai_media_os.schemas.video_metadata import ChapterItem, VideoMetadataDocument
from ai_media_os.workers.job_worker import JobHandler, JobWorker
from ai_media_os.workers.packaging_handlers import (
    JOB_GENERATE_FAKE_THUMBNAIL,
    JOB_GENERATE_THUMBNAIL_CONCEPT,
    JOB_GENERATE_VIDEO_METADATA,
    JOB_REVIEW_THUMBNAIL,
    JOB_VERIFY_THUMBNAIL_FILE,
    packaging_job_handlers,
)


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'packaging.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        thumbnail_default_width=64,
        thumbnail_default_height=36,
        asset_max_file_bytes=100_000,
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


def create_packaging_project(session: Session) -> tuple[str, str]:
    channel = Channel(name="AI & Future", slug="ai-future-packaging", niche="AI")
    project = VideoProject(
        channel=channel,
        working_title="AI Future Signals",
        topic="AI model launches and policy",
    )
    session.add(project)
    session.commit()
    versions = ContentVersionService(session)
    script = versions.create_initial_version(
        video_project_id=project.id,
        content_type=ContentType.SCRIPT,
        content="AI labs are shipping smaller useful models while regulators ask for proof.",
        content_format=ContentFormat.MARKDOWN,
    )
    scene_plan = versions.create_initial_version(
        video_project_id=project.id,
        content_type=ContentType.SCENE_PLAN,
        content='{"scenes":[{"scene_number":1}]}',
        content_format=ContentFormat.JSON,
    )
    script.status = VersionStatus.APPROVED
    scene_plan.status = VersionStatus.APPROVED
    scene = Scene(
        video_project_id=project.id,
        scene_plan_version_id=scene_plan.id,
        scene_number=1,
        start_seconds=0,
        narration="A concise opening explains what changed in AI this week.",
        duration_seconds=8,
        visual_type=VisualType.TEXT_GRAPHIC,
        visual_description="Bold editorial AI headline graphic",
    )
    render = Render(
        video_project_id=project.id,
        scene_plan_version_id=scene_plan.id,
        render_type=RenderType.FINAL,
        version_number=1,
        status=RenderStatus.RENDERED,
        output_path=f"projects/{project.id}/renders/render_v001.mp4",
        content_hash="a" * 64,
        input_hashes=["script", "scene"],
        settings={"resolution": "local-test"},
        metadata_json={"verified": True},
    )
    session.add_all([scene, render])
    session.commit()
    return project.id, render.id


def valid_metadata_json() -> str:
    return VideoMetadataDocument(
        platform="youtube",
        title="AI Future Signals This Week",
        title_ideas=["AI Future Signals This Week", "What Changed In AI"],
        description="A practical AI update for viewers.\n\nChapters:\n00:00 Opening",
        tags=["ai", "future", "models"],
        hashtags=["#AI", "#Future"],
        keywords=["ai", "future", "models"],
        chapters=[ChapterItem(start_seconds=0, title="Opening")],
        language="en",
        target_audience="AI & Future viewers",
        source_script_version_id="script-version",
        source_scene_plan_version_id="scene-plan-version",
        warnings=[],
    ).model_dump_json()


def revised_metadata_json() -> str:
    document = VideoMetadataDocument.model_validate_json(valid_metadata_json())
    return document.model_copy(update={"title": "AI Future Signals Revised"}).model_dump_json()


class StubTextProvider:
    provider_name = "ollama"
    model_name = "qwen3:8b"
    model_version = "qwen3:8b"
    prompt_version = "ollama-generate-v1"

    def __init__(self, text: str) -> None:
        self.text = text
        self.provider_settings: dict[str, Any] = {"temperature": 0.4}

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        return TextGenerationResult(
            text=self.text,
            provider=self.provider_name,
            model=self.model_name,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            provider_settings={**self.provider_settings, **request.provider_settings},
        )


def test_mocked_ollama_metadata_and_thumbnail_concept_services(
    session: Session, settings: AppSettings
) -> None:
    project_id, render_id = create_packaging_project(session)
    versions = ContentVersionService(session)
    script = versions.approved_version(project_id, ContentType.SCRIPT)
    scene_plan = versions.approved_version(project_id, ContentType.SCENE_PLAN)
    assert script is not None and scene_plan is not None
    metadata_document = VideoMetadataDocument(
        title="AI Future Signals",
        title_ideas=["AI Future Signals", "What Changed In AI"],
        description="A grounded update based on the approved script.",
        tags=["ai", "future"],
        hashtags=["#AI"],
        chapters=[ChapterItem(start_seconds=0, title="Opening")],
        language="en",
        target_audience="AI & Future viewers",
        keywords=["ai", "future"],
        source_script_version_id=script.id,
        source_scene_plan_version_id=scene_plan.id,
        source_render_id=render_id,
        warnings=[],
    )
    metadata_provider = OllamaMetadataGenerationProvider(
        StubTextProvider(metadata_document.model_dump_json()), 30
    )
    metadata = MetadataService(session, settings, metadata_provider).generate_metadata(
        project_id, render_id=render_id
    )
    replay = MetadataService(session, settings, metadata_provider).generate_metadata(
        project_id, render_id=render_id
    )
    assert metadata.id == replay.id
    assert metadata.provider == "ollama"

    concept_document = ThumbnailConceptDocument(
        concept_title="AI Future Signals thumbnail",
        text_options=["AI CHANGED AGAIN"],
        selected_text="AI CHANGED AGAIN",
        visual_description="Original editorial AI signal illustration.",
        emotional_hook="Curiosity",
        background_idea="High contrast signal grid",
        foreground_subject="Original AI signal block",
        composition_notes="Text left and visual right.",
        style_notes="Clean, original, no third-party logos.",
        source_metadata_version_id=metadata.id,
        warnings=[],
    )
    concept_provider = OllamaThumbnailConceptProvider(
        StubTextProvider(concept_document.model_dump_json()), 30
    )
    concept = ThumbnailService(
        session, settings, concept_provider=concept_provider
    ).generate_concept(project_id, metadata_version_id=metadata.id)
    assert concept.provider == "ollama"


def test_invalid_ollama_metadata_creates_no_version_or_approval(
    session: Session, settings: AppSettings
) -> None:
    project_id, render_id = create_packaging_project(session)
    version_count = session.scalar(select(func.count()).select_from(ContentVersion))
    approval_count = session.scalar(select(func.count()).select_from(ApprovalModel))
    provider = OllamaMetadataGenerationProvider(StubTextProvider("{}"), 30)

    with pytest.raises(OllamaStructuredOutputError):
        MetadataService(session, settings, provider).generate_metadata(
            project_id, render_id=render_id
        )

    assert session.scalar(select(func.count()).select_from(ContentVersion)) == version_count
    assert session.scalar(select(func.count()).select_from(ApprovalModel)) == approval_count


def test_metadata_schema_rejects_public_safety_issues() -> None:
    with pytest.raises(ValidationError):
        VideoMetadataDocument(
            platform="youtube",
            title="A" * 101,
            title_ideas=["Good title"],
            description="bad local path C:\\Users\\me\\secret.txt",
            tags=["ai", "AI"],
            hashtags=["AI"],
            keywords=["ai"],
            chapters=[
                ChapterItem(start_seconds=10, title="Later"),
                ChapterItem(start_seconds=5, title="Earlier"),
            ],
            language="en",
            target_audience="AI & Future viewers",
            source_script_version_id="script-version",
            source_scene_plan_version_id="scene-plan-version",
            warnings=[],
        )


def test_metadata_generation_is_idempotent_and_requests_approval(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, render_id = create_packaging_project(session)
    service = MetadataService(session, settings)

    first = service.generate_metadata(project_id, render_id=render_id, keyword_hints=["policy"])
    second = service.generate_metadata(project_id, render_id=render_id, keyword_hints=["policy"])

    assert first.id == second.id
    assert first.content_type == ContentType.METADATA
    assert first.status == VersionStatus.PENDING_APPROVAL
    approval = session.scalar(
        select(ApprovalModel).where(ApprovalModel.content_version_id == first.id)
    )
    assert approval is not None
    assert approval.approval_type == ApprovalType.METADATA
    assert approval.status == ApprovalStatus.PENDING
    document = VideoMetadataDocument.model_validate_json(first.content)
    assert document.title
    assert any(item.casefold() == "#ai" for item in document.hashtags)


def test_metadata_revision_can_use_approved_parent(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _render_id = create_packaging_project(session)
    original = MetadataService(session, settings).import_metadata(project_id, valid_metadata_json())
    approval = session.scalar(
        select(ApprovalModel).where(ApprovalModel.content_version_id == original.id)
    )
    assert approval is not None
    ApprovalService(session).approve(approval.id, reviewer="test")

    revised = MetadataService(session, settings).revise_metadata(
        original.id,
        revised_metadata_json(),
    )

    assert revised.id != original.id
    assert revised.parent_version_id == original.id
    assert original.status == VersionStatus.APPROVED
    assert revised.status == VersionStatus.PENDING_APPROVAL


def test_thumbnail_concept_and_fake_png_are_verifiable(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _render_id = create_packaging_project(session)
    metadata = MetadataService(session, settings).import_metadata(project_id, valid_metadata_json())
    service = ThumbnailService(session, settings)

    concept = service.generate_concept(project_id, metadata_version_id=metadata.id)
    same_concept = service.generate_concept(project_id, metadata_version_id=metadata.id)
    asset = service.generate_thumbnail(
        project_id,
        metadata_version_id=metadata.id,
        concept_version_id=concept.id,
        seed=11,
    )
    same_asset = service.generate_thumbnail(
        project_id,
        metadata_version_id=metadata.id,
        concept_version_id=concept.id,
        seed=11,
    )

    assert concept.id == same_concept.id
    assert same_asset.id == asset.id
    assert concept.content_type == ContentType.THUMBNAIL_CONCEPT
    assert ThumbnailConceptDocument.model_validate_json(concept.content).selected_text
    assert asset.asset_type == AssetType.THUMBNAIL
    assert asset.asset_role == AssetRole.THUMBNAIL
    assert asset.generation_status == AssetGenerationStatus.GENERATED
    assert asset.review_status == AssetReviewStatus.PENDING_REVIEW
    assert asset.width == 64
    assert asset.height == 36
    path = settings.data_dir / asset.file_path
    assert path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert service.verify_thumbnail_file(asset.id).ok


def test_thumbnail_import_and_review_flow(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _render_id = create_packaging_project(session)
    metadata = MetadataService(session, settings).import_metadata(project_id, valid_metadata_json())
    concept = ThumbnailService(session, settings).generate_concept(
        project_id,
        metadata_version_id=metadata.id,
    )
    generated = ThumbnailService(session, settings).generate_thumbnail(
        project_id,
        metadata_version_id=metadata.id,
        concept_version_id=concept.id,
    )
    source_path = settings.data_dir / generated.file_path

    imported = ThumbnailService(session, settings).import_thumbnail(
        project_id,
        source_path,
        metadata_version_id=metadata.id,
        concept_version_id=concept.id,
    )
    assert imported.id != generated.id
    assert imported.generation_status == AssetGenerationStatus.IMPORTED
    approved = ThumbnailService(session, settings).review_thumbnail(
        imported.id,
        AssetReviewStatus.APPROVED,
    )

    assert approved.review_status == AssetReviewStatus.APPROVED
    assert approved.generation_status == AssetGenerationStatus.APPROVED


def test_thumbnail_import_rejects_unsafe_or_unsupported_source(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, _render_id = create_packaging_project(session)
    service = ThumbnailService(session, settings)
    bad_file = settings.data_dir / "bad.txt"
    bad_file.parent.mkdir(parents=True, exist_ok=True)
    bad_file.write_text("not an image", encoding="utf-8")

    with pytest.raises(PackagingError, match="Unsupported thumbnail extension"):
        service.import_thumbnail(project_id, bad_file)
    with pytest.raises(PackagingError, match="path traversal"):
        service.import_thumbnail(project_id, Path("..") / "thumb.png")


def test_packaging_worker_handlers_create_outputs(
    session: Session,
    settings: AppSettings,
) -> None:
    project_id, render_id = create_packaging_project(session)
    queue = QueueService(session, settings)
    handlers = cast(dict[str, JobHandler], packaging_job_handlers())
    worker = JobWorker(session, handlers=handlers, settings=settings, worker_id="packaging-test")
    metadata_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_GENERATE_VIDEO_METADATA,
        payload={"render_id": render_id},
    )
    assert worker.run_once()
    session.refresh(metadata_job)
    assert metadata_job.result is not None
    metadata_id = str(metadata_job.result["content_version_id"])

    concept_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_GENERATE_THUMBNAIL_CONCEPT,
        payload={"metadata_version_id": metadata_id},
    )
    assert worker.run_once()
    session.refresh(concept_job)
    assert concept_job.result is not None
    concept_id = str(concept_job.result["content_version_id"])

    thumbnail_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_GENERATE_FAKE_THUMBNAIL,
        payload={"metadata_version_id": metadata_id, "concept_version_id": concept_id},
    )
    assert worker.run_once()
    session.refresh(thumbnail_job)
    assert thumbnail_job.result is not None
    asset_id = str(thumbnail_job.result["asset_id"])

    verify_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_VERIFY_THUMBNAIL_FILE,
        payload={"asset_id": asset_id},
    )
    review_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_REVIEW_THUMBNAIL,
        payload={"asset_id": asset_id, "review_status": AssetReviewStatus.APPROVED.value},
    )
    assert worker.run_once()
    assert worker.run_once()
    session.refresh(verify_job)
    session.refresh(review_job)

    assert metadata_job.status == JobStatus.COMPLETED
    assert concept_job.status == JobStatus.COMPLETED
    assert thumbnail_job.status == JobStatus.COMPLETED
    assert verify_job.result is not None
    assert review_job.result is not None
    assert verify_job.result["ok"] is True
    assert review_job.result["review_status"] == AssetReviewStatus.APPROVED.value
    asset = session.get(Asset, asset_id)
    assert asset is not None
    assert asset.review_status == AssetReviewStatus.APPROVED
