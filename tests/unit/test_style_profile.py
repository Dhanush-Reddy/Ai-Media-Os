import pytest
from pydantic import ValidationError

from ai_media_os.application.style_profiles import (
    REFERENCE_MINIMAL_CHARACTER_MOTION_PROFILE,
    REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
    reference_style_profile_hash,
)
from ai_media_os.schemas.style_profile import TimingRange


def test_reference_motion_profile_is_strict_and_stably_hashed() -> None:
    profile = REFERENCE_MINIMAL_CHARACTER_MOTION_PROFILE

    assert profile.profile_name == REFERENCE_MINIMAL_CHARACTER_MOTION_V1
    assert profile.format.target_resolution == "1080x1920"
    assert profile.timing_rules_seconds.semantic_visual_beat.maximum_seconds == 2.0
    assert profile.style.max_primary_subjects == 2
    assert len(reference_style_profile_hash()) == 64

    payload = profile.model_dump(mode="json") | {"unknown": True}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        profile.model_validate(payload)


def test_style_profile_timing_ranges_reject_inverted_values() -> None:
    with pytest.raises(ValidationError, match="maximum must be greater"):
        TimingRange(minimum_seconds=2.0, maximum_seconds=0.8)
