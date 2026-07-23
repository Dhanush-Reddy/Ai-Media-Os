# Narration Word Alignment

AI Media OS can force-align an approved narration asset against the approved scene narration and
store the result as an immutable `narration_alignment` content version. The alignment supplies
word-level timestamps and frame-quantized trigger points for production timelines.

The simple short-production launcher intentionally skips this optional step. It distributes caption
cues across each approved narration asset's measured duration and uses those cues for visual beats.
Run `regenerate-short-production.ps1` without `-SkipNarrationAlignment` only when word-level timing
is specifically needed.

## Runtime boundary

The application depends on the provider-neutral `NarrationAlignmentProvider` contract. Two
providers exist:

* `fake` deterministically distributes words over the audio duration for tests. It does not inspect
  speech and must not be treated as production verification.
* `whisperx` runs in a separately managed local Python environment. It uses a local alignment model,
  sets Hugging Face and Transformers offline flags, and never downloads model files itself. The
  application passes the configured FFmpeg executable explicitly because the isolated environment
  does not inherit the application's Python dependencies or tool discovery.

The main application does not depend on PyTorch, WhisperX, or CUDA. The isolated worker exchanges
JSON files with the application and returns typed failures for unavailable runtimes, timeouts, and
malformed output. Worker failures include a bounded structured diagnostic with the failing stage,
exception type, and local error message so production reports remain actionable.

## Verification gate

An alignment is automatically usable only when all checks pass:

* The source narration asset is approved, exists, and matches its recorded SHA-256 hash.
* Aligned words exactly match the persisted scene narration after punctuation normalization.
* Word timestamps are ordered, non-overlapping, and within the WAV duration.
* Every requested trigger word exists at the requested occurrence and appears in trigger order.
* Average and trigger confidence meet configured thresholds.
* The provider, model version, local model bundle hash, transcript, audio hash, trigger settings, and
  frame rate are included in the fingerprint.

`PASS` results may be embedded in a new production timeline automatically. `WARN` and `BLOCK`
results remain stored for diagnosis but do not drive timeline triggers. A newer narration revision
cannot reuse timing from an older narration hash.

## Current limits

Alignment verifies timing and transcript correspondence; it does not judge delivery quality,
emotion, pronunciation, or whether the performance sounds natural. Human listening remains the
final quality check until a separately validated audio-quality model is introduced. WhisperX and
the alignment model must be installed manually outside the repository. The configured model path
must point to the concrete model directory containing `config.json`, not only its parent directory.
