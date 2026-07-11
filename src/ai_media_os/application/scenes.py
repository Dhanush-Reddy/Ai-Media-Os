"""Scene plan generation and persistence."""

import json
import re
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ai_media_os.application.approvals import ApprovalError, ApprovalService
from ai_media_os.application.content_versions import ContentVersionService
from ai_media_os.application.scripts import ScriptPlanningError
from ai_media_os.application.transactions import write_transaction
from ai_media_os.domain.enums import (
    ApprovalStatus,
    ApprovalType,
    ContentFormat,
    ContentType,
    SceneStatus,
    VersionStatus,
    VisualType,
)
from ai_media_os.infrastructure.database.models import Approval, Claim, ContentVersion, Scene
from ai_media_os.providers.text_generation import (
    LocalRuleBasedTextProvider,
    TextGenerationProvider,
    TextGenerationRequest,
)
from ai_media_os.schemas.scene_plan import ScenePlanDocument, ScenePlanItem
from ai_media_os.utils.hashing import hash_json, hash_text


class ScenePlanningError(RuntimeError):
    """Raised when scene planning cannot proceed."""


class ScenePlanService:
    """Create strict JSON scene plans from approved scripts."""

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

    def generate_scene_plan(
        self,
        video_project_id: str,
        *,
        script_version_id: str | None = None,
        job_id: str | None = None,
    ) -> ContentVersion:
        script = self._approved_script(video_project_id, script_version_id)
        claims = self._claims(video_project_id)
        provider_fingerprint = hash_json(
            {
                "provider": self.provider.provider_name,
                "model": self.provider.model_name,
                "model_version": self.provider.model_version,
                "prompt_version": self.provider.prompt_version,
                "settings": {**self.provider.provider_settings, **self.provider_settings},
                "schema_version": "1.0",
                "output_type": "scene_plan",
                "system_prompt_hash": hash_text("scene-plan-json-system-v1"),
            }
        )
        input_hashes = [
            script.content_hash,
            hash_json([{"id": claim.id, "text": claim.claim_text} for claim in claims]),
            provider_fingerprint,
        ]
        existing = self._matching_scene_plan(
            video_project_id, input_hashes, self.provider.provider_name
        )
        if existing is not None:
            self._ensure_pending_approval(existing, job_id)
            return existing

        if isinstance(self.provider, LocalRuleBasedTextProvider):
            document = self._build_scene_document(video_project_id, script, claims)
            prompt_version = "scene-plan-template-v1"
        else:
            document = self._generate_structured_scene_document(video_project_id, script, claims)
            prompt_version = self.provider.prompt_version
        content = document.model_dump_json(indent=2)
        with write_transaction(self.session):
            version = self.versions.create_initial_version(
                video_project_id=video_project_id,
                content_type=ContentType.SCENE_PLAN,
                content=content,
                content_format=ContentFormat.JSON,
                prompt_version=prompt_version,
                provider=self.provider.provider_name,
                model=self.provider.model_name,
                input_hashes=input_hashes,
            )
            self._replace_scenes(version, document)
            version.status = VersionStatus.PENDING_APPROVAL
            self._ensure_pending_approval(version, job_id)
            self.session.flush()
            return version

    def import_scene_plan(
        self,
        video_project_id: str,
        *,
        content: str,
        script_version_id: str,
    ) -> ContentVersion:
        document = ScenePlanDocument.model_validate_json(content)
        if document.video_project_id != video_project_id:
            raise ScenePlanningError("Scene plan project does not match.")
        if document.script_content_version_id != script_version_id:
            raise ScenePlanningError("Scene plan script version does not match.")
        script = self._approved_script(video_project_id, script_version_id)
        input_hashes = [script.content_hash, hash_json(document.model_dump(mode="json"))]
        with write_transaction(self.session):
            version = self.versions.create_initial_version(
                video_project_id=video_project_id,
                content_type=ContentType.SCENE_PLAN,
                content=document.model_dump_json(indent=2),
                content_format=ContentFormat.JSON,
                prompt_version="manual-import",
                provider="manual",
                model="manual",
                input_hashes=input_hashes,
            )
            self._replace_scenes(version, document)
            version.status = VersionStatus.PENDING_APPROVAL
            self._ensure_pending_approval(version, job_id=None)
            self.session.flush()
            return version

    def _generate_structured_scene_document(
        self,
        video_project_id: str,
        script: ContentVersion,
        claims: list[Claim],
    ) -> ScenePlanDocument:
        prompt = json.dumps(
            {
                "video_project_id": video_project_id,
                "script_content_version_id": script.id,
                "script": script.content,
                "claims": [{"id": claim.id, "text": claim.claim_text} for claim in claims],
                "json_schema": ScenePlanDocument.model_json_schema(),
            },
            sort_keys=True,
        )
        try:
            result = self.provider.generate(
                TextGenerationRequest(
                    prompt=prompt,
                    system_prompt=(
                        "Return only JSON matching the supplied scene-plan schema. "
                        "Do not add markdown fences or commentary."
                    ),
                    provider_settings={
                        **self.provider_settings,
                        "json_mode": True,
                        "schema_version": "1.0",
                        "output_type": "scene_plan",
                        "system_prompt_hash": hash_text("scene-plan-json-system-v1"),
                    },
                    timeout_seconds=self.timeout_seconds,
                )
            )
            document = ScenePlanDocument.model_validate_json(result.text)
        except ValidationError as exc:
            raise ScenePlanningError(f"Generated scene plan is invalid: {exc}") from exc
        if document.video_project_id != video_project_id:
            raise ScenePlanningError("Generated scene plan project does not match.")
        if document.script_content_version_id != script.id:
            raise ScenePlanningError("Generated scene plan script version does not match.")
        return document

    def list_scenes(self, scene_plan_version_id: str) -> list[Scene]:
        return list(
            self.session.scalars(
                select(Scene)
                .where(Scene.scene_plan_version_id == scene_plan_version_id)
                .order_by(Scene.scene_number.asc())
            )
        )

    def _build_scene_document(
        self,
        video_project_id: str,
        script: ContentVersion,
        claims: list[Claim],
    ) -> ScenePlanDocument:
        paragraphs = [
            paragraph.strip()
            for paragraph in re.split(r"\n\s*\n", script.content)
            if paragraph.strip() and not paragraph.strip().startswith("#")
        ]
        if not paragraphs:
            raise ScenePlanningError("Script has no plannable narration blocks.")
        selected = paragraphs[:12]
        duration = max(6.0, min(40.0, 480.0 / len(selected)))
        scenes: list[ScenePlanItem] = []
        start = 0.0
        for index, paragraph in enumerate(selected, start=1):
            visual_type = self._visual_type_for(paragraph, index)
            claim_ids = [
                claim.id for claim in claims if _shares_keyword(paragraph, claim.claim_text)
            ][:3]
            scenes.append(
                ScenePlanItem(
                    scene_number=index,
                    start_seconds=round(start, 2),
                    duration_seconds=round(duration, 2),
                    narration=paragraph,
                    visual_type=visual_type,
                    visual_description=self._visual_description(paragraph, visual_type),
                    image_prompt=(
                        self._image_prompt(paragraph)
                        if visual_type in {VisualType.GENERATED_IMAGE, VisualType.DIAGRAM}
                        else None
                    ),
                    negative_prompt="logos, copyrighted characters, unreadable text",
                    camera_motion="slow push-in" if index == 1 else "subtle pan",
                    transition="cut" if index == 1 else "soft dissolve",
                    caption_style="clean lower-third",
                    sound_effect=None,
                    source_claim_ids=claim_ids,
                )
            )
            start += duration
        return ScenePlanDocument(
            video_project_id=video_project_id,
            script_content_version_id=script.id,
            total_duration_seconds=round(start, 2),
            scenes=scenes,
            quality_notes=[
                "Generated locally from script paragraphs.",
                "Use generated or rights-cleared visuals only.",
            ],
        )

    def _replace_scenes(self, version: ContentVersion, document: ScenePlanDocument) -> None:
        self.session.execute(delete(Scene).where(Scene.scene_plan_version_id == version.id))
        for item in document.scenes:
            self.session.add(
                Scene(
                    video_project_id=version.video_project_id,
                    scene_plan_version_id=version.id,
                    scene_number=item.scene_number,
                    start_seconds=item.start_seconds,
                    narration=item.narration,
                    duration_seconds=item.duration_seconds,
                    visual_type=item.visual_type,
                    visual_description=item.visual_description,
                    image_prompt=item.image_prompt,
                    negative_prompt=item.negative_prompt,
                    camera_motion=item.camera_motion,
                    transition=item.transition,
                    caption_style=item.caption_style,
                    sound_effect=item.sound_effect,
                    source_claim_ids=item.source_claim_ids,
                    schema_version=document.schema_version,
                    status=SceneStatus.PLANNED,
                )
            )

    def _ensure_pending_approval(
        self,
        version: ContentVersion,
        job_id: str | None,
    ) -> None:
        if version.status == VersionStatus.APPROVED:
            return
        pending = self.session.scalar(
            select(Approval).where(
                Approval.content_version_id == version.id,
                Approval.approval_type == ApprovalType.SCENE_PLAN,
                Approval.status == ApprovalStatus.PENDING,
            )
        )
        if pending is not None:
            return
        version.status = VersionStatus.PENDING_APPROVAL
        try:
            self.approvals.request_approval(
                video_project_id=version.video_project_id,
                approval_type=ApprovalType.SCENE_PLAN,
                content_version_id=version.id,
                job_id=job_id,
            )
        except ApprovalError as exc:
            if "pending approval already exists" not in str(exc):
                raise

    def _approved_script(
        self,
        video_project_id: str,
        script_version_id: str | None,
    ) -> ContentVersion:
        script = (
            self.session.get(ContentVersion, script_version_id)
            if script_version_id
            else self.versions.approved_version(video_project_id, ContentType.SCRIPT)
        )
        if script is None or script.video_project_id != video_project_id:
            raise ScriptPlanningError("Approved script version not found.")
        if script.content_type != ContentType.SCRIPT:
            raise ScriptPlanningError("Content version is not a script.")
        if script.status != VersionStatus.APPROVED:
            raise ScriptPlanningError("Scene planning requires an approved script.")
        return script

    def _matching_scene_plan(
        self,
        video_project_id: str,
        input_hashes: list[str],
        provider_name: str,
    ) -> ContentVersion | None:
        return self.session.scalar(
            select(ContentVersion)
            .where(
                ContentVersion.video_project_id == video_project_id,
                ContentVersion.content_type == ContentType.SCENE_PLAN,
                ContentVersion.input_hashes == input_hashes,
                ContentVersion.provider == provider_name,
            )
            .order_by(ContentVersion.version_number.desc())
            .limit(1)
        )

    def _claims(self, video_project_id: str) -> list[Claim]:
        return list(
            self.session.scalars(
                select(Claim)
                .where(Claim.video_project_id == video_project_id)
                .order_by(Claim.created_at.asc(), Claim.id.asc())
            )
        )

    def _visual_type_for(self, paragraph: str, index: int) -> VisualType:
        lowered = paragraph.lower()
        if "chart" in lowered or "data" in lowered or "score" in lowered:
            return VisualType.CHART
        if "how" in lowered or "why" in lowered or "system" in lowered:
            return VisualType.DIAGRAM
        if index % 4 == 0:
            return VisualType.TEXT_GRAPHIC
        return VisualType.GENERATED_IMAGE

    def _visual_description(self, paragraph: str, visual_type: VisualType) -> str:
        summary = paragraph.replace("\n", " ")[:180]
        return f"{visual_type.value.replace('_', ' ')} visual for: {summary}"

    def _image_prompt(self, paragraph: str) -> str:
        clean = paragraph.replace("\n", " ")[:240]
        return (
            "Original editorial illustration for an AI & Future YouTube video, "
            f"high clarity, no brands, no copyrighted characters, concept: {clean}"
        )


def parse_scene_plan_content(content: str) -> ScenePlanDocument:
    data = json.loads(content)
    return ScenePlanDocument.model_validate(data)


def _shares_keyword(left: str, right: str) -> bool:
    left_tokens = {token for token in re.findall(r"[A-Za-z0-9]+", left.lower()) if len(token) > 4}
    right_tokens = {token for token in re.findall(r"[A-Za-z0-9]+", right.lower()) if len(token) > 4}
    return bool(left_tokens & right_tokens)
