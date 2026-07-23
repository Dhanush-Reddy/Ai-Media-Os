"""Offline Ollama vision evaluation for generated scene images."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from ai_media_os.providers.comfyui import ComfyUIOutputError, inspect_image_bytes
from ai_media_os.providers.ollama import (
    JsonDict,
    OllamaHealthResult,
    OllamaMalformedResponseError,
    OllamaMissingModelError,
    OllamaTransport,
    UrllibOllamaTransport,
)
from ai_media_os.schemas.image_evaluation import (
    ImageEvaluationDecision,
    ImageEvaluationReport,
    ImageObjectiveMetrics,
    ImageVisionAssessment,
)
from ai_media_os.utils.hashing import hash_bytes, hash_json, hash_text

RUBRIC_VERSION = "image-evaluation-v1"


class OllamaVisionEvaluationError(RuntimeError):
    """Raised when an offline image evaluation cannot be completed safely."""


@dataclass(frozen=True)
class ImageEvaluationRequest:
    image_path: Path
    scene_context: str
    reference_image_paths: tuple[Path, ...] = ()
    minimum_width: int = 1080
    minimum_height: int = 1920
    target_aspect_ratio: float = 9 / 16
    max_image_bytes: int = 40_000_000
    timeout_seconds: float = 180.0


@dataclass(frozen=True)
class _LoadedImage:
    data: bytes
    mime_type: str
    width: int
    height: int
    content_hash: str


class OllamaVisionImageEvaluator:
    """Evaluate technical suitability and semantic quality without changing asset state."""

    provider_name = "ollama_vision"

    def __init__(
        self,
        *,
        base_url: str,
        model_name: str,
        request_timeout_seconds: float = 180.0,
        transport: OllamaTransport | None = None,
    ) -> None:
        if request_timeout_seconds <= 0:
            raise ValueError("Ollama vision timeout must be positive.")
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name.strip()
        if not self.model_name:
            raise ValueError("Ollama vision model is required.")
        self.request_timeout_seconds = request_timeout_seconds
        self.transport = transport or UrllibOllamaTransport()

    def check_health(self) -> OllamaHealthResult:
        try:
            response = self.transport.request(
                "GET",
                f"{self.base_url}/api/tags",
                payload=None,
                timeout_seconds=self.request_timeout_seconds,
            )
        except RuntimeError as exc:
            return OllamaHealthResult(False, False, self.provider_name, self.model_name, str(exc))
        models = response.get("models")
        if not isinstance(models, list):
            return OllamaHealthResult(
                True,
                False,
                self.provider_name,
                self.model_name,
                "Ollama model list response is malformed.",
            )
        names = {
            str(item.get("name") or item.get("model")) for item in models if isinstance(item, dict)
        }
        available = self.model_name in names
        return OllamaHealthResult(
            True,
            available,
            self.provider_name,
            self.model_name,
            "Ollama vision evaluator is ready."
            if available
            else f"Ollama vision model is not installed: {self.model_name}",
        )

    def evaluate(self, request: ImageEvaluationRequest) -> ImageEvaluationReport:
        if not request.scene_context.strip():
            raise OllamaVisionEvaluationError("Scene context is required for relevance checks.")
        if request.minimum_width <= 0 or request.minimum_height <= 0:
            raise OllamaVisionEvaluationError("Minimum image dimensions must be positive.")
        if request.target_aspect_ratio <= 0:
            raise OllamaVisionEvaluationError("Target aspect ratio must be positive.")
        if len(request.reference_image_paths) > 4:
            raise OllamaVisionEvaluationError("At most four character references are supported.")

        candidate = self._load_image(request.image_path, request.max_image_bytes)
        references = tuple(
            self._load_image(path, request.max_image_bytes)
            for path in request.reference_image_paths
        )
        assessment, reference_comparison_completed = self._assess(candidate, references, request)
        objective = ImageObjectiveMetrics(
            mime_type=candidate.mime_type,
            width=candidate.width,
            height=candidate.height,
            file_size_bytes=len(candidate.data),
            content_hash=candidate.content_hash,
            meets_minimum_dimensions=(
                candidate.width >= request.minimum_width
                and candidate.height >= request.minimum_height
            ),
            matches_target_aspect_ratio=(
                abs(candidate.width / candidate.height - request.target_aspect_ratio) <= 0.02
            ),
        )
        decision, warnings = self._decision(
            objective,
            assessment,
            bool(references),
            reference_comparison_completed,
        )
        fingerprint = hash_json(
            {
                "rubric_version": RUBRIC_VERSION,
                "model": self.model_name,
                "candidate_hash": candidate.content_hash,
                "reference_hashes": [reference.content_hash for reference in references],
                "scene_context_hash": hash_text(request.scene_context),
                "minimum_width": request.minimum_width,
                "minimum_height": request.minimum_height,
                "target_aspect_ratio": request.target_aspect_ratio,
            }
        )
        return ImageEvaluationReport(
            rubric_version=RUBRIC_VERSION,
            decision=decision,
            objective=objective,
            vision=assessment,
            warnings=warnings,
            provider=self.provider_name,
            model=self.model_name,
            fingerprint=fingerprint,
        )

    def _assess(
        self,
        candidate: _LoadedImage,
        references: tuple[_LoadedImage, ...],
        request: ImageEvaluationRequest,
    ) -> tuple[ImageVisionAssessment, bool]:
        prompt = (
            "/no_think\n"
            "Evaluate image 1 for a vertical short video. "
            f"Scene requirement: {request.scene_context[:3000]}\n"
            "Only the candidate image is supplied. Do not infer character consistency; "
            "use null for character_consistency_score. "
            "Score relevance, phone composition, and perceived focal-subject sharpness from "
            "0 to 100. Artifact risk measures defect severity: a clean image MUST score near "
            "0 and severe visible defects MUST score near 100; never use it as a quality score. "
            "Detect malformed anatomy, "
            "duplicates, blur, and pseudo-text. "
            "Return only one complete JSON object with exactly these keys: "
            "scene_relevance_score, composition_score, perceived_sharpness_score, "
            "character_consistency_score, artifact_risk_score, text_artifact_detected, "
            "character_present, strengths, issues, recommendation. Scores must be integers "
            "from 0 to 100; strengths and issues must be arrays of strings."
        )
        user_message: JsonDict = {
            "role": "user",
            "content": prompt,
            "images": [base64.b64encode(candidate.data).decode("ascii")],
        }
        payload: JsonDict = {
            "model": self.model_name,
            "messages": [user_message],
            "stream": False,
            "think": False,
            # Qwen3-VL can exhaust its answer while satisfying a nested JSON schema.
            # Ollama JSON mode plus strict local validation is reliable and still fails closed.
            "format": "json",
            "options": {
                "temperature": 0,
                "seed": 0,
                # A 1080x1920 Qwen3-VL image can exceed 4,096 vision tokens by itself.
                # Keep one-image evaluation but provide enough context for its visual tokens.
                "num_ctx": 8192,
                "num_predict": 768,
            },
        }
        contents = self._request_contents(payload, request)
        try:
            assessment = self._parse_first_assessment(contents)
            return assessment.model_copy(update={"character_consistency_score": None}), (
                not references
            )
        except ValidationError as first_error:
            repair_message = dict(user_message)
            repair_message["content"] = (
                f"{prompt}\nThe prior response failed validation: "
                f"{self._validation_summary(first_error)}. Return JSON only, with no prose, "
                "Markdown, or reasoning."
            )
            repair_payload = payload | {"messages": [repair_message]}
            repaired_contents = self._request_contents(repair_payload, request)
            try:
                assessment = self._parse_first_assessment(repaired_contents)
                return assessment.model_copy(update={"character_consistency_score": None}), (
                    not references
                )
            except ValidationError as second_error:
                raise OllamaVisionEvaluationError(
                    "Ollama vision response failed schema validation after one repair: "
                    f"{self._validation_summary(second_error)}"
                ) from second_error

    def _request_contents(
        self, payload: JsonDict, request: ImageEvaluationRequest
    ) -> tuple[str, ...]:
        response = self.transport.request(
            "POST",
            f"{self.base_url}/api/chat",
            payload=payload,
            timeout_seconds=min(request.timeout_seconds, self.request_timeout_seconds),
        )
        message = response.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str):
            raise OllamaMalformedResponseError("Ollama vision response is missing message content.")
        response_model = response.get("model")
        if isinstance(response_model, str) and response_model != self.model_name:
            raise OllamaMissingModelError("Ollama responded with an unexpected vision model.")
        candidates: list[str] = []
        content = str(message["content"]).strip()
        if content:
            candidates.append(content)
        # Qwen3-VL can route JSON-mode output through this field even when
        # thinking is disabled. Both channels receive identical strict parsing.
        thinking = message.get("thinking")
        if isinstance(thinking, str) and thinking.strip():
            candidates.append(thinking.strip())
        return tuple(candidates) or ("",)

    @classmethod
    def _parse_first_assessment(cls, contents: tuple[str, ...]) -> ImageVisionAssessment:
        last_error: ValidationError | None = None
        for content in contents:
            try:
                return cls._parse_assessment(content)
            except ValidationError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return ImageVisionAssessment.model_validate_json("")

    @classmethod
    def _parse_assessment(cls, content: str) -> ImageVisionAssessment:
        last_error: ValidationError | None = None
        for payload in cls._json_objects(content):
            try:
                return ImageVisionAssessment.model_validate(
                    cls._normalize_assessment_payload(payload)
                )
            except ValidationError as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        return ImageVisionAssessment.model_validate_json(content.strip())

    @staticmethod
    def _json_objects(content: str) -> list[JsonDict]:
        decoder = json.JSONDecoder()
        objects: list[JsonDict] = []
        for index, character in enumerate(content):
            if character != "{":
                continue
            try:
                value, _ = decoder.raw_decode(content[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                objects.append(value)
        return objects

    @staticmethod
    def _normalize_assessment_payload(payload: JsonDict) -> JsonDict:
        aliases: dict[str, tuple[str, ...]] = {
            "scene_relevance_score": (
                "scene_relevance_score",
                "relevance_score",
                "relevance",
            ),
            "composition_score": ("composition_score", "composition"),
            "perceived_sharpness_score": (
                "perceived_sharpness_score",
                "sharpness_score",
                "sharpness",
            ),
            "character_consistency_score": (
                "character_consistency_score",
                "character_consistency",
                "consistency",
            ),
            "artifact_risk_score": ("artifact_risk_score", "artifact_risk"),
            "text_artifact_detected": (
                "text_artifact_detected",
                "text_artifacts",
                "text_artifact",
            ),
            "character_present": ("character_present", "character_presence"),
            "strengths": ("strengths",),
            "issues": ("issues",),
            "recommendation": ("recommendation",),
        }
        normalized: JsonDict = {}
        for canonical, choices in aliases.items():
            for choice in choices:
                if choice in payload:
                    normalized[canonical] = payload[choice]
                    break
        normalized.setdefault("character_consistency_score", None)
        normalized.setdefault("strengths", [])
        normalized.setdefault("issues", [])
        for boolean_field in ("text_artifact_detected", "character_present"):
            value = normalized.get(boolean_field)
            if isinstance(value, (int, float)):
                normalized[boolean_field] = value > 0
        return normalized

    @staticmethod
    def _validation_summary(error: ValidationError) -> str:
        summaries: list[str] = []
        for item in error.errors(include_url=False, include_context=False)[:6]:
            location = ".".join(str(part) for part in item["loc"]) or "response"
            summaries.append(f"{location}: {item['msg']}")
        return "; ".join(summaries)

    @staticmethod
    def _load_image(path: Path, max_bytes: int) -> _LoadedImage:
        try:
            resolved = path.resolve(strict=True)
            if resolved.suffix.casefold() not in {".png", ".jpg", ".jpeg"}:
                raise OllamaVisionEvaluationError("Only PNG and JPEG evaluation is supported.")
            if resolved.stat().st_size > max_bytes:
                raise OllamaVisionEvaluationError("Image exceeds the evaluation size limit.")
            data = resolved.read_bytes()
            mime_type, width, height = inspect_image_bytes(data)
        except (OSError, ComfyUIOutputError) as exc:
            raise OllamaVisionEvaluationError("Image file is missing or invalid.") from exc
        return _LoadedImage(
            data=data,
            mime_type=mime_type,
            width=width,
            height=height,
            content_hash=hash_bytes(data),
        )

    @staticmethod
    def _decision(
        objective: ImageObjectiveMetrics,
        assessment: ImageVisionAssessment,
        has_references: bool,
        reference_comparison_completed: bool,
    ) -> tuple[ImageEvaluationDecision, list[str]]:
        warnings = [
            "Ollama visual scores are advisory and require human review.",
            "Perceived sharpness is not an objective frequency-domain measurement.",
        ]
        consistency = assessment.character_consistency_score
        consistency_required = has_references and assessment.character_present
        if consistency_required and not reference_comparison_completed:
            warnings.append(
                "The local vision model could not compare multiple images; character "
                "consistency requires human review."
            )
        hard_failure = (
            not objective.meets_minimum_dimensions
            or not objective.matches_target_aspect_ratio
            or assessment.scene_relevance_score < 50
            or assessment.artifact_risk_score > 70
            or (consistency_required and consistency is not None and consistency < 50)
        )
        if hard_failure:
            return ImageEvaluationDecision.FAIL, warnings
        needs_review = (
            assessment.scene_relevance_score < 75
            or assessment.composition_score < 70
            or assessment.perceived_sharpness_score < 70
            or assessment.artifact_risk_score > 35
            or assessment.text_artifact_detected
            or (consistency_required and not reference_comparison_completed)
            or (consistency_required and consistency is not None and consistency < 75)
        )
        return (
            ImageEvaluationDecision.WARN if needs_review else ImageEvaluationDecision.PASS,
            warnings,
        )
