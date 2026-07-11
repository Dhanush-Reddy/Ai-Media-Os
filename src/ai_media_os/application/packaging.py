"""Metadata and thumbnail packaging services for Milestone 8."""

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_media_os.application.approvals import ApprovalError, ApprovalService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.domain.enums import (
    ApprovalType,
    AssetGenerationStatus,
    AssetReviewStatus,
    AssetRole,
    AssetType,
    ContentFormat,
    ContentType,
    LicenseStatus,
    RenderStatus,
    VersionStatus,
)
from ai_media_os.infrastructure.database.base import utc_now
from ai_media_os.infrastructure.database.models import Asset, ContentVersion, Render, Scene
from ai_media_os.infrastructure.settings import AppSettings, get_settings
from ai_media_os.providers.metadata_generation import (
    FakeMetadataGenerationProvider,
    MetadataGenerationProvider,
    MetadataGenerationRequest,
)
from ai_media_os.providers.thumbnail_generation import (
    FakeThumbnailConceptProvider,
    FakeThumbnailImageProvider,
    ManualThumbnailProvider,
    ThumbnailConceptProvider,
    ThumbnailConceptRequest,
    ThumbnailImageProvider,
    ThumbnailImageRequest,
)
from ai_media_os.schemas.thumbnail import ThumbnailConceptDocument
from ai_media_os.schemas.video_metadata import VideoMetadataDocument
from ai_media_os.storage.filesystem import FileStorage, StorageError
from ai_media_os.storage.media_files import MediaFileError, validate_media_signature
from ai_media_os.utils.hashing import hash_file, hash_json


class PackagingError(RuntimeError):
    """Raised when metadata or thumbnail packaging fails."""


@dataclass(frozen=True)
class ThumbnailVerificationResult:
    ok: bool
    asset_id: str
    reason: str | None = None


class MetadataService:
    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        provider: MetadataGenerationProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.versions = ContentVersionService(session)
        self.provider = provider or FakeMetadataGenerationProvider()

    def generate_metadata(
        self,
        video_project_id: str,
        *,
        render_id: str | None = None,
        keyword_hints: list[str] | None = None,
        title_count: int | None = None,
        tag_count: int | None = None,
        job_id: str | None = None,
    ) -> ContentVersion:
        script = self._approved_version(video_project_id, ContentType.SCRIPT)
        scene_plan = self._approved_version(video_project_id, ContentType.SCENE_PLAN)
        render = self._render(video_project_id, render_id)
        scenes = self._scenes(scene_plan.id)
        input_hashes = [
            script.content_hash,
            scene_plan.content_hash,
            render.content_hash if render is not None and render.content_hash else "",
            hash_json(render.metadata_json if render is not None else {}),
            hash_json(keyword_hints or []),
        ]
        request = MetadataGenerationRequest(
            project_id=video_project_id,
            channel_id=script.video_project.channel_id,
            channel_name=script.video_project.channel.name,
            working_title=script.video_project.working_title,
            topic=script.video_project.topic,
            script_version_id=script.id,
            script_content=script.content,
            scene_plan_version_id=scene_plan.id,
            render_id=render.id if render is not None else None,
            target_language=script.video_project.channel.language,
            keyword_hints=keyword_hints or [],
            title_count=title_count or self.settings.metadata_title_count,
            tag_count=tag_count or self.settings.metadata_tag_count,
            input_hashes=input_hashes,
            scenes=[
                (scene.start_seconds or 0.0, scene.narration)
                for scene in sorted(scenes, key=lambda item: item.scene_number)
            ],
        )
        result = self.provider.generate(request)
        return self._store_document(
            video_project_id,
            result.document,
            parent_version_id=None,
            provider=result.provider,
            model=result.model,
            prompt_version=result.prompt_version,
            input_hashes=[*input_hashes, result.metadata["fingerprint"]],
            job_id=job_id,
        )

    def import_metadata(
        self,
        video_project_id: str,
        content: str,
        *,
        parent_version_id: str | None = None,
        job_id: str | None = None,
    ) -> ContentVersion:
        document = VideoMetadataDocument.model_validate_json(content)
        return self._store_document(
            video_project_id,
            document,
            parent_version_id=parent_version_id,
            provider="manual_metadata",
            model="manual-import",
            prompt_version="manual",
            input_hashes=[hash_json(document.model_dump(mode="json"))],
            job_id=job_id,
        )

    def revise_metadata(
        self,
        parent_version_id: str,
        content: str,
        *,
        job_id: str | None = None,
    ) -> ContentVersion:
        parent = self._version(parent_version_id, ContentType.METADATA)
        return self.import_metadata(
            parent.video_project_id,
            content,
            parent_version_id=parent.id,
            job_id=job_id,
        )

    def list_metadata(self, video_project_id: str) -> list[ContentVersion]:
        return self.versions.version_history(video_project_id, ContentType.METADATA)

    def request_metadata_approval(
        self,
        content_version_id: str,
        *,
        job_id: str | None = None,
    ) -> None:
        version = self._version(content_version_id, ContentType.METADATA)
        version.status = VersionStatus.PENDING_APPROVAL
        self.session.commit()
        try:
            ApprovalService(self.session).request_approval(
                video_project_id=version.video_project_id,
                approval_type=ApprovalType.METADATA,
                content_version_id=version.id,
                job_id=job_id,
            )
        except ApprovalError as exc:
            if "pending approval already exists" not in str(exc):
                raise

    def _store_document(
        self,
        video_project_id: str,
        document: VideoMetadataDocument,
        *,
        parent_version_id: str | None,
        provider: str,
        model: str,
        prompt_version: str,
        input_hashes: list[str],
        job_id: str | None,
    ) -> ContentVersion:
        existing = self._matching_version(video_project_id, ContentType.METADATA, input_hashes)
        if existing is not None:
            self.request_metadata_approval(existing.id, job_id=job_id)
            return existing
        content = document.model_dump_json(indent=2)
        version = self.versions.create_revision(
            parent_version_id=parent_version_id,
            video_project_id=video_project_id,
            content_type=ContentType.METADATA,
            content=content,
            content_format=ContentFormat.JSON,
            prompt_version=prompt_version,
            provider=provider,
            model=model,
            input_hashes=input_hashes,
        )
        self.request_metadata_approval(version.id, job_id=job_id)
        self.session.refresh(version)
        return version

    def _matching_version(
        self,
        video_project_id: str,
        content_type: ContentType,
        input_hashes: list[str],
    ) -> ContentVersion | None:
        return self.session.scalar(
            select(ContentVersion)
            .where(
                ContentVersion.video_project_id == video_project_id,
                ContentVersion.content_type == content_type,
                ContentVersion.input_hashes == input_hashes,
            )
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )

    def _approved_version(self, video_project_id: str, content_type: ContentType) -> ContentVersion:
        version = self.versions.approved_version(video_project_id, content_type)
        if version is None:
            raise PackagingError(f"Approved {content_type.value} version is required.")
        return version

    def _version(self, content_version_id: str, content_type: ContentType) -> ContentVersion:
        version = self.session.get(ContentVersion, content_version_id)
        if version is None or version.content_type != content_type:
            raise PackagingError(f"{content_type.value} version not found.")
        return version

    def _render(self, video_project_id: str, render_id: str | None) -> Render | None:
        if render_id is not None:
            render = self.session.get(Render, render_id)
        else:
            render = self.session.scalar(
                select(Render)
                .where(Render.video_project_id == video_project_id)
                .order_by(Render.version_number.desc())
                .limit(1)
            )
        if render is not None and render.video_project_id != video_project_id:
            raise PackagingError("Render belongs to another project.")
        if render is not None and render.status not in {
            RenderStatus.RENDERED,
            RenderStatus.APPROVED,
            RenderStatus.COMPLETED,
        }:
            raise PackagingError("Metadata generation requires a rendered or approved render.")
        return render

    def _scenes(self, scene_plan_version_id: str) -> list[Scene]:
        return list(
            self.session.scalars(
                select(Scene)
                .where(Scene.scene_plan_version_id == scene_plan_version_id)
                .order_by(Scene.scene_number.asc())
            )
        )


class ThumbnailService:
    def __init__(
        self,
        session: Session,
        settings: AppSettings | None = None,
        storage: FileStorage | None = None,
        concept_provider: ThumbnailConceptProvider | None = None,
        image_provider: ThumbnailImageProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.storage = storage or FileStorage(self.settings)
        self.versions = ContentVersionService(session)
        self.concept_provider = concept_provider or FakeThumbnailConceptProvider()
        self.image_provider = image_provider or FakeThumbnailImageProvider()

    def generate_concept(
        self,
        video_project_id: str,
        *,
        metadata_version_id: str | None = None,
    ) -> ContentVersion:
        metadata_version = self._metadata_version(video_project_id, metadata_version_id)
        metadata_document = VideoMetadataDocument.model_validate_json(metadata_version.content)
        input_hashes = [metadata_version.content_hash, hash_json(metadata_document.keywords)]
        request = ThumbnailConceptRequest(
            project_id=video_project_id,
            metadata_version_id=metadata_version.id,
            title=metadata_document.title,
            title_ideas=metadata_document.title_ideas,
            keywords=metadata_document.keywords,
            input_hashes=input_hashes,
        )
        result = self.concept_provider.generate(request)
        hashes = [*input_hashes, result.metadata["fingerprint"]]
        existing = self._matching_version(video_project_id, ContentType.THUMBNAIL_CONCEPT, hashes)
        if existing is not None:
            return existing
        return self.versions.create_initial_version(
            video_project_id=video_project_id,
            content_type=ContentType.THUMBNAIL_CONCEPT,
            content=result.document.model_dump_json(indent=2),
            content_format=ContentFormat.JSON,
            prompt_version=result.prompt_version,
            provider=result.provider,
            model=result.model,
            input_hashes=hashes,
        )

    def generate_thumbnail(
        self,
        video_project_id: str,
        *,
        metadata_version_id: str | None = None,
        concept_version_id: str | None = None,
        width: int | None = None,
        height: int | None = None,
        seed: int = 1,
    ) -> Asset:
        metadata_version = self._metadata_version(video_project_id, metadata_version_id)
        concept_version = self._concept_version(
            video_project_id,
            concept_version_id,
            metadata_version.id,
        )
        concept = ThumbnailConceptDocument.model_validate_json(concept_version.content)
        resolved_width = width or self.settings.thumbnail_default_width
        resolved_height = height or self.settings.thumbnail_default_height
        fingerprint = self._thumbnail_fingerprint(
            video_project_id,
            metadata_version.id,
            concept,
            resolved_width,
            resolved_height,
            seed,
        )
        existing = self._matching_thumbnail(video_project_id, fingerprint)
        if existing is not None and self._verified_file(existing):
            return existing
        asset = self._new_thumbnail_asset(video_project_id)
        destination = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        result = self.image_provider.generate(
            ThumbnailImageRequest(
                project_id=video_project_id,
                metadata_version_id=metadata_version.id,
                concept=concept,
                width=resolved_width,
                height=resolved_height,
                seed=seed,
                input_hashes=[metadata_version.content_hash, concept_version.content_hash],
            )
        )
        output_hash = self.storage.atomic_write(destination, result.data)
        asset.file_path = self.storage.relative_to_data_root(destination)
        asset.mime_type = "image/png"
        asset.provider = result.provider
        asset.model = result.model
        asset.model_version = result.model_version
        asset.prompt_version = result.prompt_version
        asset.prompt = concept.model_dump_json()
        asset.seed = seed
        asset.width = resolved_width
        asset.height = resolved_height
        asset.content_hash = output_hash
        asset.generation_status = AssetGenerationStatus.GENERATED
        asset.review_status = AssetReviewStatus.PENDING_REVIEW
        asset.license_status = LicenseStatus.SAFE
        asset.generation_metadata = result.metadata | {
            "fingerprint": fingerprint,
            "metadata_version_id": metadata_version.id,
            "concept_version_id": concept_version.id,
        }
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def import_thumbnail(
        self,
        video_project_id: str,
        source_path: Path,
        *,
        metadata_version_id: str | None = None,
        concept_version_id: str | None = None,
    ) -> Asset:
        self._validate_source_path(source_path)
        metadata_version = self._metadata_version(video_project_id, metadata_version_id)
        concept_version = self._concept_version(
            video_project_id,
            concept_version_id,
            metadata_version.id,
        )
        asset = self._new_thumbnail_asset(video_project_id)
        destination = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        destination = destination.with_suffix(source_path.suffix.lower())
        try:
            mime_type = validate_media_signature(source_path)
        except MediaFileError as exc:
            raise PackagingError(str(exc)) from exc
        output_hash = self.storage.atomic_write(destination, source_path.read_bytes())
        width, height = _image_dimensions(destination)
        provider = ManualThumbnailProvider()
        asset.file_path = self.storage.relative_to_data_root(destination)
        asset.mime_type = mime_type
        asset.provider = provider.provider_name
        asset.model = provider.model_name
        asset.model_version = provider.model_version
        asset.width = width
        asset.height = height
        asset.content_hash = output_hash
        asset.generation_status = AssetGenerationStatus.IMPORTED
        asset.review_status = AssetReviewStatus.PENDING_REVIEW
        asset.license_status = LicenseStatus.UNKNOWN
        asset.generation_metadata = {
            "manual_import": True,
            "metadata_version_id": metadata_version.id,
            "concept_version_id": concept_version.id,
        }
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def verify_thumbnail_file(self, asset_id: str) -> ThumbnailVerificationResult:
        asset = self._asset(asset_id)
        if asset.asset_type != AssetType.THUMBNAIL:
            return ThumbnailVerificationResult(False, asset_id, "not-thumbnail")
        if not asset.content_hash:
            return ThumbnailVerificationResult(False, asset_id, "missing-hash")
        try:
            path = self.storage.resolve_inside(self.storage.data_root, asset.file_path)
        except StorageError:
            return ThumbnailVerificationResult(False, asset_id, "unsafe-path")
        if path.suffix.lower() not in self.settings.thumbnail_allowed_extensions:
            return ThumbnailVerificationResult(False, asset_id, "unsupported-extension")
        if not path.exists():
            return ThumbnailVerificationResult(False, asset_id, "missing-file")
        if path.stat().st_size <= 0:
            return ThumbnailVerificationResult(False, asset_id, "empty-file")
        if hash_file(path) != asset.content_hash:
            return ThumbnailVerificationResult(False, asset_id, "hash-mismatch")
        return ThumbnailVerificationResult(True, asset_id)

    def review_thumbnail(self, asset_id: str, review_status: AssetReviewStatus) -> Asset:
        asset = self._asset(asset_id)
        if asset.asset_type != AssetType.THUMBNAIL:
            raise PackagingError("Asset is not a thumbnail.")
        asset.review_status = review_status
        if review_status == AssetReviewStatus.APPROVED:
            asset.generation_status = AssetGenerationStatus.APPROVED
        elif review_status == AssetReviewStatus.REJECTED:
            asset.generation_status = AssetGenerationStatus.REJECTED
        asset.updated_at = utc_now()
        self.session.commit()
        self.session.refresh(asset)
        return asset

    def list_thumbnails(self, video_project_id: str) -> list[Asset]:
        return list(
            self.session.scalars(
                select(Asset)
                .where(
                    Asset.video_project_id == video_project_id,
                    Asset.asset_type == AssetType.THUMBNAIL,
                )
                .order_by(Asset.created_at.desc(), Asset.id.asc())
            )
        )

    def latest_thumbnail(self, video_project_id: str) -> Asset | None:
        return self.session.scalar(
            select(Asset)
            .where(
                Asset.video_project_id == video_project_id,
                Asset.asset_type == AssetType.THUMBNAIL,
            )
            .order_by(Asset.created_at.desc())
            .limit(1)
        )

    def _metadata_version(
        self,
        video_project_id: str,
        metadata_version_id: str | None,
    ) -> ContentVersion:
        version = (
            self.session.get(ContentVersion, metadata_version_id)
            if metadata_version_id is not None
            else self.versions.latest_version(video_project_id, ContentType.METADATA)
        )
        if version is None or version.video_project_id != video_project_id:
            raise PackagingError("Metadata version not found for project.")
        if version.content_type != ContentType.METADATA:
            raise PackagingError("Content version is not video metadata.")
        return version

    def _concept_version(
        self,
        video_project_id: str,
        concept_version_id: str | None,
        metadata_version_id: str,
    ) -> ContentVersion:
        if concept_version_id is not None:
            version = self.session.get(ContentVersion, concept_version_id)
        else:
            version = self.session.scalar(
                select(ContentVersion)
                .where(
                    ContentVersion.video_project_id == video_project_id,
                    ContentVersion.content_type == ContentType.THUMBNAIL_CONCEPT,
                )
                .order_by(ContentVersion.version_number.desc())
                .limit(1)
            )
        if version is None:
            version = self.generate_concept(
                video_project_id,
                metadata_version_id=metadata_version_id,
            )
        if version.video_project_id != video_project_id:
            raise PackagingError("Thumbnail concept belongs to another project.")
        if version.content_type != ContentType.THUMBNAIL_CONCEPT:
            raise PackagingError("Content version is not a thumbnail concept.")
        return version

    def _matching_version(
        self,
        video_project_id: str,
        content_type: ContentType,
        input_hashes: list[str],
    ) -> ContentVersion | None:
        return self.session.scalar(
            select(ContentVersion)
            .where(
                ContentVersion.video_project_id == video_project_id,
                ContentVersion.content_type == content_type,
                ContentVersion.input_hashes == input_hashes,
            )
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )

    def _new_thumbnail_asset(self, video_project_id: str) -> Asset:
        next_number = (
            int(
                self.session.scalar(
                    select(func.count())
                    .select_from(Asset)
                    .where(
                        Asset.video_project_id == video_project_id,
                        Asset.asset_type == AssetType.THUMBNAIL,
                    )
                )
                or 0
            )
            + 1
        )
        asset = Asset(
            video_project_id=video_project_id,
            scene_id=None,
            asset_type=AssetType.THUMBNAIL,
            asset_role=AssetRole.THUMBNAIL,
            file_path=(
                Path("projects")
                / video_project_id
                / "thumbnails"
                / f"thumbnail_v{next_number:03d}.png"
            ).as_posix(),
            generation_status=AssetGenerationStatus.PLANNED,
            review_status=AssetReviewStatus.PENDING_REVIEW,
            generation_metadata={},
            license_status=LicenseStatus.UNKNOWN,
        )
        self.session.add(asset)
        self.session.flush()
        return asset

    def _thumbnail_fingerprint(
        self,
        video_project_id: str,
        metadata_version_id: str,
        concept: ThumbnailConceptDocument,
        width: int,
        height: int,
        seed: int,
    ) -> str:
        return hash_json(
            {
                "project_id": video_project_id,
                "metadata_version_id": metadata_version_id,
                "concept": concept.model_dump(mode="json"),
                "width": width,
                "height": height,
                "provider": self.image_provider.provider_name,
                "model": self.image_provider.model_name,
                "model_version": self.image_provider.model_version,
                "seed": seed,
            }
        )

    def _matching_thumbnail(self, video_project_id: str, fingerprint: str) -> Asset | None:
        candidates = self.session.scalars(
            select(Asset)
            .where(
                Asset.video_project_id == video_project_id,
                Asset.asset_type == AssetType.THUMBNAIL,
            )
            .order_by(Asset.created_at.desc())
        )
        return next(
            (
                asset
                for asset in candidates
                if asset.generation_metadata.get("fingerprint") == fingerprint
            ),
            None,
        )

    def _verified_file(self, asset: Asset) -> bool:
        return self.verify_thumbnail_file(asset.id).ok

    def _asset(self, asset_id: str) -> Asset:
        asset = self.session.get(Asset, asset_id)
        if asset is None:
            raise PackagingError(f"Asset not found: {asset_id}")
        return asset

    def _validate_source_path(self, source_path: Path) -> None:
        if ".." in source_path.parts:
            raise PackagingError("Source path traversal is not allowed.")
        if source_path.suffix.lower() not in self.settings.thumbnail_allowed_extensions:
            raise PackagingError(f"Unsupported thumbnail extension: {source_path.suffix}")
        if not source_path.is_file():
            raise PackagingError(f"Thumbnail source file not found: {source_path}")
        if source_path.stat().st_size > self.settings.asset_max_file_bytes:
            raise PackagingError("Thumbnail source file exceeds configured size limit.")


def _image_dimensions(path: Path) -> tuple[int | None, int | None]:
    data = path.read_bytes()[:32]
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    return None, None


def _mime_for_thumbnail(extension: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(extension.lower(), "application/octet-stream")
