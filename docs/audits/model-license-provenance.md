# Real Model License Provenance

Date: 2026-07-13

This audit records the exact local model files used by the real-provider smoke test. It does not provide legal advice or guarantee that model outputs are copyright-safe or platform-compliant.

## SDXL-Turbo Checkpoint

- Asset ID: `3f706778-6e5c-46b6-af10-5f156492f9d6`
- Provider: ComfyUI
- Checkpoint: `sd_xl_turbo_1.0_fp16.safetensors`
- Source: `https://huggingface.co/stabilityai/sdxl-turbo/blob/main/sd_xl_turbo_1.0_fp16.safetensors`
- Local file SHA-256: `e869ac7d6942cb327d68d5ed83a40447aadf20e0c3358d98b2cc9e270db0da26`
- License: Stability AI Community License, updated July 5, 2024
- License source: `https://huggingface.co/stabilityai/sdxl-turbo/blob/main/LICENSE.md`
- Commercial use: conditional; the license requires registration for commercial use and changes terms above its stated annual-revenue threshold
- Attribution: the license contains distribution and attribution obligations for Stability AI Materials, derivative works, and products using them; this audit does not infer that publishing a model output alone triggers those provisions
- Recorded status: `EDITORIAL_ONLY`

The model may not be treated as unconditionally commercially safe. Before revenue-producing use, confirm registration, revenue eligibility, the current license, and the current acceptable-use policy.

## Piper Lessac Voice

- Asset ID: `ef5e002e-9637-4e4a-8667-8ad50b1ab899`
- Provider: Piper
- Voice model: `en_US-lessac-medium.onnx`
- Source: `https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx`
- Local model SHA-256: `5efe09e69902187827af646e1a6e9d269dee769f9877d17b16b1b46eeaaf019f`
- Local config SHA-256: `efe19c417bed055f2d69908248c6ba650fa135bc868b0e6abb3da181dab690a0`
- Model card: `https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/lessac/medium/MODEL_CARD`
- Dataset: Lessac Blizzard 2013
- Dataset license: Blizzard 2013 Research License
- License source: `https://www.cstr.ed.ac.uk/projects/blizzard/2013/lessac_blizzard2013/license.html`
- Commercial use: not allowed by the cited dataset license; it limits the materials to research purposes and expressly excludes commercial voice-synthesis use
- Attribution: not applicable as a remediation; the asset is blocked rather than cleared through attribution
- Recorded status: `BLOCKED`

The smoke-test narration must not be used in a commercial or monetized production package. Replace it with a voice whose model card and training-data license clearly permit the intended commercial use, generate a new asset revision, obtain human approval, create a new render, and rerun the publishing gate.

## LJSpeech Replacement

- Asset ID: `8271c15c-c911-450e-8bb6-0edbde712ff1`
- Asset revision: 2, active; supersedes the inactive Lessac asset
- Provider: Piper
- Model: `en_US-ljspeech-medium.onnx`
- Config: `en_US-ljspeech-medium.onnx.json`
- Download directory: external local model storage; not committed to Git
- Download date: 2026-07-13
- Model size: 63,531,379 bytes
- Config size: 4,972 bytes
- Model SHA-256: `6f52a751e2349abe7a76735eb09dc1875298c77ea2342ffd2fef79ff81b87f22`
- Config SHA-256: `141d612cc0a95ed7efc1ca936b845c2364967f2e9217c5dbfcf69fc4d6c65860`
- Source revision: `bae641dcb5a608cff81ccaf7ff018baaca1a33e1`
- Model source: `https://huggingface.co/rhasspy/piper-voices/blob/bae641dcb5a608cff81ccaf7ff018baaca1a33e1/en/en_US/ljspeech/medium/en_US-ljspeech-medium.onnx`
- Model card: `https://huggingface.co/rhasspy/piper-voices/blob/bae641dcb5a608cff81ccaf7ff018baaca1a33e1/en/en_US/ljspeech/medium/MODEL_CARD`
- Repository license: MIT as declared by the Piper Voices repository
- Training dataset: LJ Speech; the model card says the voice was trained from scratch
- Dataset evidence: `https://keithito.com/LJ-Speech-Dataset/`
- Dataset license: public domain; the dataset page states there are no use restrictions and attribution is not required
- Commercial-use conclusion: allowed by the reviewed repository and dataset evidence
- Attribution conclusion: not required for generated narration output by the reviewed evidence
- Review date: 2026-07-13
- Reviewer decision: `VERIFIED`
- Quality review: approved by the user
- Narration path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/audio/scene_001/narration_v003.wav`
- Narration SHA-256: `8bb90f5872b055ff2be1e48707ac55d6f00e2cfdb0d7fe977d2955ad68215823`

The downloaded ONNX hash matches the source repository's published LFS object ID. Piper generation metadata independently recorded matching model and config hashes. The Lessac asset and `narration_v002.wav` remain historical, inactive, and blocked.

## Replacement Render And Gate

- Render ID: `146be226-8dd2-42b4-afb3-aa31b1501631`
- Render version: 2
- Render path: `data/projects/2d9fb350-3c4a-4d5a-9543-6c6f2e46be90/renders/render_v002.mp4`
- Render SHA-256: `fa546444d5deb337d446ca23d32891e25cfe0421029385f9aab4902f62b4755c`
- Probed duration: 6.453 seconds
- Review: approved by the user
- Publishing gate: `NEEDS_REVIEW`
- Blocking reasons: none
- Active rights summary: 2 `SAFE`, 1 `EDITORIAL_REVIEW`
- Remaining review: SDXL-Turbo commercial-license conditions
- AI disclosure: required
- Publishing: remains manual and was not attempted

The inactive blocked Lessac asset remains in history but no longer blocks the active render. Milestone 9D was not started.
