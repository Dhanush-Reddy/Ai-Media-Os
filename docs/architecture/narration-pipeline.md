# Narration Pipeline

Narration is generated one scene at a time from persisted scene-plan narration. The approved source
text is never edited. The pipeline stores both original text and effective spoken text.

```text
Approved scene plan -> normalize text -> apply pronunciation profile -> synthesize WAV
-> verify PCM -> normalize and add boundary silence -> re-verify -> atomic storage
-> cache and pending-review asset -> human approval -> render
```

Default pronunciation rules expand `AI`, `API`, and `FFmpeg`; CLI overrides use
`--pronunciation TERM=SPOKEN`. Empty and oversized segments are rejected. Sentence and paragraph
pause settings are persisted in the fingerprint and Piper applies its natural punctuation pacing;
lead and tail silence are added deterministically during audio processing.

Chatterbox generation also fingerprints the local V3 model bundle, speaker-reference WAV,
language, exaggeration, and CFG weight. The isolated worker loads only local files in offline mode.
Reference paths are not persisted or displayed; their hashes are retained for reproducibility and
rights review.

Generated WAV files must be non-empty 16-bit PCM mono at the configured sample rate. Verification
records duration, peak and RMS dBFS, leading/trailing silence, clipped-sample count, channels, sample
rate, and size. Entirely silent, corrupt, wrong-rate, wrong-channel, zero-duration, or oversized
outputs fail before asset finalization. Deterministic processing targets approximately `-16 dBFS`
RMS with a `-1 dBFS` peak ceiling. This is not a standards-compliant integrated LUFS measurement;
pre/post metrics and processing version make that limitation explicit.

Cache fingerprints include provider/version, model, voice, language, effective text, pronunciation
profile and overrides, rate, pitch, gain, pause/silence settings, sample rate, format, normalization,
target loudness, script/scene identity, and narration hash. Missing or corrupt cache files are not
reused. Approved narration cannot be overwritten.

The dashboard serves audio only through the existing ownership-recorded asset ID and safe storage
resolver. It shows the audio player, provider/model, voice/language, duration, sample rate, RMS level,
effective text, quality warnings, verification state, and review controls without exposing model,
temporary, or project filesystem paths.

Render planning always requires approved narration even if pending visual previews are enabled. It
uses narration duration for scene duration and includes ordered narration hashes in the render
fingerprint. Segment number, scene association, start, end, and spoken text provide minimum subtitle
timing metadata; sentence/word alignment is deferred.
