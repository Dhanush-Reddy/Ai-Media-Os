from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.approvals import ApprovalError, ApprovalService
from ai_media_os.application.content_versions import ContentVersionError, ContentVersionService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.prompt_templates import PromptTemplateError, PromptTemplateService
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ContentFormat,
    ContentType,
    JobStatus,
    PromptTemplateStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import Channel, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'versions.db'}",
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
def project_id(session: Session) -> str:
    channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
    project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
    session.add(project)
    session.commit()
    return project.id


def test_content_version_creation_revision_parent_rules_and_history(
    session: Session,
    project_id: str,
) -> None:
    service = ContentVersionService(session)
    first = service.create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="draft",
        content_format=ContentFormat.MARKDOWN,
    )
    second = service.create_revision(
        parent_version_id=first.id,
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="draft 2",
        content_format=ContentFormat.MARKDOWN,
    )

    assert first.version_number == 1
    assert second.version_number == 2
    latest = service.latest_version(project_id, ContentType.SCRIPT)
    assert latest is not None
    assert latest.id == second.id
    assert [item.id for item in service.version_history(project_id, ContentType.SCRIPT)] == [
        first.id,
        second.id,
    ]

    other_channel = Channel(name="Other", slug="other-channel", niche="AI")
    other_project = VideoProject(channel=other_channel, working_title="Other", topic="AI")
    session.add(other_project)
    session.commit()
    with pytest.raises(ContentVersionError):
        service.create_revision(
            parent_version_id=first.id,
            video_project_id=other_project.id,
            content_type=ContentType.SCRIPT,
            content="bad",
            content_format=ContentFormat.TEXT,
        )
    with pytest.raises(ContentVersionError):
        service.create_revision(
            parent_version_id=first.id,
            video_project_id=project_id,
            content_type=ContentType.SCENE_PLAN,
            content="bad",
            content_format=ContentFormat.JSON,
        )


def test_concurrent_version_creation_and_duplicate_prevention(
    engine: Engine,
    settings: AppSettings,
) -> None:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as setup:
        channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
        project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
        setup.add(project)
        setup.commit()
        project_id = project.id

    def create(content: str) -> int:
        with session_factory() as worker_session:
            version = ContentVersionService(worker_session).create_initial_version(
                video_project_id=project_id,
                content_type=ContentType.SCRIPT,
                content=content,
                content_format=ContentFormat.TEXT,
            )
            return version.version_number

    with ThreadPoolExecutor(max_workers=2) as executor:
        numbers = sorted(executor.map(create, ["one", "two"]))

    assert numbers == [1, 2]
    with session_factory() as check:
        first = ContentVersionService(check).latest_version(project_id, ContentType.SCRIPT)
        assert first is not None
        duplicate = first.__class__(
            video_project_id=project_id,
            content_type=ContentType.SCRIPT,
            version_number=first.version_number,
            content="duplicate",
            content_format=ContentFormat.TEXT,
            content_hash="a" * 64,
            input_hashes=[],
        )
        check.add(duplicate)
        with pytest.raises(IntegrityError):
            check.commit()


def test_version_immutability_and_approval_supersedes_previous(
    session: Session,
    project_id: str,
) -> None:
    service = ContentVersionService(session)
    first = service.create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="v1",
        content_format=ContentFormat.TEXT,
    )
    second = service.create_revision(
        parent_version_id=first.id,
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="v2",
        content_format=ContentFormat.TEXT,
    )
    service.approve_version(first.id)
    service.approve_version(second.id)
    session.refresh(first)
    session.refresh(second)
    assert first.status == VersionStatus.SUPERSEDED
    assert second.status == VersionStatus.APPROVED
    approved = service.approved_version(project_id, ContentType.SCRIPT)
    assert approved is not None
    assert approved.id == second.id

    changed = service.latest_version(project_id, ContentType.SCRIPT)
    assert changed is not None
    changed.content = "mutated"
    with pytest.raises(ContentVersionError):
        service.verify_immutable_fields(second, changed)


def test_approval_records_and_job_integration(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    content = ContentVersionService(session).create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="script",
        content_format=ContentFormat.MARKDOWN,
    )
    job = QueueService(session, settings).create_job(
        video_project_id=project_id, job_type="approve"
    )
    service = ApprovalService(session)
    approval = service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.SCRIPT,
        content_version_id=content.id,
        job_id=job.id,
    )
    session.refresh(job)
    assert approval.status == ApprovalStatus.PENDING
    assert job.status == JobStatus.WAITING_FOR_APPROVAL
    service.approve(approval.id, reviewer="human", feedback="ok")
    session.refresh(job)
    session.refresh(content)
    assert job.status.value == JobStatus.READY.value
    assert content.status == VersionStatus.APPROVED
    with pytest.raises(ApprovalError):
        service.reject(approval.id)


def test_approval_validation_and_duplicate_pending_requests(
    session: Session,
    project_id: str,
) -> None:
    script = ContentVersionService(session).create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="script",
        content_format=ContentFormat.MARKDOWN,
    )
    scene_plan = ContentVersionService(session).create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.SCENE_PLAN,
        content="{}",
        content_format=ContentFormat.JSON,
    )
    other_channel = Channel(name="Other", slug="other-validation", niche="AI")
    other_project = VideoProject(channel=other_channel, working_title="Other", topic="AI")
    session.add(other_project)
    session.commit()
    service = ApprovalService(session)

    service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.SCRIPT,
        content_version_id=script.id,
    )
    with pytest.raises(ApprovalError):
        service.request_approval(
            video_project_id=project_id,
            approval_type=ApprovalType.SCRIPT,
            content_version_id=script.id,
        )
    with pytest.raises(ApprovalError):
        service.request_approval(
            video_project_id=project_id,
            approval_type=ApprovalType.SCRIPT,
            content_version_id=scene_plan.id,
        )
    with pytest.raises(ApprovalError):
        service.request_approval(
            video_project_id=other_project.id,
            approval_type=ApprovalType.SCRIPT,
            content_version_id=script.id,
        )


def test_approval_transaction_rolls_back_related_status_changes(
    monkeypatch: pytest.MonkeyPatch,
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    content = ContentVersionService(session).create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="script",
        content_format=ContentFormat.MARKDOWN,
    )
    job = QueueService(session, settings).create_job(
        video_project_id=project_id, job_type="approve"
    )
    service = ApprovalService(session)
    approval = service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.SCRIPT,
        content_version_id=content.id,
        job_id=job.id,
    )

    def fail_approval(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated approval failure")

    monkeypatch.setattr(service.content_versions, "apply_approval_without_commit", fail_approval)
    with pytest.raises(RuntimeError, match="simulated approval failure"):
        service.approve(approval.id, reviewer="human")

    session.refresh(approval)
    session.refresh(content)
    session.refresh(job)
    assert approval.status == ApprovalStatus.PENDING
    assert content.status == VersionStatus.DRAFT
    assert job.status == JobStatus.WAITING_FOR_APPROVAL


def test_rejection_changes_expiration_publishing_and_pending_requests(
    session: Session,
    project_id: str,
) -> None:
    content = ContentVersionService(session).create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.SCENE_PLAN,
        content="{}",
        content_format=ContentFormat.JSON,
    )
    service = ApprovalService(session)
    with pytest.raises(ApprovalError):
        service.request_approval(video_project_id=project_id, approval_type=ApprovalType.SCRIPT)
    publishing = service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.PUBLISHING,
    )
    assert publishing.content_version_id is None
    rejected = service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.SCENE_PLAN,
        content_version_id=content.id,
    )
    assert service.pending_requests()
    service.request_changes(rejected.id, feedback="revise")
    session.refresh(rejected)
    assert rejected.feedback == "revise"
    expired = service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.SCENE_PLAN,
        content_version_id=content.id,
    )
    assert service.expire(expired.id).status == ApprovalStatus.EXPIRED


def test_prompt_template_versions_activation_and_immutability(session: Session) -> None:
    service = PromptTemplateService(session)
    first = service.create_prompt_version(
        name="script.long_form",
        category="script",
        template_text="Write a script",
    )
    second = service.create_prompt_version(
        name="script.long_form",
        category="script",
        template_text="Write a better script",
        parent_template_id=first.id,
    )
    service.activate_prompt(first.id)
    service.activate_prompt(second.id)
    session.refresh(first)
    session.refresh(second)
    assert first.version == "v001"
    assert second.version == "v002"
    assert first.status == PromptTemplateStatus.DEPRECATED
    assert second.status == PromptTemplateStatus.ACTIVE
    active_prompt = service.active_prompt("script.long_form")
    assert active_prompt is not None
    assert active_prompt.id == second.id
    assert len(service.prompt_history("script.long_form")) == 2
    second.template_text = "mutated"
    with pytest.raises(PromptTemplateError):
        service.verify_immutable(second, second)


def test_concurrent_version_approval_leaves_one_active_approved(
    engine: Engine,
) -> None:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as setup:
        channel = Channel(name="AI & Future", slug="ai-and-future", niche="AI")
        project = VideoProject(channel=channel, working_title="AI weekly", topic="AI")
        setup.add(project)
        setup.commit()
        service = ContentVersionService(setup)
        first = service.create_initial_version(
            video_project_id=project.id,
            content_type=ContentType.SCRIPT,
            content="v1",
            content_format=ContentFormat.TEXT,
        )
        second = service.create_revision(
            parent_version_id=first.id,
            video_project_id=project.id,
            content_type=ContentType.SCRIPT,
            content="v2",
            content_format=ContentFormat.TEXT,
        )
        version_ids = [first.id, second.id]
        project_id = project.id

    def approve(version_id: str) -> None:
        with session_factory() as worker_session:
            ContentVersionService(worker_session).approve_version(version_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(approve, version_ids))

    with session_factory() as check:
        approved = check.scalars(
            select(first.__class__).where(
                first.__class__.video_project_id == project_id,
                first.__class__.content_type == ContentType.SCRIPT,
                first.__class__.status == VersionStatus.APPROVED,
            )
        ).all()
        assert len(approved) == 1


def test_concurrent_prompt_activation_leaves_one_active_prompt(engine: Engine) -> None:
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as setup:
        service = PromptTemplateService(setup)
        first = service.create_prompt_version(
            name="script.long_form",
            category="script",
            template_text="Write a script",
        )
        second = service.create_prompt_version(
            name="script.long_form",
            category="script",
            template_text="Write a better script",
        )
        prompt_ids = [first.id, second.id]

    def activate(prompt_id: str) -> None:
        with session_factory() as worker_session:
            PromptTemplateService(worker_session).activate_prompt(prompt_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(activate, prompt_ids))

    with session_factory() as check:
        active = check.scalars(
            select(first.__class__).where(
                first.__class__.name == "script.long_form",
                first.__class__.status == PromptTemplateStatus.ACTIVE,
            )
        ).all()
        assert len(active) == 1
