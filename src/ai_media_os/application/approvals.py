"""Application service for append-only approval records."""

from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ContentType,
    JobStatus,
    VersionStatus,
)
from ai_media_os.domain.job_queue import validate_job_transition
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import Approval, ContentVersion, Job


class ApprovalError(RuntimeError):
    """Raised when approval rules are violated."""


APPROVAL_TERMINAL_STATUSES = frozenset(
    {
        ApprovalStatus.APPROVED,
        ApprovalStatus.REJECTED,
        ApprovalStatus.CHANGES_REQUESTED,
        ApprovalStatus.EXPIRED,
        ApprovalStatus.CANCELLED,
    }
)


class ApprovalService:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.content_versions = ContentVersionService(session)

    def request_approval(
        self,
        *,
        video_project_id: str,
        approval_type: ApprovalType,
        content_version_id: str | None = None,
        job_id: str | None = None,
        reviewer: str | None = None,
        feedback: str | None = None,
        expires_at: datetime | None = None,
    ) -> Approval:
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            content_version = self._validate_related_content_version(
                video_project_id=video_project_id,
                approval_type=approval_type,
                content_version_id=content_version_id,
            )
            self._ensure_no_duplicate_pending(
                video_project_id=video_project_id,
                approval_type=approval_type,
                content_version_id=content_version.id if content_version is not None else None,
            )
            approval = Approval(
                video_project_id=video_project_id,
                content_version_id=content_version.id if content_version is not None else None,
                approval_type=approval_type,
                status=ApprovalStatus.PENDING,
                reviewer=reviewer,
                feedback=feedback,
                requested_at=utc_now(),
                expires_at=expires_at,
                job_id=job_id,
            )
            if job_id is not None:
                job = self._get_job(job_id)
                if job.video_project_id != video_project_id:
                    raise ApprovalError("Approval job must belong to the same project.")
                validate_job_transition(job.status, JobStatus.WAITING_FOR_APPROVAL)
                job.status = JobStatus.WAITING_FOR_APPROVAL
                job.blocked_reason = f"Waiting for {approval_type.value} approval."
            self.session.add(approval)
            self.session.commit()
            self.session.refresh(approval)
            return approval
        except Exception:
            self.session.rollback()
            raise

    def approve(
        self, approval_id: str, reviewer: str | None = None, feedback: str | None = None
    ) -> Approval:
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            approval = self._decide_without_commit(
                approval_id,
                ApprovalStatus.APPROVED,
                reviewer=reviewer,
                feedback=feedback,
            )
            if approval.content_version_id is not None:
                version = self.content_versions._get_version(approval.content_version_id)
                self.content_versions.apply_approval_without_commit(version)
            if approval.job_id is not None:
                job = self._get_job(approval.job_id)
                validate_job_transition(job.status, JobStatus.READY)
                job.status = JobStatus.READY
                job.blocked_reason = None
            self.session.commit()
            self.session.refresh(approval)
            return approval
        except Exception:
            self.session.rollback()
            raise

    def reject(
        self, approval_id: str, reviewer: str | None = None, feedback: str | None = None
    ) -> Approval:
        return self._reject_or_block(
            approval_id,
            ApprovalStatus.REJECTED,
            "Approval rejected.",
            reviewer=reviewer,
            feedback=feedback,
            reject_content=True,
        )

    def request_changes(
        self,
        approval_id: str,
        reviewer: str | None = None,
        feedback: str | None = None,
    ) -> Approval:
        return self._reject_or_block(
            approval_id,
            ApprovalStatus.CHANGES_REQUESTED,
            "Approval requested changes.",
            reviewer=reviewer,
            feedback=feedback,
            reject_content=False,
        )

    def expire(self, approval_id: str) -> Approval:
        return self._reject_or_block(
            approval_id,
            ApprovalStatus.EXPIRED,
            "Approval expired.",
            reject_content=False,
        )

    def cancel(self, approval_id: str, feedback: str | None = None) -> Approval:
        return self._reject_or_block(
            approval_id,
            ApprovalStatus.CANCELLED,
            "Approval cancelled.",
            feedback=feedback,
            reject_content=False,
        )

    def pending_requests(self) -> list[Approval]:
        return list(
            self.session.scalars(
                select(Approval)
                .where(Approval.status == ApprovalStatus.PENDING)
                .order_by(Approval.requested_at.asc())
            ).all()
        )

    def _decide_without_commit(
        self,
        approval_id: str,
        status: ApprovalStatus,
        reviewer: str | None = None,
        feedback: str | None = None,
    ) -> Approval:
        approval = self._get_approval(approval_id)
        if approval.status != ApprovalStatus.PENDING:
            raise ApprovalError("Completed approval decisions cannot be changed.")
        approval.status = status
        approval.reviewer = reviewer or approval.reviewer
        approval.feedback = feedback
        approval.responded_at = utc_now()
        return approval

    def _reject_or_block(
        self,
        approval_id: str,
        status: ApprovalStatus,
        blocked_reason: str,
        reviewer: str | None = None,
        feedback: str | None = None,
        reject_content: bool = False,
    ) -> Approval:
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            approval = self._decide_without_commit(
                approval_id,
                status,
                reviewer=reviewer,
                feedback=feedback,
            )
            if reject_content and approval.content_version_id is not None:
                version = self.content_versions._get_version(approval.content_version_id)
                version.status = VersionStatus.REJECTED
            if approval.job_id is not None:
                job = self._get_job(approval.job_id)
                job.blocked_reason = blocked_reason
            self.session.commit()
            self.session.refresh(approval)
            return approval
        except Exception:
            self.session.rollback()
            raise

    def _validate_related_content_version(
        self,
        *,
        video_project_id: str,
        approval_type: ApprovalType,
        content_version_id: str | None,
    ) -> ContentVersion | None:
        if approval_type != ApprovalType.PUBLISHING and content_version_id is None:
            raise ApprovalError("This approval type requires a content version.")
        if content_version_id is None:
            return None
        version = self.content_versions._get_version(content_version_id)
        if version.video_project_id != video_project_id:
            raise ApprovalError("Approval content version must belong to the same project.")
        expected_content_type = APPROVAL_CONTENT_TYPE_MAP.get(approval_type)
        if expected_content_type is not None and version.content_type != expected_content_type:
            raise ApprovalError("Approval type does not match the content-version type.")
        return version

    def _ensure_no_duplicate_pending(
        self,
        *,
        video_project_id: str,
        approval_type: ApprovalType,
        content_version_id: str | None,
    ) -> None:
        query = select(Approval).where(
            Approval.video_project_id == video_project_id,
            Approval.approval_type == approval_type,
            Approval.status == ApprovalStatus.PENDING,
        )
        if content_version_id is None:
            query = query.where(Approval.content_version_id.is_(None))
        else:
            query = query.where(Approval.content_version_id == content_version_id)
        if self.session.scalar(query) is not None:
            raise ApprovalError("A pending approval already exists for this review cycle.")

    def _get_approval(self, approval_id: str) -> Approval:
        approval = self.session.get(Approval, approval_id)
        if approval is None:
            raise ApprovalError(f"Approval not found: {approval_id}")
        return approval

    def _get_job(self, job_id: str) -> Job:
        job = self.session.get(Job, job_id)
        if job is None:
            raise ApprovalError(f"Job not found: {job_id}")
        return job


APPROVAL_CONTENT_TYPE_MAP = {
    ApprovalType.RESEARCH: ContentType.RESEARCH_BRIEF,
    ApprovalType.SCRIPT: ContentType.SCRIPT,
    ApprovalType.SCENE_PLAN: ContentType.SCENE_PLAN,
    ApprovalType.METADATA: ContentType.METADATA,
    ApprovalType.THUMBNAIL: ContentType.THUMBNAIL_CONCEPT,
}
