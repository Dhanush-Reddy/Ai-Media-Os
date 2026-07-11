from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.research import (
    ClaimService,
    ResearchError,
    ResearchNoteService,
    ResearchReportService,
    SourceClassifier,
    SourceService,
    normalize_research_url,
    number_to_tier,
)
from ai_media_os.domain.enums import (
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    JobStatus,
    ResearchNoteType,
    SourceAuthorityTier,
    SourceStatus,
    SourceType,
    VerificationStatus,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import Channel, ResearchNote, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.storage.filesystem import FileStorage
from ai_media_os.workers.job_worker import JobWorker
from ai_media_os.workers.research_handlers import (
    JOB_EVALUATE_RESEARCH_READINESS,
    JOB_IMPORT_RESEARCH_SOURCE,
    research_job_handlers,
)


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'research.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        research_max_source_bytes=1000,
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


def source_service(session: Session, settings: AppSettings) -> SourceService:
    return SourceService(session, FileStorage(settings), settings)


def test_url_normalization_accepts_http_https_and_rejects_unsafe_schemes() -> None:
    assert (
        normalize_research_url("HTTPS://Example.COM?utm_source=x&id=7#section")
        == "https://example.com/?id=7"
    )
    assert normalize_research_url("http://Example.com/path?x=1") == "http://example.com/path?x=1"
    with pytest.raises(ResearchError):
        normalize_research_url("file:///tmp/source.txt")
    with pytest.raises(ResearchError):
        normalize_research_url("javascript:alert(1)")


def test_source_import_snapshot_duplicate_url_and_duplicate_content(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    service = source_service(session, settings)
    first = service.import_source(
        video_project_id=project_id,
        url="https://openai.com/index.html?utm_source=news&id=1#top",
        title="Official update",
        publisher="OpenAI",
        text="Source text\n",
    )
    assert first.source.canonical_url == "https://openai.com/index.html?id=1"
    assert first.source.snapshot_path is not None
    assert not Path(first.source.snapshot_path).is_absolute()
    assert first.source.content_hash is not None
    assert number_to_tier(first.source.authority_tier) == SourceAuthorityTier.TIER_1_PRIMARY

    with pytest.raises(ResearchError):
        service.import_source(
            video_project_id=project_id,
            url="https://OPENAI.com/index.html?id=1&utm_campaign=x",
            text="Other text",
        )

    duplicate = service.import_source(
        video_project_id=project_id,
        url="https://example.com/other",
        text="Source text",
    )
    assert duplicate.duplicate_content_source_id == first.source.id
    assert duplicate.source.duplicate_of_source_id == first.source.id

    other_channel = Channel(name="Other", slug="other-research", niche="AI")
    other_project = VideoProject(channel=other_channel, working_title="Other", topic="AI")
    session.add(other_project)
    session.commit()
    assert (
        service.import_source(
            video_project_id=other_project.id,
            url="https://openai.com/index.html?id=1",
            text="Source text",
        ).source.id
        != first.source.id
    )


def test_source_import_from_markdown_and_size_validation(
    session: Session,
    settings: AppSettings,
    project_id: str,
    tmp_path: Path,
) -> None:
    path = tmp_path / "source.md"
    path.write_text("# Source\n\nDetails", encoding="utf-8")
    service = source_service(session, settings)
    imported = service.import_source(
        video_project_id=project_id,
        url="https://example.com/manual",
        snapshot_file=path,
    )
    assert imported.source.content_hash is not None

    bad_path = tmp_path / "source.html"
    bad_path.write_text("bad", encoding="utf-8")
    with pytest.raises(ResearchError):
        service.import_source(
            video_project_id=project_id,
            url="https://example.com/bad",
            snapshot_file=bad_path,
        )
    with pytest.raises(ResearchError):
        service.import_source(
            video_project_id=project_id,
            url="https://example.com/large",
            text="x" * 1001,
        )


def test_rule_based_source_classification() -> None:
    classifier = SourceClassifier()
    assert classifier.classify(url="https://agency.gov/report").source_type == SourceType.GOVERNMENT
    assert (
        classifier.classify(url="https://arxiv.org/abs/123").source_type
        == SourceType.RESEARCH_PAPER
    )
    assert (
        classifier.classify(url="https://example.com/docs/api").source_type
        == SourceType.DOCUMENTATION
    )
    assert classifier.classify(url="https://reddit.com/r/ai").source_type == SourceType.FORUM
    assert (
        classifier.classify(url="https://x.com/user/status/1").source_type
        == SourceType.SOCIAL_MEDIA
    )
    assert classifier.classify(url="https://youtube.com/watch?v=1").source_type == SourceType.VIDEO
    assert (
        classifier.classify(url="https://example.com", source_type=SourceType.NEWS).source_type
        == SourceType.NEWS
    )


def test_research_notes_cross_project_rejection_and_update(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    source = (
        source_service(session, settings)
        .import_source(
            video_project_id=project_id,
            url="https://example.com/note",
            text="Snapshot",
        )
        .source
    )
    notes = ResearchNoteService(session)
    note = notes.create_note(
        video_project_id=project_id,
        source_id=source.id,
        note_type=ResearchNoteType.QUOTE,
        content="Important quote",
        source_location="para 2",
        metadata={"line": 2},
    )
    assert note.source_location == "para 2"
    assert notes.update_note(note.id, "Updated quote").content == "Updated quote"

    other_channel = Channel(name="Other Notes", slug="other-notes", niche="AI")
    other_project = VideoProject(channel=other_channel, working_title="Other", topic="AI")
    session.add(other_project)
    session.commit()
    with pytest.raises(ResearchError):
        notes.create_note(
            video_project_id=other_project.id,
            source_id=source.id,
            note_type=ResearchNoteType.KEY_POINT,
            content="bad",
        )


def test_claim_verification_rules(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    service = source_service(session, settings)
    claim_service = ClaimService(session)
    tier1 = service.import_source(
        video_project_id=project_id,
        url="https://example.gov/source",
        source_type=SourceType.GOVERNMENT,
        text="Primary",
    ).source
    discovery = service.import_source(
        video_project_id=project_id,
        url="https://reddit.com/r/ai/comments/1",
        text="Forum",
    ).source
    claim = claim_service.create_claim(
        video_project_id=project_id,
        claim_text="A critical AI policy changed.",
        importance=ClaimImportance.CRITICAL,
    )
    with pytest.raises(ResearchError):
        claim_service.update_verification_status(claim.id, VerificationStatus.VERIFIED)

    claim_service.link_source(
        claim_id=claim.id,
        source_id=tier1.id,
        support_type=ClaimSupportType.PRIMARY_EVIDENCE,
    )
    assert (
        claim_service.update_verification_status(
            claim.id, VerificationStatus.VERIFIED
        ).verification_status
        == VerificationStatus.VERIFIED
    )

    high = claim_service.create_claim(
        video_project_id=project_id,
        claim_text="A high-risk forum claim.",
        importance=ClaimImportance.HIGH,
    )
    claim_service.link_source(
        claim_id=high.id,
        source_id=discovery.id,
        support_type=ClaimSupportType.SUPPORTS,
    )
    with pytest.raises(ResearchError):
        claim_service.update_verification_status(high.id, VerificationStatus.VERIFIED)


def test_claim_duplicate_link_and_cross_project_rejection(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    service = source_service(session, settings)
    claim_service = ClaimService(session)
    source = service.import_source(
        video_project_id=project_id,
        url="https://example.com/claim",
        text="Snapshot",
    ).source
    claim = claim_service.create_claim(video_project_id=project_id, claim_text="Claim")
    claim_service.link_source(
        claim_id=claim.id,
        source_id=source.id,
        support_type=ClaimSupportType.SUPPORTS,
    )
    with pytest.raises(ResearchError):
        claim_service.link_source(
            claim_id=claim.id,
            source_id=source.id,
            support_type=ClaimSupportType.SUPPORTS,
        )

    other_channel = Channel(name="Other Claim", slug="other-claim", niche="AI")
    other_project = VideoProject(channel=other_channel, working_title="Other", topic="AI")
    session.add(other_project)
    session.commit()
    other_source = service.import_source(
        video_project_id=other_project.id,
        url="https://example.com/other-claim",
        text="Other",
    ).source
    with pytest.raises(ResearchError):
        claim_service.link_source(
            claim_id=claim.id,
            source_id=other_source.id,
            support_type=ClaimSupportType.SUPPORTS,
        )


def test_reports_versions_and_readiness(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    service = source_service(session, settings)
    source = service.import_source(
        video_project_id=project_id,
        url="https://example.gov/report",
        source_type=SourceType.GOVERNMENT,
        publisher="Example Gov",
        text="Primary text",
    ).source
    service.update_source_status(source.id, SourceStatus.APPROVED)
    ResearchNoteService(session).create_note(
        video_project_id=project_id,
        source_id=source.id,
        note_type=ResearchNoteType.KEY_POINT,
        content="The launch date is clearly stated.",
    )
    claim = ClaimService(session).create_claim(
        video_project_id=project_id,
        claim_text="The product launched in July.",
        importance=ClaimImportance.HIGH,
    )
    ClaimService(session).link_source(
        claim_id=claim.id,
        source_id=source.id,
        support_type=ClaimSupportType.SUPPORTS,
    )
    ClaimService(session).update_verification_status(claim.id, VerificationStatus.VERIFIED)

    reports = ResearchReportService(session, settings)
    readiness = reports.evaluate_readiness(project_id)
    assert readiness.ready_for_script is True
    brief = reports.generate_research_brief(project_id)
    assert brief.content_type == ContentType.RESEARCH_BRIEF
    assert "## Verified Claims" in brief.content
    source_report = reports.generate_source_report(project_id, content_format=ContentFormat.JSON)
    assert source_report.content_type == ContentType.SOURCE_REPORT
    second_brief = reports.generate_research_brief(project_id)
    assert second_brief.id == brief.id
    assert second_brief.version_number == brief.version_number


def test_readiness_blockers(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    ClaimService(session).create_claim(
        video_project_id=project_id,
        claim_text="A critical unresolved claim.",
        importance=ClaimImportance.CRITICAL,
    )
    readiness = ResearchReportService(session, settings).evaluate_readiness(project_id)
    assert readiness.ready_for_script is False
    assert "No approved sources." in readiness.blocking_reasons
    assert any("Critical claim is not verified" in item for item in readiness.blocking_reasons)


def test_research_job_handlers_execute(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    queue = QueueService(session, settings)
    import_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_IMPORT_RESEARCH_SOURCE,
        payload={"url": "https://example.com/job", "text": "Job source"},
    )
    worker = JobWorker(
        session,
        handlers=research_job_handlers(),
        settings=settings,
        worker_id="research-worker",
    )
    assert worker.run_once().completed is True
    session.refresh(import_job)
    assert import_job.status == JobStatus.COMPLETED
    assert import_job.result is not None
    assert "source_id" in import_job.result

    ready_job = queue.create_job(
        video_project_id=project_id,
        job_type=JOB_EVALUATE_RESEARCH_READINESS,
    )
    assert worker.run_once().completed is True
    session.refresh(ready_job)
    assert ready_job.result is not None
    assert "ready_for_script" in ready_job.result


def test_research_note_database_constraint(session: Session, project_id: str) -> None:
    note = ResearchNote(
        video_project_id=project_id,
        source_id="missing",
        note_type=ResearchNoteType.KEY_POINT,
        content="x",
        content_hash="a" * 64,
    )
    session.add(note)
    with pytest.raises(IntegrityError):
        session.commit()
