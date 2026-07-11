from collections.abc import Generator
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import ai_media_os.cli as cli_module
from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.packaging import MetadataService, ThumbnailService
from ai_media_os.application.safety import ContentSafetyService
from ai_media_os.application.safety_summaries import SafetySummaryService
from ai_media_os.cli import main as cli_main
from ai_media_os.domain.enums import (
    AssetReviewStatus,
    ClaimImportance,
    ContentFormat,
    ContentType,
    PublishingGateStatus,
    RenderStatus,
    RenderType,
    RightsStatus,
    SafetyCheckStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import (
    Approval,
    Asset,
    Channel,
    Claim,
    ContentSafetyCheck,
    ContentVersion,
    PublishingGate,
    Render,
    VideoProject,
)
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.providers.text_generation import LocalRuleBasedTextProvider
from ai_media_os.schemas.video_metadata import ChapterItem, VideoMetadataDocument
from ai_media_os.storage.filesystem import FileStorage


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'safety.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        thumbnail_default_width=64,
        thumbnail_default_height=36,
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


def build_project(session: Session, settings: AppSettings) -> tuple[str, str, str, str, str]:
    channel = Channel(name="AI & Future", slug="ai-future-safety", niche="AI")
    project = VideoProject(channel=channel, working_title="Safety Check Project", topic="AI")
    session.add(project)
    session.commit()

    versions = ContentVersionService(session)
    script = versions.create_initial_version(
        video_project_id=project.id,
        content_type=ContentType.SCRIPT,
        content="AI is moving fast and the audience needs a grounded update.",
        content_format=ContentFormat.MARKDOWN,
    )
    script.status = VersionStatus.APPROVED
    scene_plan = versions.create_initial_version(
        video_project_id=project.id,
        content_type=ContentType.SCENE_PLAN,
        content='{"scenes": []}',
        content_format=ContentFormat.JSON,
    )
    scene_plan.status = VersionStatus.APPROVED
    session.commit()

    render = Render(
        video_project_id=project.id,
        scene_plan_version_id=scene_plan.id,
        render_type=RenderType.FINAL,
        version_number=1,
        status=RenderStatus.APPROVED,
        output_path=f"projects/{project.id}/renders/render_v001.mp4",
        content_hash="r" * 64,
        input_hashes=["script-hash", "scene-hash"],
        settings={"fingerprint": "render-fingerprint"},
        metadata_json={"verified": True},
    )
    session.add(render)
    session.commit()

    metadata_doc = VideoMetadataDocument(
        title="AI Future Signals This Week",
        title_ideas=["AI Future Signals This Week", "What Changed In AI"],
        description="A practical AI update for viewers.",
        tags=["ai", "future", "models"],
        hashtags=["#AI", "#Future"],
        chapters=[ChapterItem(start_seconds=0, title="Opening")],
        language="en",
        target_audience="AI & Future viewers",
        keywords=["ai", "future", "models"],
        source_script_version_id=script.id,
        source_scene_plan_version_id=scene_plan.id,
        source_render_id=render.id,
        warnings=[],
    )
    metadata = MetadataService(session, settings).import_metadata(
        project.id, metadata_doc.model_dump_json()
    )
    approval = session.scalar(select(Approval).where(Approval.content_version_id == metadata.id))
    assert approval is not None
    ApprovalService(session).approve(approval.id, reviewer="test")

    concept = ThumbnailService(session, settings).generate_concept(
        project.id, metadata_version_id=metadata.id
    )
    thumbnail = ThumbnailService(session, settings).generate_thumbnail(
        project.id,
        metadata_version_id=metadata.id,
        concept_version_id=concept.id,
        width=64,
        height=36,
        seed=7,
    )
    ThumbnailService(session, settings).review_thumbnail(thumbnail.id, AssetReviewStatus.APPROVED)

    session.refresh(project)
    return project.id, script.id, scene_plan.id, metadata.id, thumbnail.id


def test_fake_thumbnail_requires_disclosure_and_gate(
    session: Session, settings: AppSettings
) -> None:
    project_id, _script_id, _scene_plan_id, _metadata_id, thumbnail_id = build_project(
        session, settings
    )
    service = ContentSafetyService(session, settings)

    rights = service.check_asset_rights(project_id)
    generated = next(record for record in rights if record.asset_id == thumbnail_id)
    assert generated.rights_status == RightsStatus.SAFE

    decision = service.decide_ai_disclosure(project_id)
    assert decision.required is True
    assert decision.reasons

    result = service.run_publishing_gate(project_id)
    assert result.gate.status == PublishingGateStatus.NEEDS_REVIEW
    assert result.report_version.content_type == ContentType.COPYRIGHT_REPORT

    gate_count = session.scalar(select(func.count()).select_from(PublishingGate))
    finding_count = session.scalar(select(func.count()).select_from(ContentSafetyCheck))
    summary = SafetySummaryService(session, LocalRuleBasedTextProvider()).summarize(project_id)
    assert summary.authoritative_status == result.gate.status
    assert summary.report_version_id == result.report_version.id
    assert session.scalar(select(func.count()).select_from(PublishingGate)) == gate_count
    assert session.scalar(select(func.count()).select_from(ContentSafetyCheck)) == finding_count


def test_gate_persists_blocked_report_when_required_inputs_are_missing(
    session: Session, settings: AppSettings
) -> None:
    channel = Channel(name="Missing Inputs", slug="missing-inputs", niche="AI")
    project = VideoProject(channel=channel, working_title="Incomplete", topic="AI")
    session.add(project)
    session.commit()

    result = ContentSafetyService(session, settings).run_publishing_gate(project.id)

    assert result.gate.status == PublishingGateStatus.BLOCKED
    assert {"Missing render.", "Missing metadata.", "Missing thumbnail."}.issubset(
        set(result.gate.blocking_reasons)
    )
    assert result.report_version.content_type == ContentType.COPYRIGHT_REPORT

    explicit_missing = ContentSafetyService(session, settings).run_publishing_gate(
        project.id,
        render_id="missing-render",
        metadata_version_id="missing-metadata",
        thumbnail_asset_id="missing-thumbnail",
    )
    assert explicit_missing.gate.status == PublishingGateStatus.BLOCKED


def test_gate_checks_explicit_selected_metadata(session: Session, settings: AppSettings) -> None:
    project_id, _script_id, _scene_plan_id, metadata_id, thumbnail_id = build_project(
        session, settings
    )
    selected = session.get(ContentVersion, metadata_id)
    assert selected is not None
    revised_document = VideoMetadataDocument.model_validate_json(selected.content).model_copy(
        update={"title": "A Different AI Future Update"}
    )
    latest = MetadataService(session, settings).revise_metadata(
        metadata_id, revised_document.model_dump_json()
    )
    assert latest.id != metadata_id

    result = ContentSafetyService(session, settings).run_publishing_gate(
        project_id,
        metadata_version_id=metadata_id,
        thumbnail_asset_id=thumbnail_id,
    )

    assert result.gate.metadata_version_id == metadata_id
    metadata_findings = [
        finding for finding in result.findings if finding.check_type.value == "metadata_safety"
    ]
    assert metadata_findings[0].target_id == metadata_id


def test_manual_thumbnail_import_unknown_rights_and_missing_file(
    session: Session, settings: AppSettings
) -> None:
    project_id, _script_id, _scene_plan_id, metadata_id, thumbnail_id = build_project(
        session, settings
    )
    service = ContentSafetyService(session, settings)
    storage = FileStorage(settings)
    thumbnail = session.get(Asset, thumbnail_id)
    assert thumbnail is not None
    source_path = settings.data_dir / "manual-thumbnail.png"
    source_path.write_bytes(
        storage.resolve_inside(storage.data_root, thumbnail.file_path).read_bytes()
    )

    imported = ThumbnailService(session, settings).import_thumbnail(
        project_id,
        source_path,
        metadata_version_id=metadata_id,
    )
    rights = service.check_asset_rights(project_id)
    imported_rights = next(record for record in rights if record.asset_id == imported.id)
    assert imported_rights.rights_status == RightsStatus.UNKNOWN

    stored_path = storage.resolve_inside(storage.data_root, imported.file_path)
    stored_path.unlink()
    finding = service.check_thumbnail_safety(project_id)[0]
    assert finding.status == SafetyCheckStatus.FAILED
    assert "missing" in finding.message.lower()


def test_claim_support_and_metadata_safety(session: Session, settings: AppSettings) -> None:
    project_id, script_id, scene_plan_id, metadata_id, _thumbnail_id = build_project(
        session, settings
    )
    claim = Claim(
        video_project_id=project_id,
        claim_text="Official leak confirmed",
        importance=ClaimImportance.HIGH,
    )
    session.add(claim)
    session.commit()

    service = ContentSafetyService(session, settings)
    claim_finding = service.check_claim_support(project_id)[0]
    assert claim_finding.status == SafetyCheckStatus.FAILED

    bad_metadata = VideoMetadataDocument(
        title="Official leak confirmed",
        title_ideas=["Official leak confirmed"],
        description="Official leak confirmed.",
        tags=["ai"],
        hashtags=["#AI"],
        chapters=[ChapterItem(start_seconds=0, title="Opening")],
        language="en",
        target_audience="AI & Future viewers",
        keywords=["leak"],
        source_script_version_id=script_id,
        source_scene_plan_version_id=scene_plan_id,
        source_render_id=None,
        warnings=[],
    )
    MetadataService(session, settings).revise_metadata(metadata_id, bad_metadata.model_dump_json())
    metadata_finding = service.check_metadata_safety(project_id)[0]
    assert metadata_finding.status == SafetyCheckStatus.FAILED


def test_reused_content_and_cli_commands(
    session: Session,
    settings: AppSettings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_id, script_id, _scene_plan_id, _metadata_id, _thumbnail_id = build_project(
        session, settings
    )
    versions = ContentVersionService(session)
    duplicate_script = versions.create_revision(
        parent_version_id=script_id,
        video_project_id=project_id,
        content_type=ContentType.SCRIPT,
        content="AI is moving fast and the audience needs a grounded update.",
        content_format=ContentFormat.MARKDOWN,
    )
    duplicate_script.status = VersionStatus.APPROVED
    session.commit()

    service = ContentSafetyService(session, settings)
    reused = service.check_reused_content(project_id)[0]
    assert reused.status == SafetyCheckStatus.WARNING

    cli_env = {
        "AI_MEDIA_OS_DATABASE_URL": settings.database_url,
        "AI_MEDIA_OS_DATA_DIR": str(settings.data_dir),
        "AI_MEDIA_OS_CACHE_DIR": str(settings.cache_dir),
        "AI_MEDIA_OS_PROJECTS_DIR": str(settings.projects_dir),
        "AI_MEDIA_OS_LOGS_DIR": str(settings.logs_dir),
    }
    for key, value in cli_env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    monkeypatch.setattr(
        cli_module, "SessionLocal", sessionmaker(bind=session.get_bind(), expire_on_commit=False)
    )

    exit_code = cli_main(["check-asset-rights", "--project-id", project_id])
    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert output

    exit_code = cli_main(["run-publishing-gate", "--project-id", project_id])
    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert output in {"PASS", "PASS_WITH_WARNINGS", "NEEDS_REVIEW", "BLOCKED"}

    exit_code = cli_main(["show-safety-report", "--project-id", project_id])
    output = capsys.readouterr().out.strip()
    assert exit_code == 0
    assert "gate" in output.lower()
