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

## Candidate Replacement

The Piper `en_US-ljspeech-medium` model card identifies its training dataset as LJ Speech, labels the dataset public domain, and states that the model was trained from scratch:

- Model card: `https://huggingface.co/rhasspy/piper-voices/blob/main/en/en_US/ljspeech/medium/MODEL_CARD`

This is a candidate, not yet an approved project asset. Its exact downloaded file hash and current source/license evidence must be recorded after download and before production use.

## Gate Result

After recording provenance, the publishing gate changed from `NEEDS_REVIEW` to `BLOCKED`:

- Blocking reason: the Lessac narration has a blocked rights record
- Warning: SDXL-Turbo requires editorial license review
- Warning: AI disclosure is required
- Publishing remains manual and was not attempted

Milestone 9D was not started because its production render must not build on a blocked narration asset.
