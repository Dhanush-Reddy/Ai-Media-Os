"""Application service for immutable content versions."""

from collections.abc import Sequence

from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_media_os.domain.enums import ContentFormat, ContentType, VersionStatus
from ai_media_os.infrastructure.database.models import ContentVersion
from ai_media_os.utils.hashing import hash_content_version


class ContentVersionError(RuntimeError):
    """Raised when content-version rules are violated."""


IMMUTABLE_CONTENT_VERSION_FIELDS = frozenset(
    {
        "video_project_id",
        "content_type",
        "version_number",
        "parent_version_id",
        "content",
        "content_format",
        "prompt_version",
        "provider",
        "model",
        "input_hashes",
        "content_hash",
        "created_at",
    }
)


class ContentVersionService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create_initial_version(
        self,
        *,
        video_project_id: str,
        content_type: ContentType,
        content: str,
        content_format: ContentFormat,
        prompt_version: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        input_hashes: Sequence[str] = (),
    ) -> ContentVersion:
        return self._create_version(
            video_project_id=video_project_id,
            content_type=content_type,
            content=content,
            content_format=content_format,
            parent_version_id=None,
            prompt_version=prompt_version,
            provider=provider,
            model=model,
            input_hashes=input_hashes,
        )

    def create_revision(
        self,
        *,
        parent_version_id: str | None,
        video_project_id: str,
        content_type: ContentType,
        content: str,
        content_format: ContentFormat,
        prompt_version: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        input_hashes: Sequence[str] = (),
    ) -> ContentVersion:
        if parent_version_id is not None:
            parent = self._get_version(parent_version_id)
            self._validate_parent(parent, video_project_id, content_type)
        return self._create_version(
            video_project_id=video_project_id,
            content_type=content_type,
            content=content,
            content_format=content_format,
            parent_version_id=parent_version_id,
            prompt_version=prompt_version,
            provider=provider,
            model=model,
            input_hashes=input_hashes,
        )

    def approve_version(self, content_version_id: str) -> ContentVersion:
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            version = self._get_version(content_version_id)
            self.apply_approval_without_commit(version)
            self.session.commit()
            self.session.refresh(version)
            return version
        except Exception:
            self.session.rollback()
            raise

    def reject_version(self, content_version_id: str) -> ContentVersion:
        version = self._get_version(content_version_id)
        version.status = VersionStatus.REJECTED
        self.session.commit()
        self.session.refresh(version)
        return version

    def mark_superseded(self, content_version_id: str) -> ContentVersion:
        version = self._get_version(content_version_id)
        version.status = VersionStatus.SUPERSEDED
        self.session.commit()
        self.session.refresh(version)
        return version

    def apply_approval_without_commit(self, version: ContentVersion) -> None:
        previous = self.session.scalars(
            select(ContentVersion).where(
                ContentVersion.video_project_id == version.video_project_id,
                ContentVersion.content_type == version.content_type,
                ContentVersion.status == VersionStatus.APPROVED,
                ContentVersion.id != version.id,
            )
        ).all()
        for item in previous:
            item.status = VersionStatus.SUPERSEDED
        version.status = VersionStatus.APPROVED

    def latest_version(
        self, video_project_id: str, content_type: ContentType
    ) -> ContentVersion | None:
        return self.session.scalar(
            select(ContentVersion)
            .where(
                ContentVersion.video_project_id == video_project_id,
                ContentVersion.content_type == content_type,
            )
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )

    def approved_version(
        self, video_project_id: str, content_type: ContentType
    ) -> ContentVersion | None:
        return self.session.scalar(
            select(ContentVersion).where(
                ContentVersion.video_project_id == video_project_id,
                ContentVersion.content_type == content_type,
                ContentVersion.status == VersionStatus.APPROVED,
            )
        )

    def version_history(
        self, video_project_id: str, content_type: ContentType
    ) -> list[ContentVersion]:
        return list(
            self.session.scalars(
                select(ContentVersion)
                .where(
                    ContentVersion.video_project_id == video_project_id,
                    ContentVersion.content_type == content_type,
                )
                .order_by(ContentVersion.version_number.asc())
            ).all()
        )

    def verify_immutable_fields(
        self,
        original: ContentVersion,
        candidate: ContentVersion,
    ) -> None:
        for field in IMMUTABLE_CONTENT_VERSION_FIELDS:
            if inspect(candidate).attrs[field].history.has_changes():
                raise ContentVersionError(f"Immutable content-version field changed: {field}")
            if getattr(original, field) != getattr(candidate, field):
                raise ContentVersionError(f"Immutable content-version field changed: {field}")

    def _create_version(
        self,
        *,
        video_project_id: str,
        content_type: ContentType,
        content: str,
        content_format: ContentFormat,
        parent_version_id: str | None,
        prompt_version: str | None,
        provider: str | None,
        model: str | None,
        input_hashes: Sequence[str],
    ) -> ContentVersion:
        self.session.execute(text("BEGIN IMMEDIATE"))
        try:
            next_number = (
                self.session.scalar(
                    select(func.max(ContentVersion.version_number)).where(
                        ContentVersion.video_project_id == video_project_id,
                        ContentVersion.content_type == content_type,
                    )
                )
                or 0
            ) + 1
            version = ContentVersion(
                video_project_id=video_project_id,
                content_type=content_type,
                version_number=next_number,
                parent_version_id=parent_version_id,
                content=content,
                content_format=content_format,
                prompt_version=prompt_version,
                provider=provider,
                model=model,
                input_hashes=list(input_hashes),
                status=VersionStatus.DRAFT,
                content_hash=hash_content_version(content, content_format.value, input_hashes),
            )
            self.session.add(version)
            self.session.commit()
            self.session.refresh(version)
            return version
        except IntegrityError as exc:
            self.session.rollback()
            raise ContentVersionError("Could not create a unique content version.") from exc

    def _validate_parent(
        self,
        parent: ContentVersion,
        video_project_id: str,
        content_type: ContentType,
    ) -> None:
        if parent.video_project_id != video_project_id:
            raise ContentVersionError("Parent version must belong to the same project.")
        if parent.content_type != content_type:
            raise ContentVersionError("Parent version must have the same content type.")

    def _get_version(self, content_version_id: str) -> ContentVersion:
        version = self.session.get(ContentVersion, content_version_id)
        if version is None:
            raise ContentVersionError(f"Content version not found: {content_version_id}")
        return version
