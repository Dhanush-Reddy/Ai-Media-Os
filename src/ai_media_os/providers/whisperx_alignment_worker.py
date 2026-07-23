"""Isolated WhisperX worker executed by the configured local runtime."""

import argparse
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def _health() -> int:
    try:
        import torch  # type: ignore[import-not-found]
        import whisperx  # type: ignore[import-not-found] # noqa: F401

        runtime_version = version("whisperx")
    except (ImportError, PackageNotFoundError):
        return 2
    print(
        json.dumps(
            {"whisperx_version": runtime_version, "cuda_available": torch.cuda.is_available()}
        )
    )
    return 0


def _align(request_path: Path, output_path: Path) -> int:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    stage = "import_whisperx"
    try:
        import whisperx

        stage = "read_request"
        request = json.loads(request_path.read_text(encoding="utf-8"))
        stage = "configure_ffmpeg"
        ffmpeg_path = Path(request["ffmpeg_path"])
        if not ffmpeg_path.is_file():
            raise OSError("Configured FFmpeg executable is unavailable.")
        os.environ["PATH"] = str(ffmpeg_path.parent) + os.pathsep + os.environ.get("PATH", "")
        stage = "load_audio"
        audio = whisperx.load_audio(request["audio_path"])
        stage = "load_align_model"
        model, metadata = whisperx.load_align_model(
            language_code=request["language"],
            device=request["device"],
            model_name=request["model_path"],
        )
        stage = "align"
        result = whisperx.align(
            [{"text": request["transcript"], "start": 0.0, "end": request["duration_seconds"]}],
            model,
            metadata,
            audio,
            request["device"],
            return_char_alignments=False,
        )
        stage = "write_output"
        output_path.write_text(json.dumps({"words": result["word_segments"]}), encoding="utf-8")
    except (KeyError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(
            json.dumps(
                {
                    "error_type": type(exc).__name__,
                    "message": str(exc)[:1000],
                    "stage": stage,
                }
            ),
            file=sys.stderr,
        )
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.health:
        return _health()
    if args.request is None or args.output is None:
        return 2
    return _align(args.request, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
