"""Render the two-character cutout-animation acceptance fixture."""

from __future__ import annotations

import subprocess
from pathlib import Path

from ai_media_os.infrastructure.settings import get_settings
from ai_media_os.providers.video_composition import (
    LocalFFmpegVideoComposer,
    VideoCompositionRequest,
    VideoLayerInput,
    VideoSceneInput,
)
from ai_media_os.utils.hashing import hash_file


def main() -> int:
    repository_root = Path(__file__).resolve().parents[1]
    demo_root = repository_root / "data" / "reports" / "layered-animation-demo"
    asset_root = demo_root / "assets"
    background = asset_root / "data-center-background.png"
    host = asset_root / "host-cutout.png"
    engineer = asset_root / "engineer-cutout.png"
    energy_surge = asset_root / "energy-surge-cutout.png"
    audio = demo_root / "six-second-silence.wav"
    output = demo_root / "layered-two-character-preview.mp4"
    for path in (background, host, engineer, energy_surge):
        if not path.is_file():
            raise SystemExit(f"Missing layered demo asset: {path}")

    settings = get_settings()
    if not audio.is_file():
        completed = subprocess.run(  # noqa: S603
            [
                settings.ffmpeg_path,
                "-y",
                "-f",
                "lavfi",
                "-i",
                "anullsrc=r=48000:cl=stereo",
                "-t",
                "6",
                "-c:a",
                "pcm_s16le",
                str(audio),
            ],
            capture_output=True,
            text=True,
            check=False,
            shell=False,
        )
        if completed.returncode != 0:
            raise SystemExit((completed.stderr or "Could not create demo audio.")[-1000:])

    layers = (
        VideoLayerInput(
            layer_type="background",
            image_path=background,
            image_hash=hash_file(background),
            z_index=0,
            x=0,
            y=0,
            width=1,
            height=1,
            start_seconds=0,
            end_seconds=6,
        ),
        VideoLayerInput(
            layer_type="overlay",
            image_path=energy_surge,
            image_hash=hash_file(energy_surge),
            z_index=5,
            x=0.24,
            y=0.23,
            width=0.52,
            height=0.38,
            start_seconds=2.0,
            end_seconds=5.2,
            opacity=0.82,
            motion_preset="reaction_pop",
            entrance_preset="slide_in_up",
            entrance_duration_seconds=0.35,
        ),
        VideoLayerInput(
            layer_type="character",
            image_path=host,
            image_hash=hash_file(host),
            z_index=10,
            x=0.01,
            y=0.33,
            width=0.56,
            height=0.64,
            start_seconds=0,
            end_seconds=6,
            motion_preset="character_bob",
            entrance_preset="slide_in_left",
            entrance_duration_seconds=0.55,
        ),
        VideoLayerInput(
            layer_type="character",
            image_path=engineer,
            image_hash=hash_file(engineer),
            z_index=20,
            x=0.50,
            y=0.43,
            width=0.48,
            height=0.54,
            start_seconds=1.0,
            end_seconds=6,
            motion_preset="reaction_pop",
            entrance_preset="slide_in_right",
            entrance_duration_seconds=0.50,
        ),
    )
    scene = VideoSceneInput(
        scene_id="layered-animation-demo",
        scene_number=1,
        image_path=background,
        audio_path=audio,
        duration_seconds=6,
        image_hash=hash_file(background),
        audio_hash=hash_file(audio),
        visual_layers=layers,
    )
    result = LocalFFmpegVideoComposer(settings.ffmpeg_path, settings.ffprobe_path).compose(
        VideoCompositionRequest(
            project_id="layered-animation-demo",
            scene_plan_version_id="layered-animation-demo-v1",
            scenes=[scene],
            output_path=output,
            width=1080,
            height=1920,
            fps=30,
            background_color="#101820",
            input_hashes=[layer.image_hash for layer in layers],
        )
    )
    print(result.output_path)
    print(result.output_hash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
