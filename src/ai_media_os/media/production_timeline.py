"""Deterministic production timeline presets, subtitles, and quality checks."""

import re
from dataclasses import dataclass
from pathlib import Path
from textwrap import wrap

from ai_media_os.schemas.production_timeline import (
    MotionPreset,
    ProductionTimelineDocument,
    SubtitleCue,
    SubtitleStyle,
    TimelineLayerType,
    TransitionPreset,
)

MOTION_PARAMETERS: dict[MotionPreset, dict[str, float | str]] = {
    MotionPreset.STATIC: {"zoom_start": 1.0, "zoom_end": 1.0, "axis": "none"},
    MotionPreset.SLOW_ZOOM_IN: {"zoom_start": 1.0, "zoom_end": 1.08, "axis": "center"},
    MotionPreset.SLOW_ZOOM_OUT: {"zoom_start": 1.08, "zoom_end": 1.0, "axis": "center"},
    MotionPreset.PAN_LEFT: {"zoom_start": 1.08, "zoom_end": 1.08, "axis": "left"},
    MotionPreset.PAN_RIGHT: {"zoom_start": 1.08, "zoom_end": 1.08, "axis": "right"},
    MotionPreset.PAN_UP: {"zoom_start": 1.08, "zoom_end": 1.08, "axis": "up"},
    MotionPreset.PAN_DOWN: {"zoom_start": 1.08, "zoom_end": 1.08, "axis": "down"},
    MotionPreset.KEN_BURNS_LEFT_TO_RIGHT: {
        "zoom_start": 1.06,
        "zoom_end": 1.12,
        "axis": "right",
    },
    MotionPreset.KEN_BURNS_RIGHT_TO_LEFT: {
        "zoom_start": 1.06,
        "zoom_end": 1.12,
        "axis": "left",
    },
    MotionPreset.SUBTLE_FLOAT: {"zoom_start": 1.03, "zoom_end": 1.05, "axis": "up"},
    MotionPreset.PARALLAX_PUSH: {"zoom_start": 1.0, "zoom_end": 1.14, "axis": "center"},
}

TRANSITION_PARAMETERS: dict[TransitionPreset, dict[str, str | bool]] = {
    TransitionPreset.CUT: {"video": "cut", "audio_crossfade": False},
    TransitionPreset.CROSSFADE: {"video": "fade", "audio_crossfade": True},
    TransitionPreset.FADE_TO_BLACK: {"video": "fadeblack", "audio_crossfade": True},
    TransitionPreset.SLIDE_LEFT: {"video": "slideleft", "audio_crossfade": True},
    TransitionPreset.SLIDE_RIGHT: {"video": "slideright", "audio_crossfade": True},
    TransitionPreset.ZOOM_BLUR: {"video": "zoomin", "audio_crossfade": True},
    TransitionPreset.WHIP_LEFT: {"video": "wipeleft", "audio_crossfade": True},
    TransitionPreset.WHIP_RIGHT: {"video": "wiperight", "audio_crossfade": True},
}


@dataclass(frozen=True)
class TimelineQualityFinding:
    status: str
    code: str
    message: str


def display_copy_from_description(description: str) -> str | None:
    """Extract display copy without feeding it to an image model."""

    normalized = " ".join(description.split())
    marker_patterns = (
        r"\bheadline:\s*([^;]+)",
        r"^Kinetic text sequence:\s*(.+)$",
        r"^Four kinetic checklist items appear:\s*(.+)$",
        r"^Editorial qualification card:\s*(.+)$",
    )
    for pattern in marker_patterns:
        match = re.search(pattern, normalized, flags=re.IGNORECASE)
        if match:
            return _format_display_copy(match.group(1))

    contrast = re.match(r"^Kinetic contrast:\s*(.+)$", normalized, flags=re.IGNORECASE)
    if contrast:
        phrases = re.findall(r"\b[A-Z][A-Z ]{2,}\b", contrast.group(1))
        cleaned = [" ".join(phrase.split()) for phrase in phrases if phrase.strip()]
        return "\n".join(cleaned) or None
    return None


def split_subtitle_text(text: str, *, max_characters: int = 42) -> list[str]:
    normalized = " ".join(text.split())
    if not normalized:
        return []
    lines = wrap(
        normalized,
        width=max_characters,
        break_long_words=False,
        break_on_hyphens=False,
    )
    if len(lines) <= 2:
        return ["\n".join(lines)]
    chunks: list[str] = []
    for index in range(0, len(lines), 2):
        chunks.append("\n".join(lines[index : index + 2]))
    return chunks


def scene_subtitle_cues(
    text: str, duration_seconds: float, style: SubtitleStyle
) -> list[SubtitleCue]:
    chunks = split_subtitle_text(text, max_characters=style.max_characters_per_line)
    if not chunks:
        return []
    total_characters = sum(len(chunk.replace("\n", "")) for chunk in chunks)
    cursor = 0.0
    cues: list[SubtitleCue] = []
    for index, chunk in enumerate(chunks):
        weight = len(chunk.replace("\n", "")) / max(total_characters, 1)
        end = duration_seconds if index == len(chunks) - 1 else cursor + duration_seconds * weight
        cues.append(
            SubtitleCue(start_seconds=round(cursor, 3), end_seconds=round(end, 3), text=chunk)
        )
        cursor = end
    return cues


def render_srt(timeline: ProductionTimelineDocument) -> str:
    rows: list[str] = []
    index = 1
    for scene in timeline.scenes:
        for cue in scene.subtitle_cues:
            rows.extend(
                [
                    str(index),
                    f"{_srt_time(scene.start_seconds + cue.start_seconds)} --> "
                    f"{_srt_time(scene.start_seconds + cue.end_seconds)}",
                    cue.text,
                    "",
                ]
            )
            index += 1
    return "\n".join(rows)


def render_ass(timeline: ProductionTimelineDocument) -> str:
    style = timeline.subtitle_style
    primary = _ass_color(style.primary_color)
    outline = _ass_color(style.outline_color)
    header = (
        "[Script Info]\nScriptType: v4.00+\n"
        f"PlayResX: {timeline.width}\nPlayResY: {timeline.height}\nWrapStyle: 0\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, Bold, Italic, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV\n"
        f"Style: Default,{style.font_family},{style.font_size},{primary},{outline},-1,0,1,"
        f"{style.outline_width},{style.shadow},2,80,80,{style.bottom_margin}\n"
        f"Style: Headline,{style.font_family},72,{primary},{outline},-1,0,1,"
        "4,2,8,100,100,70\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Text\n"
    )
    events: list[str] = []
    for scene in timeline.scenes:
        for layer in scene.layers:
            if (
                layer.layer_type
                not in {
                    TimelineLayerType.HEADLINE,
                    TimelineLayerType.SUPPORTING_TEXT,
                    TimelineLayerType.BRANDING,
                }
                or not layer.text
            ):
                continue
            text = _ass_text(layer.text)
            x = round((layer.x + layer.width / 2) * timeline.width)
            y = round(layer.y * timeline.height)
            font_size = layer.font_size or 72
            override = rf"{{\an8\pos({x},{y})\fs{font_size}\fad(220,220)}}"
            events.append(
                f"Dialogue: {layer.z_index},{_ass_time(scene.start_seconds + layer.start_seconds)},"
                f"{_ass_time(scene.start_seconds + layer.end_seconds)},Headline,{override}{text}"
            )
        for cue in scene.subtitle_cues:
            text = _ass_text(cue.text)
            events.append(
                f"Dialogue: 0,{_ass_time(scene.start_seconds + cue.start_seconds)},"
                f"{_ass_time(scene.start_seconds + cue.end_seconds)},Default,{text}"
            )
    return header + "\n".join(events) + "\n"


def write_subtitles_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8", newline="\n")
    temporary.replace(path)


def validate_production_timeline(
    timeline: ProductionTimelineDocument,
) -> list[TimelineQualityFinding]:
    findings: list[TimelineQualityFinding] = []
    asset_usage: dict[str, int] = {}
    for scene in timeline.scenes:
        visual_layers = [layer for layer in scene.layers if layer.asset_id]
        if not visual_layers:
            findings.append(
                TimelineQualityFinding(
                    "BLOCK", "missing_visual", f"Scene {scene.order} has no visual asset."
                )
            )
        for layer in visual_layers:
            if layer.asset_id:
                asset_usage[layer.asset_id] = asset_usage.get(layer.asset_id, 0) + 1
        if scene.duration_seconds > 10 and all(
            layer.motion == MotionPreset.STATIC for layer in scene.layers
        ):
            findings.append(
                TimelineQualityFinding(
                    "WARN",
                    "static_scene",
                    f"Scene {scene.order} is static for more than 10 seconds.",
                )
            )
        if not scene.subtitle_cues:
            findings.append(
                TimelineQualityFinding(
                    "WARN", "missing_subtitles", f"Scene {scene.order} has no subtitles."
                )
            )
        for cue in scene.subtitle_cues:
            if any(
                len(line) > timeline.subtitle_style.max_characters_per_line
                for line in cue.text.splitlines()
            ):
                findings.append(
                    TimelineQualityFinding(
                        "BLOCK",
                        "subtitle_overflow",
                        f"Scene {scene.order} subtitle exceeds safe width.",
                    )
                )
            if len(cue.text.splitlines()) > timeline.subtitle_style.max_lines:
                findings.append(
                    TimelineQualityFinding(
                        "BLOCK",
                        "subtitle_lines",
                        f"Scene {scene.order} subtitle exceeds line limit.",
                    )
                )
    repeated = [asset_id for asset_id, count in asset_usage.items() if count > 3]
    if repeated:
        findings.append(
            TimelineQualityFinding(
                "WARN", "repeated_visual", "A visual asset is used in more than three scenes."
            )
        )
    if timeline.audio_mix.music_asset_id and not timeline.audio_mix.music_hash:
        findings.append(
            TimelineQualityFinding(
                "BLOCK", "music_hash", "Selected music is missing its content hash."
            )
        )
    if not findings:
        findings.append(
            TimelineQualityFinding(
                "PASS", "timeline_valid", "Timeline passed deterministic production checks."
            )
        )
    return findings


def _srt_time(seconds: float) -> str:
    milliseconds = round(seconds * 1000)
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"


def _ass_time(seconds: float) -> str:
    centiseconds = round(seconds * 100)
    hours, remainder = divmod(centiseconds, 360_000)
    minutes, remainder = divmod(remainder, 6_000)
    whole_seconds, centis = divmod(remainder, 100)
    return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{centis:02d}"


def _ass_color(color: str) -> str:
    red, green, blue = color[1:3], color[3:5], color[5:7]
    return f"&H00{blue}{green}{red}"


def _format_display_copy(value: str) -> str:
    cleaned = value.strip().rstrip(".;")
    return "\n".join(part.strip() for part in cleaned.split("/") if part.strip())


def _ass_text(value: str) -> str:
    return value.replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")
