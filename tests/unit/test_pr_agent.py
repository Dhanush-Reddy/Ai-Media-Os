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
        "Changes the reviewer policy and needs strict AI review."
    ]


def test_high_path_risk_is_labeled_but_can_be_approved() -> None:
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

    assert combined["decision"] == "approve"
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


def test_failure_note_is_short_and_safe_for_known_failures() -> None:
    module = load_review_module()

    missing_key = module.failure_note(RuntimeError("NVIDIA_API_KEY repository secret is required."))
    http_error = module.failure_note(RuntimeError("NVIDIA API returned HTTP 401: secret body"))
    invalid_json = module.failure_note(
        RuntimeError("NVIDIA response did not contain a JSON object.")
    )

    assert missing_key == "AI review failed: NVIDIA_API_KEY is missing."
    assert http_error == "NVIDIA API returned HTTP 401."
    assert invalid_json == "AI review failed: model response did not contain valid JSON."


def test_validate_simplification_review_rejects_missing_required_fields() -> None:
    module = load_review_module()

    try:
        module.validate_simplification_review({"summary": "Lean already. Ship."})
    except RuntimeError as exc:
        assert "missing required fields" in str(exc)
    else:
        raise AssertionError("validate_simplification_review should fail closed")


def test_render_markdown_includes_senior_simplification_review() -> None:
    module = load_review_module()
    review = {
        "decision": "approve",
        "risk": "low",
        "summary": "Looks safe.",
        "findings": [],
        "tests_to_add": [],
    }
    simplification_review = {
        "summary": "One helper can be removed.",
        "opportunities": [
            {
                "tag": "stdlib",
                "file": "src/example.py",
                "line": 12,
                "current": "manual path join",
                "replacement": "pathlib.Path",
                "why": "uses an installed stdlib abstraction with less code",
                "suggested_change": {
                    "language": "python",
                    "description": "Use pathlib instead of manual string joining.",
                    "code": "path = Path(base_dir) / filename",
                },
            }
        ],
        "net_lines_possible": 8,
    }

    markdown = module.render_markdown(
        review,
        ["src/example.py"],
        simplification_review,
        "https://github.com/DietrichGebert/ponytail",
    )

    assert "Senior simplification review" in markdown
    assert "Ponytail-style over-engineering pass" in markdown
    assert "Suggested change:" in markdown
    assert "```python" in markdown
    assert "path = Path(base_dir) / filename" in markdown
    assert "Net: -8 lines possible." in markdown


def test_render_markdown_includes_finding_code_suggestion() -> None:
    module = load_review_module()
    review = {
        "decision": "block",
        "risk": "high",
        "summary": "Unsafe subprocess call.",
        "findings": [
            {
                "severity": "high",
                "file": "src/example.py",
                "line": 20,
                "title": "Unsafe shell command",
                "explanation": "Shell interpolation can execute unintended input.",
                "recommended_fix": "Pass arguments as a list.",
                "suggested_change": {
                    "language": "python",
                    "description": "Use an argument array.",
                    "code": 'subprocess.run(["git", "status"], check=True)',
                },
            }
        ],
        "tests_to_add": [],
    }

    markdown = module.render_markdown(
        review,
        ["src/example.py"],
        None,
        "https://github.com/DietrichGebert/ponytail",
    )

    assert "Unsafe shell command" in markdown
    assert "Use an argument array." in markdown
    assert 'subprocess.run(["git", "status"], check=True)' in markdown


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
