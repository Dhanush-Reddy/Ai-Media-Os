import pytest

from ai_media_os.cli import (
    _resolve_approval_decision,
    _resolve_render_review_status,
    build_parser,
)
from ai_media_os.domain.enums import ApprovalStatus, RenderStatus


def test_cli_parses_approval_listing_and_interactive_review() -> None:
    parser = build_parser()

    listed = parser.parse_args(
        [
            "list-approvals",
            "--project-id",
            "project-1",
            "--type",
            "production_timeline",
            "--status",
            "pending",
        ]
    )
    reviewed = parser.parse_args(["review-approval", "approval-1"])

    assert listed.type == "production_timeline"
    assert listed.status == "pending"
    assert reviewed.decision is None


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        ("1", ApprovalStatus.APPROVED),
        ("2", ApprovalStatus.REJECTED),
        ("3", ApprovalStatus.CHANGES_REQUESTED),
    ],
)
def test_cli_approval_menu_resolves_numbered_choices(
    monkeypatch: pytest.MonkeyPatch,
    choice: str,
    expected: ApprovalStatus,
) -> None:
    monkeypatch.setattr("builtins.input", lambda _prompt: choice)

    assert _resolve_approval_decision(None) == expected


def test_cli_render_review_uses_numbered_menu(monkeypatch: pytest.MonkeyPatch) -> None:
    parser = build_parser()
    parsed = parser.parse_args(["review-render", "render-1"])
    monkeypatch.setattr("builtins.input", lambda _prompt: "1")

    assert parsed.status is None
    assert _resolve_render_review_status(parsed.status) == RenderStatus.APPROVED
