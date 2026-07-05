from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError, StatementError
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.domain.enums import (
    AssetType,
    ContentFormat,
    ContentType,
    JobStatus,
    LicenseStatus,
    RenderStatus,
    RenderType,
    ResearchNoteType,
    ResourceClass,
    VersionStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Approval,
    Asset,
    CacheEntry,
    Channel,
    Claim,
    ClaimSource,
    ContentVersion,
    Job,
    JobDependency,
    PromptTemplate,
    Render,
    ResearchNote,
    Scene,
    Source,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.utils.hashing import hash_prompt_template


@pytest.fixture()
def engine(tmp_path: Path) -> Generator[Engine]:
    settings = AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
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
    database_session = session_factory()
    try:
        yield database_session
    finally:
        database_session.close()


def test_database_initialization_creates_expected_tables(engine: Engine) -> None:
    expected_tables = {
        "channels",
        "video_projects",
        "content_versions",
        "approvals",
        "sources",
        "research_notes",
        "claims",
        "claim_sources",
        "scenes",
        "assets",
        "jobs",
        "job_dependencies",
        "cache_entries",
        "prompt_templates",
        "renders",
    }

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table'")
        ).scalars()

    assert expected_tables.issubset(set(rows))


def test_sqlite_wal_mode_is_enabled(engine: Engine) -> None:
    with engine.connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode")).scalar_one()

    assert journal_mode == "wal"


def test_sqlite_foreign_keys_are_enforced(engine: Engine) -> None:
    with engine.connect() as connection:
        foreign_keys = connection.execute(text("PRAGMA foreign_keys")).scalar_one()

    assert foreign_keys == 1


def test_foreign_key_violation_fails(session: Session) -> None:
    project = VideoProject(
        channel_id="missing-channel",
        working_title="Future of AI",
        topic="AI model progress",
    )
    session.add(project)

    with pytest.raises(IntegrityError):
        session.commit()


def test_utc_timestamp_defaults_are_timezone_aware(session: Session) -> None:
    channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
    session.add(channel)
    session.commit()
    channel_id = channel.id
    session.expire_all()
    reloaded_channel = session.get(Channel, channel_id)

    assert reloaded_channel is not None
    assert reloaded_channel.created_at.tzinfo is not None
    assert reloaded_channel.updated_at.tzinfo is not None


def test_invalid_enum_value_fails(session: Session) -> None:
    channel = Channel(
        name="AI & Future",
        slug="ai-and-future",
        niche="AI",
        status="not-a-status",
    )
    session.add(channel)

    with pytest.raises((IntegrityError, StatementError)):
        session.commit()


def test_parent_delete_does_not_cascade_project_data(session: Session) -> None:
    channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
    project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
    session.add(project)
    session.commit()

    session.delete(channel)

    with pytest.raises(IntegrityError):
        session.commit()


def test_job_requires_video_project(session: Session) -> None:
    job = Job(job_type="generate_script")
    session.add(job)

    with pytest.raises(IntegrityError):
        session.commit()


def test_model_creation_and_relationships(session: Session) -> None:
    channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI", language="en")
    project = VideoProject(
        channel=channel,
        working_title="AI weekly briefing",
        topic="New AI tools and research",
        target_duration_seconds=600,
    )
    content_version = ContentVersion(
        video_project=project,
        content_type=ContentType.SCRIPT,
        version_number=1,
        content="# Script",
        content_format=ContentFormat.MARKDOWN,
        status=VersionStatus.DRAFT,
        content_hash="a" * 64,
    )
    scene_plan = ContentVersion(
        video_project=project,
        content_type=ContentType.SCENE_PLAN,
        version_number=1,
        content="{}",
        content_format=ContentFormat.JSON,
        status=VersionStatus.DRAFT,
        content_hash="b" * 64,
    )
    approval = Approval(
        video_project=project, content_version=content_version, approval_type="script"
    )
    source = Source(
        video_project=project,
        url="https://example.com/source",
        canonical_url="https://example.com/source",
        authority_tier=1,
    )
    claim = Claim(video_project=project, claim_text="A verifiable claim.", confidence=0.9)
    claim_source = ClaimSource(claim=claim, source=source)
    note = ResearchNote(
        video_project=project,
        source=source,
        note_type=ResearchNoteType.KEY_POINT,
        content="A useful note.",
        content_hash="e" * 64,
    )
    scene = Scene(
        video_project=project,
        scene_plan_version=scene_plan,
        scene_number=1,
        narration="AI is changing quickly.",
        duration_seconds=5.5,
        visual_type=VisualType.GENERATED_IMAGE,
    )
    asset = Asset(
        video_project=project,
        scene=scene,
        asset_type=AssetType.IMAGE,
        file_path="data/projects/project/images/scene_001.png",
        license_status=LicenseStatus.SAFE,
    )
    first_job = Job(
        video_project=project,
        job_type="generate_script",
        status=JobStatus.READY,
        resource_class=ResourceClass.CPU_LIGHT,
    )
    second_job = Job(
        video_project=project,
        job_type="create_scene_plan",
        status=JobStatus.WAITING_FOR_DEPENDENCY,
        dependency_count=1,
    )
    dependency = JobDependency(job=second_job, depends_on_job=first_job)
    cache_entry = CacheEntry(
        cache_key="cache-key",
        provider="manual",
        model="manual",
        operation="script",
        input_hash="c" * 64,
        output_hash="d" * 64,
        output_path="data/cache/output.md",
    )
    prompt_template = PromptTemplate(
        name="long_form_script",
        category="script",
        version="v001",
        template_text="Write a script.",
        content_hash=hash_prompt_template("long_form_script", "v001", "Write a script."),
    )
    render = Render(
        video_project=project,
        render_type=RenderType.PREVIEW,
        version_number=1,
        status=RenderStatus.PENDING,
        output_path="data/projects/project/renders/preview_v001.mp4",
    )

    session.add_all(
        [
            channel,
            approval,
            claim_source,
            note,
            asset,
            dependency,
            cache_entry,
            prompt_template,
            render,
        ]
    )
    session.commit()

    assert project.channel == channel
    assert project.content_versions == [content_version, scene_plan]
    assert content_version.input_hashes == []
    assert project.approvals == [approval]
    assert claim.source_links == [claim_source]
    assert source.claim_links == [claim_source]
    assert source.research_notes == [note]
    assert scene.assets == [asset]
    assert second_job.dependencies == [dependency]


def test_unique_content_version_per_project_type_and_number(session: Session) -> None:
    channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
    project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
    first = ContentVersion(
        video_project=project,
        content_type=ContentType.SCRIPT,
        version_number=1,
        content="first",
        content_hash="a" * 64,
    )
    duplicate = ContentVersion(
        video_project=project,
        content_type=ContentType.SCRIPT,
        version_number=1,
        content="duplicate",
        content_hash="b" * 64,
    )
    session.add_all([first, duplicate])

    with pytest.raises(IntegrityError):
        session.commit()


def test_scene_constraints_reject_empty_narration(session: Session) -> None:
    channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
    project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
    scene_plan = ContentVersion(
        video_project=project,
        content_type=ContentType.SCENE_PLAN,
        version_number=1,
        content="{}",
        content_hash="a" * 64,
    )
    scene = Scene(
        video_project=project,
        scene_plan_version=scene_plan,
        scene_number=1,
        narration="   ",
        duration_seconds=1,
        visual_type=VisualType.GENERATED_IMAGE,
    )
    session.add(scene)

    with pytest.raises(IntegrityError):
        session.commit()
