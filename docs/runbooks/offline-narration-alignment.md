# Offline Narration Timing Commands

Run commands from the repository root in PowerShell.

```powershell
$PYTHON = ".\.venv\Scripts\python.exe"
$ASSET_ID = "3f2f3bac-f0c7-40ea-8ffe-66c67c707db1"
$PROJECT_ID = "e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f"
$SCENE_ID = "1393f90f-a0a8-4420-8711-ca5a6e93f0d9"
```

Do not type angle-bracket placeholders such as `<ASSET_ID>` in PowerShell.

## 1. Test the flow without a speech model

This validates persistence and trigger wiring, not real speech timing.

```powershell
& $PYTHON -m ai_media_os.cli align-narration $ASSET_ID `
  --provider fake `
  --language en `
  --frame-rate 30 `
  --trigger "ai_icon=AI" `
  --trigger "sparkle=brilliant" `
  --trigger "pose_cut=then" `
  --trigger "fall_apart=fall" `
  --trigger "tuesday_card=Tuesday"
```

## 2. Configure the real offline provider

Create the WhisperX environment and obtain its alignment model manually outside this repository.
Do not put model weights in `.venv` or commit them. Example local environment variables:

```powershell
$env:AI_MEDIA_OS_ALIGNMENT_DEFAULT_PROVIDER = "whisperx"
$env:AI_MEDIA_OS_WHISPERX_PYTHON_PATH = "C:\AI-Models\WhisperX\venv\Scripts\python.exe"
$env:AI_MEDIA_OS_WHISPERX_MODEL_PATH = "C:\AI-Models\WhisperX\models\wav2vec2-en"
$env:AI_MEDIA_OS_WHISPERX_DEVICE = "cuda"
$env:AI_MEDIA_OS_WHISPERX_COMPUTE_TYPE = "float16"
$env:AI_MEDIA_OS_WHISPERX_EXPECTED_RUNTIME_VERSION = "3.4.2"
```

The configured runtime version must match the installed package exactly. The model directory must
already contain all required files; the worker runs offline and will fail rather than download.

## 3. Health check and real alignment

```powershell
& $PYTHON -m ai_media_os.cli check-alignment-provider --provider whisperx

& $PYTHON -m ai_media_os.cli align-narration $ASSET_ID `
  --provider whisperx `
  --language en `
  --frame-rate 30 `
  --trigger "ai_icon=AI" `
  --trigger "sparkle=brilliant" `
  --trigger "pose_cut=then" `
  --trigger "fall_apart=fall" `
  --trigger "tuesday_card=Tuesday"
```

Exit code `0` means the timing report is `PASS` and automatically usable. Exit code `2` means the
report was stored but requires attention; inspect its issues instead of using those triggers.

## 4. Inspect results

```powershell
& $PYTHON -m ai_media_os.cli list-narration-alignments --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli show-narration-alignment `
  --project-id $PROJECT_ID `
  --scene-id $SCENE_ID
```

## 5. Generate a new timeline

After a real alignment passes, generate a new timeline using the existing timeline command. The
service embeds the alignment ID, content hash, and verified trigger frames only when they match the
selected approved narration asset.

Do not approve an older pending timeline merely to pick up new timing. Generate a revision, inspect
the trigger frames, render it, and then use the normal timeline and render approval flow.
