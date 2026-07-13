"""Provider-neutral video composition interfaces and FFmpeg boundary."""

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ai_media_os.utils.hashing import hash_file

JsonDict = dict[str, Any]


class VideoCompositionError(RuntimeError):
    """Raised when local video composition fails."""


@dataclass(frozen=True)
class VideoSceneInput:
    scene_id: str
    scene_number: int
    image_path: Path
    audio_path: Path
    duration_seconds: float
    image_hash: str
    audio_hash: str
    motion_preset: str = "static"
    transition_preset: str = "cut"
    transition_duration_seconds: float = 0
    subtitle_path: Path | None = None
    subtitle_hash: str | None = None


@dataclass(frozen=True)
class VideoCompositionRequest:
    project_id: str
    scene_plan_version_id: str
    scenes: list[VideoSceneInput]
    output_path: Path
    width: int
    height: int
    fps: int
    background_color: str
    input_hashes: list[str]
    metadata: JsonDict = field(default_factory=dict)


@dataclass(frozen=True)
class VideoCompositionResult:
    output_path: Path
    output_hash: str
    duration_seconds: float
    width: int
    height: int
    fps: int
    provider: str
    provider_version: str
    metadata: JsonDict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


class VideoComposerProvider(Protocol):
    provider_name: str
    provider_version: str

    def compose(self, request: VideoCompositionRequest) -> VideoCompositionResult:
        """Compose a local preview video."""


class LocalFFmpegVideoComposer:
    provider_name = "local_ffmpeg"
    provider_version = "v1"

    def __init__(self, ffmpeg_path: str = "ffmpeg", ffprobe_path: str = "ffprobe") -> None:
        self.ffmpeg_path = ffmpeg_path
        self.ffprobe_path = ffprobe_path

    def is_available(self) -> bool:
        return self._executable(self.ffmpeg_path) is not None

    def compose(self, request: VideoCompositionRequest) -> VideoCompositionResult:
        ffmpeg = self._required_executable(self.ffmpeg_path, "ffmpeg")
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        temp_dir = request.output_path.parent / f".render-{request.output_path.stem}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_output = request.output_path.with_name(f".tmp-{request.output_path.name}")
        segment_paths: list[Path] = []
        try:
            for index, scene in enumerate(request.scenes, start=1):
                segment_path = temp_dir / f"segment_{index:03d}.mp4"
                self._run(
                    [
                        ffmpeg,
                        "-y",
                        "-loop",
                        "1",
                        "-t",
                        f"{scene.duration_seconds:.3f}",
                        "-i",
                        str(scene.image_path),
                        "-i",
                        str(scene.audio_path),
                        "-vf",
                        self._video_filter(request, scene),
                        "-shortest",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "veryfast",
                        "-c:a",
                        "aac",
                        "-movflags",
                        "+faststart",
                        str(segment_path),
                    ]
                )
                segment_paths.append(segment_path)
            concat_file = temp_dir / "segments.txt"
            concat_file.write_text(
                "".join(f"file {self._concat_path(path)}\n" for path in segment_paths),
                encoding="utf-8",
            )
            self._run(
                [
                    ffmpeg,
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-c",
                    "copy",
                    "-movflags",
                    "+faststart",
                    str(temp_output),
                ]
            )
            if not temp_output.exists() or temp_output.stat().st_size <= 0:
                raise VideoCompositionError("FFmpeg did not create a non-empty MP4 output.")
            os.replace(temp_output, request.output_path)
            return VideoCompositionResult(
                output_path=request.output_path,
                output_hash=hash_file(request.output_path),
                duration_seconds=round(sum(scene.duration_seconds for scene in request.scenes), 3),
                width=request.width,
                height=request.height,
                fps=request.fps,
                provider=self.provider_name,
                provider_version=self.provider_version,
                metadata={"scene_count": len(request.scenes)},
            )
        finally:
            if temp_output.exists():
                temp_output.unlink()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def probe_duration(self, path: Path) -> float | None:
        executable = self._executable(self.ffprobe_path)
        if executable is None:
            return None
        completed = subprocess.run(  # noqa: S603
            [
                executable,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            return None
        try:
            return round(float(completed.stdout.strip()), 3)
        except ValueError:
            return None

    def _required_executable(self, value: str, label: str) -> str:
        executable = self._executable(value)
        if executable is None:
            raise VideoCompositionError(
                f"{label} is not available. Install {label} or set "
                f"AI_MEDIA_OS_{label.upper()}_PATH."
            )
        return executable

    def _executable(self, value: str) -> str | None:
        path = Path(value)
        if path.is_absolute() and path.is_file():
            return str(path)
        return shutil.which(value)

    def _concat_path(self, path: Path) -> str:
        escaped = str(path).replace("'", r"'\''")
        return f"'{escaped}'"

    def _video_filter(self, request: VideoCompositionRequest, scene: VideoSceneInput) -> str:
        base = (
            f"scale={request.width}:{request.height}:force_original_aspect_ratio=increase,"
            f"crop={request.width}:{request.height},fps={request.fps}"
        )
        frames = max(1, round(scene.duration_seconds * request.fps))
        motion = {
            "static": "",
            "slow_zoom_in": (
                f",zoompan=z='min(zoom+0.0005,1.08)':d={frames}:"
                f"s={request.width}x{request.height}:fps={request.fps}"
            ),
            "slow_zoom_out": (
                f",zoompan=z='max(1.08-on/{frames}*0.08,1.0)':d={frames}:"
                f"s={request.width}x{request.height}:fps={request.fps}"
            ),
            "pan_left": (
                f",zoompan=z=1.08:x='(iw-iw/zoom)*(1-on/{frames})':d={frames}:"
                f"s={request.width}x{request.height}:fps={request.fps}"
            ),
            "pan_right": (
                f",zoompan=z=1.08:x='(iw-iw/zoom)*on/{frames}':d={frames}:"
                f"s={request.width}x{request.height}:fps={request.fps}"
            ),
        }.get(scene.motion_preset, "")
        filters = base + motion
        if scene.transition_preset != "cut" and scene.transition_duration_seconds > 0:
            fade_out_start = max(0, scene.duration_seconds - scene.transition_duration_seconds)
            filters += (
                f",fade=t=in:st=0:d={scene.transition_duration_seconds:.3f},"
                f"fade=t=out:st={fade_out_start:.3f}:d={scene.transition_duration_seconds:.3f}"
            )
        if scene.subtitle_path is not None:
            subtitle_path = self._filter_path(scene.subtitle_path)
            filters += f",subtitles=filename='{subtitle_path}'"
        return filters + ",format=yuv420p"

    @staticmethod
    def _filter_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")

    def _run(self, args: list[str]) -> None:
        completed = subprocess.run(  # noqa: S603
            args,
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            diagnostic = (completed.stderr or completed.stdout or "FFmpeg failed.").strip()
            raise VideoCompositionError(diagnostic[-1000:])


class FakeVideoComposer:
    provider_name = "fake_video_composer"
    provider_version = "v1"

    def compose(self, request: VideoCompositionRequest) -> VideoCompositionResult:
        request.output_path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + b"fake-mp4"
        request.output_path.write_bytes(payload)
        return VideoCompositionResult(
            output_path=request.output_path,
            output_hash=hash_file(request.output_path),
            duration_seconds=round(sum(scene.duration_seconds for scene in request.scenes), 3),
            width=request.width,
            height=request.height,
            fps=request.fps,
            provider=self.provider_name,
            provider_version=self.provider_version,
            metadata={"fake": True, "scene_count": len(request.scenes)},
        )
