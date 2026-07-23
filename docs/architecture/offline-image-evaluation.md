# Offline Image Evaluation

AI Media OS can evaluate generated scene images through a local Ollama vision model. The
evaluator sends image bytes only to the configured localhost Ollama endpoint and does not
change asset approval, rights, safety, or publishing state.

Objective checks cover file validity, exact dimensions, aspect ratio, and content hash.
Ollama provides advisory scores for scene relevance, phone-readable composition, perceived
sharpness, visible artifacts, and pseudo-text. To stay within the target laptop's local-model
context and memory limits, Ollama receives only one candidate image at a time. Reference IDs
are retained in the evaluation fingerprint, but character consistency is explicitly deferred
to human review instead of fabricating an automated comparison score. Perceived sharpness and
semantic scores are model opinions, not laboratory measurements, and always require human
review.

## One-time model setup

`qwen3-vl:4b` is the default because it supports image input while remaining practical for
the target laptop. Pulling a model requires internet once; evaluation is offline afterward.

```powershell
ollama --version
ollama pull qwen3-vl:4b
ollama serve

.\.venv\Scripts\python.exe -m ai_media_os.cli check-image-evaluator `
  --model qwen3-vl:4b
```

If the installed Ollama version cannot run Qwen3-VL, use the smaller fallback and pass the
same model name to every evaluation command:

```powershell
ollama pull qwen2.5vl:3b
```

## Generate a normal vertical master

Keep ComfyUI Desktop running with the Z-Image model installed. This is the normal production
test and is more realistic for the RTX 4050 than native 4K diffusion.

```powershell
$SCENE_ID = "<scene-id>"

$ASSET_ID = .\.venv\Scripts\python.exe -m ai_media_os.cli generate-scene-image `
  --scene-id $SCENE_ID `
  --provider comfyui `
  --model z_image_turbo_bf16.safetensors `
  --workflow-path workflows/comfyui/z_image_turbo_v001.json `
  --width 1080 `
  --height 1920 `
  --steps 8 `
  --cfg 1.0 `
  --sampler res_multistep `
  --scheduler simple `
  --timeout-seconds 900 `
  --seed 42 `
  --text-free `
  --visual-style faceless_editorial

$ASSET_ID
```

## Evaluate relevance and quality

Use an approved master-character asset when one exists so the report records the intended
reference. The local evaluator still sends only the candidate image; character consistency
remains `null` and requires human review.

```powershell
$REFERENCE_ASSET_ID = "<approved-character-reference-asset-id>"

.\.venv\Scripts\python.exe -m ai_media_os.cli evaluate-image `
  --asset-id $ASSET_ID `
  --reference-asset-id $REFERENCE_ASSET_ID `
  --model qwen3-vl:4b `
  --minimum-width 1080 `
  --minimum-height 1920 `
  --output ".\data\reports\image-evaluation-$ASSET_ID.json"
```

To evaluate any local image without a database asset, provide the scene meaning explicitly:

```powershell
.\.venv\Scripts\python.exe -m ai_media_os.cli evaluate-image `
  --image-path "C:\path\candidate.png" `
  --reference-image "C:\path\approved-character.png" `
  --scene-context "The recurring analyst explains how an AI processor connects to four modules." `
  --model qwen3-vl:4b
```

## Native vertical 4K stress test

Vertical 4K is `2160x3840`. This may run out of VRAM because the current workflow performs
native diffusion and VAE decoding rather than tiled AI upscaling. It is a test, not the
recommended batch-production path.

```powershell
$ASSET_4K_ID = .\.venv\Scripts\python.exe -m ai_media_os.cli generate-scene-image `
  --scene-id $SCENE_ID `
  --provider comfyui `
  --model z_image_turbo_bf16.safetensors `
  --workflow-path workflows/comfyui/z_image_turbo_v001.json `
  --width 2160 `
  --height 3840 `
  --steps 8 `
  --cfg 1.0 `
  --sampler res_multistep `
  --scheduler simple `
  --timeout-seconds 1200 `
  --seed 42 `
  --text-free `
  --visual-style faceless_editorial

.\.venv\Scripts\python.exe -m ai_media_os.cli evaluate-image `
  --asset-id $ASSET_4K_ID `
  --reference-asset-id $REFERENCE_ASSET_ID `
  --model qwen3-vl:4b `
  --minimum-width 2160 `
  --minimum-height 3840 `
  --output ".\data\reports\image-evaluation-4k-$ASSET_4K_ID.json"
```

If native 4K fails, return to 1080x1920. A tiled AI-upscale workflow should be implemented and
measured separately instead of presenting ordinary resizing as newly generated detail.

## Exit behavior

- `PASS`: command exits `0`; objective requirements and configured score thresholds passed.
- `WARN`: command exits `0`; inspect the listed issues before approval.
- `FAIL`: command exits `2`; regenerate or revise the prompt before approval.

The report is advisory. It cannot approve an asset or bypass human review.

## One-command project run

For a project that already has an approved script, approved scene plan, and active approved
narration for every scene, the interactive runner generates all visuals sequentially, evaluates
each with Ollama, asks for explicit visual approval, creates and validates the short timeline,
asks for timeline approval, renders, verifies, and asks for final render approval.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-short-production.ps1 `
  -ProjectId <project-id> `
  -Quality 1080p `
  -VisionModel qwen3-vl:4b
```

Add `-ReferenceAssetId <approved-character-reference-asset-id>` to record which character
reference must be checked during human review. Use `-Quality 4k` only as a native-generation
VRAM stress test. Generation is sequential and cache-first: exact matching, hash-valid assets
are reused. The production runner also uses the explicit `--reuse-existing` policy: an active
pending or approved image is reused whenever its stored file hash verifies, even if generation
settings have changed since it was created. Rejected, changes-requested, missing, and corrupt
assets are never reused. New and reusable pending images are staged below the project's `images/.pending/`
directory. The script shows image and evaluation progress, never approves a failed Ollama
report, and requires `APPROVE` or `REJECT` at every visual checkpoint. Approval promotes the
staged file into its versioned scene directory. Rejection keeps the database audit record but
deletes the staged image file and invalidates its generation cache key.
