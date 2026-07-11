"""Small persisted workflow orchestrator used as the comparison baseline."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_media_os.application.approvals import ApprovalError, ApprovalService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.application.transactions import write_transaction
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    AssetType,
    ContentType,
    JobStatus,
    PublishingGateStatus,
    RenderStatus,
    ResourceClass,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import new_uuid, utc_now
from ai_media_os.infrastructure.database.models import (
    Approval,
    Asset,
    ContentVersion,
    Job,
    PublishingGate,
    Render,
    VideoProject,
    WorkflowEventRecord,
    WorkflowInstance,
)
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.workers.asset_handlers import JOB_PLAN_SCENE_ASSETS
from ai_media_os.workers.packaging_handlers import (
    JOB_GENERATE_THUMBNAIL_CONCEPT,
    JOB_GENERATE_VIDEO_METADATA,
)
from ai_media_os.workers.safety_handlers import JOB_RUN_PUBLISHING_GATE
from ai_media_os.workflows.models import (
    WorkflowEvent,
    WorkflowEventType,
    WorkflowStage,
    WorkflowState,
    WorkflowStatus,
)


class WorkflowError(RuntimeError):
    """Raised when workflow orchestration rules are violated."""


TERMINAL_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.REJECTED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
}


class SimpleWorkflowOrchestrator:
    """Coordinate logical workflow state above existing application services."""

    def __init__(self, session: Session, settings: AppSettings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.queue = QueueService(session, self.settings)
        self.approvals = ApprovalService(session)

    def start(self, project_id: UUID) -> str:
        with write_transaction(self.session):
            project_key = str(project_id)
            if self.session.get(VideoProject, project_key) is None:
                raise WorkflowError(f"Video project not found: {project_key}")
            research_job = self.queue.create_job(
                video_project_id=project_key,
                job_type="workflow.fake_research",
                payload={"workflow_stage": WorkflowStage.RESEARCH.value},
                resource_class=ResourceClass.CPU_LIGHT,
            )
            now = utc_now()
            workflow = WorkflowInstance(
                id=new_uuid(),
                video_project_id=project_key,
                current_stage=WorkflowStage.RESEARCH.value,
                status=WorkflowStatus.RUNNING.value,
                research_job_id=research_job.id,
                max_revisions=self.settings.workflow_max_script_revisions,
                metadata_json={"orchestrator": "simple"},
                created_at=now,
                updated_at=now,
            )
            self.session.add(workflow)
            self.session.flush()
            return workflow.id

    def resume(self, workflow_id: str, event: WorkflowEvent) -> WorkflowState:
        with write_transaction(self.session):
            workflow = self._get_workflow(workflow_id)
            self._validate_event_identity(workflow, event)
            if self._event_was_processed(workflow_id, event.event_id):
                return self._to_state(workflow)
            if WorkflowStatus(workflow.status) in TERMINAL_STATUSES:
                return self._to_state(workflow)

            match event.event_type:
                case WorkflowEventType.RESEARCH_COMPLETED:
                    self._handle_research_completed(workflow, event)
                case WorkflowEventType.RESEARCH_FAILED:
                    self._handle_failure(workflow, event, WorkflowStage.FAILED)
                case WorkflowEventType.SCRIPT_COMPLETED:
                    self._handle_script_completed(workflow, event)
                case WorkflowEventType.SCRIPT_FAILED:
                    self._handle_failure(workflow, event, WorkflowStage.FAILED)
                case WorkflowEventType.SCRIPT_APPROVED:
                    self._handle_script_approved(workflow, event)
                case WorkflowEventType.SCRIPT_CHANGES_REQUESTED:
                    self._handle_script_changes_requested(workflow, event)
                case WorkflowEventType.SCRIPT_REJECTED:
                    self._handle_script_rejected(workflow, event)
                case WorkflowEventType.SCENE_PLAN_APPROVED:
                    self._handle_scene_plan_approved(workflow, event)
                case WorkflowEventType.ASSETS_PLANNED:
                    self._handle_assets_planned(workflow, event)
                case WorkflowEventType.ASSETS_GENERATED:
                    self._handle_assets_generated(workflow, event)
                case WorkflowEventType.ASSETS_APPROVED:
                    self._handle_assets_approved(workflow, event)
                case WorkflowEventType.RENDER_VERIFIED:
                    self._handle_render_verified(workflow, event)
                case WorkflowEventType.METADATA_APPROVED:
                    self._handle_metadata_approved(workflow, event)
                case WorkflowEventType.THUMBNAIL_APPROVED:
                    self._handle_thumbnail_approved(workflow, event)
                case WorkflowEventType.SAFETY_REVIEW_COMPLETED:
                    self._handle_safety_review_completed(workflow, event)
                case WorkflowEventType.WORKFLOW_CANCELLED:
                    self._handle_cancelled(workflow, event)

            workflow.last_event_id = event.event_id
            workflow.updated_at = utc_now()
            self._record_event(workflow, event)
            self.session.flush()
            self.session.refresh(workflow)
            return self._to_state(workflow)

    def get_state(self, workflow_id: str) -> WorkflowState:
        return self._to_state(self._get_workflow(workflow_id))

    def _handle_research_completed(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.RESEARCH)
        self._validate_job(
            event.job_id,
            workflow.video_project_id,
            workflow.research_job_id,
            {JobStatus.COMPLETED},
        )
        version = self._validate_content_version(
            event.content_version_id,
            workflow.video_project_id,
            ContentType.RESEARCH_BRIEF,
        )
        script_job = self.queue.create_job(
            video_project_id=workflow.video_project_id,
            job_type="workflow.fake_script",
            payload={"workflow_id": workflow.id, "revision_number": workflow.revision_number},
            resource_class=ResourceClass.CPU_LIGHT,
        )
        workflow.research_content_version_id = version.id
        workflow.script_job_id = script_job.id
        workflow.current_stage = WorkflowStage.SCRIPT.value
        workflow.status = WorkflowStatus.RUNNING.value

    def _handle_script_completed(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        if WorkflowStage(workflow.current_stage) not in {
            WorkflowStage.SCRIPT,
            WorkflowStage.SCRIPT_REVISION,
        }:
            raise WorkflowError("Script completion arrived in an invalid workflow state.")
        self._validate_job(
            event.job_id,
            workflow.video_project_id,
            workflow.script_job_id,
            {JobStatus.COMPLETED},
        )
        version = self._validate_content_version(
            event.content_version_id,
            workflow.video_project_id,
            ContentType.SCRIPT,
        )
        approval = self.approvals.request_approval(
            video_project_id=workflow.video_project_id,
            approval_type=ApprovalType.SCRIPT,
            content_version_id=version.id,
        )
        workflow.script_content_version_id = version.id
        workflow.approval_id = approval.id
        workflow.current_stage = WorkflowStage.WAIT_FOR_SCRIPT_APPROVAL.value
        workflow.status = WorkflowStatus.WAITING_FOR_APPROVAL.value

    def _handle_script_approved(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.WAIT_FOR_SCRIPT_APPROVAL)
        approval = self._validate_approval(event.approval_id, workflow)
        self.approvals.approve(approval.id, feedback=event.feedback)
        workflow.current_stage = WorkflowStage.COMPLETE.value
        workflow.status = WorkflowStatus.COMPLETED.value

    def _handle_script_changes_requested(
        self, workflow: WorkflowInstance, event: WorkflowEvent
    ) -> None:
        self._require_stage(workflow, WorkflowStage.WAIT_FOR_SCRIPT_APPROVAL)
        approval = self._validate_approval(event.approval_id, workflow)
        try:
            self.approvals.request_changes(approval.id, feedback=event.feedback)
        except ApprovalError as exc:
            raise WorkflowError(str(exc)) from exc
        if workflow.revision_number >= workflow.max_revisions:
            workflow.current_stage = WorkflowStage.FAILED.value
            workflow.status = WorkflowStatus.FAILED.value
            workflow.error_message = "Maximum script revision count exhausted."
            return
        workflow.revision_number += 1
        revision_job = self.queue.create_job(
            video_project_id=workflow.video_project_id,
            job_type="workflow.fake_script_revision",
            payload={"workflow_id": workflow.id, "revision_number": workflow.revision_number},
            resource_class=ResourceClass.CPU_LIGHT,
        )
        workflow.script_job_id = revision_job.id
        workflow.approval_id = None
        workflow.current_stage = WorkflowStage.SCRIPT_REVISION.value
        workflow.status = WorkflowStatus.RUNNING.value

    def _handle_script_rejected(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.WAIT_FOR_SCRIPT_APPROVAL)
        approval = self._validate_approval(event.approval_id, workflow)
        self.approvals.reject(approval.id, feedback=event.feedback)
        workflow.current_stage = WorkflowStage.REJECTED.value
        workflow.status = WorkflowStatus.REJECTED.value
        workflow.error_message = event.feedback

    def _handle_scene_plan_approved(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        version = self._validate_approved_content_version(
            event.content_version_id,
            workflow.video_project_id,
            ContentType.SCENE_PLAN,
            ApprovalType.SCENE_PLAN,
        )
        asset_job = self.queue.create_job(
            video_project_id=workflow.video_project_id,
            job_type=JOB_PLAN_SCENE_ASSETS,
            payload={"workflow_id": workflow.id, "scene_plan_version_id": version.id},
            resource_class=ResourceClass.CPU_LIGHT,
        )
        workflow.current_stage = WorkflowStage.ASSET_PLANNING.value
        workflow.status = WorkflowStatus.RUNNING.value
        workflow.metadata_json = {
            **dict(workflow.metadata_json),
            "scene_plan_content_version_id": version.id,
            "asset_planning_job_id": asset_job.id,
        }

    def _handle_assets_planned(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        expected_job_id = dict(workflow.metadata_json).get("asset_planning_job_id")
        self._validate_job(
            event.job_id,
            workflow.video_project_id,
            str(expected_job_id) if expected_job_id else None,
            {JobStatus.COMPLETED},
        )
        workflow.current_stage = WorkflowStage.ASSET_GENERATION.value
        workflow.status = WorkflowStatus.RUNNING.value
        workflow.metadata_json = {**dict(workflow.metadata_json), "assets_planned": True}

    def _handle_assets_generated(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.ASSET_GENERATION)
        assets = self._scene_assets(workflow.video_project_id)
        if not assets or any(
            asset.generation_status
            not in {
                AssetGenerationStatus.GENERATED,
                AssetGenerationStatus.IMPORTED,
                AssetGenerationStatus.APPROVED,
            }
            or not asset.content_hash
            for asset in assets
        ):
            raise WorkflowError("All scene assets must be generated or imported before review.")
        workflow.current_stage = WorkflowStage.ASSET_REVIEW.value
        workflow.status = WorkflowStatus.WAITING_FOR_APPROVAL.value
        workflow.metadata_json = {**dict(workflow.metadata_json), "assets_generated": True}

    def _handle_assets_approved(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.ASSET_REVIEW)
        assets = self._scene_assets(workflow.video_project_id)
        if not assets or any(
            asset.review_status != AssetReviewStatus.APPROVED
            or asset.generation_status != AssetGenerationStatus.APPROVED
            for asset in assets
        ):
            raise WorkflowError("All scene assets must have persisted approval before continuing.")
        workflow.current_stage = WorkflowStage.MILESTONE_6_COMPLETE.value
        workflow.status = WorkflowStatus.COMPLETED.value
        workflow.metadata_json = {**dict(workflow.metadata_json), "assets_approved": True}

    def _handle_render_verified(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        render_id = str(event.metadata.get("render_id") or "")
        if not render_id:
            raise WorkflowError("Render verification event is missing render_id metadata.")
        render = self.session.get(Render, render_id)
        if render is None or render.video_project_id != workflow.video_project_id:
            raise WorkflowError("Workflow render was not found for this project.")
        if render.status != RenderStatus.APPROVED or not render.content_hash:
            raise WorkflowError("Workflow render must be verified and approved.")
        metadata_job = self.queue.create_job(
            video_project_id=workflow.video_project_id,
            job_type=JOB_GENERATE_VIDEO_METADATA,
            payload={"workflow_id": workflow.id, "render_id": render_id},
            resource_class=ResourceClass.CPU_LIGHT,
        )
        workflow.current_stage = WorkflowStage.METADATA_GENERATION.value
        workflow.status = WorkflowStatus.RUNNING.value
        workflow.metadata_json = {
            **dict(workflow.metadata_json),
            "verified_render_id": render_id,
            "metadata_job_id": metadata_job.id,
        }

    def _handle_metadata_approved(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        version = self._validate_approved_content_version(
            event.content_version_id,
            workflow.video_project_id,
            ContentType.METADATA,
            ApprovalType.METADATA,
        )
        concept_job = self.queue.create_job(
            video_project_id=workflow.video_project_id,
            job_type=JOB_GENERATE_THUMBNAIL_CONCEPT,
            payload={"workflow_id": workflow.id, "metadata_version_id": version.id},
            resource_class=ResourceClass.CPU_LIGHT,
        )
        workflow.current_stage = WorkflowStage.THUMBNAIL_CONCEPT.value
        workflow.status = WorkflowStatus.RUNNING.value
        workflow.metadata_json = {
            **dict(workflow.metadata_json),
            "metadata_content_version_id": version.id,
            "thumbnail_concept_job_id": concept_job.id,
        }

    def _handle_thumbnail_approved(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        asset_id = str(event.metadata.get("thumbnail_asset_id") or "")
        if not asset_id:
            raise WorkflowError("Thumbnail approval event is missing thumbnail_asset_id metadata.")
        thumbnail = self.session.get(Asset, asset_id)
        if thumbnail is None or thumbnail.video_project_id != workflow.video_project_id:
            raise WorkflowError("Workflow thumbnail was not found for this project.")
        if (
            thumbnail.asset_type != AssetType.THUMBNAIL
            or thumbnail.review_status != AssetReviewStatus.APPROVED
            or thumbnail.generation_status != AssetGenerationStatus.APPROVED
        ):
            raise WorkflowError("Workflow thumbnail must have persisted approval.")
        safety_gate_job = self.queue.create_job(
            video_project_id=workflow.video_project_id,
            job_type=JOB_RUN_PUBLISHING_GATE,
            payload={
                "workflow_id": workflow.id,
                "render_id": dict(workflow.metadata_json).get("verified_render_id"),
                "metadata_version_id": dict(workflow.metadata_json).get(
                    "metadata_content_version_id"
                ),
                "thumbnail_asset_id": asset_id,
            },
            resource_class=ResourceClass.CPU_LIGHT,
        )
        workflow.current_stage = WorkflowStage.SAFETY_REVIEW.value
        workflow.status = WorkflowStatus.RUNNING.value
        workflow.metadata_json = {
            **dict(workflow.metadata_json),
            "thumbnail_asset_id": asset_id,
            "thumbnail_approved": True,
            "safety_gate_job_id": safety_gate_job.id,
        }

    def _handle_safety_review_completed(
        self, workflow: WorkflowInstance, event: WorkflowEvent
    ) -> None:
        expected_job_id = str(dict(workflow.metadata_json).get("safety_gate_job_id") or "")
        job = self._validate_job(
            event.job_id,
            workflow.video_project_id,
            expected_job_id or None,
            {JobStatus.COMPLETED},
        )
        job_result = job.result or {}
        gate_id = str(event.metadata.get("gate_id") or job_result.get("gate_id") or "")
        gate = self.session.get(PublishingGate, gate_id)
        if gate is None or gate.video_project_id != workflow.video_project_id:
            raise WorkflowError("Persisted publishing gate was not found for this project.")
        gate_status = gate.status.value
        supplied_status = str(event.metadata.get("gate_status") or job_result.get("status") or "")
        if supplied_status and supplied_status != gate_status:
            raise WorkflowError(
                "Safety review status does not match the persisted publishing gate."
            )
        report_version_id = str(
            event.metadata.get("report_version_id") or job_result.get("report_version_id") or ""
        )
        if report_version_id != gate.report_content_version_id:
            raise WorkflowError(
                "Safety review report does not match the persisted publishing gate."
            )
        workflow.metadata_json = {
            **dict(workflow.metadata_json),
            "safety_gate_status": gate_status,
            "safety_gate_id": gate.id,
            "safety_gate_report_id": gate.report_content_version_id,
        }
        if gate.status in {
            PublishingGateStatus.PASS,
            PublishingGateStatus.PASS_WITH_WARNINGS,
        }:
            workflow.current_stage = WorkflowStage.MILESTONE_8_5_COMPLETE.value
            workflow.status = WorkflowStatus.COMPLETED.value
        elif gate.status == PublishingGateStatus.NEEDS_REVIEW:
            workflow.current_stage = WorkflowStage.SAFETY_REVIEW.value
            workflow.status = WorkflowStatus.WAITING_FOR_APPROVAL.value
        else:
            workflow.current_stage = WorkflowStage.FAILED.value
            workflow.status = WorkflowStatus.FAILED.value
            workflow.error_message = str(
                event.metadata.get("summary") or event.feedback or "Safety gate blocked."
            )

    def _handle_failure(
        self, workflow: WorkflowInstance, event: WorkflowEvent, stage: WorkflowStage
    ) -> None:
        if event.event_type == WorkflowEventType.RESEARCH_FAILED:
            self._require_stage(workflow, WorkflowStage.RESEARCH)
            self._validate_job(
                event.job_id,
                workflow.video_project_id,
                workflow.research_job_id,
                {JobStatus.FAILED},
            )
        else:
            if WorkflowStage(workflow.current_stage) not in {
                WorkflowStage.SCRIPT,
                WorkflowStage.SCRIPT_REVISION,
            }:
                raise WorkflowError("Script failure arrived in an invalid workflow state.")
            self._validate_job(
                event.job_id,
                workflow.video_project_id,
                workflow.script_job_id,
                {JobStatus.FAILED},
            )
        workflow.current_stage = stage.value
        workflow.status = WorkflowStatus.FAILED.value
        workflow.error_message = event.feedback or f"{event.event_type.value} received."

    def _handle_cancelled(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        workflow.current_stage = WorkflowStage.CANCELLED.value
        workflow.status = WorkflowStatus.CANCELLED.value
        workflow.error_message = event.feedback

    def _validate_event_identity(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        if event.workflow_id != workflow.id:
            raise WorkflowError("Event workflow ID does not match the target workflow.")
        if str(event.video_project_id) != workflow.video_project_id:
            raise WorkflowError("Event project ID does not match the workflow project.")

    def _event_was_processed(self, workflow_id: str, event_id: str) -> bool:
        return (
            self.session.scalar(
                select(WorkflowEventRecord).where(
                    WorkflowEventRecord.workflow_id == workflow_id,
                    WorkflowEventRecord.event_id == event_id,
                )
            )
            is not None
        )

    def _record_event(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self.session.add(
            WorkflowEventRecord(
                workflow_id=workflow.id,
                video_project_id=workflow.video_project_id,
                event_id=event.event_id,
                event_type=event.event_type.value,
                job_id=event.job_id,
                content_version_id=event.content_version_id,
                approval_id=event.approval_id,
                feedback=event.feedback,
                metadata_json=dict(event.metadata),
                created_at=event.timestamp,
            )
        )

    def _require_stage(self, workflow: WorkflowInstance, stage: WorkflowStage) -> None:
        if WorkflowStage(workflow.current_stage) != stage:
            raise WorkflowError(
                f"Expected workflow stage {stage.value}, got {workflow.current_stage}."
            )

    def _validate_job(
        self,
        job_id: str | None,
        project_id: str,
        expected_job_id: str | None,
        allowed_statuses: set[JobStatus] | None = None,
    ) -> Job:
        if job_id is None:
            raise WorkflowError("Workflow event is missing the required job reference.")
        if expected_job_id is not None and job_id != expected_job_id:
            raise WorkflowError("Workflow event job does not match the expected workflow job.")
        job = self.session.get(Job, job_id)
        if job is None:
            raise WorkflowError(f"Workflow event job not found: {job_id}")
        if job.video_project_id != project_id:
            raise WorkflowError("Workflow event job belongs to another project.")
        if allowed_statuses is not None and job.status not in allowed_statuses:
            expected = ", ".join(sorted(status.value for status in allowed_statuses))
            raise WorkflowError(f"Workflow event job must have status: {expected}.")
        return job

    def _validate_approved_content_version(
        self,
        content_version_id: str | None,
        project_id: str,
        content_type: ContentType,
        approval_type: ApprovalType,
    ) -> ContentVersion:
        version = self._validate_content_version(content_version_id, project_id, content_type)
        if version.status != VersionStatus.APPROVED:
            raise WorkflowError("Workflow content version is not approved.")
        approval = self.session.scalar(
            select(Approval).where(
                Approval.video_project_id == project_id,
                Approval.content_version_id == version.id,
                Approval.approval_type == approval_type,
                Approval.status == ApprovalStatus.APPROVED,
            )
        )
        if approval is None:
            raise WorkflowError("Workflow content version has no persisted approval decision.")
        return version

    def _scene_assets(self, project_id: str) -> list[Asset]:
        return list(
            self.session.scalars(
                select(Asset).where(
                    Asset.video_project_id == project_id,
                    Asset.asset_role.in_({AssetRole.SCENE_VISUAL, AssetRole.SCENE_NARRATION}),
                )
            ).all()
        )

    def _validate_content_version(
        self,
        content_version_id: str | None,
        project_id: str,
        content_type: ContentType,
    ) -> ContentVersion:
        if content_version_id is None:
            raise WorkflowError("Workflow event is missing the required content-version reference.")
        version = self.session.get(ContentVersion, content_version_id)
        if version is None:
            raise WorkflowError(f"Workflow event content version not found: {content_version_id}")
        if version.video_project_id != project_id:
            raise WorkflowError("Workflow event content version belongs to another project.")
        if version.content_type != content_type:
            raise WorkflowError("Workflow event content version has the wrong content type.")
        return version

    def _validate_approval(
        self,
        approval_id: str | None,
        workflow: WorkflowInstance,
    ) -> Approval:
        if approval_id is None:
            raise WorkflowError("Workflow event is missing the required approval reference.")
        if workflow.approval_id != approval_id:
            raise WorkflowError("Workflow event approval does not match the workflow approval.")
        approval = self.session.get(Approval, approval_id)
        if approval is None:
            raise WorkflowError(f"Workflow approval not found: {approval_id}")
        if approval.video_project_id != workflow.video_project_id:
            raise WorkflowError("Workflow approval belongs to another project.")
        if approval.content_version_id != workflow.script_content_version_id:
            raise WorkflowError("Workflow approval does not match the current script version.")
        return approval

    def _get_workflow(self, workflow_id: str) -> WorkflowInstance:
        workflow = self.session.get(WorkflowInstance, workflow_id)
        if workflow is None:
            raise WorkflowError(f"Workflow not found: {workflow_id}")
        return workflow

    @staticmethod
    def _to_state(workflow: WorkflowInstance) -> WorkflowState:
        return WorkflowState(
            workflow_id=workflow.id,
            video_project_id=UUID(workflow.video_project_id),
            current_stage=WorkflowStage(workflow.current_stage),
            status=WorkflowStatus(workflow.status),
            research_job_id=workflow.research_job_id,
            research_content_version_id=workflow.research_content_version_id,
            script_job_id=workflow.script_job_id,
            script_content_version_id=workflow.script_content_version_id,
            approval_id=workflow.approval_id,
            revision_number=workflow.revision_number,
            max_revisions=workflow.max_revisions,
            last_event_id=workflow.last_event_id,
            created_at=workflow.created_at,
            updated_at=workflow.updated_at,
            error_message=workflow.error_message,
            metadata=dict(workflow.metadata_json),
        )
