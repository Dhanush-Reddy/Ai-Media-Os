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
class AudioReactionCue:
    timestamp_seconds: float
    effect: str


@dataclass(frozen=True)
class VideoLayerInput:
    layer_type: str
    image_path: Path
    image_hash: str
    z_index: int
    x: float
    y: float
    width: float
    height: float
    start_seconds: float
    end_seconds: float
    opacity: float = 1.0
    motion_preset: str = "static"
    entrance_preset: str | None = None
    entrance_duration_seconds: float = 0.35


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
    visual_beat_times_seconds: tuple[float, ...] = ()
    audio_reaction_cues: tuple[AudioReactionCue, ...] = ()
    visual_layers: tuple[VideoLayerInput, ...] = ()


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
    engagement_audio_profile: str | None = None
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
                self._run(self._segment_command(ffmpeg, request, scene, segment_path))
                segment_paths.append(segment_path)
            concat_file = temp_dir / "segments.txt"
            concat_file.write_text(
                "".join(f"file {self._concat_path(path)}\n" for path in segment_paths),
                encoding="utf-8",
            )
            concat_output = (
                temp_dir / "narration-only.mp4" if request.engagement_audio_profile else temp_output
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
                    str(concat_output),
                ]
            )
            if request.engagement_audio_profile:
                supported_profiles = {
                    "procedural_ambient_reveal_v1",
                    "procedural_mellow_pulse_v2",
                    "procedural_semantic_reactions_v3",
                }
                if request.engagement_audio_profile not in supported_profiles:
                    raise VideoCompositionError(
                        f"Unsupported engagement audio profile: {request.engagement_audio_profile}"
                    )
                duration = sum(scene.duration_seconds for scene in request.scenes)
                beat_times = self._global_beat_times(request.scenes)
                reveal_times = self._global_reveal_times(request.scenes)
                reaction_cues = self._global_reaction_cues(request.scenes)
                self._run(
                    self._engagement_audio_command(
                        ffmpeg,
                        concat_output,
                        temp_output,
                        duration,
                        reveal_times,
                        beat_times=beat_times,
                        profile=request.engagement_audio_profile,
                        reaction_cues=reaction_cues,
                    )
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
                metadata={
                    "scene_count": len(request.scenes),
                    "engagement_audio_profile": request.engagement_audio_profile,
                },
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
            "subtle_float": (
                f",zoompan=z='1.03+on/{frames}*0.02':y='(ih-ih/zoom)*(0.55-0.05*on/{frames})':"
                f"d={frames}:s={request.width}x{request.height}:fps={request.fps}"
            ),
            "parallax_push": (
                f",zoompan=z='min(zoom+0.0009,1.14)':d={frames}:"
                f"s={request.width}x{request.height}:fps={request.fps}"
            ),
            "beat_punch": self._beat_punch_filter(request, scene, frames),
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

    def _segment_command(
        self,
        ffmpeg: str,
        request: VideoCompositionRequest,
        scene: VideoSceneInput,
        output_path: Path,
    ) -> list[str]:
        if scene.visual_layers:
            return self._layered_segment_command(ffmpeg, request, scene, output_path)
        return [
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
            str(output_path),
        ]

    def _layered_segment_command(
        self,
        ffmpeg: str,
        request: VideoCompositionRequest,
        scene: VideoSceneInput,
        output_path: Path,
    ) -> list[str]:
        layers = sorted(scene.visual_layers, key=lambda item: item.z_index)
        command = [ffmpeg, "-y"]
        for layer in layers:
            command.extend(
                [
                    "-loop",
                    "1",
                    "-t",
                    f"{scene.duration_seconds:.3f}",
                    "-i",
                    str(layer.image_path),
                ]
            )
        audio_index = len(layers)
        command.extend(["-i", str(scene.audio_path)])
        filters = [
            f"color=c={request.background_color}:s={request.width}x{request.height}:"
            f"r={request.fps}:d={scene.duration_seconds:.3f}[canvas]"
        ]
        previous = "canvas"
        for index, layer in enumerate(layers):
            layer_label = f"layer{index}"
            output_label = f"composite{index}"
            layer_width = max(2, round(layer.width * request.width))
            layer_height = max(2, round(layer.height * request.height))
            if layer.layer_type == "background":
                preparation = (
                    f"[{index}:v]scale={request.width}:{request.height}:"
                    "force_original_aspect_ratio=increase,"
                    f"crop={request.width}:{request.height},format=rgba"
                )
            else:
                preparation = (
                    f"[{index}:v]scale={layer_width}:{layer_height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={layer_width}:{layer_height}:(ow-iw)/2:(oh-ih)/2:color=black@0,"
                    "format=rgba"
                )
            if layer.opacity < 1:
                preparation += f",colorchannelmixer=aa={layer.opacity:.3f}"
            filters.append(f"{preparation}[{layer_label}]")
            x_expression, y_expression = self._layer_position(request, layer)
            enable = f"between(t,{layer.start_seconds:.3f},{layer.end_seconds:.3f})"
            filters.append(
                f"[{previous}][{layer_label}]overlay=x='{x_expression}':y='{y_expression}':"
                f"enable='{enable}':eof_action=pass[{output_label}]"
            )
            previous = output_label
        if scene.subtitle_path is not None:
            subtitle_path = self._filter_path(scene.subtitle_path)
            filters.append(
                f"[{previous}]subtitles=filename='{subtitle_path}',format=yuv420p[video]"
            )
        else:
            filters.append(f"[{previous}]format=yuv420p[video]")
        command.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[video]",
                "-map",
                f"{audio_index}:a:0",
                "-t",
                f"{scene.duration_seconds:.3f}",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        return command

    @staticmethod
    def _layer_position(
        request: VideoCompositionRequest,
        layer: VideoLayerInput,
    ) -> tuple[str, str]:
        base_x = round(layer.x * request.width)
        base_y = round(layer.y * request.height)
        elapsed = f"(t-{layer.start_seconds:.3f})"
        x_expression = str(base_x)
        y_expression = str(base_y)
        if layer.motion_preset == "character_bob":
            y_expression = f"{base_y}+10*sin(2*PI*{elapsed}/1.25)"
        elif layer.motion_preset == "character_bob_alternate":
            y_expression = f"{base_y}+8*sin(2*PI*{elapsed}/1.10+PI)"
        elif layer.motion_preset == "reaction_pop":
            y_expression = f"{base_y}-14*exp(-3*{elapsed})*abs(sin(8*{elapsed}))"
        elif layer.motion_preset == "background_drift":
            x_expression = (
                f"{base_x}-8+16*{elapsed}/max(0.1,{layer.end_seconds - layer.start_seconds:.3f})"
            )
        duration = max(0.05, layer.entrance_duration_seconds)
        if layer.entrance_preset == "slide_in_left":
            x_expression = (
                f"if(lt(t,{layer.start_seconds + duration:.3f}),"
                f"-overlay_w+({base_x}+overlay_w)*{elapsed}/{duration:.3f},{x_expression})"
            )
        elif layer.entrance_preset == "slide_in_right":
            x_expression = (
                f"if(lt(t,{layer.start_seconds + duration:.3f}),"
                f"main_w-(main_w-{base_x})*{elapsed}/{duration:.3f},{x_expression})"
            )
        elif layer.entrance_preset == "slide_in_up":
            y_expression = (
                f"if(lt(t,{layer.start_seconds + duration:.3f}),"
                f"main_h-(main_h-{base_y})*{elapsed}/{duration:.3f},{y_expression})"
            )
        return x_expression, y_expression

    @staticmethod
    def _beat_punch_filter(
        request: VideoCompositionRequest,
        scene: VideoSceneInput,
        frames: int,
    ) -> str:
        beat_frames = [
            min(frames - 1, max(0, round(timestamp * request.fps)))
            for timestamp in scene.visual_beat_times_seconds
        ]
        if not beat_frames:
            beat_frames = [0]
        pulses = "+".join(
            f"{0.065 if index == len(beat_frames) - 1 else 0.028:.3f}*exp(-abs(on-{frame})/6)"
            for index, frame in enumerate(beat_frames)
        )
        return (
            f",zoompan=z='min(1.16,1.02+{pulses})':"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:"
            f"s={request.width}x{request.height}:fps={request.fps}"
        )

    @staticmethod
    def _global_reveal_times(scenes: list[VideoSceneInput]) -> list[float]:
        reveal_times: list[float] = []
        cursor = 0.0
        for scene in scenes:
            if scene.visual_beat_times_seconds:
                reveal_times.append(cursor + scene.visual_beat_times_seconds[-1])
            cursor += scene.duration_seconds
        return reveal_times

    @staticmethod
    def _global_beat_times(scenes: list[VideoSceneInput]) -> list[float]:
        beat_times: list[float] = []
        cursor = 0.0
        for scene in scenes:
            beat_times.extend(
                cursor + timestamp for timestamp in scene.visual_beat_times_seconds[1:]
            )
            cursor += scene.duration_seconds
        return beat_times

    @staticmethod
    def _global_reaction_cues(scenes: list[VideoSceneInput]) -> list[AudioReactionCue]:
        cues: list[AudioReactionCue] = []
        cursor = 0.0
        for scene in scenes:
            cues.extend(
                AudioReactionCue(cursor + cue.timestamp_seconds, cue.effect)
                for cue in scene.audio_reaction_cues
            )
            cursor += scene.duration_seconds
        return cues

    @staticmethod
    def _engagement_audio_source(duration: float, reveal_times: list[float]) -> str:
        # The generated bed is deterministic, local, and cannot introduce licensed material.
        expression = "0.020*sin(2*PI*110*t)+0.012*sin(2*PI*165*t)"
        for reveal_time in reveal_times:
            start = max(0.0, reveal_time)
            expression += (
                f"+0.070*sin(2*PI*660*(t-{start:.3f}))"
                f"*exp(-14*max(0\\,t-{start:.3f}))"
                f"*between(t\\,{start:.3f}\\,{start + 0.240:.3f})"
            )
        return f"aevalsrc=exprs='{expression}':s=48000:d={duration:.3f}"

    @staticmethod
    def _mellow_engagement_audio_source(
        duration: float,
        beat_times: list[float],
        reveal_times: list[float],
    ) -> str:
        breathing = "(0.72+0.18*sin(2*PI*0.125*t))"
        expression = (
            f"{breathing}*("
            "0.030*sin(2*PI*130.813*t)"
            "+0.024*sin(2*PI*164.814*t)"
            "+0.019*sin(2*PI*195.998*t)"
            "+0.014*sin(2*PI*246.942*t))"
        )
        reveal_keys = {round(value, 3) for value in reveal_times}
        for beat_time in beat_times:
            start = max(0.0, beat_time)
            if round(start, 3) in reveal_keys:
                continue
            expression += (
                f"+0.026*sin(2*PI*440*(t-{start:.3f}))"
                f"*exp(-24*max(0\\,t-{start:.3f}))"
                f"*between(t\\,{start:.3f}\\,{start + 0.140:.3f})"
            )
        for reveal_time in reveal_times:
            start = max(0.0, reveal_time)
            decay = f"exp(-10*max(0\\,t-{start:.3f}))"
            window = f"between(t\\,{start:.3f}\\,{start + 0.420:.3f})"
            expression += (
                f"+(0.070*sin(2*PI*659.255*(t-{start:.3f}))"
                f"+0.040*sin(2*PI*987.767*(t-{start:.3f})))*{decay}*{window}"
            )
        return f"aevalsrc=exprs='{expression}':s=48000:d={duration:.3f}"

    @classmethod
    def _semantic_engagement_audio_source(
        cls,
        duration: float,
        reaction_cues: list[AudioReactionCue],
    ) -> str:
        breathing = "(0.72+0.18*sin(2*PI*0.125*t))"
        expression = (
            f"{breathing}*("
            "0.030*sin(2*PI*130.813*t)"
            "+0.024*sin(2*PI*164.814*t)"
            "+0.019*sin(2*PI*195.998*t)"
            "+0.014*sin(2*PI*246.942*t))"
        )
        for cue in reaction_cues:
            expression += cls._reaction_expression(cue)
        return f"aevalsrc=exprs='{expression}':s=48000:d={duration:.3f}"

    @staticmethod
    def _reaction_expression(cue: AudioReactionCue) -> str:
        start = max(0.0, cue.timestamp_seconds)
        elapsed = f"(t-{start:.3f})"
        safe_elapsed = f"max(0\\,t-{start:.3f})"
        effects = {
            "scene_whoosh": (
                0.34,
                f"0.032*sin(2*PI*(120*{elapsed}+260*{elapsed}*{elapsed}))"
                f"*sin(PI*{safe_elapsed}/0.340)",
            ),
            "digital_tick": (
                0.16,
                f"(0.026*sin(2*PI*180*{elapsed})"
                f"+0.016*sin(2*PI*360*{elapsed}))*exp(-26*{safe_elapsed})",
            ),
            "electric_pulse": (
                0.26,
                f"0.042*sin(2*PI*220*{elapsed}+4*sin(2*PI*35*{elapsed}))*exp(-15*{safe_elapsed})",
            ),
            "air_sweep": (
                0.40,
                f"0.034*sin(2*PI*(95*{elapsed}+300*{elapsed}*{elapsed}))"
                f"*sin(PI*{safe_elapsed}/0.400)",
            ),
            "soft_impact": (
                0.28,
                f"(0.050*sin(2*PI*82*{elapsed})"
                f"+0.025*sin(2*PI*48*{elapsed}))*exp(-12*{safe_elapsed})",
            ),
            "reveal_impact": (
                0.42,
                f"(0.065*sin(2*PI*62*{elapsed})"
                f"+0.032*sin(2*PI*(110*{elapsed}-45*{elapsed}*{elapsed})))"
                f"*exp(-8*{safe_elapsed})",
            ),
            "cta_confirm": (
                0.32,
                f"0.038*sin(2*PI*150*{elapsed})*exp(-18*{safe_elapsed})"
                f"+0.030*sin(2*PI*150*(t-{start + 0.140:.3f}))"
                f"*exp(-18*max(0\\,t-{start + 0.140:.3f}))"
                f"*between(t\\,{start + 0.140:.3f}\\,{start + 0.320:.3f})",
            ),
        }
        duration, effect = effects.get(cue.effect, effects["soft_impact"])
        return f"+({effect})*between(t\\,{start:.3f}\\,{start + duration:.3f})"

    @classmethod
    def _engagement_audio_command(
        cls,
        ffmpeg: str,
        narration_video: Path,
        output_path: Path,
        duration: float,
        reveal_times: list[float],
        *,
        beat_times: list[float] | None = None,
        profile: str = "procedural_ambient_reveal_v1",
        reaction_cues: list[AudioReactionCue] | None = None,
    ) -> list[str]:
        fade_out = max(0.0, duration - 0.8)
        if profile == "procedural_semantic_reactions_v3":
            source = cls._semantic_engagement_audio_source(duration, reaction_cues or [])
            audio_filter = (
                "[0:a]aresample=48000[narration];"
                "[1:a]highpass=f=55,lowpass=f=4200,"
                "aecho=0.8:0.30:45|90:0.10|0.04,volume=0.82,"
                f"afade=t=in:st=0:d=0.6,afade=t=out:st={fade_out:.3f}:d=0.8[music];"
                "[narration][music]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0,alimiter=limit=0.92[aout]"
            )
        elif profile == "procedural_mellow_pulse_v2":
            source = cls._mellow_engagement_audio_source(
                duration,
                beat_times or [],
                reveal_times,
            )
            audio_filter = (
                "[0:a]aresample=48000[narration];"
                "[1:a]highpass=f=70,lowpass=f=5000,"
                "aecho=0.8:0.35:60|120:0.12|0.06,volume=0.82,"
                f"afade=t=in:st=0:d=0.6,afade=t=out:st={fade_out:.3f}:d=0.8[music];"
                "[narration][music]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0,alimiter=limit=0.92[aout]"
            )
        else:
            source = cls._engagement_audio_source(duration, reveal_times)
            audio_filter = (
                f"[1:a]afade=t=in:st=0:d=0.4,"
                f"afade=t=out:st={fade_out:.3f}:d=0.8[engagement];"
                "[0:a][engagement]amix=inputs=2:duration=first:"
                "dropout_transition=0:normalize=0[aout]"
            )
        return [
            ffmpeg,
            "-y",
            "-i",
            str(narration_video),
            "-f",
            "lavfi",
            "-i",
            source,
            "-filter_complex",
            audio_filter,
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

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
