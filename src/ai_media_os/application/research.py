"""Local, deterministic research pipeline services."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import (
    ClaimImportance,
    ClaimSupportType,
    ContentFormat,
    ContentType,
    ResearchNoteType,
    SourceAuthorityTier,
    SourceStatus,
    SourceType,
    VerificationStatus,
)
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import (
    Claim,
    ClaimSource,
    ContentVersion,
    ResearchNote,
    Source,
)
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.storage.filesystem import FileStorage
from ai_media_os.utils.hashing import hash_json, hash_text

JsonDict = dict[str, Any]

TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "msclkid",
        "ref",
        "spm",
    }
)

TIER_TO_NUMBER = {
    SourceAuthorityTier.TIER_1_PRIMARY: 1,
    SourceAuthorityTier.TIER_2_RELIABLE_SECONDARY: 2,
    SourceAuthorityTier.TIER_3_DISCOVERY: 3,
    SourceAuthorityTier.UNRATED: None,
}
NUMBER_TO_TIER = {value: key for key, value in TIER_TO_NUMBER.items()}


class ResearchError(ValueError):
    """Raised when local research pipeline rules are violated."""


@dataclass(frozen=True)
class ClassificationSuggestion:
    source_type: SourceType
    authority_tier: SourceAuthorityTier
    confidence: float
    reason: str


@dataclass(frozen=True)
class SourceImportResult:
    source: Source
    duplicate_content_source_id: str | None = None


@dataclass(frozen=True)
class ReadinessResult:
    ready_for_script: bool
    score: float
    blocking_reasons: list[str]
    warnings: list[str]
    metadata: JsonDict

    def as_dict(self) -> JsonDict:
        return {
            "ready_for_script": self.ready_for_script,
            "score": self.score,
            "blocking_reasons": self.blocking_reasons,
            "warnings": self.warnings,
            "metadata": self.metadata,
        }


def normalize_research_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"}:
        raise ResearchError("Remote research source URLs must use http or https.")
    if not parsed.netloc:
        raise ResearchError("Remote research source URL must include a hostname.")

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ResearchError("Remote research source URL must include a hostname.")
    netloc = hostname
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"

    path = parsed.path or "/"
    query_items = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    query = urlencode(query_items, doseq=True)
    return urlunsplit((scheme, netloc, path, query, ""))


def source_type_to_authority_tier(source_type: SourceType) -> SourceAuthorityTier:
    if source_type in {
        SourceType.OFFICIAL,
        SourceType.DOCUMENTATION,
        SourceType.RESEARCH_PAPER,
        SourceType.REGULATORY,
        SourceType.GOVERNMENT,
    }:
        return SourceAuthorityTier.TIER_1_PRIMARY
    if source_type in {SourceType.NEWS, SourceType.INDUSTRY_PUBLICATION}:
        return SourceAuthorityTier.TIER_2_RELIABLE_SECONDARY
    if source_type in {
        SourceType.BLOG,
        SourceType.FORUM,
        SourceType.SOCIAL_MEDIA,
        SourceType.VIDEO,
    }:
        return SourceAuthorityTier.TIER_3_DISCOVERY
    return SourceAuthorityTier.UNRATED


def tier_to_number(tier: SourceAuthorityTier) -> int | None:
    return TIER_TO_NUMBER[tier]


def number_to_tier(value: int | None) -> SourceAuthorityTier:
    return NUMBER_TO_TIER.get(value, SourceAuthorityTier.UNRATED)


class SourceClassifier:
    """Small rule-based classifier for manually imported research sources."""

    def classify(
        self,
        *,
        url: str,
        publisher: str | None = None,
        source_type: SourceType | None = None,
    ) -> ClassificationSuggestion:
        if source_type is not None:
            return ClassificationSuggestion(
                source_type=source_type,
                authority_tier=source_type_to_authority_tier(source_type),
                confidence=1.0,
                reason="Manual source type supplied.",
            )

        parsed = urlsplit(normalize_research_url(url))
        host = parsed.hostname or ""
        path = parsed.path.lower()
        publisher_text = (publisher or "").lower()

        if host.endswith(".gov") or ".gov." in host:
            return self._suggest(SourceType.GOVERNMENT, 0.95, "Government hostname.")
        if "arxiv.org" in host or "doi.org" in host:
            return self._suggest(SourceType.RESEARCH_PAPER, 0.9, "Research identifier host.")
        if "docs" in host or "/docs" in path or "/documentation" in path:
            return self._suggest(SourceType.DOCUMENTATION, 0.85, "Documentation URL pattern.")
        if any(domain in host for domain in ("reddit.com", "news.ycombinator.com")):
            return self._suggest(SourceType.FORUM, 0.9, "Forum hostname.")
        if any(domain in host for domain in ("twitter.com", "x.com", "threads.net", "bsky.app")):
            return self._suggest(SourceType.SOCIAL_MEDIA, 0.9, "Social media hostname.")
        if any(domain in host for domain in ("youtube.com", "youtu.be", "vimeo.com")):
            return self._suggest(SourceType.VIDEO, 0.9, "Video hostname.")
        if any(name in publisher_text for name in ("reuters", "associated press", "bbc")):
            return self._suggest(SourceType.NEWS, 0.75, "Known news publisher text.")
        if host and not host.startswith(("www.", "m.")):
            return self._suggest(SourceType.OFFICIAL, 0.55, "Specific organization hostname.")
        return self._suggest(SourceType.OTHER, 0.3, "No specific classification rule matched.")

    def _suggest(
        self, source_type: SourceType, confidence: float, reason: str
    ) -> ClassificationSuggestion:
        return ClassificationSuggestion(
            source_type=source_type,
            authority_tier=source_type_to_authority_tier(source_type),
            confidence=confidence,
            reason=reason,
        )


class SourceService:
    def __init__(
        self,
        session: Session,
        storage: FileStorage | None = None,
        settings: AppSettings | None = None,
        classifier: SourceClassifier | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.classifier = classifier or SourceClassifier()

    def import_source(
        self,
        *,
        video_project_id: str,
        url: str,
        title: str | None = None,
        publisher: str | None = None,
        author: str | None = None,
        publication_date: datetime | None = None,
        source_type: SourceType | None = None,
        authority_tier: SourceAuthorityTier | None = None,
        language: str | None = None,
        text: str | None = None,
        snapshot_file: Path | None = None,
        notes: str | None = None,
    ) -> SourceImportResult:
        canonical_url = normalize_research_url(url)
        if self.source_for_canonical_url(video_project_id, canonical_url) is not None:
            raise ResearchError("Source already exists for this project and canonical URL.")

        snapshot_text = self._load_snapshot_text(text=text, snapshot_file=snapshot_file)
        content_hash = hash_text(snapshot_text) if snapshot_text is not None else None
        duplicate = self._find_duplicate_content(video_project_id, content_hash)
        suggestion = self.classifier.classify(
            url=canonical_url,
            publisher=publisher,
            source_type=source_type,
        )
        selected_tier = authority_tier or suggestion.authority_tier
        source = Source(
            video_project_id=video_project_id,
            url=url,
            canonical_url=canonical_url,
            title=title,
            publisher=publisher,
            author=author,
            source_type=suggestion.source_type,
            authority_tier=tier_to_number(selected_tier),
            publication_date=publication_date,
            language=language,
            content_hash=content_hash,
            duplicate_of_source_id=duplicate.id if duplicate is not None else None,
            notes=notes,
            status=SourceStatus.IMPORTED,
        )
        self.session.add(source)
        try:
            self.session.flush()
        except IntegrityError as exc:
            self.session.rollback()
            msg = "Source already exists for this project and canonical URL."
            raise ResearchError(msg) from exc

        if snapshot_text is not None:
            source.snapshot_path = self._store_snapshot(source, snapshot_text)
        self.session.commit()
        self.session.refresh(source)
        return SourceImportResult(
            source=source,
            duplicate_content_source_id=duplicate.id if duplicate is not None else None,
        )

    def list_project_sources(self, video_project_id: str) -> list[Source]:
        return list(
            self.session.scalars(
                select(Source)
                .where(Source.video_project_id == video_project_id)
                .order_by(Source.created_at.asc(), Source.id.asc())
            ).all()
        )

    def update_source_status(self, source_id: str, status: SourceStatus) -> Source:
        source = self._get_source(source_id)
        source.status = status
        source.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(source)
        return source

    def source_for_canonical_url(self, video_project_id: str, canonical_url: str) -> Source | None:
        return self.session.scalar(
            select(Source).where(
                Source.video_project_id == video_project_id,
                Source.canonical_url == canonical_url,
            )
        )

    def duplicate_content_sources(self, video_project_id: str) -> list[Source]:
        return list(
            self.session.scalars(
                select(Source)
                .where(
                    Source.video_project_id == video_project_id,
                    Source.duplicate_of_source_id.is_not(None),
                )
                .order_by(Source.created_at.asc())
            ).all()
        )

    def _load_snapshot_text(self, *, text: str | None, snapshot_file: Path | None) -> str | None:
        if text is not None and snapshot_file is not None:
            raise ResearchError("Provide source text or snapshot file, not both.")
        if text is None and snapshot_file is None:
            return None
        if snapshot_file is not None:
            if snapshot_file.suffix.lower() not in self.settings.research_allowed_text_extensions:
                raise ResearchError("Unsupported research snapshot file extension.")
            raw = snapshot_file.read_bytes()
            if len(raw) > self.settings.research_max_source_bytes:
                raise ResearchError("Research source snapshot exceeds configured size limit.")
            text = raw.decode("utf-8")
        assert text is not None
        normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        if not normalized:
            raise ResearchError("Research source snapshot cannot be empty.")
        if len(normalized.encode("utf-8")) > self.settings.research_max_source_bytes:
            raise ResearchError("Research source snapshot exceeds configured size limit.")
        return normalized

    def _find_duplicate_content(
        self,
        video_project_id: str,
        content_hash: str | None,
    ) -> Source | None:
        if content_hash is None:
            return None
        return self.session.scalar(
            select(Source)
            .where(
                Source.video_project_id == video_project_id,
                Source.content_hash == content_hash,
            )
            .order_by(Source.created_at.asc())
            .limit(1)
        )

    def _store_snapshot(self, source: Source, snapshot_text: str) -> str:
        relative = Path("projects") / source.video_project_id / "research" / "sources" / source.id
        snapshot_path = self.storage.resolve_inside(
            self.storage.data_root, relative / "snapshot.txt"
        )
        metadata_path = self.storage.resolve_inside(
            self.storage.data_root, relative / "metadata.json"
        )
        content_hash = self.storage.atomic_write(
            snapshot_path,
            snapshot_text.encode("utf-8"),
        )
        metadata = {
            "source_id": source.id,
            "canonical_url": source.canonical_url,
            "content_hash": content_hash,
            "stored_at": utc_now().isoformat(),
        }
        self.storage.atomic_write(
            metadata_path,
            json.dumps(metadata, sort_keys=True, indent=2).encode("utf-8"),
        )
        return self.storage.relative_to_data_root(snapshot_path)

    def _get_source(self, source_id: str) -> Source:
        source = self.session.get(Source, source_id)
        if source is None:
            raise ResearchError(f"Source not found: {source_id}")
        return source


class ResearchNoteService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_note(
        self,
        *,
        video_project_id: str,
        source_id: str,
        note_type: ResearchNoteType,
        content: str,
        source_location: str | None = None,
        metadata: JsonDict | None = None,
    ) -> ResearchNote:
        source = self._get_source(source_id)
        if source.video_project_id != video_project_id:
            raise ResearchError("Research note source must belong to the same project.")
        normalized = content.strip()
        if not normalized:
            raise ResearchError("Research note content cannot be empty.")
        note = ResearchNote(
            video_project_id=video_project_id,
            source_id=source_id,
            note_type=note_type,
            content=normalized,
            content_hash=hash_text(normalized),
            source_location=source_location,
            metadata_json=metadata or {},
        )
        self.session.add(note)
        self.session.commit()
        self.session.refresh(note)
        return note

    def update_note(self, note_id: str, content: str) -> ResearchNote:
        note = self._get_note(note_id)
        normalized = content.strip()
        if not normalized:
            raise ResearchError("Research note content cannot be empty.")
        note.content = normalized
        note.content_hash = hash_text(normalized)
        note.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(note)
        return note

    def delete_note(self, note_id: str) -> None:
        note = self._get_note(note_id)
        self.session.delete(note)
        self.session.commit()

    def list_source_notes(self, source_id: str) -> list[ResearchNote]:
        return list(
            self.session.scalars(
                select(ResearchNote)
                .where(ResearchNote.source_id == source_id)
                .order_by(ResearchNote.created_at.asc())
            ).all()
        )

    def list_project_notes(self, video_project_id: str) -> list[ResearchNote]:
        return list(
            self.session.scalars(
                select(ResearchNote)
                .where(ResearchNote.video_project_id == video_project_id)
                .order_by(ResearchNote.created_at.asc())
            ).all()
        )

    def _get_source(self, source_id: str) -> Source:
        source = self.session.get(Source, source_id)
        if source is None:
            raise ResearchError(f"Source not found: {source_id}")
        return source

    def _get_note(self, note_id: str) -> ResearchNote:
        note = self.session.get(ResearchNote, note_id)
        if note is None:
            raise ResearchError(f"Research note not found: {note_id}")
        return note


class ClaimService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_claim(
        self,
        *,
        video_project_id: str,
        claim_text: str,
        importance: ClaimImportance = ClaimImportance.MEDIUM,
        confidence: float | None = None,
        valid_until: datetime | None = None,
    ) -> Claim:
        normalized = claim_text.strip()
        if not normalized:
            raise ResearchError("Claim text cannot be empty.")
        claim = Claim(
            video_project_id=video_project_id,
            claim_text=normalized,
            importance=importance,
            confidence=confidence,
            verification_status=VerificationStatus.UNVERIFIED,
            valid_until=valid_until,
        )
        self.session.add(claim)
        self.session.commit()
        self.session.refresh(claim)
        return claim

    def link_source(
        self,
        *,
        claim_id: str,
        source_id: str,
        support_type: ClaimSupportType,
        quoted_excerpt: str | None = None,
        source_location: str | None = None,
        notes: str | None = None,
    ) -> ClaimSource:
        claim = self._get_claim(claim_id)
        source = self._get_source(source_id)
        if claim.video_project_id != source.video_project_id:
            raise ResearchError("Claim and source must belong to the same project.")
        link = ClaimSource(
            claim_id=claim_id,
            source_id=source_id,
            support_type=support_type,
            quoted_excerpt=quoted_excerpt,
            source_location=source_location,
            notes=notes,
        )
        self.session.add(link)
        try:
            self.session.commit()
        except IntegrityError as exc:
            self.session.rollback()
            raise ResearchError("Duplicate claim-source link.") from exc
        self.session.refresh(link)
        return link

    def update_verification_status(
        self,
        claim_id: str,
        status: VerificationStatus,
        *,
        override_reason: str | None = None,
    ) -> Claim:
        claim = self._get_claim(claim_id)
        self.session.expire(claim, ["source_links"])
        if status == VerificationStatus.VERIFIED:
            self._validate_verified_claim(claim, override_reason)
        claim.verification_status = status
        if override_reason:
            existing = claim.source_links[0].notes if claim.source_links else None
            if claim.source_links:
                claim.source_links[0].notes = "; ".join(
                    item for item in (existing, f"Manual override: {override_reason}") if item
                )
        claim.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(claim)
        return claim

    def unsupported_claims(self, video_project_id: str) -> list[Claim]:
        claims = self.list_project_claims(video_project_id)
        return [
            claim
            for claim in claims
            if claim.importance in {ClaimImportance.HIGH, ClaimImportance.CRITICAL}
            and not any(
                link.support_type in {ClaimSupportType.SUPPORTS, ClaimSupportType.PRIMARY_EVIDENCE}
                for link in claim.source_links
            )
        ]

    def contradicted_claims(self, video_project_id: str) -> list[Claim]:
        return [
            claim
            for claim in self.list_project_claims(video_project_id)
            if claim.verification_status == VerificationStatus.CONTRADICTED
            or any(link.support_type == ClaimSupportType.CONTRADICTS for link in claim.source_links)
        ]

    def list_project_claims(self, video_project_id: str) -> list[Claim]:
        return list(
            self.session.scalars(
                select(Claim)
                .where(Claim.video_project_id == video_project_id)
                .order_by(Claim.created_at.asc(), Claim.id.asc())
            ).all()
        )

    def _validate_verified_claim(self, claim: Claim, override_reason: str | None) -> None:
        links = claim.source_links
        if any(link.support_type == ClaimSupportType.CONTRADICTS for link in links):
            raise ResearchError("Contradicting sources prevent automatic claim verification.")
        supporting = [
            link
            for link in links
            if link.support_type
            in {
                ClaimSupportType.SUPPORTS,
                ClaimSupportType.PARTIALLY_SUPPORTS,
                ClaimSupportType.PRIMARY_EVIDENCE,
            }
        ]
        if not supporting:
            raise ResearchError("A verified claim requires at least one supporting source.")
        if claim.importance == ClaimImportance.CRITICAL:
            primary = [
                link
                for link in supporting
                if number_to_tier(link.source.authority_tier) == SourceAuthorityTier.TIER_1_PRIMARY
            ]
            secondary_source_ids = {
                link.source_id
                for link in supporting
                if number_to_tier(link.source.authority_tier)
                == SourceAuthorityTier.TIER_2_RELIABLE_SECONDARY
            }
            if not primary and len(secondary_source_ids) < 2:
                if not override_reason:
                    raise ResearchError(
                        "A verified critical claim requires a Tier 1 source or two "
                        "reliable secondary sources."
                    )
        if claim.importance == ClaimImportance.HIGH:
            discovery_only = all(
                number_to_tier(link.source.authority_tier) == SourceAuthorityTier.TIER_3_DISCOVERY
                for link in supporting
            )
            if discovery_only and not override_reason:
                raise ResearchError("Discovery-only sources cannot verify a high-importance claim.")

    def _get_claim(self, claim_id: str) -> Claim:
        claim = self.session.get(Claim, claim_id)
        if claim is None:
            raise ResearchError(f"Claim not found: {claim_id}")
        return claim

    def _get_source(self, source_id: str) -> Source:
        source = self.session.get(Source, source_id)
        if source is None:
            raise ResearchError(f"Source not found: {source_id}")
        return source


class ResearchReportService:
    def __init__(self, session: Session, settings: AppSettings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.content_versions = ContentVersionService(session)

    def generate_research_brief(self, video_project_id: str) -> ContentVersion:
        sources = self._sources(video_project_id)
        notes = self._notes(video_project_id)
        claims = self._claims(video_project_id)
        readiness = self.evaluate_readiness(video_project_id)
        content = self._brief_markdown(video_project_id, sources, notes, claims, readiness)
        input_hashes = self._input_hashes(sources, notes, claims, readiness.as_dict())
        existing = self._matching_report(
            video_project_id,
            ContentType.RESEARCH_BRIEF,
            ContentFormat.MARKDOWN,
            "research-brief-v1",
            input_hashes,
        )
        if existing is not None:
            return existing
        return self.content_versions.create_initial_version(
            video_project_id=video_project_id,
            content_type=ContentType.RESEARCH_BRIEF,
            content=content,
            content_format=ContentFormat.MARKDOWN,
            provider="local_rules",
            model="research-brief-v1",
            input_hashes=input_hashes,
        )

    def generate_source_report(
        self,
        video_project_id: str,
        *,
        content_format: ContentFormat = ContentFormat.MARKDOWN,
    ) -> ContentVersion:
        sources = self._sources(video_project_id)
        claims = self._claims(video_project_id)
        report = self._source_report_data(sources, claims)
        if content_format == ContentFormat.JSON:
            content = json.dumps(report, sort_keys=True, indent=2)
        else:
            content = self._source_report_markdown(report)
        input_hashes = self._input_hashes(sources, [], claims, report)
        existing = self._matching_report(
            video_project_id,
            ContentType.SOURCE_REPORT,
            content_format,
            "source-report-v1",
            input_hashes,
        )
        if existing is not None:
            return existing
        return self.content_versions.create_initial_version(
            video_project_id=video_project_id,
            content_type=ContentType.SOURCE_REPORT,
            content=content,
            content_format=content_format,
            provider="local_rules",
            model="source-report-v1",
            input_hashes=input_hashes,
        )

    def _matching_report(
        self,
        video_project_id: str,
        content_type: ContentType,
        content_format: ContentFormat,
        model: str,
        input_hashes: list[str],
    ) -> ContentVersion | None:
        return self.session.scalar(
            select(ContentVersion)
            .where(
                ContentVersion.video_project_id == video_project_id,
                ContentVersion.content_type == content_type,
                ContentVersion.content_format == content_format,
                ContentVersion.provider == "local_rules",
                ContentVersion.model == model,
                ContentVersion.input_hashes == input_hashes,
            )
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )

    def evaluate_readiness(self, video_project_id: str) -> ReadinessResult:
        sources = self._sources(video_project_id)
        claims = self._claims(video_project_id)
        blockers: list[str] = []
        warnings: list[str] = []
        approved = [source for source in sources if source.status == SourceStatus.APPROVED]
        if not approved:
            blockers.append("No approved sources.")
        if not any(source.snapshot_path for source in sources):
            blockers.append("No source snapshots.")
        for claim in claims:
            if claim.importance == ClaimImportance.CRITICAL and claim.verification_status in {
                VerificationStatus.UNVERIFIED,
                VerificationStatus.PARTIALLY_VERIFIED,
            }:
                blockers.append(f"Critical claim is not verified: {claim.id}")
            if claim.importance == ClaimImportance.CRITICAL and claim.verification_status in {
                VerificationStatus.CONTRADICTED,
                VerificationStatus.DISPUTED,
            }:
                blockers.append(f"Critical claim is contradicted or disputed: {claim.id}")
            if claim.importance == ClaimImportance.HIGH and not claim.source_links:
                blockers.append(f"High-importance claim has no supporting source: {claim.id}")
        if approved and all(
            number_to_tier(source.authority_tier) == SourceAuthorityTier.TIER_3_DISCOVERY
            for source in approved
        ):
            blockers.append("All approved sources are Tier 3 discovery sources.")
        for source in sources:
            if source.publication_date is None:
                warnings.append(f"Source missing publication date: {source.id}")
            if not source.publisher:
                warnings.append(f"Source missing publisher: {source.id}")
        content_hashes = [source.content_hash for source in sources if source.content_hash]
        duplicate_ratio = 0.0
        if content_hashes:
            most_common = Counter(content_hashes).most_common(1)[0][1]
            duplicate_ratio = most_common / len(content_hashes)
            if duplicate_ratio > self.settings.research_duplicate_content_warning_threshold:
                warnings.append("Duplicate-content concentration is high.")
        if approved:
            publisher_counts = Counter(
                source.publisher or source.canonical_url for source in approved
            )
            concentration = publisher_counts.most_common(1)[0][1] / len(approved)
            if concentration > self.settings.research_max_source_concentration:
                warnings.append("Source concentration is high.")
        primary_count = sum(
            number_to_tier(source.authority_tier) == SourceAuthorityTier.TIER_1_PRIMARY
            for source in approved
        )
        if primary_count < self.settings.research_min_primary_sources:
            warnings.append("Primary source count is below the configured target.")

        score = max(0.0, 1.0 - (len(blockers) * 0.25) - (len(warnings) * 0.05))
        return ReadinessResult(
            ready_for_script=not blockers,
            score=round(score, 2),
            blocking_reasons=blockers,
            warnings=warnings,
            metadata={
                "source_count": len(sources),
                "approved_source_count": len(approved),
                "primary_source_count": primary_count,
                "duplicate_content_ratio": round(duplicate_ratio, 3),
            },
        )

    def _sources(self, video_project_id: str) -> list[Source]:
        return list(self.session.scalars(self._source_query(video_project_id)).all())

    def _notes(self, video_project_id: str) -> list[ResearchNote]:
        return list(
            self.session.scalars(
                select(ResearchNote)
                .where(ResearchNote.video_project_id == video_project_id)
                .order_by(ResearchNote.created_at.asc(), ResearchNote.id.asc())
            ).all()
        )

    def _claims(self, video_project_id: str) -> list[Claim]:
        return list(
            self.session.scalars(
                select(Claim)
                .where(Claim.video_project_id == video_project_id)
                .order_by(Claim.created_at.asc(), Claim.id.asc())
            ).all()
        )

    def _source_query(self, video_project_id: str) -> Select[tuple[Source]]:
        return (
            select(Source)
            .where(Source.video_project_id == video_project_id)
            .order_by(Source.created_at.asc(), Source.id.asc())
        )

    def _brief_markdown(
        self,
        video_project_id: str,
        sources: list[Source],
        notes: list[ResearchNote],
        claims: list[Claim],
        readiness: ReadinessResult,
    ) -> str:
        verified = [
            claim for claim in claims if claim.verification_status == VerificationStatus.VERIFIED
        ]
        unverified = [
            claim for claim in claims if claim.verification_status != VerificationStatus.VERIFIED
        ]
        contradictions = [
            claim
            for claim in claims
            if claim.verification_status
            in {VerificationStatus.CONTRADICTED, VerificationStatus.DISPUTED}
            or any(link.support_type == ClaimSupportType.CONTRADICTS for link in claim.source_links)
        ]
        sections = [
            "# Research Brief",
            "",
            f"Project ID: `{video_project_id}`",
            "",
            "## Research Status",
            f"- Ready for script: `{str(readiness.ready_for_script).lower()}`",
            f"- Score: `{readiness.score}`",
            "",
            "## Executive Summary",
            self._note_lines(notes, ResearchNoteType.SUMMARY) or "No summary notes recorded.",
            "",
            "## Key Findings",
            self._note_lines(notes, ResearchNoteType.KEY_POINT) or "No key findings recorded.",
            "",
            "## Verified Claims",
            self._claim_lines(verified) or "No verified claims recorded.",
            "",
            "## Unverified Claims",
            self._claim_lines(unverified) or "No unverified claims recorded.",
            "",
            "## Contradictions",
            self._claim_lines(contradictions) or "No contradictions recorded.",
            "",
            "## Risks and Open Questions",
            self._note_lines(notes, ResearchNoteType.RISK) or "No risks recorded.",
            "",
            "## Primary Sources",
            self._source_lines(sources, SourceAuthorityTier.TIER_1_PRIMARY)
            or "No primary sources.",
            "",
            "## Secondary Sources",
            self._source_lines(sources, SourceAuthorityTier.TIER_2_RELIABLE_SECONDARY)
            or "No secondary sources.",
            "",
            "## Discovery Sources",
            self._source_lines(sources, SourceAuthorityTier.TIER_3_DISCOVERY)
            or "No discovery sources.",
            "",
            "## Recommended Script Boundaries",
            "Use verified claims as factual anchors. Treat unverified claims, "
            "contradictions, and risk notes as review boundaries, not script-ready facts.",
            "",
        ]
        return "\n".join(sections)

    def _source_report_data(self, sources: list[Source], claims: list[Claim]) -> JsonDict:
        by_type = Counter(source.source_type.value for source in sources)
        by_tier = Counter(number_to_tier(source.authority_tier).value for source in sources)
        by_status = Counter(source.status.value for source in sources)
        claims_per_source = {
            source.id: len(source.claim_links)
            for source in sorted(sources, key=lambda item: (item.created_at, item.id))
        }
        return {
            "total_sources": len(sources),
            "source_count_by_type": dict(sorted(by_type.items())),
            "source_count_by_authority_tier": dict(sorted(by_tier.items())),
            "source_count_by_status": dict(sorted(by_status.items())),
            "duplicate_url_findings": [],
            "duplicate_content_findings": [
                {"source_id": source.id, "duplicate_of_source_id": source.duplicate_of_source_id}
                for source in sources
                if source.duplicate_of_source_id is not None
            ],
            "sources_without_publication_dates": [
                source.id for source in sources if source.publication_date is None
            ],
            "sources_without_publishers": [source.id for source in sources if not source.publisher],
            "claims_per_source": claims_per_source,
            "unsupported_claims": [
                claim.id
                for claim in claims
                if claim.importance in {ClaimImportance.HIGH, ClaimImportance.CRITICAL}
                and not claim.source_links
            ],
            "contradicted_claims": [
                claim.id
                for claim in claims
                if claim.verification_status == VerificationStatus.CONTRADICTED
            ],
            "required_manual_review_items": [
                claim.id
                for claim in claims
                if claim.verification_status
                in {VerificationStatus.UNVERIFIED, VerificationStatus.DISPUTED}
            ],
            "snapshots": [
                {
                    "source_id": source.id,
                    "content_hash": source.content_hash,
                    "snapshot_path": source.snapshot_path,
                    "retrieved_at": source.retrieved_at.isoformat(),
                }
                for source in sources
            ],
        }

    def _source_report_markdown(self, report: JsonDict) -> str:
        lines = [
            "# Source Report",
            "",
            f"- Total sources: {report['total_sources']}",
            "- Source count by type: "
            f"`{json.dumps(report['source_count_by_type'], sort_keys=True)}`",
            "- Source count by authority tier: "
            f"`{json.dumps(report['source_count_by_authority_tier'], sort_keys=True)}`",
            "- Source count by status: "
            f"`{json.dumps(report['source_count_by_status'], sort_keys=True)}`",
            f"- Duplicate content findings: {len(report['duplicate_content_findings'])}",
            "- Sources without publication dates: "
            f"{len(report['sources_without_publication_dates'])}",
            f"- Sources without publishers: {len(report['sources_without_publishers'])}",
            f"- Unsupported claims: {len(report['unsupported_claims'])}",
            f"- Contradicted claims: {len(report['contradicted_claims'])}",
            "",
            "## Snapshots",
        ]
        snapshots = report["snapshots"]
        if snapshots:
            lines.extend(
                f"- `{item['source_id']}` `{item['content_hash']}` `{item['snapshot_path']}`"
                for item in snapshots
            )
        else:
            lines.append("No snapshots recorded.")
        return "\n".join(lines) + "\n"

    def _input_hashes(
        self,
        sources: list[Source],
        notes: list[ResearchNote],
        claims: list[Claim],
        metadata: JsonDict,
    ) -> list[str]:
        source_hash = hash_json(
            [
                {
                    "id": source.id,
                    "canonical_url": source.canonical_url,
                    "content_hash": source.content_hash,
                    "status": source.status,
                }
                for source in sources
            ]
        )
        note_hash = hash_json(
            [
                {"id": note.id, "content_hash": note.content_hash, "type": note.note_type}
                for note in notes
            ]
        )
        claim_hash = hash_json(
            [
                {
                    "id": claim.id,
                    "text": claim.claim_text,
                    "importance": claim.importance,
                    "status": claim.verification_status,
                    "links": [
                        {
                            "source_id": link.source_id,
                            "support_type": link.support_type,
                        }
                        for link in claim.source_links
                    ],
                }
                for claim in claims
            ]
        )
        return [source_hash, note_hash, claim_hash, hash_json(metadata)]

    def _note_lines(self, notes: list[ResearchNote], note_type: ResearchNoteType) -> str:
        selected = [note for note in notes if note.note_type == note_type]
        return "\n".join(f"- {note.content}" for note in selected)

    def _claim_lines(self, claims: list[Claim]) -> str:
        return "\n".join(f"- `{claim.importance.value}` {claim.claim_text}" for claim in claims)

    def _source_lines(self, sources: list[Source], tier: SourceAuthorityTier) -> str:
        selected = [source for source in sources if number_to_tier(source.authority_tier) == tier]
        return "\n".join(
            f"- {source.title or source.canonical_url} ({source.publisher or 'unknown publisher'})"
            for source in selected
        )
