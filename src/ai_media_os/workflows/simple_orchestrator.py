"""Small persisted workflow orchestrator used as the comparison baseline."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_media_os.application.approvals import ApprovalError, ApprovalService
from ai_media_os.application.job_queue import QueueService
from ai_media_os.domain.enums import ApprovalType, ContentType, ResourceClass
from ai_media_os.infrastructure.database.base import new_uuid, utc_now
from ai_media_os.infrastructure.database.models import (
    Approval,
    ContentVersion,
    Job,
    VideoProject,
    WorkflowEventRecord,
    WorkflowInstance,
)
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.workers.asset_handlers import JOB_PLAN_SCENE_ASSETS
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
        self.session.commit()
        return workflow.id

    def resume(self, workflow_id: str, event: WorkflowEvent) -> WorkflowState:
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
            case WorkflowEventType.WORKFLOW_CANCELLED:
                self._handle_cancelled(workflow, event)

        workflow.last_event_id = event.event_id
        workflow.updated_at = utc_now()
        self._record_event(workflow, event)
        self.session.commit()
        self.session.refresh(workflow)
        return self._to_state(workflow)

    def get_state(self, workflow_id: str) -> WorkflowState:
        return self._to_state(self._get_workflow(workflow_id))

    def _handle_research_completed(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.RESEARCH)
        self._validate_job(event.job_id, workflow.video_project_id, workflow.research_job_id)
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
        self._validate_job(event.job_id, workflow.video_project_id, workflow.script_job_id)
        version = self._validate_content_version(
            event.content_version_id,
            workflow.video_project_id,
            ContentType.SCRIPT,
        )
        self.session.commit()
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
        self.session.commit()
        self.approvals.approve(approval.id, feedback=event.feedback)
        workflow.current_stage = WorkflowStage.COMPLETE.value
        workflow.status = WorkflowStatus.COMPLETED.value

    def _handle_script_changes_requested(
        self, workflow: WorkflowInstance, event: WorkflowEvent
    ) -> None:
        self._require_stage(workflow, WorkflowStage.WAIT_FOR_SCRIPT_APPROVAL)
        approval = self._validate_approval(event.approval_id, workflow)
        self.session.commit()
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
        self.session.commit()
        self.approvals.reject(approval.id, feedback=event.feedback)
        workflow.current_stage = WorkflowStage.REJECTED.value
        workflow.status = WorkflowStatus.REJECTED.value
        workflow.error_message = event.feedback

    def _handle_scene_plan_approved(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        version = self._validate_content_version(
            event.content_version_id,
            workflow.video_project_id,
            ContentType.SCENE_PLAN,
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
        )
        workflow.current_stage = WorkflowStage.ASSET_GENERATION.value
        workflow.status = WorkflowStatus.RUNNING.value
        workflow.metadata_json = {**dict(workflow.metadata_json), "assets_planned": True}

    def _handle_assets_generated(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.ASSET_GENERATION)
        workflow.current_stage = WorkflowStage.ASSET_REVIEW.value
        workflow.status = WorkflowStatus.WAITING_FOR_APPROVAL.value
        workflow.metadata_json = {**dict(workflow.metadata_json), "assets_generated": True}

    def _handle_assets_approved(self, workflow: WorkflowInstance, event: WorkflowEvent) -> None:
        self._require_stage(workflow, WorkflowStage.ASSET_REVIEW)
        workflow.current_stage = WorkflowStage.MILESTONE_6_COMPLETE.value
        workflow.status = WorkflowStatus.COMPLETED.value
        workflow.metadata_json = {**dict(workflow.metadata_json), "assets_approved": True}

    def _handle_failure(
        self, workflow: WorkflowInstance, event: WorkflowEvent, stage: WorkflowStage
    ) -> None:
        if event.event_type == WorkflowEventType.RESEARCH_FAILED:
            self._require_stage(workflow, WorkflowStage.RESEARCH)
            self._validate_job(event.job_id, workflow.video_project_id, workflow.research_job_id)
        else:
            if WorkflowStage(workflow.current_stage) not in {
                WorkflowStage.SCRIPT,
                WorkflowStage.SCRIPT_REVISION,
            }:
                raise WorkflowError("Script failure arrived in an invalid workflow state.")
            self._validate_job(event.job_id, workflow.video_project_id, workflow.script_job_id)
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
        return job

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
