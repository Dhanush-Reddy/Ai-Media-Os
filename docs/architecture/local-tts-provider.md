# Local TTS Provider

Milestone 9C adds optional offline narration through a separately installed Piper executable and
ONNX voice model. Chatterbox Multilingual is now a second, heavier provider for expressive or
speaker-conditioned dialogue. `fake_voice` remains the default, and automated tests do not require
either runtime, model downloads, a GPU, network access, speakers, or other audio hardware.

## Provider Choice

Piper remains the lightweight adapter because it has a small offline subprocess boundary,
predictable WAV output, and low memory requirements. Chatterbox uses the same provider contract but
runs in an isolated Python environment because of its heavier dependency and GPU requirements. See
`chatterbox-multilingual-voice.md`.

Install Piper and a compatible voice model manually, then configure:

```text
AI_MEDIA_OS_VOICE_DEFAULT_PROVIDER=fake_voice
AI_MEDIA_OS_PIPER_EXECUTABLE_PATH=C:\path\to\piper.exe
AI_MEDIA_OS_PIPER_MODEL_PATH=C:\path\to\voice.onnx
AI_MEDIA_OS_PIPER_CONFIG_PATH=C:\path\to\voice.onnx.json
AI_MEDIA_OS_TTS_VOICE_ID=en_US-lessac-medium
AI_MEDIA_OS_TTS_LANGUAGE=en-US
```

The application never downloads or executes a model installer. The adapter validates configured
paths, invokes Piper with an argument list and `shell=False`, passes narration through a managed
temporary input file, writes only
to a managed temporary file, applies a bounded timeout, sanitizes process failures, and removes the
temporary directory after reading the result.

## Commands

```powershell
python -m ai_media_os.cli check-voice-provider --provider piper --model-path C:\models\voice.onnx --voice en_US-lessac-medium
python -m ai_media_os.cli generate-scene-narration --scene-id $SCENE_ID --provider piper --model-path C:\models\voice.onnx --voice en_US-lessac-medium
python -m ai_media_os.cli list-narration-assets --project-id $PROJECT_ID
python -m ai_media_os.cli verify-audio-asset NARRATION_ASSET_ID
python -m ai_media_os.cli preview-narration NARRATION_ASSET_ID
```

Health checks validate the executable with a bounded `--help` call and require an ONNX model,
optional JSON configuration, and voice ID. Generation accepts WAV only and uses the voice model's
native sample rate unless `AI_MEDIA_OS_TTS_SAMPLE_RATE` explicitly requires a particular rate.

## Limitations

Piper supports one configured narrator profile per generation command. Piper pitch is not supported
and produces a warning. Chatterbox adds multilingual speaker conditioning, but the current scene
contract still stores one utterance and one narration asset per scene. True EBU R128 LUFS
measurement, word timestamps, overlapping dialogue, streaming, and cloud TTS are not implemented.
Generated narration remains synthetic, pending human review, and subject to the safety and
publishing gate.
