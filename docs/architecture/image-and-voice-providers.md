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

## Local demo flow

For an existing project with an approved scene plan and at least one scene, the current fake providers can generate visible local demo output:

```powershell
$PROJECT_ID = "existing-project-id"
$SCENE_PLAN_VERSION_ID = "approved-scene-plan-version-id"
$SCENE_ID = "existing-scene-id"

python -m ai_media_os.cli plan-scene-assets --project-id $PROJECT_ID --scene-plan-version-id $SCENE_PLAN_VERSION_ID
python -m ai_media_os.cli generate-scene-image --scene-id $SCENE_ID --width 1280 --height 720 --seed 42
python -m ai_media_os.cli generate-scene-voice --scene-id $SCENE_ID --voice-name ai-future-neutral --language en --seed 42
python -m ai_media_os.cli list-assets --project-id $PROJECT_ID
python -m ai_media_os.cli verify-asset-file IMAGE_ASSET_ID
python -m ai_media_os.cli verify-asset-file VOICE_ASSET_ID
python -m ai_media_os.web
```

Open `http://127.0.0.1:8000/projects/{project_id}/assets` to inspect the generated scene assets. These commands do not require real ComfyUI or real TTS. The fake image provider creates a real PNG file. The fake voice provider creates a WAV file that the asset verifier can read and hash.

Known limitations:

- Real image generation is available only through the optional, separately installed local ComfyUI adapter documented in `comfyui-image-provider.md`.
- No real Kokoro, Piper, Coqui, or other TTS integration.
- This provider milestone does not itself compose video or generate thumbnails; later milestones consume its assets for those stages.
- Publishing, analytics, Shorts, and Telegram remain deferred. Milestone 8.5 now evaluates the stored rights metadata through local risk checks.

Future integration points:

- Expand the initial ComfyUI adapter only after the fixed text-to-image workflow is validated locally.
- Add a local TTS adapter behind `VoiceGenerationProvider`.
- Add richer provider provenance while retaining the current rights-check interface.
