"""Read/query services for the local operations dashboard."""

from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ai_media_os.dashboard.labels import (
    approval_status_label,
    approval_type_label,
    authority_tier_label,
    content_type_label,
    job_status_label,
    job_type_label,
    project_status_label,
    resource_class_label,
    source_status_label,
    source_type_label,
)
from ai_media_os.dashboard.markdown import render_safe_markdown
from ai_media_os.dashboard.progress import calculate_progress, stage_statuses
from ai_media_os.dashboard.view_models import (
    ActivityItem,
    ApprovalItem,
    AssetItem,
    AssetView,
    ClaimSummary,
    DashboardHome,
    JobGroups,
    JobItem,
    JsonDict,
    MetadataView,
    MetricCard,
    ProjectListItem,
    RenderItem,
    RenderView,
    ResearchView,
    SceneItem,
    ScenePlanView,
    ScriptView,
    SourceSummary,
    StageStatus,
    ThumbnailView,
)
from ai_media_os.domain.enums import (
    ApprovalStatus,
    AssetRole,
    AssetType,
    ClaimImportance,
    ContentFormat,
    ContentType,
    JobStatus,
    ResourceClass,
    SourceStatus,
    VerificationStatus,
    VideoProjectStatus,
)
from ai_media_os.infrastructure.database.models import (
    Approval,
    Asset,
    Channel,
    Claim,
    ContentVersion,
    Job,
    Render,
    Scene,
    Source,
    VideoProject,
    WorkflowInstance,
)
from ai_media_os.infrastructure.settings import AppSettings, get_settings


class DashboardQueries:
    """Build dashboard view models without mutating application state."""

    def __init__(self, session: Session, settings: AppSettings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.timezone = self._timezone(self.settings.dashboard_timezone)

    def home(self) -> DashboardHome:
        active_projects = self.session.scalar(
            select(func.count())
            .select_from(VideoProject)
            .where(VideoProject.status != VideoProjectStatus.ARCHIVED)
        )
        cards = [
            MetricCard("Total Channels", self._count(Channel)),
            MetricCard("Total Video Projects", self._count(VideoProject)),
            MetricCard("Active Projects", int(active_projects or 0), "success"),
            MetricCard("Currently Working", self._count_jobs(JobStatus.RUNNING), "progress"),
            MetricCard(
                "Waiting for Approval",
                self._count_jobs(JobStatus.WAITING_FOR_APPROVAL),
                "warning",
            ),
            MetricCard("Needs Attention", self._count_jobs(JobStatus.FAILED), "error"),
            MetricCard(
                "Pending Approvals",
                self._count_approvals(ApprovalStatus.PENDING),
                "warning",
            ),
        ]
        activity = self.activity(limit=12)
        return DashboardHome(
            cards=cards,
            recent_activity=activity,
            recent_completed=[
                item for item in activity if item.tone == "success" and "Finished" in item.title
            ][:5],
            recent_errors=[item for item in activity if item.tone == "error"][:5],
        )

    def projects(self, filter_name: str = "all") -> list[ProjectListItem]:
        projects = list(
            self.session.scalars(
                select(VideoProject)
                .options(
                    selectinload(VideoProject.channel),
                    selectinload(VideoProject.sources),
                    selectinload(VideoProject.claims).selectinload(Claim.source_links),
                    selectinload(VideoProject.approvals),
                    selectinload(VideoProject.jobs),
                    selectinload(VideoProject.content_versions),
                )
                .order_by(VideoProject.updated_at.desc())
            ).all()
        )
        items = [self.project_list_item(project) for project in projects]
        if filter_name == "active":
            return [item for item in items if item.status_value in {"draft", "active"}]
        if filter_name == "waiting":
            return [item for item in items if item.pending_approval_count > 0]
        if filter_name == "completed":
            return [item for item in items if item.status_value == "completed"]
        if filter_name == "attention":
            return [item for item in items if item.failed_job_count > 0]
        return items

    def project(self, project_id: str) -> VideoProject | None:
        return self.session.scalar(
            select(VideoProject)
            .where(VideoProject.id == project_id)
            .options(
                selectinload(VideoProject.channel),
                selectinload(VideoProject.sources).selectinload(Source.claim_links),
                selectinload(VideoProject.claims).selectinload(Claim.source_links),
                selectinload(VideoProject.approvals).selectinload(Approval.content_version),
                selectinload(VideoProject.jobs),
                selectinload(VideoProject.content_versions),
                selectinload(VideoProject.scenes),
                selectinload(VideoProject.assets).selectinload(Asset.scene),
                selectinload(VideoProject.renders),
            )
        )

    def project_list_item(self, project: VideoProject) -> ProjectListItem:
        progress = calculate_progress(
            sources=list(project.sources),
            claims=list(project.claims),
            content_versions=list(project.content_versions),
            approvals=list(project.approvals),
        )
        return ProjectListItem(
            id=project.id,
            working_title=project.working_title,
            channel_name=project.channel.name,
            topic=project.topic,
            status_label=project_status_label(project.status),
            status_value=project.status.value,
            workflow_stage=self.workflow_stage(project.id) or progress.current_stage,
            progress=progress,
            source_count=len(project.sources),
            claim_count=len(project.claims),
            pending_approval_count=sum(
                approval.status == ApprovalStatus.PENDING for approval in project.approvals
            ),
            running_job_count=sum(job.status == JobStatus.RUNNING for job in project.jobs),
            failed_job_count=sum(job.status == JobStatus.FAILED for job in project.jobs),
            updated_at=self.display_time(project.updated_at),
        )

    def stage_statuses_for_project(self, project: VideoProject) -> list[StageStatus]:
        return [
            StageStatus(name=name, status=status, tone=tone)
            for name, status, tone in stage_statuses(
                sources=list(project.sources),
                claims=list(project.claims),
                content_versions=list(project.content_versions),
                approvals=list(project.approvals),
            )
        ]

    def research_view(self, project: VideoProject) -> ResearchView:
        sources = list(project.sources)
        claims = list(project.claims)
        versions = list(project.content_versions)
        latest_brief = self.latest_version(versions, ContentType.RESEARCH_BRIEF)
        latest_report = self.latest_version(versions, ContentType.SOURCE_REPORT)
        brief_versions = self.version_labels(versions, ContentType.RESEARCH_BRIEF)
        report_versions = self.version_labels(versions, ContentType.SOURCE_REPORT)
        blockers, warnings = self.readiness(project)
        if blockers:
            readiness_status = "Not Ready for Script"
            readiness_tone = "error"
        elif warnings:
            readiness_status = "Ready with Warnings"
            readiness_tone = "warning"
        else:
            readiness_status = "Ready for Script"
            readiness_tone = "success"
        return ResearchView(
            source_summary=self.source_summary(sources),
            claim_summary=self.claim_summary(claims),
            readiness_status=readiness_status,
            readiness_tone=readiness_tone,
            readiness_blockers=blockers,
            readiness_warnings=warnings,
            latest_brief_html=(
                render_safe_markdown(latest_brief.content) if latest_brief is not None else None
            ),
            latest_source_report=self.report_content(latest_report),
            older_brief_versions=brief_versions[1:],
            older_source_report_versions=report_versions[1:],
        )

    def script_view(self, project: VideoProject) -> ScriptView:
        versions = list(project.content_versions)
        latest_script = self.latest_version(versions, ContentType.SCRIPT)
        latest_fact_check = self.latest_version(versions, ContentType.FACT_CHECK_REPORT)
        quality_result: JsonDict | None = None
        if latest_fact_check is not None:
            fact_check = self.report_content(latest_fact_check)
            latest_fact_check_data = fact_check if isinstance(fact_check, dict) else None
        else:
            latest_fact_check_data = None
        if latest_fact_check_data is not None:
            quality_result = {
                "passed": latest_fact_check_data.get("passed"),
                "unverified_claims": latest_fact_check_data.get("unverified_claims_mentioned", []),
                "missing_anchors": latest_fact_check_data.get("missing_research_anchors", []),
            }
        return ScriptView(
            latest_script_html=(
                render_safe_markdown(latest_script.content) if latest_script is not None else None
            ),
            script_status=latest_script.status.value if latest_script is not None else None,
            script_version_number=(
                latest_script.version_number if latest_script is not None else None
            ),
            latest_fact_check=latest_fact_check_data,
            quality_result=quality_result,
            older_script_versions=self.version_labels(versions, ContentType.SCRIPT)[1:],
        )

    def scene_plan_view(self, project: VideoProject) -> ScenePlanView:
        versions = list(project.content_versions)
        latest_plan = self.latest_version(versions, ContentType.SCENE_PLAN)
        scenes = sorted(
            [
                scene
                for scene in project.scenes
                if latest_plan is not None and scene.scene_plan_version_id == latest_plan.id
            ],
            key=lambda item: item.scene_number,
        )
        plan_data = self.report_content(latest_plan)
        quality_notes: list[str] = []
        total_duration_seconds: float | None = None
        if isinstance(plan_data, dict):
            raw_quality_notes = plan_data.get("quality_notes", [])
            if isinstance(raw_quality_notes, Sequence) and not isinstance(raw_quality_notes, str):
                quality_notes = [str(item) for item in raw_quality_notes if item is not None]
            total_value = plan_data.get("total_duration_seconds")
            if isinstance(total_value, int | float | str):
                total_duration_seconds = float(total_value)
        return ScenePlanView(
            scene_plan_status=latest_plan.status.value if latest_plan is not None else None,
            scene_plan_version_number=latest_plan.version_number
            if latest_plan is not None
            else None,
            total_duration_seconds=total_duration_seconds,
            scene_count=len(scenes),
            quality_notes=quality_notes,
            scenes=[self.scene_item(scene) for scene in scenes],
            older_scene_plan_versions=self.version_labels(versions, ContentType.SCENE_PLAN)[1:],
        )

    def scene_item(self, scene: Scene) -> SceneItem:
        return SceneItem(
            scene_number=scene.scene_number,
            start_seconds=scene.start_seconds,
            duration_seconds=scene.duration_seconds,
            visual_type=scene.visual_type.value.replace("_", " ").title(),
            narration=scene.narration,
            visual_description=scene.visual_description,
            image_prompt=scene.image_prompt,
            source_claim_ids=scene.source_claim_ids,
        )

    def asset_view(self, project: VideoProject) -> AssetView:
        items = [self.asset_item(asset) for asset in sorted(project.assets, key=_asset_sort_key)]
        return AssetView(
            assets=items,
            visual_count=sum(
                asset.asset_role == AssetRole.SCENE_VISUAL for asset in project.assets
            ),
            narration_count=sum(
                asset.asset_role == AssetRole.SCENE_NARRATION for asset in project.assets
            ),
            missing_count=sum(not item.has_file for item in items),
            pending_review_count=sum(item.review_status == "Pending Review" for item in items),
        )

    def asset_item(self, asset: Asset) -> AssetItem:
        has_file = False
        warning: str | None = None
        if asset.content_hash and asset.file_path:
            try:
                path = self.settings.data_dir.resolve() / asset.file_path
                has_file = path.exists()
                if not has_file:
                    warning = "Missing file"
            except OSError:
                warning = "File cannot be checked"
        else:
            warning = "No generated file"
        next_action = "Review asset" if has_file else "Generate or import asset"
        if asset.review_status.value == "approved":
            next_action = "Ready for next milestone"
        preview_url = (
            f"/assets/{asset.id}/preview"
            if has_file
            and asset.asset_type
            in {AssetType.IMAGE, AssetType.CHART, AssetType.SCREENSHOT, AssetType.THUMBNAIL}
            else None
        )
        return AssetItem(
            id=asset.id,
            scene_number=asset.scene.scene_number if asset.scene is not None else None,
            asset_type=asset.asset_type.value.replace("_", " ").title(),
            asset_role=asset.asset_role.value.replace("_", " ").title(),
            generation_status=asset.generation_status.value.replace("_", " ").title(),
            review_status=asset.review_status.value.replace("_", " ").title(),
            provider=asset.provider,
            model=asset.model,
            seed=asset.seed,
            content_hash=asset.content_hash,
            mime_type=asset.mime_type,
            duration_seconds=asset.duration_seconds,
            width=asset.width,
            height=asset.height,
            has_file=has_file,
            file_warning=warning,
            preview_url=preview_url,
            next_action=next_action,
        )

    def render_view(self, project: VideoProject) -> RenderView:
        renders = [
            self.render_item(render) for render in sorted(project.renders, key=_render_sort_key)
        ]
        return RenderView(
            renders=renders,
            latest=renders[0] if renders else None,
            rendered_count=sum(
                item.status in {"Rendered", "Completed", "Approved"} for item in renders
            ),
            failed_count=sum(item.status == "Failed" for item in renders),
        )

    def render_item(self, render: Render) -> RenderItem:
        has_file = False
        warning: str | None = None
        if render.output_path:
            try:
                path = self.settings.data_dir.resolve() / render.output_path
                has_file = path.exists()
                if not has_file:
                    warning = "Missing file"
            except OSError:
                warning = "File cannot be checked"
        else:
            warning = "No output path"
        return RenderItem(
            id=render.id,
            version_number=render.version_number,
            status=render.status.value.replace("_", " ").title(),
            provider=render.provider,
            output_path=f"render_v{render.version_number:03d}.mp4",
            content_hash=render.content_hash,
            duration_seconds=render.duration_seconds,
            width=render.width,
            height=render.height,
            fps=render.fps,
            file_size=render.file_size,
            has_file=has_file,
            file_warning=warning,
            preview_url=f"/renders/{render.id}/preview" if has_file else None,
            error_message=render.error_message,
            created_at=self.display_time(render.created_at),
        )

    def metadata_view(self, project: VideoProject) -> MetadataView:
        versions = list(project.content_versions)
        latest = self.latest_version(versions, ContentType.METADATA)
        data = self.report_content(latest)
        parsed = data if isinstance(data, dict) else {}
        title_ideas = _string_list(parsed.get("title_ideas"))
        tags = _string_list(parsed.get("tags"))
        hashtags = _string_list(parsed.get("hashtags"))
        warnings = _string_list(parsed.get("warnings"))
        chapters = parsed.get("chapters", [])
        chapter_items = list(chapters) if isinstance(chapters, list) else []
        if latest is None:
            next_action = "Generate metadata"
        elif latest.status.value == "pending_approval":
            next_action = "Review metadata"
        elif latest.status.value == "approved":
            next_action = "Generate thumbnail concept"
        else:
            next_action = "Revise metadata"
        return MetadataView(
            latest_version_id=latest.id if latest is not None else None,
            version_number=latest.version_number if latest is not None else None,
            status=latest.status.value.replace("_", " ").title() if latest is not None else None,
            title=_optional_string(parsed.get("title")),
            title_ideas=title_ideas,
            description=_optional_string(parsed.get("description")),
            tags=tags,
            hashtags=hashtags,
            chapters=[item for item in chapter_items if isinstance(item, dict)],
            warnings=warnings,
            source_script_version_id=_optional_string(parsed.get("source_script_version_id")),
            source_render_id=_optional_string(parsed.get("source_render_id")),
            older_versions=self.version_labels(versions, ContentType.METADATA)[1:],
            next_action=next_action,
        )

    def thumbnail_view(self, project: VideoProject) -> ThumbnailView:
        versions = list(project.content_versions)
        concept = self.latest_version(versions, ContentType.THUMBNAIL_CONCEPT)
        data = self.report_content(concept)
        parsed = data if isinstance(data, dict) else {}
        thumbnails = [
            self.asset_item(asset)
            for asset in sorted(
                [asset for asset in project.assets if asset.asset_type == AssetType.THUMBNAIL],
                key=_asset_sort_key,
                reverse=True,
            )
        ]
        latest_asset = thumbnails[0] if thumbnails else None
        if concept is None:
            next_action = "Generate thumbnail concept"
        elif latest_asset is None:
            next_action = "Generate thumbnail image"
        elif latest_asset.review_status == "Pending Review":
            next_action = "Review thumbnail"
        elif latest_asset.review_status == "Approved":
            next_action = "Ready for final video approval"
        else:
            next_action = "Revise thumbnail"
        return ThumbnailView(
            concept_version_id=concept.id if concept is not None else None,
            concept_title=_optional_string(parsed.get("concept_title")),
            selected_text=_optional_string(parsed.get("selected_text")),
            text_options=_string_list(parsed.get("text_options")),
            visual_description=_optional_string(parsed.get("visual_description")),
            warnings=_string_list(parsed.get("warnings")),
            asset=latest_asset,
            thumbnails=thumbnails,
            approved_count=sum(item.review_status == "Approved" for item in thumbnails),
            pending_review_count=sum(item.review_status == "Pending Review" for item in thumbnails),
            next_action=next_action,
        )

    def source_summary(self, sources: list[Source]) -> SourceSummary:
        return SourceSummary(
            total=len(sources),
            approved=sum(source.status == SourceStatus.APPROVED for source in sources),
            unreviewed=sum(source.status == SourceStatus.IMPORTED for source in sources),
            rejected=sum(source.status == SourceStatus.REJECTED for source in sources),
            tier_1=sum(source.authority_tier == 1 for source in sources),
            tier_2=sum(source.authority_tier == 2 for source in sources),
            tier_3=sum(source.authority_tier == 3 for source in sources),
            duplicate_warnings=sum(source.duplicate_of_source_id is not None for source in sources),
        )

    def claim_summary(self, claims: list[Claim]) -> ClaimSummary:
        return ClaimSummary(
            verified=sum(
                claim.verification_status == VerificationStatus.VERIFIED for claim in claims
            ),
            partially_verified=sum(
                claim.verification_status == VerificationStatus.PARTIALLY_VERIFIED
                for claim in claims
            ),
            unverified=sum(
                claim.verification_status == VerificationStatus.UNVERIFIED for claim in claims
            ),
            contradicted=sum(
                claim.verification_status == VerificationStatus.CONTRADICTED for claim in claims
            ),
            disputed=sum(
                claim.verification_status == VerificationStatus.DISPUTED for claim in claims
            ),
            high_priority_needing_review=sum(
                claim.importance in {ClaimImportance.HIGH, ClaimImportance.CRITICAL}
                and claim.verification_status != VerificationStatus.VERIFIED
                for claim in claims
            ),
        )

    def approvals(self) -> list[ApprovalItem]:
        approvals = list(
            self.session.scalars(
                select(Approval)
                .where(Approval.status == ApprovalStatus.PENDING)
                .options(
                    selectinload(Approval.video_project),
                    selectinload(Approval.content_version),
                )
                .order_by(Approval.requested_at.asc())
            ).all()
        )
        return [self.approval_item(approval) for approval in approvals]

    def approval_item(self, approval: Approval) -> ApprovalItem:
        content = approval.content_version
        return ApprovalItem(
            id=approval.id,
            approval_type=approval_type_label(approval.approval_type),
            project_id=approval.video_project_id,
            project_title=approval.video_project.working_title,
            content_type=content_type_label(content.content_type if content is not None else None),
            version_number=content.version_number if content is not None else None,
            requested_at=self.display_time(approval.requested_at),
            expires_at=self.display_time(approval.expires_at) if approval.expires_at else None,
            status=approval_status_label(approval.status),
            preview=(content.content[:500] if content is not None else approval.feedback or ""),
        )

    def jobs(
        self,
        *,
        status: str | None = None,
        project_id: str | None = None,
        resource_class: str | None = None,
        job_type: str | None = None,
    ) -> JobGroups:
        query = select(Job).options(selectinload(Job.video_project)).order_by(Job.created_at.desc())
        if status:
            try:
                query = query.where(Job.status == JobStatus(status))
            except ValueError:
                return JobGroups([], [], [], [], [], [], [], [])
        if project_id:
            query = query.where(Job.video_project_id == project_id)
        if resource_class:
            try:
                query = query.where(Job.resource_class == ResourceClass(resource_class))
            except ValueError:
                return JobGroups([], [], [], [], [], [], [], [])
        if job_type:
            query = query.where(Job.job_type == job_type)
        jobs = [self.job_item(job) for job in self.session.scalars(query).all()]
        return JobGroups(
            running=[job for job in jobs if job.status_value == JobStatus.RUNNING.value],
            waiting=[
                job
                for job in jobs
                if job.status_value
                in {
                    JobStatus.PENDING.value,
                    JobStatus.READY.value,
                    JobStatus.WAITING_FOR_DEPENDENCY.value,
                    JobStatus.WAITING_FOR_APPROVAL.value,
                }
            ],
            scheduled=[job for job in jobs if job.status_value == JobStatus.READY.value],
            retrying=[job for job in jobs if job.status_value == JobStatus.RETRYING.value],
            failed=[job for job in jobs if job.status_value == JobStatus.FAILED.value],
            completed=[job for job in jobs if job.status_value == JobStatus.COMPLETED.value],
            paused=[job for job in jobs if job.status_value == JobStatus.PAUSED.value],
            cancelled=[job for job in jobs if job.status_value == JobStatus.CANCELLED.value],
        )

    def job_item(self, job: Job) -> JobItem:
        return JobItem(
            id=job.id,
            job_type=job_type_label(job.job_type),
            project_id=job.video_project_id,
            project_title=job.video_project.working_title,
            status=job_status_label(job.status),
            status_value=job.status.value,
            priority=job.priority,
            resource_class=resource_class_label(job.resource_class),
            created_at=self.display_time(job.created_at),
            started_at=self.display_time(job.started_at) if job.started_at else None,
            completed_at=self.display_time(job.completed_at) if job.completed_at else None,
            attempts=job.attempts,
            max_attempts=job.max_attempts,
            worker=job.claimed_by or "",
            error_summary=job.last_error_message or job.error_message,
            technical_details=job.last_error_details or {},
        )

    def activity(self, *, project_id: str | None = None, limit: int = 20) -> list[ActivityItem]:
        items: list[ActivityItem] = []
        project_query = select(VideoProject).order_by(VideoProject.created_at.desc()).limit(limit)
        if project_id is not None:
            project_query = project_query.where(VideoProject.id == project_id)
        for project in self.session.scalars(project_query):
            items.append(
                ActivityItem(
                    timestamp=self.display_time(project.created_at),
                    title="Project created",
                    detail=project.working_title,
                    project_id=project.id,
                    tone="success",
                )
            )
        items.extend(self._job_activity(project_id, limit))
        items.extend(self._approval_activity(project_id, limit))
        items.extend(self._content_activity(project_id, limit))
        return sorted(items, key=lambda item: item.timestamp, reverse=True)[:limit]

    def display_time(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(self.timezone)

    def workflow_stage(self, project_id: str) -> str | None:
        workflow = self.session.scalar(
            select(WorkflowInstance)
            .where(WorkflowInstance.video_project_id == project_id)
            .order_by(WorkflowInstance.updated_at.desc())
            .limit(1)
        )
        return workflow.current_stage.replace("_", " ").title() if workflow is not None else None

    def latest_version(
        self, versions: list[ContentVersion], content_type: ContentType
    ) -> ContentVersion | None:
        candidates = [version for version in versions if version.content_type == content_type]
        return max(candidates, key=lambda version: version.version_number, default=None)

    def version_labels(
        self, versions: list[ContentVersion], content_type: ContentType
    ) -> list[str]:
        return [
            (
                f"v{version.version_number} - "
                f"{self.display_time(version.created_at).strftime('%Y-%m-%d %H:%M')}"
            )
            for version in sorted(
                [item for item in versions if item.content_type == content_type],
                key=lambda item: item.version_number,
                reverse=True,
            )
        ]

    def readiness(self, project: VideoProject) -> tuple[list[str], list[str]]:
        blockers: list[str] = []
        warnings: list[str] = []
        if project.claims and any(
            claim.importance == ClaimImportance.CRITICAL
            and claim.verification_status != VerificationStatus.VERIFIED
            for claim in project.claims
        ):
            blockers.append("One critical claim is not verified.")
        if not any(source.status == SourceStatus.APPROVED for source in project.sources):
            blockers.append("No sources have been approved yet.")
        if not any(source.snapshot_path for source in project.sources):
            blockers.append("No source snapshots are available.")
        if any(source.publication_date is None for source in project.sources):
            warnings.append("Some sources do not have publication dates.")
        if any(not source.publisher for source in project.sources):
            warnings.append("Some sources do not have publisher names.")
        if any(source.duplicate_of_source_id for source in project.sources):
            warnings.append("Duplicate source content was detected.")
        return blockers, warnings

    def report_content(self, version: ContentVersion | None) -> str | dict[str, object] | None:
        if version is None:
            return None
        if version.content_format == ContentFormat.JSON:
            import json

            parsed = json.loads(version.content)
            return parsed if isinstance(parsed, dict) else {"report": parsed}
        return version.content

    def _job_activity(self, project_id: str | None, limit: int) -> list[ActivityItem]:
        query = select(Job).order_by(Job.updated_at.desc()).limit(limit)
        if project_id is not None:
            query = query.where(Job.video_project_id == project_id)
        items: list[ActivityItem] = []
        for job in self.session.scalars(query):
            tone = "error" if job.status == JobStatus.FAILED else "neutral"
            if job.status == JobStatus.COMPLETED:
                tone = "success"
            items.append(
                ActivityItem(
                    timestamp=self.display_time(job.updated_at),
                    title=f"Job {job_status_label(job.status)}",
                    detail=job_type_label(job.job_type),
                    project_id=job.video_project_id,
                    tone=tone,
                )
            )
        return items

    def _approval_activity(self, project_id: str | None, limit: int) -> list[ActivityItem]:
        query = select(Approval).order_by(Approval.requested_at.desc()).limit(limit)
        if project_id is not None:
            query = query.where(Approval.video_project_id == project_id)
        items: list[ActivityItem] = []
        for approval in self.session.scalars(query):
            timestamp = approval.responded_at or approval.requested_at
            tone = "warning" if approval.status == ApprovalStatus.PENDING else "success"
            items.append(
                ActivityItem(
                    timestamp=self.display_time(timestamp),
                    title=f"Approval {approval_status_label(approval.status)}",
                    detail=approval_type_label(approval.approval_type),
                    project_id=approval.video_project_id,
                    tone=tone,
                )
            )
        return items

    def _content_activity(self, project_id: str | None, limit: int) -> list[ActivityItem]:
        query = select(ContentVersion).order_by(ContentVersion.created_at.desc()).limit(limit)
        if project_id is not None:
            query = query.where(ContentVersion.video_project_id == project_id)
        return [
            ActivityItem(
                timestamp=self.display_time(version.created_at),
                title="Content version created",
                detail=f"{content_type_label(version.content_type)} v{version.version_number}",
                project_id=version.video_project_id,
                tone="success",
            )
            for version in self.session.scalars(query)
        ]

    def _count(self, model: type[Channel] | type[VideoProject]) -> int:
        return int(self.session.scalar(select(func.count()).select_from(model)) or 0)

    def _count_jobs(self, status: JobStatus) -> int:
        return int(
            self.session.scalar(select(func.count()).select_from(Job).where(Job.status == status))
            or 0
        )

    def _count_approvals(self, status: ApprovalStatus) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(Approval).where(Approval.status == status)
            )
            or 0
        )

    def _timezone(self, key: str) -> tzinfo:
        try:
            return ZoneInfo(key)
        except ZoneInfoNotFoundError:
            if key == "Asia/Kolkata":
                return timezone(timedelta(hours=5, minutes=30), name="Asia/Kolkata")
            return UTC


def grouped_source_type_counts(sources: list[Source]) -> dict[str, int]:
    return dict(Counter(source_type_label(source.source_type) for source in sources))


def grouped_source_status_counts(sources: list[Source]) -> dict[str, int]:
    return dict(Counter(source_status_label(source.status) for source in sources))


def source_authority_display(source: Source) -> str:
    return authority_tier_label(source.authority_tier)


def _asset_sort_key(asset: Asset) -> tuple[int, str, datetime]:
    scene_number = asset.scene.scene_number if asset.scene is not None else 0
    return (scene_number, asset.asset_role.value, asset.created_at)


def _render_sort_key(render: Render) -> tuple[int, datetime]:
    return (-render.version_number, render.created_at)


def _string_list(value: object) -> list[str]:
    if isinstance(value, Sequence) and not isinstance(value, str):
        return [str(item) for item in value if item is not None]
    return []


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None
