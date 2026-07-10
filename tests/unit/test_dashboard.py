import re
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ai_media_os.api.app import create_app
from ai_media_os.application.approvals import ApprovalService
from ai_media_os.application.assets import (
    AssetPlanningService,
    ImageAssetService,
    VoiceAssetService,
)
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.job_queue import FailureInfo, QueueService
from ai_media_os.application.packaging import MetadataService, ThumbnailService
from ai_media_os.application.renders import RenderPlanningService, VideoCompositionService
from ai_media_os.application.research import ClaimService, SourceService
from ai_media_os.application.safety import ContentSafetyService
from ai_media_os.application.scenes import ScenePlanService
from ai_media_os.application.scripts import ScriptGenerationService
from ai_media_os.dashboard.markdown import render_safe_markdown
from ai_media_os.dashboard.progress import calculate_progress
from ai_media_os.dashboard.queries import DashboardQueries
from ai_media_os.dashboard.routes import get_dashboard_session
from ai_media_os.dashboard.security import csrf_token
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    JobStatus,
    ResourceClass,
    SourceStatus,
    SourceType,
    VerificationStatus,
)
from ai_media_os.infrastructure.database.base import Base
from ai_media_os.infrastructure.database.models import Approval, Channel, VideoProject
from ai_media_os.infrastructure.database.session import create_db_engine
from ai_media_os.infrastructure.settings import AppSettings
from ai_media_os.providers.video_composition import FakeVideoComposer
from ai_media_os.storage.filesystem import FileStorage


@pytest.fixture()
def settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'dashboard.db'}",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "data" / "cache",
        projects_dir=tmp_path / "data" / "projects",
        logs_dir=tmp_path / "data" / "logs",
        dashboard_csrf_secret="test-dashboard-secret",  # noqa: S106
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
def client(session: Session, settings: AppSettings) -> Generator[TestClient]:
    app = create_app(settings)

    def override_session() -> Generator[Session]:
        yield session

    app.dependency_overrides[get_dashboard_session] = override_session
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def project_id(session: Session, settings: AppSettings) -> str:
    channel = Channel(name="AI & Future", slug="ai-future-dashboard", niche="AI")
    project = VideoProject(channel=channel, working_title="AI weekly", topic="AI model launches")
    session.add(project)
    session.commit()
    source = (
        SourceService(session, FileStorage(settings), settings)
        .import_source(
            video_project_id=project.id,
            url="https://example.gov/report",
            title="Government report",
            publisher="Example Gov",
            source_type=SourceType.GOVERNMENT,
            text="Official source text",
        )
        .source
    )
    SourceService(session, FileStorage(settings), settings).update_source_status(
        source.id,
        SourceStatus.APPROVED,
    )
    claim_service = ClaimService(session)
    claim = claim_service.create_claim(
        video_project_id=project.id,
        claim_text="A verified research claim.",
        importance=ClaimImportance.HIGH,
    )
    claim_service.link_source(
        claim_id=claim.id,
        source_id=source.id,
        support_type=ClaimSupportType.SUPPORTS,
    )
    claim_service.update_verification_status(claim.id, VerificationStatus.VERIFIED)
    ContentVersionService(session).create_initial_version(
        video_project_id=project.id,
        content_type=ContentType.RESEARCH_BRIEF,
        content="# Brief\n\n<script>alert(1)</script>\n\n- Safe point",
        content_format=ContentFormat.MARKDOWN,
    )
    ContentVersionService(session).create_initial_version(
        video_project_id=project.id,
        content_type=ContentType.SOURCE_REPORT,
        content='{"total_sources": 1}',
        content_format=ContentFormat.JSON,
    )
    script = ScriptGenerationService(session).generate_script(project.id)
    pending_script = session.scalar(
        select(Approval).where(Approval.content_version_id == script.id)
    )
    assert pending_script is not None
    ApprovalService(session).approve(pending_script.id, reviewer="fixture")
    ScriptGenerationService(session).generate_fact_check_report(project.id)
    scene_plan = ScenePlanService(session).generate_scene_plan(project.id)
    scene_approval = session.scalar(
        select(Approval).where(Approval.content_version_id == scene_plan.id)
    )
    assert scene_approval is not None
    ApprovalService(session).approve(scene_approval.id, reviewer="fixture")
    assets = AssetPlanningService(session, settings).plan_scene_assets(
        project.id,
        scene_plan_version_id=scene_plan.id,
    )
    scene_ids = {str(asset.scene_id) for asset in assets if asset.scene_id is not None}
    for scene_id in scene_ids:
        ImageAssetService(session, settings).generate_for_scene(scene_id, width=16, height=9)
        VoiceAssetService(session, settings).generate_for_scene(scene_id)
    render = RenderPlanningService(session, settings).plan_render(
        project.id,
        scene_plan_version_id=scene_plan.id,
    )
    composition_service = VideoCompositionService(
        session,
        settings,
        provider=FakeVideoComposer(),
    )
    composed = composition_service.compose_video(
        project.id,
        render_id=render.id,
    )
    metadata = MetadataService(session, settings).generate_metadata(
        project.id,
        render_id=composed.id,
    )
    concept = ThumbnailService(session, settings).generate_concept(
        project.id,
        metadata_version_id=metadata.id,
    )
    ThumbnailService(session, settings).generate_thumbnail(
        project.id,
        metadata_version_id=metadata.id,
        concept_version_id=concept.id,
        width=64,
        height=36,
    )
    return project.id


def test_dashboard_routes_empty_state(client: TestClient) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/projects").status_code == 200
    assert client.get("/approvals").status_code == 200
    assert client.get("/jobs").status_code == 200
    assert "No projects match this filter" in client.get("/projects").text


def test_project_safety_page_and_summary(
    client: TestClient,
    session: Session,
    project_id: str,
) -> None:
    ContentSafetyService(session).run_publishing_gate(project_id)
    detail = client.get(f"/projects/{project_id}")
    assert detail.status_code == 200
    assert "Safety" in detail.text
    safety = client.get(f"/projects/{project_id}/safety")
    assert safety.status_code == 200
    assert "Content Safety" in safety.text
    assert "Publishing Gate" in safety.text


def test_project_routes_and_research_rendering(
    client: TestClient,
    project_id: str,
) -> None:
    detail = client.get(f"/projects/{project_id}")
    assert detail.status_code == 200
    assert "Research Sources" in detail.text
    research = client.get(f"/projects/{project_id}/research")
    assert research.status_code == 200
    assert "Government report" in research.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in research.text
    assert "<script>alert(1)</script>" not in research.text
    assert "Older versions" not in research.text
    script = client.get(f"/projects/{project_id}/script")
    assert script.status_code == 200
    assert "Fact Check" in script.text
    scenes = client.get(f"/projects/{project_id}/scenes")
    assert scenes.status_code == 200
    assert "Scene Breakdown" in scenes.text
    assets = client.get(f"/projects/{project_id}/assets")
    assert assets.status_code == 200
    assert "Scene Assets" in assets.text
    assert "fake-placeholder-voice" in assets.text
    assert "seconds" in assets.text
    assert "data/projects" not in assets.text
    assert f"projects/{project_id}/images" not in assets.text
    assert "/assets/" in assets.text
    preview_match = re.search(r'class="asset-preview" src="([^"]+)"', assets.text)
    assert preview_match is not None
    preview_url = preview_match.group(1)
    preview = client.get(preview_url)
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/png")
    renders = client.get(f"/projects/{project_id}/renders")
    assert renders.status_code == 200
    assert "Video Renders" in renders.text
    render_detail_match = re.search(r'href="([^"]+/renders/[^"]+)"', renders.text)
    assert render_detail_match is not None
    render_detail = client.get(render_detail_match.group(1))
    assert render_detail.status_code == 200
    assert "Render Detail" in render_detail.text
    render_preview_match = re.search(
        r'class="render-player"[^>]+src="([^"]+)"',
        render_detail.text,
    )
    assert render_preview_match is not None
    render_preview = client.get(render_preview_match.group(1))
    assert render_preview.status_code == 200
    assert render_preview.headers["content-type"].startswith("video/mp4")
    metadata = client.get(f"/projects/{project_id}/metadata")
    assert metadata.status_code == 200
    assert "Video Metadata" in metadata.text
    assert "AI weekly" in metadata.text
    thumbnail = client.get(f"/projects/{project_id}/thumbnail")
    assert thumbnail.status_code == 200
    assert "Thumbnail History" in thumbnail.text
    thumbnail_match = re.search(r'class="thumbnail-preview" src="([^"]+)"', thumbnail.text)
    assert thumbnail_match is not None
    thumbnail_preview = client.get(thumbnail_match.group(1))
    assert thumbnail_preview.status_code == 200
    assert thumbnail_preview.headers["content-type"].startswith("image/png")


def test_unknown_and_invalid_project_return_404(client: TestClient) -> None:
    assert client.get("/projects/not-a-uuid").status_code == 404
    assert client.get("/projects/00000000-0000-0000-0000-000000000000").status_code == 404


def test_view_models_progress_activity_and_labels(
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    queries = DashboardQueries(session, settings)
    project = queries.project(project_id)
    assert project is not None
    progress = calculate_progress(
        sources=list(project.sources),
        claims=list(project.claims),
        content_versions=list(project.content_versions),
        approvals=list(project.approvals),
    )
    assert progress.research_progress >= 90
    assert progress.overall_progress <= 20
    assert queries.project_list_item(project).workflow_stage
    assert queries.activity(project_id=project_id)
    research = queries.research_view(project)
    assert research.source_summary.total == 1
    assert research.claim_summary.verified == 1
    assert research.readiness_status == "Ready with Warnings"


def test_safe_markdown_removes_unsafe_html() -> None:
    rendered = render_safe_markdown("# Title\n\n<script>alert(1)</script>\n\n- **ok**")
    assert "<script>" not in rendered
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in rendered
    assert "<strong>ok</strong>" in rendered


def test_approval_actions_csrf_feedback_and_duplicate_protection(
    client: TestClient,
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    version = ContentVersionService(session).create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.RESEARCH_BRIEF,
        content="Research v2",
        content_format=ContentFormat.MARKDOWN,
    )
    approval = ApprovalService(session).request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.RESEARCH,
        content_version_id=version.id,
    )
    assert client.get("/approvals").status_code == 200
    assert client.post(f"/approvals/{approval.id}/approve", data={"csrf": "bad"}).status_code == 403
    response = client.post(
        f"/approvals/{approval.id}/approve",
        data={"csrf": csrf_token(settings), "feedback": "looks good"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.refresh(approval)
    assert approval.status == ApprovalStatus.APPROVED
    assert approval.feedback == "looks good"
    duplicate = client.post(
        f"/approvals/{approval.id}/reject",
        data={"csrf": csrf_token(settings), "feedback": "late"},
        follow_redirects=False,
    )
    assert duplicate.status_code == 303


def test_request_changes_and_rejection_posts(
    client: TestClient,
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    service = ContentVersionService(session)
    approval_service = ApprovalService(session)
    changes_version = service.create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.RESEARCH_BRIEF,
        content="Research changes",
        content_format=ContentFormat.MARKDOWN,
    )
    changes = approval_service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.RESEARCH,
        content_version_id=changes_version.id,
    )
    client.post(
        f"/approvals/{changes.id}/request-changes",
        data={"csrf": csrf_token(settings), "feedback": "revise"},
    )
    session.refresh(changes)
    assert changes.status == ApprovalStatus.CHANGES_REQUESTED
    reject_version = service.create_initial_version(
        video_project_id=project_id,
        content_type=ContentType.RESEARCH_BRIEF,
        content="Research reject",
        content_format=ContentFormat.MARKDOWN,
    )
    rejected = approval_service.request_approval(
        video_project_id=project_id,
        approval_type=ApprovalType.RESEARCH,
        content_version_id=reject_version.id,
    )
    client.post(
        f"/approvals/{rejected.id}/reject",
        data={"csrf": csrf_token(settings), "feedback": "no"},
    )
    session.refresh(rejected)
    assert rejected.status == ApprovalStatus.REJECTED


def test_jobs_filters_actions_and_fragments(
    client: TestClient,
    session: Session,
    settings: AppSettings,
    project_id: str,
) -> None:
    queue = QueueService(session, settings)
    running = queue.create_job(
        video_project_id=project_id,
        job_type="dashboard.running",
        resource_class=ResourceClass.CPU_LIGHT,
    )
    claimed = queue.claim_next_job("worker-a")
    assert claimed is not None
    queue.create_job(video_project_id=project_id, job_type="dashboard.failed")
    claimed_failed = queue.claim_next_job("worker-b")
    assert claimed_failed is not None
    queue.fail_job(
        claimed_failed.id,
        "worker-b",
        failure=FailureInfo("test", "safe error", {"detail": "hidden"}, retryable=False),
    )
    response = client.get("/jobs?status=RUNNING")
    assert response.status_code == 200
    assert "Dashboard Running" in response.text
    assert "safe error" not in client.get("/jobs?status=RUNNING").text
    assert client.get("/ui/fragments/status-counters").status_code == 200
    assert client.get("/ui/fragments/running-jobs").status_code == 200
    assert client.get("/ui/fragments/pending-approvals").status_code == 200
    assert client.get("/ui/fragments/activity").status_code == 200
    assert client.post(f"/jobs/{running.id}/pause", data={"csrf": "bad"}).status_code == 403
    pause = client.post(
        f"/jobs/{running.id}/cancel",
        data={"csrf": csrf_token(settings)},
        follow_redirects=False,
    )
    assert pause.status_code == 303
    session.refresh(running)
    assert running.cancel_requested_at is not None or running.status == JobStatus.CANCELLED


def test_state_changing_routes_reject_get(client: TestClient, project_id: str) -> None:
    assert client.get("/jobs/not-a-job/cancel").status_code == 405
    assert client.get("/approvals/not-an-approval/approve").status_code == 405
