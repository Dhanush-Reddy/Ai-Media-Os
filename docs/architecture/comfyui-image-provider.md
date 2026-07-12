# Local ComfyUI Image Provider

Milestone 9B adds optional real scene-image generation through a separately installed ComfyUI
server. `fake_image` remains the default and tests do not require ComfyUI, a checkpoint, a GPU, or
network access.

## Setup

Install ComfyUI manually, place a compatible checkpoint in its normal checkpoint directory, start
its HTTP server on localhost, and configure:

```text
AI_MEDIA_OS_IMAGE_DEFAULT_PROVIDER=fake_image
AI_MEDIA_OS_COMFYUI_BASE_URL=http://127.0.0.1:8188
AI_MEDIA_OS_COMFYUI_DEFAULT_CHECKPOINT=your-checkpoint.safetensors
AI_MEDIA_OS_COMFYUI_DEFAULT_WORKFLOW_PATH=workflows/comfyui/text_to_image_v001.json
```

The application does not install ComfyUI or download checkpoints. The initial API workflow is a
single text-to-image graph compatible with a standard checkpoint loader, CLIP encoders, sampler,
VAE decoder, and `SaveImage`. Its fixed node mapping is:

| Setting | Node/field |
| --- | --- |
| Positive prompt | `6.text` |
| Negative prompt | `7.text` |
| Checkpoint | `4.ckpt_name` |
| Seed, steps, CFG, sampler, scheduler | `3` inputs |
| Width and height | `5` inputs |
| Output prefix | `9.filename_prefix` |

Only these known fields are changed. Templates must be below `workflows/comfyui`, must be valid
JSON, and must retain the expected node classes and inputs.

## Commands

```powershell
python -m ai_media_os.cli check-image-provider --provider comfyui --model your-checkpoint.safetensors
python -m ai_media_os.cli generate-scene-image --scene-id $SCENE_ID --provider comfyui --model your-checkpoint.safetensors --seed 42
python -m ai_media_os.cli list-assets --project-id $PROJECT_ID
python -m ai_media_os.cli verify-asset-file IMAGE_ASSET_ID
```

The provider submits `/prompt`, polls `/history/{prompt_id}`, discovers exactly one safe output,
and downloads it through `/view`. Polling and requests have bounded timeouts. PNG, JPEG, and WebP
signatures and dimensions are verified before atomic project storage, cache insertion, or asset
finalization. Generated assets remain pending human review and use unknown rights status until the
safety engine evaluates their provenance.

## Security And Idempotency

HTTP endpoints are restricted by default to `127.0.0.1`, `localhost`, and `::1`; redirects,
credentials, URL paths, remote/LAN hosts, unsafe output names, traversal, malformed workflows, and
oversized outputs are rejected. Raw storage paths and stack traces are not shown in the dashboard.

Cache fingerprints include provider/version, workflow content hash/version, checkpoint, prompt,
negative prompt, scene and narration hash, seed, dimensions, steps, CFG, sampler, and scheduler.
Missing or corrupt cache files are not reused. Approved assets cannot be regenerated or imported
over. The existing queue serializes claimed work; deployments should run one GPU-heavy image worker
at a time to avoid duplicate local submissions during concurrent generation.

## Limitations

The bundled workflow has not selected or bundled a checkpoint and may require adjustment for a
user's locally installed model. There is no automatic installation, model download, cloud API,
ControlNet, inpainting, image-to-image, upscaling, character-consistency workflow, or workflow
editor. Synthetic provenance triggers the existing disclosure and publishing-gate review; it is
not a legal or platform-compliance guarantee. Milestone 9C (real local voice) is not included.
