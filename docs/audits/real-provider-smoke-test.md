# Real Provider Smoke Test

## Result

**PASS_WITH_LIMITATIONS**

The real local image, narration, and video providers completed a one-scene pipeline without cloud services or automatic publishing. The publishing gate returned `NEEDS_REVIEW` because explicit license/provenance records are not populated for the ComfyUI and Piper assets. AI disclosure is required.

## Run Details

- Date: 2026-07-12
- Baseline tag: `v0.9.3`
- Baseline commit: `b244d88`
- Asset revision fix: `82b7b5e`
- Project ID: `2d9fb350-3c4a-4d5a-9543-6c6f2e46be90`
- Scene ID: `27ca7ba9-336f-481a-9e71-9c7248ad0a94`
- Scene plan version: `231b0409-24bf-4b5a-8dce-0b94ad5a0946`
- Script version: `0221ce0b-1fe0-4d3b-b0d5-b8f19dee35c1` (approved)
- Text provider: deterministic fake provider for metadata; configured Ollama model `qwen3:8b` was not installed

## Image

- Asset ID: `3f706778-6e5c-46b6-af10-5f156492f9d6`
- Provider: `comfyui`
- Checkpoint: `sd_xl_turbo_1.0_fp16.safetensors`
- Model version: `local-checkpoint`
- Workflow: `text-to-image-v001`
- Workflow hash: `390825846ab623c0600b1d1a4759d8fd530b2f4fe20ccfe95b6f454abc576ca2`
- Settings: 768x432, 2 steps, CFG 1.0, Euler sampler, normal scheduler, seed 20260712
- Path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/images/scene_001/visual_v002.png`
- SHA-256: `46e6a015a2978364c4aea4a8c5fe816f9db600025481bc42f19a5481c1729bbf`
- Generation time: 19.625 seconds
- Review: approved by the user; file verification passed

The prior `visual_v001.png` remained on disk. The generated image is readable, has no watermark or generated text, and remained correctly framed in the final 16:9 render.

## Narration

- Asset ID: `ef5e002e-9637-4e4a-8667-8ad50b1ab899`
- Provider: `piper`
- Voice model: `en_US-lessac-medium.onnx`
- Model version: `local-onnx`
- Path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/audio/scene_001/narration_v002.wav`
- SHA-256: `657a7749aa64c4562110993e3411c43a1e06ef1273f3683b4a57be19ab761e2d`
- Duration: 4.898 seconds
- Format: 22050 Hz, mono WAV
- Post-processing: -16.527 dBFS RMS, -1.0 dBFS peak, zero clipped samples
- Review: approved by the user; file verification passed

The prior `narration_v001.wav` remained on disk. The `AI` pronunciation override used `A I`.

## Render

- Render ID: `be0eccc7-5db1-4281-aedf-a515c8cc90f1`
- Provider: local FFmpeg 8.1.2
- Path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/renders/render_v001.mp4`
- SHA-256: `02bf366ef7188808ad7f319a7fa21cc11412a6ac0c81865c30ae25c04f007f36`
- Recorded duration: 4.898 seconds
- Probed duration: 4.921 seconds
- Video: H.264, 1280x720, 24 FPS
- Audio: AAC, 22050 Hz, mono
- Input hashes: approved `visual_v002.png` and `narration_v002.wav` hashes
- Review: approved by the user; file verification passed

A representative frame was nonblank and correctly fitted. FFprobe confirmed both video and audio streams.

## Packaging

- Metadata version: `cbc4866d-c978-48d0-8388-485f1f03b7b1` (approved)
- Selected title: `Demo: AI Agents Planning Tasks`
- Metadata SHA-256: `9477699d9371b593e6632d98dcd155b95dc9f010a122bed05327b71c72370c76`
- Thumbnail concept version: `e094e6ef-af44-44b7-b96b-52805f433b5d`
- Thumbnail asset: `68e09385-f167-456d-b01d-1cff9f2a7d7c` (approved)
- Thumbnail path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/thumbnails/thumbnail_v001.png`
- Thumbnail SHA-256: `b4e92ce7ee6e6f207abaa135af364a7ebf044d89c63c28e8f3f46c5444ff1c59`
- Thumbnail provider: deterministic `fake_thumbnail`, 1280x720

Metadata safety passed. The thumbnail file verified and its text was reviewed before approval.

## Safety Gate

- Publishing gate: `NEEDS_REVIEW`
- Blocking reasons: none
- Rights summary: 1 `SAFE`, 2 `UNKNOWN`
- Script safety: passed
- Metadata safety: passed
- Thumbnail safety: warning because AI disclosure is required
- Reused-content check: passed
- Human review required: yes
- Publishing: remains manual and was not attempted

AI disclosure reasons:

- Generated script, metadata, or report versions are present.
- Generated image, audio, or thumbnail assets are present.
- Asset metadata indicates synthetic generation.

Suggested disclosure:

> This video includes AI-assisted scripting and synthetic/generated visuals or audio.

The real ComfyUI and Piper assets have synthetic provider metadata but no explicit license/provenance fields, so the rights engine conservatively recorded them as `UNKNOWN`. The fake thumbnail was recorded as `SAFE` with disclosure required.

## Problems And Fixes

1. Regeneration originally targeted existing `v001` paths. Commit `82b7b5e` advances genuine regeneration/import outputs to the next available versioned path and preserves prior files.
2. FFmpeg was absent. FFmpeg 8.1.2 was installed locally with WinGet; no repository dependency was added.
3. The first composition attempt was denied access to the WinGet package directory by the execution sandbox. Retrying the same render ID with approved executable access succeeded, preserving the failed attempt details during recovery.
4. The old demo project had no script content version. A minimal script matching the reviewed narration was created and approved through the application approval workflow.
5. Ollama was reachable, but configured model `qwen3:8b` was unavailable. Deterministic fake metadata generation was used instead.
6. Asset and render review services persist current review status but do not create append-only `Approval` rows; script and metadata approvals do. This remains an approval-history limitation.

## Conclusion

The core real-provider path succeeded:

`ComfyUI image -> Piper narration -> human approvals -> FFmpeg render -> metadata -> thumbnail -> safety report -> publishing gate`

The result is `PASS_WITH_LIMITATIONS`: media generation and composition work locally, while publishing remains gated on explicit rights/provenance review and AI disclosure. Milestone 9D was not started.

## Voice License Remediation

On 2026-07-13, provenance review established that the original Piper Lessac voice depends on a research-only dataset license. Its asset remains historical, inactive, and `BLOCKED`.

The replacement used Piper `en_US-ljspeech-medium`, trained from scratch on the public-domain LJ Speech dataset:

- Active narration asset: `8271c15c-c911-450e-8bb6-0edbde712ff1`
- Path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/audio/scene_001/narration_v003.wav`
- Narration SHA-256: `8bb90f5872b055ff2be1e48707ac55d6f00e2cfdb0d7fe977d2955ad68215823`
- Model SHA-256: `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22`
- Config SHA-256: `141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860`
- Quality review: approved
- Replacement render: `146be226-8dd2-42b4-afb3-aa31b1501631`
- Render path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/renders/render_v002.mp4`
- Render SHA-256: `fa546444d5deb337d446ca23d32891e25cfe0421029385f9aab4902f62b4755c`
- Render review: approved
- Updated publishing gate: `NEEDS_REVIEW`
- Updated blocking reasons: none

The gate still requires human review for SDXL-Turbo's conditional commercial-license terms, and AI disclosure remains required. The narration-specific publishing block is resolved without deleting the Lessac history.
