from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def load_review_module() -> ModuleType:
    module_path = Path("scripts/review_pull_request.py")
    spec = importlib.util.spec_from_file_location("review_pull_request", module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_path_risk_blocks_reviewer_policy_changes() -> None:
    module = load_review_module()
    config: dict[str, Any] = module.load_config()

    risk, notes = module.classify_path_risk(["config/pr-review-rules.json"], config)

    assert risk == "critical"
    assert notes == [
        "config/pr-review-rules.json -> critical: "
        "The reviewer must not approve changes to its own policy."
    ]


def test_high_path_risk_overrides_ai_approval() -> None:
    module = load_review_module()
    config: dict[str, Any] = module.load_config()
    review = {
        "decision": "approve",
        "risk": "low",
        "summary": "Looks safe.",
        "findings": [],
        "tests_to_add": [],
    }

    combined = module.combine_decisions(review, "high", ["workflow changed"], config)

    assert combined["decision"] == "block"
    assert combined["risk"] == "high"
    assert combined["path_risk_notes"] == ["workflow changed"]


def test_extract_json_object_from_nvidia_markdown_response() -> None:
    module = load_review_module()

    parsed = module.extract_json_object(
        """
```json
{
  "decision": "approve",
  "risk": "low",
  "summary": "Looks safe.",
  "findings": [],
  "tests_to_add": []
}
```
"""
    )

    assert parsed["decision"] == "approve"


def test_validate_review_rejects_missing_required_fields() -> None:
    module = load_review_module()

    try:
        module.validate_review({"decision": "approve"})
    except RuntimeError as exc:
        assert "missing required fields" in str(exc)
    else:
        raise AssertionError("validate_review should fail closed on invalid schema")


def test_nvidia_base_url_must_be_https() -> None:
    module = load_review_module()

    assert (
        module.validate_nvidia_base_url("https://integrate.api.nvidia.com/v1/")
        == "https://integrate.api.nvidia.com/v1"
    )

    try:
        module.validate_nvidia_base_url("file:///tmp/review")
    except RuntimeError as exc:
        assert "absolute HTTPS URL" in str(exc)
    else:
        raise AssertionError("NVIDIA base URL validation should reject non-HTTPS URLs")
