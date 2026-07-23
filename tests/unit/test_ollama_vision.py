import json
from pathlib import Path

from ai_media_os.cli import build_parser
from ai_media_os.providers.image_generation import (
    FakeImageGenerationProvider,
    ImageGenerationRequest,
)
from ai_media_os.providers.ollama import JsonDict
from ai_media_os.providers.ollama_vision import (
    ImageEvaluationRequest,
    OllamaVisionImageEvaluator,
)
from ai_media_os.schemas.image_evaluation import ImageEvaluationDecision


class FakeVisionTransport:
    def __init__(
        self,
        assessment: JsonDict,
        contents: list[str] | None = None,
        thinking: str | None = None,
    ) -> None:
        self.assessment = assessment
        self.contents = contents or []
        self.thinking = thinking
        self.calls: list[tuple[str, str, JsonDict | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        payload: JsonDict | None,
        timeout_seconds: float,
    ) -> JsonDict:
        self.calls.append((method, url, payload))
        if method == "GET":
            return {"models": [{"name": "qwen3-vl:4b"}]}
        response_index = sum(call[0] == "POST" for call in self.calls) - 1
        content = (
            self.contents[min(response_index, len(self.contents) - 1)]
            if self.contents
            else json.dumps(self.assessment)
        )
        return {
            "model": "qwen3-vl:4b",
            "message": {
                "role": "assistant",
                "content": content,
                "thinking": self.thinking,
            },
        }


def _assessment(**overrides: object) -> JsonDict:
    payload: JsonDict = {
        "scene_relevance_score": 90,
        "composition_score": 86,
        "perceived_sharpness_score": 88,
        "character_consistency_score": None,
        "artifact_risk_score": 10,
        "text_artifact_detected": False,
        "character_present": True,
        "strengths": ["Clear focal subject"],
        "issues": [],
        "recommendation": "Keep this composition.",
    }
    payload.update(overrides)
    return payload


def _write_fake_image(path: Path, width: int, height: int) -> None:
    result = FakeImageGenerationProvider().generate(
        ImageGenerationRequest(
            prompt="Original recurring analyst explaining an AI processor",
            negative_prompt=None,
            width=width,
            height=height,
            seed=7,
            scene_id="scene-1",
            prompt_version="test-v1",
        )
    )
    path.write_bytes(result.data)


def test_offline_vision_evaluation_sends_one_image_and_defers_consistency(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.png"
    reference = tmp_path / "reference.png"
    _write_fake_image(candidate, 1080, 1920)
    _write_fake_image(reference, 512, 512)
    transport = FakeVisionTransport(_assessment(character_consistency_score=91))
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=transport,
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="The analyst explains a processor architecture.",
            reference_image_paths=(reference,),
        )
    )

    assert report.decision == ImageEvaluationDecision.WARN
    assert report.vision.character_consistency_score is None
    assert report.objective.meets_minimum_dimensions is True
    assert report.objective.matches_target_aspect_ratio is True
    payload = transport.calls[-1][2]
    assert payload is not None
    assert payload["model"] == "qwen3-vl:4b"
    assert payload["format"] == "json"
    assert len(payload["messages"][0]["images"]) == 1
    assert payload["messages"][0]["content"].startswith("/no_think")
    assert payload["think"] is False
    assert payload["options"]["temperature"] == 0
    assert payload["options"]["num_ctx"] == 8192
    assert payload["options"]["num_predict"] == 768


def test_objective_resolution_failure_cannot_be_overridden_by_vision_score(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "small.png"
    _write_fake_image(candidate, 540, 960)
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=FakeVisionTransport(_assessment()),
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="A clear vertical AI explainer scene.",
        )
    )

    assert report.decision == ImageEvaluationDecision.FAIL
    assert report.objective.meets_minimum_dimensions is False


def test_vision_risk_scores_are_advisory_but_can_fail_the_report(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    _write_fake_image(candidate, 1080, 1920)
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=FakeVisionTransport(
            _assessment(scene_relevance_score=35, artifact_risk_score=80)
        ),
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="A processor connected to four software modules.",
        )
    )

    assert report.decision == ImageEvaluationDecision.FAIL
    assert any("advisory" in warning for warning in report.warnings)


def test_object_only_scene_does_not_require_character_consistency(tmp_path: Path) -> None:
    candidate = tmp_path / "object.png"
    reference = tmp_path / "reference.png"
    _write_fake_image(candidate, 1080, 1920)
    _write_fake_image(reference, 512, 512)
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=FakeVisionTransport(
            _assessment(character_present=False, character_consistency_score=None)
        ),
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="Object-only processor insert with no person or character.",
            reference_image_paths=(reference,),
        )
    )

    assert report.decision == ImageEvaluationDecision.PASS


def test_fenced_json_is_accepted_and_invalid_json_gets_one_repair(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    _write_fake_image(candidate, 1080, 1920)
    valid = json.dumps(_assessment())
    fenced_evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=FakeVisionTransport(_assessment(), [f"```json\n{valid}\n```"]),
    )
    repaired_transport = FakeVisionTransport(_assessment(), ["", valid])
    repaired_evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=repaired_transport,
    )
    request = ImageEvaluationRequest(
        image_path=candidate,
        scene_context="A clear vertical AI explainer scene.",
    )

    assert fenced_evaluator.evaluate(request).decision == ImageEvaluationDecision.PASS
    assert repaired_evaluator.evaluate(request).decision == ImageEvaluationDecision.PASS
    post_calls = [call for call in repaired_transport.calls if call[0] == "POST"]
    assert len(post_calls) == 2
    assert post_calls[1][2] is not None
    assert len(post_calls[1][2]["messages"]) == 1


def test_reference_request_never_sends_multiple_images(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "candidate.png"
    reference = tmp_path / "reference.png"
    _write_fake_image(candidate, 1080, 1920)
    _write_fake_image(reference, 512, 512)
    transport = FakeVisionTransport(_assessment(character_consistency_score=99))
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=transport,
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="A recurring analyst explains an AI processor.",
            reference_image_paths=(reference,),
        )
    )

    assert report.decision == ImageEvaluationDecision.WARN
    assert report.vision.character_consistency_score is None
    assert any("consistency requires human review" in item for item in report.warnings)
    post_calls = [call for call in transport.calls if call[0] == "POST"]
    assert len(post_calls) == 1
    assert len(post_calls[-1][2]["messages"][0]["images"]) == 1


def test_json_routed_through_thinking_field_is_strictly_validated(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    _write_fake_image(candidate, 1080, 1920)
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=FakeVisionTransport(
            _assessment(),
            contents=[""],
            thinking=json.dumps(_assessment()),
        ),
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="A crisp AI control-room scene.",
        )
    )

    assert report.decision == ImageEvaluationDecision.PASS


def test_valid_thinking_json_is_used_when_content_is_invalid_prose(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    _write_fake_image(candidate, 1080, 1920)
    transport = FakeVisionTransport(
        _assessment(),
        contents=["I evaluated the image but did not return JSON."],
        thinking=json.dumps(_assessment()),
    )
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=transport,
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="A crisp AI control-room scene.",
        )
    )

    assert report.decision == ImageEvaluationDecision.PASS
    assert len([call for call in transport.calls if call[0] == "POST"]) == 1


def test_embedded_json_and_known_qwen_aliases_are_normalized(tmp_path: Path) -> None:
    candidate = tmp_path / "candidate.png"
    _write_fake_image(candidate, 1080, 1920)
    aliased = {
        "relevance": 92,
        "composition": 88,
        "sharpness": 94,
        "artifact_risk": 4,
        "text_artifacts": 0,
        "character_presence": 100,
        "strengths": ["Clear subject"],
        "issues": [],
        "recommendation": "Use this image.",
    }
    evaluator = OllamaVisionImageEvaluator(
        base_url="http://localhost:11434",
        model_name="qwen3-vl:4b",
        transport=FakeVisionTransport(
            _assessment(),
            contents=[f"Result follows:\n```json\n{json.dumps(aliased)}\n```"],
        ),
    )

    report = evaluator.evaluate(
        ImageEvaluationRequest(
            image_path=candidate,
            scene_context="A crisp AI control-room scene.",
        )
    )

    assert report.decision == ImageEvaluationDecision.PASS
    assert report.vision.scene_relevance_score == 92
    assert report.vision.text_artifact_detected is False
    assert report.vision.character_present is True


def test_image_evaluation_cli_contract() -> None:
    parser = build_parser()
    health = parser.parse_args(["check-image-evaluator", "--model", "qwen3-vl:4b"])
    evaluate = parser.parse_args(
        [
            "evaluate-image",
            "--asset-id",
            "asset-1",
            "--reference-asset-id",
            "reference-1",
            "--reference-project-id",
            "project-1",
            "--minimum-width",
            "2160",
            "--minimum-height",
            "3840",
        ]
    )

    assert health.model == "qwen3-vl:4b"
    assert evaluate.asset_id == "asset-1"
    assert evaluate.reference_asset_id == ["reference-1"]
    assert evaluate.reference_project_id == "project-1"
    assert (evaluate.minimum_width, evaluate.minimum_height) == (2160, 3840)

    project_images = parser.parse_args(
        [
            "generate-project-images",
            "--project-id",
            "project-1",
            "--provider",
            "comfyui",
            "--width",
            "1080",
            "--height",
            "1920",
        ]
    )
    assert project_images.project_id == "project-1"
    assert (project_images.width, project_images.height) == (1080, 1920)

    staged_project_images = parser.parse_args(
        [
            "generate-project-images",
            "--project-id",
            "project-1",
            "--stage-for-review",
            "--reuse-existing",
        ]
    )
    assert staged_project_images.stage_for_review is True
    assert staged_project_images.reuse_existing is True
