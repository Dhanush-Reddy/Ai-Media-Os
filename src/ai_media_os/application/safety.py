"""Local content safety and rights checks for AI Media OS."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session, selectinload

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import (
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetType,
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    LicenseStatus,
    PublishingGateStatus,
    RenderStatus,
    RightsStatus,
    SafetyCheckStatus,
    SafetyCheckType,
    SafetySeverity,
    SafetyTargetType,
    VerificationStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.models import (
    Asset,
    Claim,
    ContentSafetyCheck,
    ContentVersion,
    PublishingGate,
    Render,
    RightsRecord,
    VideoProject,
)
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.schemas.safety import (
    PublishingGateDocument,
    RightsRecordDocument,
    SafetyFindingDocument,
    SafetyReportDocument,
)
from ai_media_os.schemas.thumbnail import ThumbnailConceptDocument
from ai_media_os.schemas.video_metadata import VideoMetadataDocument
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.utils.hashing import hash_file, hash_json

JsonDict = dict[str, Any]

WRITE_TRANSACTION_DEPTH_KEY = "ai_media_os_write_transaction_depth"


class SafetyError(RuntimeError):
    """Raised when content-safety checks cannot be completed."""


@dataclass(frozen=True)
class DisclosureDecision:
    required: bool
    reasons: list[str] = field(default_factory=list)
    suggested_text: str | None = None


@dataclass(frozen=True)
class SafetyRunResult:
    gate: PublishingGate
    report: SafetyReportDocument
    report_version: ContentVersion
    findings: list[ContentSafetyCheck]
    rights_records: list[RightsRecord]
    disclosure: DisclosureDecision


class ContentSafetyService:
    def __init__(self, session: Session, settings: AppSettings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.content_versions = ContentVersionService(session)
        self.storage = FileStorage(self.settings)

    @contextmanager
    def _write_transaction(self) -> Generator[None, None, None]:
        depth = int(self.session.info.get(WRITE_TRANSACTION_DEPTH_KEY, 0))
        started = depth == 0
        self.session.info[WRITE_TRANSACTION_DEPTH_KEY] = depth + 1
        if started:
            self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            yield
            if started:
                self.session.commit()
        except Exception:
            if started:
                self.session.rollback()
            raise
        finally:
            if depth == 0:
                self.session.info.pop(WRITE_TRANSACTION_DEPTH_KEY, None)
            else:
                self.session.info[WRITE_TRANSACTION_DEPTH_KEY] = depth

    def check_asset_rights(self, video_project_id: str) -> list[RightsRecord]:
        project = self._project(video_project_id)
        with self._write_transaction():
            records: list[RightsRecord] = []
            for asset in sorted(project.assets, key=lambda item: (item.created_at, item.id)):
                record = self._evaluate_asset_rights(asset)
                existing = self._rights_by_fingerprint(record.assessment_fingerprint)
                if existing is not None:
                    records.append(existing)
                    continue
                self.session.add(record)
                self.session.flush()
                records.append(record)
                self._ensure_check_for_rights(record)
            return records

    def check_claim_support(self, video_project_id: str) -> list[ContentSafetyCheck]:
        project = self._project(video_project_id)
        with self._write_transaction():
            findings: list[ContentSafetyCheck] = []
            for claim in sorted(project.claims, key=lambda item: (item.created_at, item.id)):
                finding = self._evaluate_claim_support(project, claim)
                existing = self._check_by_fingerprint(finding.assessment_fingerprint)
                if existing is not None:
                    findings.append(existing)
                    continue
                self.session.add(finding)
                self.session.flush()
                findings.append(finding)
            return findings

    def check_script_safety(self, video_project_id: str) -> list[ContentSafetyCheck]:
        project = self._project(video_project_id)
        script = self._latest_version(project.id, ContentType.SCRIPT)
        if script is None:
            raise SafetyError("Script version not found for project.")
        with self._write_transaction():
            finding = self._evaluate_script_safety(project, script)
            existing = self._check_by_fingerprint(finding.assessment_fingerprint)
            if existing is not None:
                return [existing]
            self.session.add(finding)
            self.session.flush()
            return [finding]

    def check_metadata_safety(self, video_project_id: str) -> list[ContentSafetyCheck]:
        project = self._project(video_project_id)
        metadata = self._latest_version(project.id, ContentType.METADATA)
        if metadata is None:
            raise SafetyError("Metadata version not found for project.")
        with self._write_transaction():
            finding = self._evaluate_metadata_safety(project, metadata)
            existing = self._check_by_fingerprint(finding.assessment_fingerprint)
            if existing is not None:
                return [existing]
            self.session.add(finding)
            self.session.flush()
            return [finding]

    def check_thumbnail_safety(self, video_project_id: str) -> list[ContentSafetyCheck]:
        project = self._project(video_project_id)
        thumbnail = self._latest_thumbnail(project.id)
        if thumbnail is None:
            raise SafetyError("Thumbnail asset not found for project.")
        with self._write_transaction():
            finding = self._evaluate_thumbnail_safety(project, thumbnail)
            existing = self._check_by_fingerprint(finding.assessment_fingerprint)
            if existing is not None:
                return [existing]
            self.session.add(finding)
            self.session.flush()
            return [finding]

    def check_reused_content(self, video_project_id: str) -> list[ContentSafetyCheck]:
        project = self._project(video_project_id)
        with self._write_transaction():
            finding = self._evaluate_reused_content(project)
            existing = self._check_by_fingerprint(finding.assessment_fingerprint)
            if existing is not None:
                return [existing]
            self.session.add(finding)
            self.session.flush()
            return [finding]

    def decide_ai_disclosure(self, video_project_id: str) -> DisclosureDecision:
        project = self._project(video_project_id)
        reasons: list[str] = []
        if any(
            self._is_synthetic_provider(version.provider) for version in project.content_versions
        ):
            reasons.append("Generated script, metadata, or report versions are present.")
        if any(self._is_synthetic_provider(asset.provider) for asset in project.assets):
            reasons.append("Generated image, audio, or thumbnail assets are present.")
        if any(self._synthetic_metadata_flag(asset) for asset in project.assets):
            reasons.append("Asset metadata indicates synthetic generation.")
        decision = DisclosureDecision(
            required=bool(reasons),
            reasons=reasons,
            suggested_text=(
                "This video includes AI-assisted scripting and synthetic/generated "
                "visuals or audio."
                if reasons
                else None
            ),
        )
        with self._write_transaction():
            fingerprint = self._disclosure_fingerprint(project.id, decision)
            existing = self._check_by_fingerprint(fingerprint)
            if existing is None:
                finding = ContentSafetyCheck(
                    video_project_id=project.id,
                    target_type=SafetyTargetType.PROJECT,
                    target_id=project.id,
                    check_type=SafetyCheckType.AI_DISCLOSURE,
                    status=SafetyCheckStatus.WARNING
                    if decision.required
                    else SafetyCheckStatus.PASSED,
                    severity=SafetySeverity.MEDIUM if decision.required else SafetySeverity.INFO,
                    message="AI disclosure is required."
                    if decision.required
                    else "AI disclosure is not required.",
                    evidence=decision.reasons,
                    recommendation=decision.suggested_text,
                    assessment_fingerprint=fingerprint,
                    rule_version=self.settings.safety_rule_version,
                )
                self.session.add(finding)
                self.session.flush()
            return decision

    def run_publishing_gate(
        self,
        video_project_id: str,
        *,
        render_id: str | None = None,
        metadata_version_id: str | None = None,
        thumbnail_asset_id: str | None = None,
    ) -> SafetyRunResult:
        with self._write_transaction():
            project = self._project(video_project_id)
            render = self._render(project.id, render_id)
            metadata = self._metadata_version(project.id, metadata_version_id)
            thumbnail = self._thumbnail_asset(project.id, thumbnail_asset_id)
            rights_records = self.check_asset_rights(project.id)
            findings = [
                *self.check_claim_support(project.id),
                *self.check_script_safety(project.id),
                *self.check_metadata_safety(project.id),
                *self.check_thumbnail_safety(project.id),
                *self.check_reused_content(project.id),
            ]
            disclosure = self.decide_ai_disclosure(project.id)
            if disclosure.required:
                findings.append(self._disclosure_check(project.id, disclosure))
            rights_summary = Counter(record.rights_status.value for record in rights_records)
            check_summary = Counter(finding.status.value for finding in findings)
            blocking_reasons: list[str] = []
            warnings: list[str] = []
            for finding in findings:
                if finding.status == SafetyCheckStatus.FAILED:
                    blocking_reasons.append(finding.message)
                elif finding.status == SafetyCheckStatus.WARNING:
                    warnings.append(finding.message)
            for record in rights_records:
                if record.rights_status == RightsStatus.BLOCKED:
                    blocking_reasons.append(f"Blocked rights record for asset {record.asset_id}.")
                elif record.rights_status in {RightsStatus.UNKNOWN, RightsStatus.EDITORIAL_REVIEW}:
                    warnings.append(f"Review required for asset {record.asset_id}.")
            if render is None:
                blocking_reasons.append("Missing render.")
            elif not self._render_is_verified(render):
                blocking_reasons.append("Render verification failed.")
            if metadata is None:
                blocking_reasons.append("Missing metadata.")
            elif metadata.status != VersionStatus.APPROVED:
                warnings.append("Metadata is not approved yet.")
            if thumbnail is None:
                blocking_reasons.append("Missing thumbnail.")
            elif thumbnail.review_status != AssetReviewStatus.APPROVED:
                warnings.append("Thumbnail is not approved yet.")
            status = self._gate_status(blocking_reasons, warnings, rights_records, disclosure)
            report = self._build_report(
                project=project,
                render=render,
                metadata=metadata,
                thumbnail=thumbnail,
                status=status,
                blocking_reasons=blocking_reasons,
                warnings=warnings,
                rights_records=rights_records,
                findings=findings,
                disclosure=disclosure,
                rights_summary=dict(rights_summary),
                check_summary=dict(check_summary),
            )
            fingerprint = self._gate_fingerprint(project.id, render, metadata, thumbnail, report)
            existing = self._gate_by_fingerprint(fingerprint)
            if existing is not None:
                report_version = self._report_by_hash(fingerprint)
                if report_version is None:
                    raise SafetyError("Publishing gate report was not found after replay.")
                return SafetyRunResult(
                    existing, report, report_version, findings, rights_records, disclosure
                )
            report_version = self.content_versions.create_initial_version(
                video_project_id=project.id,
                content_type=ContentType.COPYRIGHT_REPORT,
                content=report.model_dump_json(indent=2),
                content_format=ContentFormat.JSON,
                provider="local_rules",
                model="safety-gate-v1",
                prompt_version=self.settings.safety_rule_version,
                input_hashes=[fingerprint],
            )
            gate = PublishingGate(
                video_project_id=project.id,
                render_id=render.id if render is not None else None,
                metadata_version_id=metadata.id if metadata is not None else None,
                thumbnail_asset_id=thumbnail.id if thumbnail is not None else None,
                status=status,
                summary=report.gate.summary,
                blocking_reasons=blocking_reasons,
                warnings=warnings,
                ai_disclosure_required=disclosure.required,
                ai_disclosure_reasons=disclosure.reasons,
                ai_disclosure_text=disclosure.suggested_text,
                human_review_required=status
                in {PublishingGateStatus.NEEDS_REVIEW, PublishingGateStatus.BLOCKED},
                report_content_version_id=report_version.id,
                assessment_fingerprint=fingerprint,
                rule_version=self.settings.safety_rule_version,
            )
            self.session.add(gate)
            self.session.flush()
            self.session.refresh(gate)
            return SafetyRunResult(
                gate, report, report_version, findings, rights_records, disclosure
            )

    def latest_report(self, video_project_id: str) -> ContentVersion | None:
        return self.content_versions.latest_version(video_project_id, ContentType.COPYRIGHT_REPORT)

    def list_findings(self, video_project_id: str) -> list[ContentSafetyCheck]:
        return list(
            self.session.scalars(
                select(ContentSafetyCheck)
                .where(ContentSafetyCheck.video_project_id == video_project_id)
                .order_by(ContentSafetyCheck.created_at.desc(), ContentSafetyCheck.id.desc())
            ).all()
        )

    def latest_gate(self, video_project_id: str) -> PublishingGate | None:
        return self.session.scalar(
            select(PublishingGate)
            .where(PublishingGate.video_project_id == video_project_id)
            .order_by(PublishingGate.created_at.desc(), PublishingGate.id.desc())
            .limit(1)
        )

    def _evaluate_asset_rights(self, asset: Asset) -> RightsRecord:
        source_type = str(
            asset.generation_metadata.get("source_type") or self._asset_source_type(asset)
        )
        review_notes: list[str] = []
        rights_status = self._rights_status_from_asset(asset)
        if not asset.content_hash:
            review_notes.append("Content hash is missing.")
            rights_status = RightsStatus.UNKNOWN
        if not self._file_is_valid(asset):
            review_notes.append("Asset file is missing or unsafe.")
            rights_status = RightsStatus.BLOCKED
        if (
            asset.review_status == AssetReviewStatus.REJECTED
            or asset.generation_status == AssetGenerationStatus.REJECTED
        ):
            review_notes.append("Asset has been rejected.")
            rights_status = RightsStatus.BLOCKED
        if asset.license_status == LicenseStatus.ATTRIBUTION_REQUIRED:
            rights_status = RightsStatus.ATTRIBUTION_REQUIRED
        elif (
            asset.license_status == LicenseStatus.EDITORIAL_ONLY
            and rights_status != RightsStatus.BLOCKED
        ):
            rights_status = RightsStatus.EDITORIAL_REVIEW
        elif (
            asset.license_status == LicenseStatus.UNKNOWN
            and asset.source_url
            and not asset.license_name
        ):
            review_notes.append("External source URL has no license information.")
            rights_status = RightsStatus.UNKNOWN
        elif self._is_synthetic_provider(asset.provider) and rights_status != RightsStatus.BLOCKED:
            rights_status = RightsStatus.SAFE
            review_notes.append("Synthetic asset requires AI disclosure.")
        fingerprint = self._rights_fingerprint(asset, source_type, rights_status, review_notes)
        return RightsRecord(
            video_project_id=asset.video_project_id,
            asset_id=asset.id,
            source_type=source_type,
            source_url=asset.source_url,
            license_name=asset.license_name,
            license_url=asset.generation_metadata.get("license_url")
            if isinstance(asset.generation_metadata, dict)
            else None,
            rights_status=rights_status,
            attribution_text=self._attribution_text(asset),
            review_notes="; ".join(review_notes) if review_notes else None,
            provider=asset.provider,
            model=asset.model,
            content_hash=asset.content_hash,
            assessment_fingerprint=fingerprint,
            rule_version=self.settings.safety_rule_version,
        )

    def _evaluate_claim_support(self, project: VideoProject, claim: Claim) -> ContentSafetyCheck:
        evidence = [f"claim:{claim.id}"]
        evidence.extend(
            f"source:{link.source_id}:{link.support_type.value}" for link in claim.source_links
        )
        supports = any(
            link.support_type.value in {"supports", "partially_supports", "primary_evidence"}
            for link in claim.source_links
        )
        contradicts = claim.verification_status.value == "contradicted" or any(
            link.support_type.value == "contradicts" for link in claim.source_links
        )
        if contradicts:
            status, severity, message, recommendation = (
                SafetyCheckStatus.FAILED,
                SafetySeverity.CRITICAL,
                f"Claim is contradicted: {claim.claim_text}",
                "Remove or qualify the claim.",
            )
        elif claim.importance.value in {"high", "critical"} and not supports:
            status, severity, message, recommendation = (
                SafetyCheckStatus.FAILED,
                SafetySeverity.HIGH,
                f"High-priority claim lacks supporting evidence: {claim.claim_text}",
                "Add at least one supporting source or remove the claim.",
            )
        elif not supports:
            status, severity, message, recommendation = (
                SafetyCheckStatus.WARNING,
                SafetySeverity.LOW,
                f"Claim is not sourced yet: {claim.claim_text}",
                "Add a supporting source if this claim matters to the final package.",
            )
        elif claim.verification_status.value != "verified":
            status, severity, message, recommendation = (
                SafetyCheckStatus.WARNING,
                SafetySeverity.MEDIUM,
                f"Claim needs review: {claim.claim_text}",
                "Verify the claim or qualify it in the script.",
            )
        else:
            status, severity, message, recommendation = (
                SafetyCheckStatus.PASSED,
                SafetySeverity.INFO,
                f"Claim is supported: {claim.claim_text}",
                None,
            )
        fingerprint = self._check_fingerprint(
            project.id,
            SafetyCheckType.CLAIM_SUPPORT,
            claim.id,
            claim.claim_text,
            evidence,
            claim.verification_status.value,
        )
        return self._new_check(
            project.id,
            SafetyTargetType.CONTENT_VERSION,
            claim.id,
            SafetyCheckType.CLAIM_SUPPORT,
            status,
            severity,
            message,
            evidence,
            recommendation,
            fingerprint,
        )

    def _evaluate_script_safety(
        self, project: VideoProject, script: ContentVersion
    ) -> ContentSafetyCheck:
        evidence = [f"script:{script.id}", f"hash:{script.content_hash or ''}"]
        issues: list[str] = []
        if script.status != VersionStatus.APPROVED:
            issues.append("Script version is not approved.")
        if _contains_local_path(script.content):
            issues.append("Script contains a local filesystem path.")
        if self._has_repeated_paragraphs(script.content):
            issues.append("Script contains excessive repeated text.")
        unsupported_claims = self._unsupported_claims_in_text(project, script.content)
        if unsupported_claims:
            issues.append("Script mentions unsupported claims: " + ", ".join(unsupported_claims))
        status = (
            SafetyCheckStatus.FAILED
            if any(
                "unsupported" in issue.lower() or "local filesystem" in issue.lower()
                for issue in issues
            )
            else (SafetyCheckStatus.WARNING if issues else SafetyCheckStatus.PASSED)
        )
        severity = (
            SafetySeverity.HIGH
            if status == SafetyCheckStatus.FAILED
            else (
                SafetySeverity.MEDIUM
                if status == SafetyCheckStatus.WARNING
                else SafetySeverity.INFO
            )
        )
        recommendation = (
            "Revise the script to remove unsupported claims and unsafe text." if issues else None
        )
        fingerprint = self._check_fingerprint(
            project.id,
            SafetyCheckType.SCRIPT_SAFETY,
            script.id,
            script.content_hash or script.id,
            evidence,
            script.status.value,
        )
        return self._new_check(
            project.id,
            SafetyTargetType.CONTENT_VERSION,
            script.id,
            SafetyCheckType.SCRIPT_SAFETY,
            status,
            severity,
            "; ".join(issues) if issues else "Script safety check passed.",
            evidence,
            recommendation,
            fingerprint,
        )

    def _evaluate_metadata_safety(
        self, project: VideoProject, metadata: ContentVersion
    ) -> ContentSafetyCheck:
        document = VideoMetadataDocument.model_validate_json(metadata.content)
        evidence = [f"metadata:{metadata.id}"]
        issues: list[str] = []
        if metadata.status != VersionStatus.APPROVED:
            issues.append("Metadata version is not approved.")
        if _contains_local_path(document.title) or _contains_local_path(document.description):
            issues.append("Metadata contains a local filesystem path.")
        risky_words = _risky_marketing_words(f"{document.title} {document.description}")
        if risky_words and not self._metadata_claims_supported(project, document):
            issues.append(
                "Metadata uses unsupported marketing language: " + ", ".join(sorted(risky_words))
            )
        unsupported_claims = self._unsupported_claims_in_text(
            project,
            f"{document.title}\n{document.description}\n"
            + "\n".join(chapter.title for chapter in document.chapters),
        )
        if unsupported_claims:
            issues.append(
                "Metadata introduces unsupported claims: " + ", ".join(unsupported_claims)
            )
        status = (
            SafetyCheckStatus.FAILED
            if any(
                "unsupported" in issue.lower() or "local filesystem" in issue.lower()
                for issue in issues
            )
            else (SafetyCheckStatus.WARNING if issues else SafetyCheckStatus.PASSED)
        )
        severity = (
            SafetySeverity.HIGH
            if status == SafetyCheckStatus.FAILED
            else (
                SafetySeverity.MEDIUM
                if status == SafetyCheckStatus.WARNING
                else SafetySeverity.INFO
            )
        )
        recommendation = (
            "Revise the title and description to match supported research claims."
            if issues
            else None
        )
        fingerprint = self._check_fingerprint(
            project.id,
            SafetyCheckType.METADATA_SAFETY,
            metadata.id,
            metadata.content_hash or metadata.id,
            evidence,
            metadata.status.value,
        )
        return self._new_check(
            project.id,
            SafetyTargetType.CONTENT_VERSION,
            metadata.id,
            SafetyCheckType.METADATA_SAFETY,
            status,
            severity,
            "; ".join(issues) if issues else "Metadata safety check passed.",
            evidence,
            recommendation,
            fingerprint,
        )

    def _evaluate_thumbnail_safety(
        self, project: VideoProject, thumbnail: Asset
    ) -> ContentSafetyCheck:
        evidence = [f"thumbnail:{thumbnail.id}", f"hash:{thumbnail.content_hash or ''}"]
        issues: list[str] = []
        if (
            thumbnail.review_status == AssetReviewStatus.REJECTED
            or thumbnail.generation_status == AssetGenerationStatus.REJECTED
        ):
            issues.append("Thumbnail has been rejected.")
        if not self._file_is_valid(thumbnail):
            issues.append("Thumbnail file is missing or unsafe.")
        if not thumbnail.content_hash:
            issues.append("Thumbnail hash is missing.")
        concept = self._thumbnail_concept(thumbnail)
        if concept is not None:
            unsupported_claims = self._unsupported_claims_in_text(
                project,
                f"{concept.concept_title}\n{concept.selected_text}\n{concept.visual_description}",
            )
            if unsupported_claims:
                issues.append(
                    "Thumbnail text uses unsupported claims: " + ", ".join(unsupported_claims)
                )
            if self._is_synthetic_provider(thumbnail.provider):
                issues.append("Thumbnail requires AI disclosure.")
        if (
            thumbnail.license_status == LicenseStatus.UNKNOWN
            and thumbnail.generation_status == AssetGenerationStatus.IMPORTED
        ):
            issues.append("Manual thumbnail has unknown rights and needs review.")
        status = (
            SafetyCheckStatus.FAILED
            if any("missing" in issue.lower() or "rejected" in issue.lower() for issue in issues)
            else (SafetyCheckStatus.WARNING if issues else SafetyCheckStatus.PASSED)
        )
        severity = (
            SafetySeverity.HIGH
            if status == SafetyCheckStatus.FAILED
            else (
                SafetySeverity.MEDIUM
                if status == SafetyCheckStatus.WARNING
                and any("unsupported" in issue.lower() for issue in issues)
                else (SafetySeverity.LOW if issues else SafetySeverity.INFO)
            )
        )
        recommendation = (
            "Fix the thumbnail file and review the displayed text before publishing."
            if issues
            else None
        )
        fingerprint = self._check_fingerprint(
            project.id,
            SafetyCheckType.THUMBNAIL_SAFETY,
            thumbnail.id,
            thumbnail.content_hash or thumbnail.id,
            evidence,
            thumbnail.review_status.value,
        )
        return self._new_check(
            project.id,
            SafetyTargetType.ASSET,
            thumbnail.id,
            SafetyCheckType.THUMBNAIL_SAFETY,
            status,
            severity,
            "; ".join(issues) if issues else "Thumbnail safety check passed.",
            evidence,
            recommendation,
            fingerprint,
        )

    def _evaluate_reused_content(self, project: VideoProject) -> ContentSafetyCheck:
        evidence: list[str] = []
        issues: list[str] = []
        latest_script = self._latest_version(project.id, ContentType.SCRIPT)
        if latest_script is not None:
            for previous in self._versions(project.id, ContentType.SCRIPT):
                if previous.id == latest_script.id:
                    continue
                if (
                    _text_similarity(latest_script.content, previous.content)
                    >= self.settings.safety_similarity_threshold
                ):
                    issues.append(f"Script similarity with version {previous.version_number}.")
                    evidence.append(f"script:{previous.id}")
                    break
        latest_metadata = self._latest_version(project.id, ContentType.METADATA)
        if latest_metadata is not None:
            current = VideoMetadataDocument.model_validate_json(latest_metadata.content)
            for previous in self._versions(project.id, ContentType.METADATA):
                if previous.id == latest_metadata.id:
                    continue
                prior = VideoMetadataDocument.model_validate_json(previous.content)
                similarity = max(
                    _text_similarity(current.title, prior.title),
                    _text_similarity(current.description, prior.description),
                    _text_similarity(current.title, " ".join(prior.title_ideas)),
                )
                if similarity >= self.settings.safety_similarity_threshold:
                    issues.append(f"Metadata similarity with version {previous.version_number}.")
                    evidence.append(f"metadata:{previous.id}")
                    break
        latest_render = self._latest_render(project.id)
        if latest_render is not None:
            for previous_render in self._renders(project.id):
                if previous_render.id == latest_render.id:
                    continue
                if previous_render.settings.get("fingerprint") and previous_render.settings.get(
                    "fingerprint"
                ) == latest_render.settings.get("fingerprint"):
                    issues.append("Render fingerprint matches a previous render.")
                    evidence.append(f"render:{previous_render.id}")
                    break
        thumbnail = self._latest_thumbnail(project.id)
        if thumbnail is not None:
            concept = self._thumbnail_concept(thumbnail)
            if concept is not None and latest_metadata is not None:
                for previous in self._versions(project.id, ContentType.METADATA):
                    if previous.id == latest_metadata.id:
                        continue
                    prior = VideoMetadataDocument.model_validate_json(previous.content)
                    similarity = max(
                        _text_similarity(concept.selected_text, prior.title),
                        _text_similarity(concept.concept_title, prior.title),
                    )
                    if similarity >= self.settings.safety_similarity_threshold:
                        issues.append(
                            "Thumbnail text similarity with metadata version "
                            f"{previous.version_number}."
                        )
                        evidence.append(f"thumbnail:{thumbnail.id}")
                        break
        status = SafetyCheckStatus.WARNING if issues else SafetyCheckStatus.PASSED
        severity = SafetySeverity.MEDIUM if issues else SafetySeverity.INFO
        recommendation = "Review reused-content risk before publishing." if issues else None
        fingerprint = self._check_fingerprint(
            project.id,
            SafetyCheckType.REUSED_CONTENT,
            project.id,
            project.updated_at.isoformat(),
            evidence,
            "reused-content-v1",
        )
        return self._new_check(
            project.id,
            SafetyTargetType.PROJECT,
            project.id,
            SafetyCheckType.REUSED_CONTENT,
            status,
            severity,
            "; ".join(issues) if issues else "No strong reused-content risk detected.",
            evidence,
            recommendation,
            fingerprint,
        )

    def _build_report(
        self,
        *,
        project: VideoProject,
        render: Render | None,
        metadata: ContentVersion | None,
        thumbnail: Asset | None,
        status: PublishingGateStatus,
        blocking_reasons: list[str],
        warnings: list[str],
        rights_records: list[RightsRecord],
        findings: list[ContentSafetyCheck],
        disclosure: DisclosureDecision,
        rights_summary: dict[str, int],
        check_summary: dict[str, int],
    ) -> SafetyReportDocument:
        finding_docs = [self._finding_document(finding) for finding in findings]
        return SafetyReportDocument(
            project_id=project.id,
            render_id=render.id if render is not None else None,
            metadata_version_id=metadata.id if metadata is not None else None,
            thumbnail_asset_id=thumbnail.id if thumbnail is not None else None,
            gate=PublishingGateDocument(
                project_id=project.id,
                render_id=render.id if render is not None else None,
                metadata_version_id=metadata.id if metadata is not None else None,
                thumbnail_asset_id=thumbnail.id if thumbnail is not None else None,
                status=status,
                summary=self._gate_summary(status),
                blocking_reasons=blocking_reasons,
                warnings=warnings,
                ai_disclosure_required=disclosure.required,
                ai_disclosure_reasons=disclosure.reasons,
                ai_disclosure_text=disclosure.suggested_text,
                human_review_required=status
                in {PublishingGateStatus.NEEDS_REVIEW, PublishingGateStatus.BLOCKED},
                findings=finding_docs,
                rights_status_summary=rights_summary,
                check_status_summary=check_summary,
                next_action=self._next_action(status),
                rule_version=self.settings.safety_rule_version,
            ),
            findings=finding_docs,
            rights_records=[self._rights_document(record) for record in rights_records],
            ai_disclosure_required=disclosure.required,
            ai_disclosure_reasons=disclosure.reasons,
            ai_disclosure_text=disclosure.suggested_text,
            blocking_reasons=blocking_reasons,
            warnings=warnings,
            rule_version=self.settings.safety_rule_version,
        )

    def _new_check(
        self,
        project_id: str,
        target_type: SafetyTargetType,
        target_id: str,
        check_type: SafetyCheckType,
        status: SafetyCheckStatus,
        severity: SafetySeverity,
        message: str,
        evidence: list[str],
        recommendation: str | None,
        fingerprint: str,
    ) -> ContentSafetyCheck:
        return ContentSafetyCheck(
            video_project_id=project_id,
            target_type=target_type,
            target_id=target_id,
            check_type=check_type,
            status=status,
            severity=severity,
            message=message,
            evidence=evidence,
            recommendation=recommendation,
            assessment_fingerprint=fingerprint,
            rule_version=self.settings.safety_rule_version,
        )

    def _rights_document(self, record: RightsRecord) -> RightsRecordDocument:
        return RightsRecordDocument(
            asset_id=record.asset_id,
            source_type=record.source_type,
            source_url=record.source_url,
            license_name=record.license_name,
            license_url=record.license_url,
            rights_status=record.rights_status,
            attribution_text=record.attribution_text,
            review_notes=record.review_notes,
        )

    def _finding_document(self, finding: ContentSafetyCheck) -> SafetyFindingDocument:
        return SafetyFindingDocument(
            check_type=finding.check_type.value,
            target_type=finding.target_type,
            target_id=finding.target_id,
            status=finding.status,
            severity=finding.severity,
            message=finding.message,
            evidence=list(finding.evidence),
            recommendation=finding.recommendation,
        )

    def _gate_status(
        self,
        blocking_reasons: list[str],
        warnings: list[str],
        rights_records: list[RightsRecord],
        disclosure: DisclosureDecision,
    ) -> PublishingGateStatus:
        if blocking_reasons or any(
            record.rights_status == RightsStatus.BLOCKED for record in rights_records
        ):
            return PublishingGateStatus.BLOCKED
        if any(
            record.rights_status in {RightsStatus.UNKNOWN, RightsStatus.EDITORIAL_REVIEW}
            for record in rights_records
        ):
            return PublishingGateStatus.NEEDS_REVIEW
        if disclosure.required:
            return PublishingGateStatus.NEEDS_REVIEW
        if warnings:
            return PublishingGateStatus.PASS_WITH_WARNINGS
        return PublishingGateStatus.PASS

    def _gate_summary(self, status: PublishingGateStatus) -> str:
        return {
            PublishingGateStatus.PASS: "Publishing gate passed.",
            PublishingGateStatus.PASS_WITH_WARNINGS: "Publishing gate passed with warnings.",
            PublishingGateStatus.NEEDS_REVIEW: "Publishing gate needs human review.",
            PublishingGateStatus.BLOCKED: "Publishing gate is blocked.",
        }[status]

    def _next_action(self, status: PublishingGateStatus) -> str:
        return {
            PublishingGateStatus.PASS: "Ready for publishing approval.",
            PublishingGateStatus.PASS_WITH_WARNINGS: "Review warnings before publishing.",
            PublishingGateStatus.NEEDS_REVIEW: "Review the safety findings.",
            PublishingGateStatus.BLOCKED: "Resolve blocking issues before publishing.",
        }[status]

    def _rights_fingerprint(
        self, asset: Asset, source_type: str, rights_status: RightsStatus, review_notes: list[str]
    ) -> str:
        return hash_json(
            {
                "asset_id": asset.id,
                "project_id": asset.video_project_id,
                "content_hash": asset.content_hash,
                "provider": asset.provider,
                "model": asset.model,
                "source_type": source_type,
                "rights_status": rights_status,
                "review_notes": review_notes,
                "rule_version": self.settings.safety_rule_version,
            }
        )

    def _check_fingerprint(
        self,
        project_id: str,
        check_type: SafetyCheckType,
        target_id: str,
        basis: str,
        evidence: list[str],
        rule_basis: str,
    ) -> str:
        return hash_json(
            {
                "project_id": project_id,
                "check_type": check_type.value,
                "target_id": target_id,
                "basis": basis,
                "evidence": evidence,
                "rule_basis": rule_basis,
                "rule_version": self.settings.safety_rule_version,
            }
        )

    def _disclosure_fingerprint(self, project_id: str, decision: DisclosureDecision) -> str:
        return hash_json(
            {
                "project_id": project_id,
                "required": decision.required,
                "reasons": decision.reasons,
                "suggested_text": decision.suggested_text,
                "rule_version": self.settings.safety_rule_version,
            }
        )

    def _rights_by_fingerprint(self, fingerprint: str) -> RightsRecord | None:
        return self.session.scalar(
            select(RightsRecord).where(RightsRecord.assessment_fingerprint == fingerprint)
        )

    def _check_by_fingerprint(self, fingerprint: str) -> ContentSafetyCheck | None:
        return self.session.scalar(
            select(ContentSafetyCheck).where(
                ContentSafetyCheck.assessment_fingerprint == fingerprint
            )
        )

    def _gate_by_fingerprint(self, fingerprint: str) -> PublishingGate | None:
        return self.session.scalar(
            select(PublishingGate).where(PublishingGate.assessment_fingerprint == fingerprint)
        )

    def _report_by_hash(self, fingerprint: str) -> ContentVersion | None:
        return self.session.scalar(
            select(ContentVersion)
            .where(
                ContentVersion.content_type == ContentType.COPYRIGHT_REPORT,
                ContentVersion.input_hashes == [fingerprint],
            )
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )

    def _project(self, project_id: str) -> VideoProject:
        project = self.session.scalar(
            select(VideoProject)
            .where(VideoProject.id == project_id)
            .options(
                selectinload(VideoProject.claims).selectinload(Claim.source_links),
                selectinload(VideoProject.content_versions),
                selectinload(VideoProject.assets),
                selectinload(VideoProject.renders),
            )
        )
        if project is None:
            raise SafetyError(f"Project not found: {project_id}")
        return project

    def _latest_version(self, project_id: str, content_type: ContentType) -> ContentVersion | None:
        return self.content_versions.latest_version(project_id, content_type)

    def _versions(self, project_id: str, content_type: ContentType) -> list[ContentVersion]:
        return self.content_versions.version_history(project_id, content_type)

    def _latest_thumbnail(self, project_id: str) -> Asset | None:
        return self.session.scalar(
            select(Asset)
            .where(Asset.video_project_id == project_id, Asset.asset_type == AssetType.THUMBNAIL)
            .order_by(Asset.created_at.desc(), Asset.id.desc())
            .limit(1)
        )

    def _gate_fingerprint(
        self,
        project_id: str,
        render: Render | None,
        metadata: ContentVersion | None,
        thumbnail: Asset | None,
        report: SafetyReportDocument,
    ) -> str:
        return hash_json(
            {
                "project_id": project_id,
                "render_id": render.id if render is not None else None,
                "render_hash": render.content_hash if render is not None else None,
                "metadata_version_id": metadata.id if metadata is not None else None,
                "metadata_hash": metadata.content_hash if metadata is not None else None,
                "thumbnail_asset_id": thumbnail.id if thumbnail is not None else None,
                "thumbnail_hash": thumbnail.content_hash if thumbnail is not None else None,
                "report_hash": report.gate.model_dump_json(),
                "blocking_reasons": report.blocking_reasons,
                "warnings": report.warnings,
                "disclosure_required": report.ai_disclosure_required,
                "disclosure_reasons": report.ai_disclosure_reasons,
                "rule_version": self.settings.safety_rule_version,
            }
        )

    def _render(self, project_id: str, render_id: str | None) -> Render | None:
        if render_id is not None:
            render = self.session.get(Render, render_id)
            if render is None or render.video_project_id != project_id:
                raise SafetyError(f"Render not found for project: {render_id}")
            return render
        return self._latest_render(project_id)

    def _renders(self, project_id: str) -> list[Render]:
        return list(
            self.session.scalars(
                select(Render)
                .where(Render.video_project_id == project_id)
                .order_by(Render.version_number.asc(), Render.created_at.asc())
            ).all()
        )

    def _latest_render(self, project_id: str) -> Render | None:
        return self.session.scalar(
            select(Render)
            .where(Render.video_project_id == project_id)
            .order_by(Render.version_number.desc(), Render.created_at.desc())
            .limit(1)
        )

    def _metadata_version(self, project_id: str, version_id: str | None) -> ContentVersion | None:
        if version_id is not None:
            version = self.session.get(ContentVersion, version_id)
            if version is None or version.video_project_id != project_id:
                raise SafetyError(f"Metadata version not found for project: {version_id}")
            if version.content_type != ContentType.METADATA:
                raise SafetyError("Content version is not metadata.")
            return version
        return self._latest_version(project_id, ContentType.METADATA)

    def _thumbnail_asset(self, project_id: str, asset_id: str | None) -> Asset | None:
        if asset_id is not None:
            asset = self.session.get(Asset, asset_id)
            if asset is None or asset.video_project_id != project_id:
                raise SafetyError(f"Thumbnail asset not found for project: {asset_id}")
            if asset.asset_type != AssetType.THUMBNAIL:
                raise SafetyError("Asset is not a thumbnail.")
            return asset
        return self._latest_thumbnail(project_id)

    def _render_is_verified(self, render: Render) -> bool:
        return render.status == RenderStatus.APPROVED

    def _file_is_valid(self, asset: Asset) -> bool:
        try:
            path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        except StorageError:
            return False
        if not path.exists() or path.stat().st_size <= 0:
            return False
        if (
            asset.asset_type == AssetType.THUMBNAIL
            and path.suffix.lower() not in self.settings.thumbnail_allowed_extensions
        ):
            return False
        if asset.content_hash and hash_file(path) != asset.content_hash:
            return False
        return True

    def _thumbnail_concept(self, thumbnail: Asset) -> ThumbnailConceptDocument | None:
        if thumbnail.prompt:
            try:
                return ThumbnailConceptDocument.model_validate_json(thumbnail.prompt)
            except ValueError:
                return None
        metadata = (
            thumbnail.generation_metadata if isinstance(thumbnail.generation_metadata, dict) else {}
        )
        concept_version_id = metadata.get("concept_version_id")
        if concept_version_id:
            version = self.session.get(ContentVersion, str(concept_version_id))
            if version is not None and version.content_type == ContentType.THUMBNAIL_CONCEPT:
                return ThumbnailConceptDocument.model_validate_json(version.content)
        if {
            "concept_title",
            "selected_text",
            "visual_description",
            "emotional_hook",
            "background_idea",
            "foreground_subject",
            "composition_notes",
            "style_notes",
        }.issubset(metadata):
            return ThumbnailConceptDocument.model_validate(
                {
                    "concept_title": metadata["concept_title"],
                    "text_options": metadata.get("text_options") or [metadata["selected_text"]],
                    "selected_text": metadata["selected_text"],
                    "visual_description": metadata["visual_description"],
                    "emotional_hook": metadata["emotional_hook"],
                    "background_idea": metadata["background_idea"],
                    "foreground_subject": metadata["foreground_subject"],
                    "composition_notes": metadata["composition_notes"],
                    "style_notes": metadata["style_notes"],
                    "source_metadata_version_id": str(metadata.get("metadata_version_id") or ""),
                    "warnings": list(metadata.get("warnings") or []),
                }
            )
        return None

    def _synthetic_metadata_flag(self, asset: Asset) -> bool:
        metadata = asset.generation_metadata if isinstance(asset.generation_metadata, dict) else {}
        if metadata.get("manual_import"):
            return False
        if metadata.get("synthetic") or metadata.get("generated"):
            return True
        return self._is_synthetic_provider(asset.provider)

    def _is_synthetic_provider(self, provider: str | None) -> bool:
        if not provider:
            return False
        lowered = provider.casefold()
        return any(token in lowered for token in ("fake", "rules", "synthetic", "local_rules"))

    def _rights_status_from_asset(self, asset: Asset) -> RightsStatus:
        if (
            asset.review_status == AssetReviewStatus.REJECTED
            or asset.generation_status == AssetGenerationStatus.REJECTED
        ):
            return RightsStatus.BLOCKED
        if asset.license_status == LicenseStatus.BLOCKED:
            return RightsStatus.BLOCKED
        if asset.license_status == LicenseStatus.ATTRIBUTION_REQUIRED:
            return RightsStatus.ATTRIBUTION_REQUIRED
        if asset.license_status == LicenseStatus.EDITORIAL_ONLY:
            return RightsStatus.EDITORIAL_REVIEW
        if self._is_synthetic_provider(asset.provider):
            return RightsStatus.SAFE
        if (
            asset.generation_status == AssetGenerationStatus.IMPORTED
            and asset.license_status == LicenseStatus.UNKNOWN
        ):
            return RightsStatus.UNKNOWN
        if asset.license_status == LicenseStatus.SAFE:
            return RightsStatus.SAFE
        return RightsStatus.UNKNOWN

    def _asset_source_type(self, asset: Asset) -> str:
        metadata = asset.generation_metadata if isinstance(asset.generation_metadata, dict) else {}
        source_type = metadata.get("source_type")
        if source_type:
            return str(source_type)
        if asset.generation_status == AssetGenerationStatus.IMPORTED:
            return "manual_import"
        if self._is_synthetic_provider(asset.provider):
            return "synthetic_provider"
        return asset.asset_role.value

    def _attribution_text(self, asset: Asset) -> str | None:
        if self._is_synthetic_provider(asset.provider):
            return "AI-generated asset created with a local rules-based provider."
        parts = [part for part in (asset.creator, asset.license_name, asset.source_url) if part]
        return " | ".join(parts) if parts else None

    def _unsupported_claims_in_text(self, project: VideoProject, text: str) -> list[str]:
        unsupported: list[str] = []
        for claim in project.claims:
            if not _claim_text_covered(claim.claim_text, text):
                continue
            supported = any(
                link.support_type
                in {
                    ClaimSupportType.SUPPORTS,
                    ClaimSupportType.PARTIALLY_SUPPORTS,
                    ClaimSupportType.PRIMARY_EVIDENCE,
                }
                for link in claim.source_links
            )
            contradicted = claim.verification_status == VerificationStatus.CONTRADICTED or any(
                link.support_type == ClaimSupportType.CONTRADICTS for link in claim.source_links
            )
            if contradicted or (
                claim.importance in {ClaimImportance.HIGH, ClaimImportance.CRITICAL}
                and not supported
            ):
                unsupported.append(claim.claim_text)
        return unsupported

    def _metadata_claims_supported(
        self, project: VideoProject, document: VideoMetadataDocument
    ) -> bool:
        text = "\n".join(
            [
                document.title,
                document.description,
                " ".join(document.title_ideas),
                " ".join(document.keywords),
                " ".join(chapter.title for chapter in document.chapters),
            ]
        )
        return not self._unsupported_claims_in_text(project, text)

    def _has_repeated_paragraphs(self, text: str) -> bool:
        paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
        if len(paragraphs) < 2:
            return False
        counts = Counter(paragraphs)
        return any(count > 1 for count in counts.values())

    def _ensure_check_for_rights(self, record: RightsRecord) -> None:
        status = {
            RightsStatus.SAFE: SafetyCheckStatus.PASSED,
            RightsStatus.ATTRIBUTION_REQUIRED: SafetyCheckStatus.WARNING,
            RightsStatus.EDITORIAL_REVIEW: SafetyCheckStatus.WARNING,
            RightsStatus.UNKNOWN: SafetyCheckStatus.WARNING,
            RightsStatus.BLOCKED: SafetyCheckStatus.FAILED,
        }[record.rights_status]
        severity = {
            RightsStatus.SAFE: SafetySeverity.INFO,
            RightsStatus.ATTRIBUTION_REQUIRED: SafetySeverity.LOW,
            RightsStatus.EDITORIAL_REVIEW: SafetySeverity.MEDIUM,
            RightsStatus.UNKNOWN: SafetySeverity.MEDIUM,
            RightsStatus.BLOCKED: SafetySeverity.HIGH,
        }[record.rights_status]
        recommendation = {
            RightsStatus.SAFE: None,
            RightsStatus.ATTRIBUTION_REQUIRED: "Keep required attribution with the asset.",
            RightsStatus.EDITORIAL_REVIEW: (
                "Review whether this asset can be used in the final package."
            ),
            RightsStatus.UNKNOWN: "Add license or provenance details before publishing.",
            RightsStatus.BLOCKED: "Replace or remove the asset.",
        }[record.rights_status]
        existing = self._check_by_fingerprint(record.assessment_fingerprint)
        if existing is not None:
            return
        self.session.add(
            self._new_check(
                record.video_project_id,
                SafetyTargetType.ASSET,
                record.asset_id,
                SafetyCheckType.ASSET_RIGHTS,
                status,
                severity,
                record.review_notes or "Asset rights review completed.",
                [f"asset:{record.asset_id}", f"rights:{record.rights_status.value}"],
                recommendation,
                record.assessment_fingerprint,
            )
        )

    def _disclosure_check(
        self, project_id: str, decision: DisclosureDecision
    ) -> ContentSafetyCheck:
        fingerprint = self._disclosure_fingerprint(project_id, decision)
        existing = self._check_by_fingerprint(fingerprint)
        if existing is not None:
            return existing
        return self._new_check(
            project_id,
            SafetyTargetType.PROJECT,
            project_id,
            SafetyCheckType.AI_DISCLOSURE,
            SafetyCheckStatus.WARNING if decision.required else SafetyCheckStatus.PASSED,
            SafetySeverity.MEDIUM if decision.required else SafetySeverity.INFO,
            "AI disclosure is required." if decision.required else "AI disclosure is not required.",
            decision.reasons,
            decision.suggested_text,
            fingerprint,
        )

    def _claim_text_covered(self, claim_text: str, text: str) -> bool:
        return _claim_text_covered(claim_text, text)

    def _risky_marketing_words(self, text: str) -> set[str]:
        return _risky_marketing_words(text)


_RISKY_PHRASES = {
    "guaranteed",
    "100% true",
    "official leak",
    "confirmed",
    "breaking",
}


def _contains_local_path(value: str) -> bool:
    lowered = value.casefold()
    return any(
        marker in lowered
        for marker in (
            "c:\\",
            "d:\\",
            "e:\\",
            "\\users\\",
            "/users/",
            "data/projects/",
        )
    )


def _risky_marketing_words(text: str) -> set[str]:
    lowered = text.casefold()
    return {phrase for phrase in _RISKY_PHRASES if phrase in lowered}


def _claim_text_covered(claim_text: str, text: str) -> bool:
    claim = re.sub(r"[^a-z0-9]+", " ", claim_text.casefold()).strip()
    haystack = re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()
    if not claim or not haystack:
        return False
    if claim in haystack:
        return True
    return _text_similarity(claim, haystack) >= 0.82


def _text_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left.casefold(), right.casefold()).ratio()
