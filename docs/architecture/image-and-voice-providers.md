# Image and Voice Providers

Milestone 6 adds provider-neutral asset generation foundations without real GPU or TTS dependencies.

Implemented capabilities:

- `ImageGenerationProvider` interface with deterministic `FakeImageGenerationProvider`.
- `VoiceGenerationProvider` interface with deterministic `FakeVoiceGenerationProvider`.
- Manual image and audio import with extension, size, missing-file, and traversal validation.
- Per-scene asset planning for one visual and one narration asset per scene.
- Asset records with role, generation status, review status, model metadata, hashes, and generated metadata.
- Cache integration for fake image and fake voice generation.
- Dashboard asset page with safe image previews and audio metadata.
- CLI and queue handlers for planning, generation, import, review, listing, and verification.

Fake image generation produces deterministic local PNG placeholders from prompt, scene, seed, and settings.
Fake voice generation produces deterministic WAV placeholders from narration, voice, language, rate, scene, and seed.

Manual imports copy user-supplied files into project asset folders and store only project-relative paths plus hashes. The dashboard does not expose raw filesystem paths.

Known limitations:

- No real ComfyUI integration.
- No real Kokoro, Piper, Coqui, or other TTS integration.
- No FFmpeg composition, thumbnails, publishing, analytics, Shorts, Telegram, or Content Safety implementation.
- Rights metadata remains basic license status metadata; full rights checks are deferred.

Future integration points:

- Add a ComfyUI adapter behind `ImageGenerationProvider`.
- Add a local TTS adapter behind `VoiceGenerationProvider`.
- Feed approved assets into Milestone 7 timeline and video composition.
