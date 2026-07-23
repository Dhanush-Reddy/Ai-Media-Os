"""Generate, verify, and persist local narration word alignments."""

import json
import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import (
    AssetReviewStatus,
    AssetRole,
    ContentFormat,
    ContentType,
)
from ai_media_os.infrastructure.database.models import Asset, ContentVersion
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.providers.narration_alignment import (
    NarrationAlignmentProvider,
    NarrationAlignmentRequest,
    normalize_word,
)
from ai_media_os.schemas.narration_alignment import (
    AlignedWord,
    AlignmentDecision,
    AlignmentVerification,
    NarrationAlignmentDocument,
    WordTrigger,
)
from ai_media_os.storage.filesystem import FileStorage
from ai_media_os.utils.hashing import hash_file, hash_json, hash_text

ALIGNMENT_RULE_VERSION = "narration-alignment-v1"
COMPOUND_WORD_ALIGNMENT_RULE_VERSION = "narration-alignment-v2-compound-words"
ALIGNMENT_TIMING_TOLERANCE_SECONDS = 0.02


class NarrationAlignmentError(RuntimeError):
    """Raised when narration cannot be aligned or safely reused."""


@dataclass(frozen=True)
class TriggerRequest:
    name: str
    word: str
    occurrence: int = 1


def _normalize_alignment_words(
    words: list[AlignedWord], *, duration_seconds: float
) -> tuple[list[AlignedWord], bool]:
    if not words:
        raise NarrationAlignmentError("Narration alignment returned no words.")

    normalized: list[AlignedWord] = []
    was_clamped = False
    last_index = len(words) - 1
    for index, word in enumerate(words):
        if word.start_seconds > duration_seconds + ALIGNMENT_TIMING_TOLERANCE_SECONDS:
            raise NarrationAlignmentError("Aligned words exceed narration duration.")

        end_seconds = word.end_seconds
        if index == last_index and end_seconds > duration_seconds:
            end_seconds = duration_seconds
            was_clamped = True
        elif index != last_index and end_seconds > duration_seconds:
            raise NarrationAlignmentError("Aligned words exceed narration duration.")

        if end_seconds > duration_seconds + ALIGNMENT_TIMING_TOLERANCE_SECONDS:
            raise NarrationAlignmentError("Aligned words exceed narration duration.")
        if end_seconds <= word.start_seconds:
            raise NarrationAlignmentError("Aligned word end must follow its start.")

        if end_seconds == word.end_seconds:
            normalized.append(word)
        else:
            normalized.append(word.model_copy(update={"end_seconds": end_seconds}))

    return normalized, was_clamped


class NarrationAlignmentService:
    def __init__(
        self,
        session: Session,
        provider: NarrationAlignmentProvider,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.versions = ContentVersionService(session)

    def align_asset(
        self,
        asset_id: str,
        *,
        language: str = "en",
        frame_rate: int = 30,
        triggers: list[TriggerRequest] | None = None,
        timeout_seconds: float = 600,
    ) -> ContentVersion:
        asset = self._approved_narration(asset_id)
        if asset.scene is None or asset.content_hash is None or asset.duration_seconds is None:
            raise NarrationAlignmentError(
                "Narration asset is missing scene, hash, or duration data."
            )
        audio_path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        if not audio_path.is_file() or hash_file(audio_path) != asset.content_hash:
            raise NarrationAlignmentError("Narration file is missing or its hash does not match.")
        transcript = asset.scene.narration.strip()
        rule_version = _alignment_rule_version(transcript)
        trigger_requests = triggers or []
        input_fingerprint = hash_json(
            {
                "rule_version": rule_version,
                "project_id": asset.video_project_id,
                "scene_id": asset.scene_id,
                "asset_id": asset.id,
                "asset_hash": asset.content_hash,
                "transcript_hash": hash_text(transcript),
                "language": language,
                "frame_rate": frame_rate,
                "provider": self.provider.provider_name,
                "model": self.provider.model_name,
                "model_version": self.provider.model_version,
                "provider_configuration": self.provider.configuration_fingerprint,
                "triggers": [request.__dict__ for request in trigger_requests],
            }
        )
        existing = self._by_fingerprint(asset.video_project_id, input_fingerprint)
        if existing is not None:
            return existing
        result = self.provider.align(
            NarrationAlignmentRequest(
                audio_path=audio_path,
                audio_hash=asset.content_hash,
                transcript=transcript,
                language=language,
                duration_seconds=asset.duration_seconds,
                timeout_seconds=timeout_seconds,
                settings={"frame_rate": frame_rate},
            )
        )
        words, was_clamped = _normalize_alignment_words(
            result.words, duration_seconds=asset.duration_seconds
        )
        verification, resolved_triggers = verify_alignment(
            transcript=transcript,
            words=words,
            duration_seconds=asset.duration_seconds,
            frame_rate=frame_rate,
            triggers=trigger_requests,
            minimum_average_confidence=self.settings.alignment_minimum_average_confidence,
            minimum_trigger_confidence=self.settings.alignment_minimum_trigger_confidence,
        )
        if was_clamped:
            verification = verification.model_copy(
                update={
                    "warnings": [
                        *verification.warnings,
                        "Final aligned word exceeded the narration duration and was clamped.",
                    ]
                }
            )
        if result.provider == "fake_alignment":
            verification = verification.model_copy(
                update={
                    "decision": AlignmentDecision.WARN,
                    "auto_usable": False,
                    "warnings": [
                        *verification.warnings,
                        "Fake alignment does not inspect speech and is never production-usable.",
                    ],
                }
            )
        document = NarrationAlignmentDocument(
            rule_version=rule_version,
            project_id=asset.video_project_id,
            scene_id=asset.scene_id,
            narration_asset_id=asset.id,
            narration_asset_hash=asset.content_hash,
            transcript=transcript,
            transcript_hash=hash_text(transcript),
            language=language,
            audio_duration_seconds=asset.duration_seconds,
            frame_rate=frame_rate,
            provider=result.provider,
            model=result.model,
            model_version=result.model_version,
            provider_settings_hash=result.settings_hash,
            words=words,
            triggers=resolved_triggers,
            verification=verification,
            fingerprint=input_fingerprint,
        )
        latest = self.versions.latest_version(
            asset.video_project_id, ContentType.NARRATION_ALIGNMENT
        )
        return self.versions.create_revision(
            parent_version_id=latest.id if latest is not None else None,
            video_project_id=asset.video_project_id,
            content_type=ContentType.NARRATION_ALIGNMENT,
            content=document.model_dump_json(indent=2),
            content_format=ContentFormat.JSON,
            prompt_version=rule_version,
            provider=result.provider,
            model=f"{result.model}:{result.model_version}",
            input_hashes=[asset.content_hash, hash_text(transcript), input_fingerprint],
        )

    def latest_for_scene(self, project_id: str, scene_id: str) -> ContentVersion | None:
        versions = self.versions.version_history(project_id, ContentType.NARRATION_ALIGNMENT)
        for version in reversed(versions):
            try:
                document = NarrationAlignmentDocument.model_validate_json(version.content)
            except ValueError:
                continue
            if document.scene_id == scene_id:
                return version
        return None

    def _by_fingerprint(self, project_id: str, fingerprint: str) -> ContentVersion | None:
        versions = self.session.scalars(
            select(ContentVersion).where(
                ContentVersion.video_project_id == project_id,
                ContentVersion.content_type == ContentType.NARRATION_ALIGNMENT,
            )
        )
        for version in versions:
            try:
                if json.loads(version.content).get("fingerprint") == fingerprint:
                    return version
            except (json.JSONDecodeError, AttributeError):
                continue
        return None

    def _approved_narration(self, asset_id: str) -> Asset:
        asset = self.session.get(Asset, asset_id)
        if asset is None:
            raise NarrationAlignmentError(f"Narration asset not found: {asset_id}")
        if asset.asset_role != AssetRole.SCENE_NARRATION:
            raise NarrationAlignmentError("Only scene narration assets can be aligned.")
        if asset.review_status != AssetReviewStatus.APPROVED:
            raise NarrationAlignmentError("Narration must be approved before timing alignment.")
        return asset


def verify_alignment(
    *,
    transcript: str,
    words: list[AlignedWord],
    duration_seconds: float,
    frame_rate: int,
    triggers: list[TriggerRequest],
    minimum_average_confidence: float = 0.75,
    minimum_trigger_confidence: float = 0.65,
) -> tuple[AlignmentVerification, list[WordTrigger]]:
    expected = [
        normalize_word(token)
        for token in re.findall(r"[\w']+(?:-[\w']+)*", transcript)
    ]
    actual = [word.normalized_text for word in words]
    issues: list[str] = []
    warnings: list[str] = []
    transcript_match = expected == actual
    if not transcript_match:
        issues.append("Aligned words do not exactly match the approved scene narration.")
    timestamps_monotonic = all(
        word.end_seconds > word.start_seconds
        and (
            index == 0
            or word.start_seconds
            >= words[index - 1].end_seconds - ALIGNMENT_TIMING_TOLERANCE_SECONDS
        )
        for index, word in enumerate(words)
    )
    if not timestamps_monotonic:
        issues.append("Word timestamps overlap or are out of order.")
    audio_bounds_valid = bool(words) and words[-1].end_seconds <= (
        duration_seconds + ALIGNMENT_TIMING_TOLERANCE_SECONDS
    )
    if not audio_bounds_valid:
        issues.append("Word timestamps exceed the narration duration.")
    confidences = [word.confidence for word in words if word.confidence is not None]
    average_confidence = sum(confidences) / len(confidences) if confidences else None
    if average_confidence is None:
        warnings.append("Provider did not return word confidence scores.")
    elif average_confidence < minimum_average_confidence:
        warnings.append(f"Average word confidence is below {minimum_average_confidence:.2f}.")
    resolved: list[WordTrigger] = []
    previous_trigger = -1.0
    trigger_order_valid = True
    for trigger in triggers:
        matches = [word for word in words if word.normalized_text == normalize_word(trigger.word)]
        if len(matches) < trigger.occurrence:
            issues.append(f"Required trigger word was not aligned: {trigger.word}")
            trigger_order_valid = False
            continue
        match = matches[trigger.occurrence - 1]
        if match.start_seconds < previous_trigger:
            issues.append("Required trigger words are not in the requested order.")
            trigger_order_valid = False
        if match.confidence is not None and match.confidence < minimum_trigger_confidence:
            issues.append(f"Trigger confidence is too low: {trigger.word}")
        resolved.append(
            WordTrigger(
                name=trigger.name,
                word=trigger.word,
                occurrence=trigger.occurrence,
                start_seconds=match.start_seconds,
                end_seconds=match.end_seconds,
                start_frame=round(match.start_seconds * frame_rate),
                confidence=match.confidence,
            )
        )
        previous_trigger = match.start_seconds
    if issues:
        decision = AlignmentDecision.BLOCK
    elif warnings:
        decision = AlignmentDecision.WARN
    else:
        decision = AlignmentDecision.PASS
    return (
        AlignmentVerification(
            decision=decision,
            auto_usable=decision == AlignmentDecision.PASS,
            transcript_match=transcript_match,
            timestamps_monotonic=timestamps_monotonic,
            audio_bounds_valid=audio_bounds_valid,
            trigger_order_valid=trigger_order_valid,
            average_confidence=average_confidence,
            issues=issues,
            warnings=warnings,
        ),
        resolved,
    )


def _alignment_rule_version(transcript: str) -> str:
    if re.search(r"[\w']+-[\w']+", transcript):
        return COMPOUND_WORD_ALIGNMENT_RULE_VERSION
    return ALIGNMENT_RULE_VERSION
