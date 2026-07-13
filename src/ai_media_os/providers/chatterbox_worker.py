"""Isolated Chatterbox worker executed by a separately managed Python environment."""

from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
from importlib.metadata import PackageNotFoundError, distribution
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
    _remove_provider_directory_from_import_path()
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
            package = distribution("chatterbox-tts")
            package_version = package.version
        except PackageNotFoundError:
            return 3
        direct_url_text = package.read_text("direct_url.json")
        source_revision = None
        if direct_url_text:
            try:
                direct_url = json.loads(direct_url_text)
                source_revision = direct_url.get("vcs_info", {}).get("commit_id")
            except json.JSONDecodeError:
                source_revision = None
        print(
            json.dumps(
                {
                    "chatterbox_version": package_version,
                    "cuda_available": torch.cuda.is_available(),
                    "source_revision": source_revision,
                    "v3_api_available": (
                        "t3_model"
                        in inspect.signature(ChatterboxMultilingualTTS.from_local).parameters
                    ),
                }
            )
        )
        return 0
    if args.request is None or args.output is None:
        return 2
    try:
        payload = json.loads(args.request.read_text(encoding="utf-8-sig"))
        model_path = Path(str(payload["model_path"]))
        reference_value = payload.get("reference_audio_path")
        reference_path = Path(str(reference_value)) if reference_value else None
        device = str(payload["device"])
        _configure_offline_tokenizer(model_path)
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
        torchaudio.save(
            str(args.output),
            wav.cpu(),
            model.sr,
            encoding="PCM_S",
            bits_per_sample=16,
        )
    except (AssertionError, KeyError, OSError, TypeError, ValueError):
        return 2
    except RuntimeError:
        return 4
    return 0


def _remove_provider_directory_from_import_path() -> None:
    """Prevent the adjacent provider module from shadowing the installed package."""
    provider_directory = Path(__file__).resolve().parent
    sys.path = [entry for entry in sys.path if Path(entry or ".").resolve() != provider_directory]


def _configure_offline_tokenizer(model_path: Path) -> None:
    """Keep upstream tokenizer initialization on explicitly downloaded local files."""
    from chatterbox.models.tokenizers import (  # type: ignore[import-not-found]
        tokenizer as tokenizer_module,
    )

    cangjie_path = model_path / "Cangjie5_TC.json"

    def local_hub_download(*_args: object, **_kwargs: object) -> str:
        if not cangjie_path.is_file():
            raise FileNotFoundError("Local Cangjie mapping is unavailable.")
        return str(cangjie_path)

    def disable_network_segmenter(converter: object) -> None:
        converter.segmenter = None  # type: ignore[attr-defined]

    tokenizer_module.hf_hub_download = local_hub_download
    tokenizer_module.ChineseCangjieConverter._init_segmenter = disable_network_segmenter


if __name__ == "__main__":
    sys.exit(main())
