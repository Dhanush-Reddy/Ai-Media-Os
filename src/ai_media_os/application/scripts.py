"""Script generation, fact checking, and quality checks."""

import json
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_media_os.application.approvals import ApprovalError, ApprovalService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.research import ResearchReportService
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ClaimImportance,
    ContentFormat,
    ContentType,
    SourceStatus,
    VerificationStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.models import Approval, Claim, ContentVersion, VideoProject
from ai_media_os.providers.text_generation import (
    LocalRuleBasedTextProvider,
    TextGenerationError,
    TextGenerationProvider,
    TextGenerationRequest,
)
from ai_media_os.utils.hashing import hash_json


class ScriptPlanningError(RuntimeError):
    """Raised when script generation or checks cannot proceed."""


@dataclass(frozen=True)
class ScriptQualityResult:
    passed: bool
    score: float
    blocking_reasons: list[str]
    warnings: list[str]

    def as_dict(self) -> dict[str, object]:
        return {
            "passed": self.passed,
            "score": self.score,
            "blocking_reasons": self.blocking_reasons,
            "warnings": self.warnings,
        }


class ScriptGenerationService:
    """Create approval-gated script versions from approved research inputs."""

    def __init__(
        self,
        session: Session,
        provider: TextGenerationProvider | None = None,
        *,
        provider_settings: dict[str, Any] | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.session = session
        self.provider = provider or LocalRuleBasedTextProvider()
        self.provider_settings = provider_settings or {}
        self.timeout_seconds = timeout_seconds
        self.versions = ContentVersionService(session)
        self.approvals = ApprovalService(session)

    def generate_script(
        self,
        video_project_id: str,
        *,
        revision_feedback: str | None = None,
        job_id: str | None = None,
    ) -> ContentVersion:
        project = self._project(video_project_id)
        readiness = ResearchReportService(self.session).evaluate_readiness(video_project_id)
        if not readiness.ready_for_script:
            raise ScriptPlanningError(
                "Research is not ready for script generation: "
                + "; ".join(readiness.blocking_reasons)
            )
        research_brief = self._latest_research_brief(video_project_id)
        if research_brief is None:
            research_brief = ResearchReportService(self.session).generate_research_brief(
                video_project_id
            )
        claims = self._claims(video_project_id)
        prompt = self._build_script(project, research_brief, claims, revision_feedback)
        request = TextGenerationRequest(
            prompt=prompt,
            provider_settings=self.provider_settings,
            timeout_seconds=self.timeout_seconds,
        )
        input_hashes = [
            research_brief.content_hash,
            hash_json([self._claim_payload(claim) for claim in claims]),
            hash_json({"revision_feedback": revision_feedback or ""}),
            hash_json({"target_duration_seconds": project.target_duration_seconds}),
            hash_json(
                {
                    "provider": self.provider.provider_name,
                    "model": self.provider.model_name,
                    "model_version": self.provider.model_version,
                    "prompt_version": self.provider.prompt_version,
                    "provider_settings": {
                        **self.provider.provider_settings,
                        **self.provider_settings,
                    },
                    "request": request.fingerprint_payload(),
                }
            ),
        ]
        existing = self._matching_version(video_project_id, ContentType.SCRIPT, input_hashes)
        if existing is not None:
            self._ensure_pending_approval(existing, ApprovalType.SCRIPT, job_id)
            return existing

        try:
            result = self.provider.generate(request)
        except TextGenerationError:
            raise
        except Exception as exc:
            raise TextGenerationError(
                f"Text provider {self.provider.provider_name} failed."
            ) from exc
        version = self.versions.create_initial_version(
            video_project_id=video_project_id,
            content_type=ContentType.SCRIPT,
            content=result.text,
            content_format=ContentFormat.MARKDOWN,
            prompt_version=result.prompt_version,
            provider=result.provider,
            model=result.model,
            input_hashes=input_hashes,
        )
        version.status = VersionStatus.PENDING_APPROVAL
        self.session.commit()
        self._ensure_pending_approval(version, ApprovalType.SCRIPT, job_id)
        return version

    def generate_fact_check_report(
        self,
        video_project_id: str,
        *,
        script_version_id: str | None = None,
    ) -> ContentVersion:
        script = self._script_version(video_project_id, script_version_id)
        claims = self._claims(video_project_id)
        mentioned = [
            claim for claim in claims if self._claim_is_referenced(script.content, claim.claim_text)
        ]
        report = {
            "script_content_version_id": script.id,
            "verified_claims_mentioned": [
                claim.id
                for claim in mentioned
                if claim.verification_status == VerificationStatus.VERIFIED
            ],
            "unverified_claims_mentioned": [
                claim.id
                for claim in mentioned
                if claim.verification_status != VerificationStatus.VERIFIED
            ],
            "missing_research_anchors": [
                claim.id
                for claim in claims
                if claim.importance in {ClaimImportance.HIGH, ClaimImportance.CRITICAL}
                and not self._claim_is_referenced(script.content, claim.claim_text)
            ],
            "passed": all(
                claim.verification_status == VerificationStatus.VERIFIED for claim in mentioned
            ),
        }
        content = json.dumps(report, sort_keys=True, indent=2)
        input_hashes = [script.content_hash, hash_json([self._claim_payload(c) for c in claims])]
        existing = self._matching_version(
            video_project_id, ContentType.FACT_CHECK_REPORT, input_hashes
        )
        if existing is not None:
            return existing
        return self.versions.create_initial_version(
            video_project_id=video_project_id,
            content_type=ContentType.FACT_CHECK_REPORT,
            content=content,
            content_format=ContentFormat.JSON,
            provider="local_rules",
            model="fact-check-v1",
            input_hashes=input_hashes,
        )

    def evaluate_script_quality(
        self,
        video_project_id: str,
        *,
        script_version_id: str | None = None,
    ) -> ScriptQualityResult:
        script = self._script_version(video_project_id, script_version_id)
        warnings: list[str] = []
        blockers: list[str] = []
        if "## Hook" not in script.content:
            blockers.append("Script is missing a hook section.")
        if "## Main Story" not in script.content:
            blockers.append("Script is missing a main story section.")
        if "## Outro" not in script.content:
            warnings.append("Script is missing a clear outro.")
        if len(script.content.split()) < 120:
            warnings.append("Script is short for a long-form video.")
        fact_report = json.loads(
            self.generate_fact_check_report(
                video_project_id,
                script_version_id=script.id,
            ).content
        )
        if fact_report["unverified_claims_mentioned"]:
            blockers.append("Script mentions unverified claims.")
        score = max(0.0, 1.0 - (len(blockers) * 0.3) - (len(warnings) * 0.08))
        return ScriptQualityResult(
            passed=not blockers,
            score=round(score, 2),
            blocking_reasons=blockers,
            warnings=warnings,
        )

    def _build_script(
        self,
        project: VideoProject,
        research_brief: ContentVersion,
        claims: list[Claim],
        revision_feedback: str | None,
    ) -> str:
        verified_claims = [
            claim.claim_text
            for claim in claims
            if claim.verification_status == VerificationStatus.VERIFIED
        ]
        target_minutes = max(1, int((project.target_duration_seconds or 480) / 60))
        lines = [
            f"# {project.working_title}",
            "",
            f"Target duration: {target_minutes} minutes",
            f"Topic: {project.topic}",
            "",
            "## Hook",
            (
                f"What if the next AI shift is already visible in {project.topic}? "
                "In this episode, we separate durable signals from noisy headlines."
            ),
            "",
            "## Main Story",
            "Here are the research-backed points that matter:",
        ]
        if verified_claims:
            lines.extend(f"- {claim}" for claim in verified_claims)
        else:
            lines.append("- No verified claims were supplied; keep the episode exploratory.")
        lines.extend(
            [
                "",
                "## Context and Stakes",
                (
                    "For AI & Future viewers, the important question is not only what changed, "
                    "but what becomes practical, risky, or strategically useful next."
                ),
                "",
                "## Review Boundaries",
                "Do not present unverified or contradicted research items as facts.",
                "",
                "## Outro",
                (
                    "The useful takeaway: track the evidence, watch the incentives, and keep "
                    "testing whether the trend changes what builders and teams can actually do."
                ),
                "",
                "## Research Brief Snapshot",
                research_brief.content[:1200],
            ]
        )
        if revision_feedback:
            lines.extend(["", "## Revision Notes", revision_feedback])
        return "\n".join(lines) + "\n"

    def _ensure_pending_approval(
        self,
        version: ContentVersion,
        approval_type: ApprovalType,
        job_id: str | None,
    ) -> None:
        pending = self.session.scalar(
            select(Approval).where(
                Approval.content_version_id == version.id,
                Approval.approval_type == approval_type,
                Approval.status == ApprovalStatus.PENDING,
            )
        )
        if pending is not None:
            return
        version.status = VersionStatus.PENDING_APPROVAL
        self.session.commit()
        try:
            self.approvals.request_approval(
                video_project_id=version.video_project_id,
                approval_type=approval_type,
                content_version_id=version.id,
                job_id=job_id,
            )
        except ApprovalError as exc:
            if "pending approval already exists" not in str(exc):
                raise

    def _matching_version(
        self,
        video_project_id: str,
        content_type: ContentType,
        input_hashes: list[str],
    ) -> ContentVersion | None:
        filters = [
            ContentVersion.video_project_id == video_project_id,
            ContentVersion.content_type == content_type,
            ContentVersion.input_hashes == input_hashes,
        ]
        if content_type == ContentType.SCRIPT:
            filters.append(ContentVersion.provider == self.provider.provider_name)
        return self.session.scalar(
            select(ContentVersion)
            .where(*filters)
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )

    def _latest_research_brief(self, video_project_id: str) -> ContentVersion | None:
        return self.versions.latest_version(video_project_id, ContentType.RESEARCH_BRIEF)

    def _script_version(
        self,
        video_project_id: str,
        script_version_id: str | None,
    ) -> ContentVersion:
        version = (
            self.session.get(ContentVersion, script_version_id)
            if script_version_id
            else self.versions.latest_version(video_project_id, ContentType.SCRIPT)
        )
        if version is None or version.video_project_id != video_project_id:
            raise ScriptPlanningError("Script version not found for project.")
        if version.content_type != ContentType.SCRIPT:
            raise ScriptPlanningError("Content version is not a script.")
        return version

    def _project(self, video_project_id: str) -> VideoProject:
        project = self.session.get(VideoProject, video_project_id)
        if project is None:
            raise ScriptPlanningError(f"Project not found: {video_project_id}")
        return project

    def _claims(self, video_project_id: str) -> list[Claim]:
        return list(
            self.session.scalars(
                select(Claim)
                .where(Claim.video_project_id == video_project_id)
                .options(selectinload(Claim.source_links))
                .order_by(Claim.created_at.asc(), Claim.id.asc())
            )
        )

    def _claim_payload(self, claim: Claim) -> dict[str, object]:
        return {
            "id": claim.id,
            "text": claim.claim_text,
            "importance": claim.importance,
            "status": claim.verification_status,
            "source_ids": sorted(link.source_id for link in claim.source_links),
        }

    def _claim_is_referenced(self, script: str, claim_text: str) -> bool:
        tokens = [
            token for token in re.findall(r"[A-Za-z0-9]+", claim_text.lower()) if len(token) > 4
        ]
        if not tokens:
            return False
        script_lower = script.lower()
        return sum(token in script_lower for token in tokens) >= max(1, min(3, len(tokens)))


def approved_source_count(session: Session, video_project_id: str) -> int:
    project = session.get(VideoProject, video_project_id)
    if project is None:
        return 0
    return sum(source.status == SourceStatus.APPROVED for source in project.sources)
