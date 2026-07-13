"""Isolated Chatterbox worker executed by a separately managed Python environment."""

from __future__ import annotations

import argparse
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--health", action="store_true")
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        import torch  # type: ignore[import-not-found]
        import torchaudio  # type: ignore[import-not-found]
        from chatterbox.mtl_tts import (  # type: ignore[import-not-found]
            ChatterboxMultilingualTTS,
        )
    except (ImportError, OSError, PackageNotFoundError):
        return 3

    if args.health:
        try:
            package_version = version("chatterbox-tts")
        except PackageNotFoundError:
            return 3
        print(
            json.dumps(
                {
                    "chatterbox_version": package_version,
                    "cuda_available": torch.cuda.is_available(),
                }
            )
        )
        return 0
    if args.request is None or args.output is None:
        return 2
    try:
        payload = json.loads(args.request.read_text(encoding="utf-8"))
        model_path = Path(str(payload["model_path"]))
        reference_value = payload.get("reference_audio_path")
        reference_path = Path(str(reference_value)) if reference_value else None
        device = str(payload["device"])
        if device == "cuda" and not torch.cuda.is_available():
            return 3
        torch.manual_seed(int(payload["seed"]))
        if device == "cuda":
            torch.cuda.manual_seed_all(int(payload["seed"]))
        model = ChatterboxMultilingualTTS.from_local(
            model_path,
            device=device,
            t3_model="v3",
        )
        wav = model.generate(
            str(payload["text"]),
            language_id=str(payload["language"]),
            audio_prompt_path=str(reference_path) if reference_path is not None else None,
            exaggeration=float(payload["exaggeration"]),
            cfg_weight=float(payload["cfg_weight"]),
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        torchaudio.save(str(args.output), wav.cpu(), model.sr)
    except (AssertionError, KeyError, OSError, TypeError, ValueError):
        return 2
    except RuntimeError:
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
