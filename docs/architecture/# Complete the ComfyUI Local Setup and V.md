# Complete the ComfyUI Local Setup and Validate Milestone 9B

## What This Means

Your Milestone 9B code may already be implemented and pushed.

The remaining work is the **local runtime validation**:

```text
Install one image model
→ Run one working ComfyUI workflow manually
→ Export the workflow in API format
→ Point AI Media OS to that workflow
→ Run a real image-generation smoke test
→ Verify storage, approvals, caching, and replay behavior
```

You do not need to rewrite Milestone 9B if the provider code is already complete.

## 1. Confirm ComfyUI Desktop Is Running

1. Open **ComfyUI Desktop**.
2. Wait for the canvas to load.
3. Run:

```powershell
nvidia-smi
```

4. Confirm the local ComfyUI address opens:

```text
http://127.0.0.1:8188
```

Use the actual port shown by ComfyUI if different.

## 2. Install One Image Model

Recommended first checkpoint:

```text
sd_xl_turbo_1.0_fp16.safetensors
```

### Template method

1. Open:

```text
Workflow → Browse Workflow Templates
```

2. Search for:

```text
SDXL Turbo
```

3. Load the workflow.
4. Follow the missing-model download prompt if shown.

### Manual method

Copy the model to:

```text
ComfyUI/models/checkpoints/
```

Then refresh or restart ComfyUI and select the model in the `Load Checkpoint` node.

Do not place the model inside the AI Media OS repository.

## 3. Run a Manual Text-to-Image Test

Use a basic workflow containing:

```text
Load Checkpoint
CLIP Text Encode — Positive
CLIP Text Encode — Negative
Empty Latent Image
KSampler
VAE Decode
Save Image
```

Start with:

```text
Width: 512
Height: 512
Batch size: 1
Steps: 2
CFG: 1.0
Sampler: euler
Scheduler: normal
Denoise: 1.0
```

Prompt:

```text
A cinematic futuristic artificial intelligence data center,
realistic documentary photography, detailed server racks,
soft volumetric lighting, wide composition, highly detailed
```

Negative prompt:

```text
blurry, distorted, low quality, watermark, logo,
duplicate objects, malformed details
```

Click **Run** or **Queue Prompt**.

After 512 × 512 works, test:

```text
768 × 432
```

## 4. Save the Editable Workflow

Use:

```text
File → Save
```

Suggested filename:

```text
sdxl_turbo_text_to_image_v001.json
```

## 5. Export the API Workflow

1. Open **Settings**.
2. Enable:

```text
Enable dev mode options
```

3. Use:

```text
File → Export Workflow (API)
```

4. Save as:

```text
text_to_image_v001_api.json
```

5. Copy it into the repository:

```text
Ai-Media-Os/workflows/comfyui/text_to_image_v001.json
```

The editable UI workflow and API workflow are different formats.

## 6. Identify Workflow Node IDs

Open:

```text
workflows/comfyui/text_to_image_v001.json
```

Identify the exact node IDs for:

- Checkpoint
- Positive prompt
- Negative prompt
- Seed
- Width
- Height
- Steps
- CFG
- Sampler
- Scheduler
- Save Image output prefix

Do not guess node IDs.

## 7. Configure AI Media OS

Use settings similar to:

```text
IMAGE_PROVIDER_DEFAULT=fake
COMFYUI_BASE_URL=http://127.0.0.1:8188
COMFYUI_DEFAULT_WORKFLOW_PATH=workflows/comfyui/text_to_image_v001.json
COMFYUI_DEFAULT_CHECKPOINT=sd_xl_turbo_1.0_fp16.safetensors
COMFYUI_DEFAULT_WIDTH=768
COMFYUI_DEFAULT_HEIGHT=432
COMFYUI_DEFAULT_STEPS=2
COMFYUI_DEFAULT_CFG=1.0
COMFYUI_DEFAULT_SAMPLER=euler
COMFYUI_DEFAULT_SCHEDULER=normal
COMFYUI_HEALTHCHECK_ENABLED=true
COMFYUI_ALLOW_REMOTE_HOST=false
```

Keep the default provider as `fake` until the smoke test succeeds.

## 8. Run the Provider Health Check

With ComfyUI running:

```powershell
python -m ai_media_os.cli check-image-provider --provider comfyui
```

If your CLI differs, first run:

```powershell
python -m ai_media_os.cli --help
```

Expected result:

```text
Provider: comfyui
Reachable: yes
Workflow: valid
Checkpoint: available
Ready: yes
```

## 9. Generate One Scene Image

Use an existing project and scene:

```powershell
python -m ai_media_os.cli generate-scene-image `
  --project-id <project-id> `
  --scene-id <scene-id> `
  --provider comfyui `
  --model sd_xl_turbo_1.0_fp16.safetensors
```

Confirm:

- ComfyUI receives the request.
- Generation completes.
- AI Media OS stores a project-owned copy.
- An asset record is created.
- Status is `PENDING_REVIEW`.
- Provider, model, workflow, seed, dimensions, and hash are recorded.

## 10. Verify Asset Storage

Confirm:

- File exists.
- File opens.
- File is non-empty.
- MIME type is correct.
- Dimensions are recorded.
- Hash is recorded.
- Raw ComfyUI absolute paths are not exposed.
- The project owns a verified copy outside ComfyUI's temporary output path.

## 11. Verify Approval Behavior

Confirm:

- New images start as pending review.
- Rendering cannot use them before approval.
- Approve and reject actions work.
- Approved assets cannot be overwritten.
- Regeneration creates a new version or distinct asset.

## 12. Verify Cache and Idempotency

Run the identical request again.

Expected:

```text
Reuse the existing verified result
```

It should not silently create a duplicate.

Then change only the seed.

Expected:

```text
A new fingerprint and output are created
```

## 13. Verify Failure Handling

### ComfyUI stopped

1. Close ComfyUI.
2. Run the health check.
3. Confirm a clear unavailable-provider error.
4. Confirm the worker does not crash.

### Invalid workflow

Temporarily use an invalid test workflow path.

Confirm:

- Validation fails before submission.
- No asset is created.
- No workflow state advances.

Restore the valid workflow afterward.

## 14. Run the Full Quality Suite

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
git diff --check
```

Targeted tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -k "comfyui or image_provider"
```

## 15. Commit Only Missing Repository Files

Commit the API workflow and documentation if they are not already merged.

Do not commit:

```text
*.safetensors
ComfyUI installation files
ComfyUI output images
.env
temporary files
```

## Completion Checklist

- [ ] ComfyUI starts.
- [ ] Local server is reachable.
- [ ] One checkpoint is installed.
- [ ] Manual image generation succeeds.
- [ ] Editable workflow is saved.
- [ ] API workflow is exported.
- [ ] API workflow is stored under `workflows/comfyui/`.
- [ ] Provider health check passes.
- [ ] AI Media OS generates one real scene image.
- [ ] Project storage contains the verified image.
- [ ] Asset begins as pending review.
- [ ] Approval is required before rendering.
- [ ] Identical rerun does not create a duplicate.
- [ ] Changed seed creates a new output.
- [ ] Unavailable ComfyUI fails cleanly.
- [ ] Full tests pass.
- [ ] Model files are not committed.

## Send Back These Results

```text
Checkpoint filename:
Workflow filename:
API workflow path:
Health-check output:
Generation command:
Generation output:
Asset status:
Test result:
Error, if any:
```