"""Read-only LLM summaries for deterministic safety reports."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import ContentType, PublishingGateStatus
from ai_media_os.providers.text_generation import TextGenerationProvider, TextGenerationRequest
from ai_media_os.schemas.safety import SafetyReportDocument
from ai_media_os.utils.hashing import hash_text


class SafetySummaryError(RuntimeError):
    """Raised when a safety report cannot be summarized."""


@dataclass(frozen=True)
class SafetySummaryResult:
    text: str
    authoritative_status: PublishingGateStatus
    report_version_id: str
    provider: str
    model: str


class SafetySummaryService:
    """Summarize a report without changing any deterministic safety record."""

    def __init__(
        self,
        session: Session,
        provider: TextGenerationProvider,
        *,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.session = session
        self.provider = provider
        self.timeout_seconds = timeout_seconds

    def summarize(self, video_project_id: str) -> SafetySummaryResult:
        report_version = ContentVersionService(self.session).latest_version(
            video_project_id, ContentType.COPYRIGHT_REPORT
        )
        if report_version is None:
            raise SafetySummaryError("Safety report not found for project.")
        report = SafetyReportDocument.model_validate_json(report_version.content)
        result = self.provider.generate(
            TextGenerationRequest(
                prompt=report_version.content,
                system_prompt=(
                    "Summarize this deterministic safety report for a human reviewer. "
                    "Do not change the gate status, remove blockers, approve content, or make "
                    "legal claims."
                ),
                provider_settings={
                    "output_type": "safety_summary",
                    "schema_version": report.schema_version,
                    "system_prompt_hash": hash_text("safety-summary-system-v1"),
                },
                timeout_seconds=self.timeout_seconds,
            )
        )
        return SafetySummaryResult(
            text=result.text,
            authoritative_status=report.gate.status,
            report_version_id=report_version.id,
            provider=result.provider,
            model=result.model,
        )
