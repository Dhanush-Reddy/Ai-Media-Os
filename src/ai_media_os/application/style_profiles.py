"""Built-in, validated production style profiles."""

from ai_media_os.schemas.style_profile import (
    REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
    ReferenceMotionStyleProfile,
)
from ai_media_os.utils.hashing import hash_json

__all__ = [
    "REFERENCE_MINIMAL_CHARACTER_MOTION_PROFILE",
    "REFERENCE_MINIMAL_CHARACTER_MOTION_V1",
    "reference_style_profile_hash",
]


def _range(minimum: float, maximum: float) -> dict[str, float]:
    return {"minimum_seconds": minimum, "maximum_seconds": maximum}


REFERENCE_MINIMAL_CHARACTER_MOTION_PROFILE = ReferenceMotionStyleProfile.model_validate(
    {
        "profile_name": REFERENCE_MINIMAL_CHARACTER_MOTION_V1,
        "reference_set": {
            "unique_videos": 2,
            "duplicate_uploads": 3,
            "durations_seconds": [37.143438, 32.242083],
            "source_resolution": "478x850",
            "source_fps": 60,
        },
        "format": {
            "aspect_ratio": "9:16",
            "target_resolution": "1080x1920",
            "target_fps": 30,
            "audio_sample_rate_hz": 48000,
        },
        "style": {
            "category": "2D cutout motion graphics",
            "background": "flat desaturated blue-grey",
            "main_character": (
                "original consistent faceless technical host with a stable silhouette"
            ),
            "caption_style": "white text with thick dark outline, lower center",
            "max_primary_subjects": 2,
        },
        "timing_rules_seconds": {
            "hook_target": _range(0.0, 2.5),
            "full_scene": _range(2.5, 5.0),
            "semantic_visual_beat": _range(0.8, 2.0),
            "micro_animation": _range(0.25, 0.8),
            "icon_pop": _range(0.25, 0.5),
            "pose_transition": _range(0.2, 0.6),
            "caption_phrase": _range(0.7, 1.8),
            "cta": _range(4.0, 6.0),
        },
        "motion_vocabulary": [
            "slow_push_in",
            "slow_pan",
            "short_slide",
            "scale_pop",
            "pose_swap",
            "opacity_fade",
            "background_blur",
            "radial_emphasis",
            "eye_expression_swap",
        ],
        "avoid": [
            "continuous_full_body_animation",
            "unrelated_decorative_motion",
            "random_camera_shake",
            "excessive_particles",
            "new_full_image_for_every_word",
        ],
        "narrative_structure": [
            "immediate_hook",
            "mechanism",
            "personal_consequence",
            "simple_solution",
            "related_content_cta",
        ],
        "analysis_pipeline": [
            "ffprobe_metadata",
            "scene_detection",
            "optical_flow",
            "word_timestamp_transcription",
            "keyframe_visual_semantics",
            "narration_visual_alignment",
            "retention_heuristics",
            "reference_output_comparison",
        ],
        "current_narration": {
            "duration_seconds": 10.42,
            "sample_rate_hz": 24000,
            "channels": 1,
            "peak_dbfs": -1.0004,
            "rms_dbfs": -22.0797,
            "clipping_detected": False,
            "typical_internal_pause_seconds": _range(0.14, 0.3),
            "initial_silence_seconds": 0.178,
            "ending_silence_seconds": 0.46,
        },
        "rights_constraints": [
            "Create an original recurring character; do not copy reference branding or marks.",
            "Use the reference only for timing, composition, and motion-language analysis.",
        ],
    }
)


def reference_style_profile_hash() -> str:
    """Return the stable hash used to invalidate timelines when the preset changes."""

    return hash_json(REFERENCE_MINIMAL_CHARACTER_MOTION_PROFILE.model_dump(mode="json"))
