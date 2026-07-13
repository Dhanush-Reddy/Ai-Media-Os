# Chatterbox Multilingual Voice Provider

Chatterbox Multilingual V3 is an optional local `VoiceGenerationProvider` for expressive,
multilingual narration and dialogue. It does not replace Piper. `fake_voice` remains the default,
Piper remains the lightweight production narrator, and Chatterbox is selected explicitly when
speaker conditioning or more expressive delivery is needed.

The core project does not depend on PyTorch or `chatterbox-tts`. Chatterbox runs through a small
worker script using a separately managed Python environment. This isolates its pinned PyTorch,
Transformers, Diffusers, audio, and UI dependencies from AI Media OS.

## Local Installation

Install the runtime outside this repository. The application never installs packages or downloads
model weights automatically.

```powershell
$CHATTERBOX_ROOT = "C:\AI-Models\Chatterbox"
py -3.12 -m venv "$CHATTERBOX_ROOT\.venv"
& "$CHATTERBOX_ROOT\.venv\Scripts\python.exe" -m pip install --upgrade pip
& "$CHATTERBOX_ROOT\.venv\Scripts\python.exe" -m pip install `
  "git+https://github.com/resemble-ai/chatterbox.git@65b18437192794391a0308a8f705b1e33e633948"

& "$CHATTERBOX_ROOT\.venv\Scripts\python.exe" -m pip install --force-reinstall `
  torch==2.6.0 torchaudio==2.6.0 `
  --index-url https://download.pytorch.org/whl/cu124
```

The second command selects the CUDA build used by the RTX 4050 target. Verify
`torch.cuda.is_available()` before downloading weights; the default PyPI Torch wheel may be
CPU-only on Windows.

Use an explicitly initiated Hugging Face download to create a local V3 model directory. Pin and
record the exact model revision used for production.

```powershell
& "$CHATTERBOX_ROOT\.venv\Scripts\hf.exe" download ResembleAI/chatterbox `
  ve.pt t3_mtl23ls_v3.safetensors s3gen.pt `
  grapheme_mtl_merged_expanded_v1.json conds.pt Cangjie5_TC.json `
  --local-dir "$CHATTERBOX_ROOT\multilingual-v3"
```

Configure `.env`:

```text
AI_MEDIA_OS_CHATTERBOX_PYTHON_PATH=C:\AI-Models\Chatterbox\.venv\Scripts\python.exe
AI_MEDIA_OS_CHATTERBOX_MODEL_PATH=C:\AI-Models\Chatterbox\multilingual-v3
AI_MEDIA_OS_CHATTERBOX_REFERENCE_AUDIO_PATH=C:\AI-Models\Chatterbox\voices\narrator.wav
AI_MEDIA_OS_CHATTERBOX_DEVICE=cuda
AI_MEDIA_OS_CHATTERBOX_REQUEST_TIMEOUT_SECONDS=600
AI_MEDIA_OS_CHATTERBOX_EXAGGERATION=0.5
AI_MEDIA_OS_CHATTERBOX_CFG_WEIGHT=0.5
AI_MEDIA_OS_CHATTERBOX_EXPECTED_RUNTIME_VERSION=0.1.7
AI_MEDIA_OS_CHATTERBOX_SOURCE_REVISION=65b18437192794391a0308a8f705b1e33e633948
```

The configured model directory must contain `ve.pt`, `t3_mtl23ls_v3.safetensors`, `s3gen.pt`, and
`grapheme_mtl_merged_expanded_v1.json`. Either `conds.pt` or an approved reference WAV is required.
The worker sets Hugging Face and Transformers offline modes before importing Chatterbox.

## Health And Generation

```powershell
python -m ai_media_os.cli check-voice-provider `
  --provider chatterbox `
  --model-path C:\AI-Models\Chatterbox\multilingual-v3 `
  --reference-audio C:\AI-Models\Chatterbox\voices\narrator.wav

python -m ai_media_os.cli generate-scene-narration `
  --scene-id $SCENE_ID `
  --provider chatterbox `
  --model-path C:\AI-Models\Chatterbox\multilingual-v3 `
  --reference-audio C:\AI-Models\Chatterbox\voices\narrator.wav `
  --voice narrator `
  --language en `
  --exaggeration 0.6 `
  --cfg-weight 0.4
```

The provider supports Arabic, Danish, German, Greek, English, Spanish, Finnish, French, Hebrew,
Hindi, Italian, Japanese, Korean, Malay, Dutch, Norwegian, Polish, Portuguese, Russian, Swedish,
Swahili, Turkish, and Chinese language IDs. Locale forms such as `en-US` normalize to `en`.

Dialogue is generated one persisted scene utterance at a time. Assign a stable `--voice` name and a
reviewed reference WAV to each character. The current scene schema still stores one narration asset
per scene; overlapping speakers and multiple dialogue tracks inside one scene are not implemented.

## Safety, Rights, And Reproducibility

Generated assets start as `PENDING_REVIEW` with `UNKNOWN` license status. Human quality approval,
model provenance review, and reference-voice consent review are separate decisions. A reference
record should establish the speaker's consent, source, permitted purpose, content hash, and review
decision. Do not use a person's voice without authorization.

The cache fingerprint includes the model bundle hash, reference WAV hash, language, speaker ID,
text, seed, exaggeration, CFG weight, and existing narration processing controls. Stored metadata
contains hashes but not the raw reference-audio filesystem path. Chatterbox output is marked
synthetic and watermarked, so AI disclosure remains required.

The upstream code repository currently declares an MIT license, but production review must verify
the exact downloaded model revision, model-card terms, training-data evidence, and reference-audio
rights. A repository license alone is not a commercial-use guarantee.

## Runtime Constraints

Chatterbox Multilingual V3 is a 500M-parameter model. RTX 4050 Laptop performance and VRAM use must
be measured locally; successful loading is not assumed. Queue jobs using this provider must declare
`GPU_HEAVY`, and the configured resource limit keeps them sequential. CPU mode is available for
diagnosis but may be too slow for routine production.

The adapter does not provide streaming, word alignment, overlapping dialogue, automatic speaker
enrollment, speaking-rate control, automatic model installation, cloud inference, or publishing.
