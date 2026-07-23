# Local Production And Approval Commands

This runbook contains the routine PowerShell commands for finding current IDs, reviewing outputs,
approving or rejecting work, rendering videos, creating packaging, running the safety gate, and
finding local files.

Run commands from:

```text
C:\Users\gspra\OneDrive\Desktop\Dhanush\Ai-Media-Os
```

Do not type angle-bracket placeholders such as `<SCENE_ID>` in PowerShell. Assign the real ID to a
variable first.

## 1. Start A PowerShell Session

```powershell
Set-Location "C:\Users\gspra\OneDrive\Desktop\Dhanush\Ai-Media-Os"

$PYTHON = (Resolve-Path ".\.venv\Scripts\python.exe").Path
$PROJECT_ID = "e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f"

if (-not (Test-Path -LiteralPath $PYTHON -PathType Leaf)) {
  throw "Python executable was not found: $PYTHON"
}
```

The virtual environment does not need to be activated when `$PYTHON` is used. To activate it
manually:

```powershell
.\.venv\Scripts\Activate.ps1
```

PowerShell variables do not survive after the terminal is closed. Run the setup block again in
every new terminal before using `& $PYTHON`. If the prompt already begins with `(.venv)`, commands
may use `python` directly instead:

```powershell
python -m ai_media_os.cli list-channels
python -m ai_media_os.cli list-projects
```

## 2. Important ID Types

These IDs are different and must not be interchanged:

| ID | Example | Used by |
| --- | --- | --- |
| Project ID | `e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f` | Most project commands |
| Timeline version ID | `ca5d5e21-9a0c-4cde-b338-422605b7c93d` | Show, validate, and render timeline |
| Approval request ID | `5ed9b965-de68-4e71-9d8a-caa5ed31185d` | Approve, reject, or request changes |
| Scene ID | `1393f90f-a0a8-4420-8711-ca5a6e93f0d9` | Generate scene image or narration |
| Asset ID | `3f2f3bac-f0c7-40ea-8ffe-66c67c707db1` | Preview, verify, and review media |
| Render ID | A UUID printed by `list-renders` | Verify and review a video render |
| Metadata version ID | A UUID printed by `list-metadata` | Metadata approval and thumbnail input |
| Thumbnail asset ID | A UUID printed by `list-thumbnails` | Thumbnail verification and review |

The example beginning `5ed9...` is an approval request ID, not a timeline version ID.

## 3. Find Projects

```powershell
& $PYTHON -m ai_media_os.cli list-channels
& $PYTHON -m ai_media_os.cli list-projects
```

The channel columns are `CHANNEL_ID`, `SLUG`, `NAME`, `STATUS`, `CREATED_DATE`, and `TAG`. The
project columns are `PROJECT_ID`, `CHANNEL_ID`, `STATUS`, `WORKING_TITLE`, `CREATED_DATE`, and
`TAG`. A project's `CHANNEL_ID` points to the matching channel row. `LATEST` identifies the newest
record in the displayed result set.

To filter projects by channel:

```powershell
$CHANNEL_ID = "replace-with-real-channel-id"
& $PYTHON -m ai_media_os.cli list-projects --channel-id $CHANNEL_ID
```

## 4. Find The Latest Timeline

List every production timeline version:

```powershell
& $PYTHON -m ai_media_os.cli list-content-versions `
  --project-id $PROJECT_ID `
  --type production_timeline
```

The list is oldest first. Store the newest timeline ID automatically:

```powershell
$LATEST_TIMELINE_ROW = & $PYTHON -m ai_media_os.cli list-content-versions `
  --project-id $PROJECT_ID `
  --type production_timeline | Select-Object -Last 1

$TIMELINE_ID = ($LATEST_TIMELINE_ROW -split "`t")[0]
Write-Host "Latest timeline: $TIMELINE_ID"
```

Current Milestone 9D timeline:

```powershell
$TIMELINE_ID = "ca5d5e21-9a0c-4cde-b338-422605b7c93d"
```

Inspect and validate it:

```powershell
& $PYTHON -m ai_media_os.cli show-timeline --timeline-version-id $TIMELINE_ID
& $PYTHON -m ai_media_os.cli validate-timeline --timeline-version-id $TIMELINE_ID
```

`WARN` permits human review. `BLOCK` must be fixed before approval or rendering.

## 5. Find Approval Requests

List all project approvals, newest first:

```powershell
& $PYTHON -m ai_media_os.cli list-approvals --project-id $PROJECT_ID
```

List only pending production-timeline approvals:

```powershell
& $PYTHON -m ai_media_os.cli list-approvals `
  --project-id $PROJECT_ID `
  --type production_timeline `
  --status pending
```

Store the newest pending approval ID:

```powershell
$LATEST_APPROVAL_ROW = & $PYTHON -m ai_media_os.cli list-approvals `
  --project-id $PROJECT_ID `
  --type production_timeline `
  --status pending | Select-Object -First 1

$APPROVAL_ID = ($LATEST_APPROVAL_ROW -split "`t")[0]
Write-Host "Latest pending approval: $APPROVAL_ID"
```

Current Milestone 9D timeline approval:

```powershell
$APPROVAL_ID = "5ed9b965-de68-4e71-9d8a-caa5ed31185d"
```

## 6. Approve, Reject, Or Request Changes

Use the interactive approval menu:

```powershell
& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID
```

The menu is:

```text
1. Approve
2. Reject
3. Request changes
```

Direct non-interactive forms:

```powershell
& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID --decision 1
& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID --decision 2
& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID --decision 3
```

Add feedback when needed:

```powershell
& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID `
  --decision 3 `
  --feedback "Replace Scene 4 visual and reduce the caption length."
```

The older commands remain available:

```powershell
& $PYTHON -m ai_media_os.cli approve $APPROVAL_ID
& $PYTHON -m ai_media_os.cli reject $APPROVAL_ID
& $PYTHON -m ai_media_os.cli request-changes $APPROVAL_ID
```

## 7. One-Command Latest Approval Helper

The helper lists pending approvals newest first, selects the newest matching request, and shows the
numbered decision menu:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\review-latest-approval.ps1 `
  -ProjectId $PROJECT_ID `
  -Type production_timeline `
  -ListOnly
```

List and then open the numbered decision menu:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\review-latest-approval.ps1 `
  -ProjectId $PROJECT_ID `
  -Type production_timeline
```

Approve the newest matching request without the menu:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\review-latest-approval.ps1 `
  -ProjectId $PROJECT_ID `
  -Type production_timeline `
  -Decision 1
```

Review one exact approval request:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\review-latest-approval.ps1 `
  -ProjectId $PROJECT_ID `
  -ApprovalId $APPROVAL_ID
```

## 8. Find Scenes

Find the newest approved scene-plan version:

```powershell
& $PYTHON -m ai_media_os.cli list-content-versions `
  --project-id $PROJECT_ID `
  --type scene_plan
```

For the current project:

```powershell
$SCENE_PLAN_ID = "880b21be-6836-409a-b0c1-f1caab2cc156"
& $PYTHON -m ai_media_os.cli list-scenes --scene-plan-version-id $SCENE_PLAN_ID
```

Current Scene 1 ID:

```powershell
$SCENE_ID = "1393f90f-a0a8-4420-8711-ca5a6e93f0d9"
```

## 9. Generate And Review Narration

Generate Chatterbox narration:

```powershell
& $PYTHON -m ai_media_os.cli generate-scene-narration `
  --scene-id $SCENE_ID `
  --provider chatterbox `
  --reference-audio "C:\AI-Models\Chatterbox\voices\shorts-narrator.wav" `
  --voice shorts-narrator `
  --language en `
  --exaggeration 0.6 `
  --cfg-weight 0.4 `
  --seed 1
```

List narration assets:

```powershell
& $PYTHON -m ai_media_os.cli list-narration-assets --project-id $PROJECT_ID
```

Preview and verify one narration asset:

```powershell
$ASSET_ID = "3f2f3bac-f0c7-40ea-8ffe-66c67c707db1"
& $PYTHON -m ai_media_os.cli preview-narration $ASSET_ID
& $PYTHON -m ai_media_os.cli verify-audio-asset $ASSET_ID
```

Review narration with the numbered menu:

```powershell
& $PYTHON -m ai_media_os.cli review-asset $ASSET_ID
```

## 10. Generate And Review Images

Generate or reuse the project's short-form images, then evaluate them with Ollama:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\run-short-production.ps1 `
  -ProjectId $PROJECT_ID `
  -Quality 1080p `
  -VisionModel qwen3-vl:4b `
  -ReferenceAssetId dcccf9b4-2644-4a77-8350-f4194e583a03
```

List all project assets:

```powershell
& $PYTHON -m ai_media_os.cli list-assets --project-id $PROJECT_ID
```

Verify and review an image asset:

```powershell
$IMAGE_ASSET_ID = "replace-with-real-image-asset-id"
& $PYTHON -m ai_media_os.cli verify-asset-file $IMAGE_ASSET_ID
& $PYTHON -m ai_media_os.cli review-asset $IMAGE_ASSET_ID
```

Pending images are staged under `.pending`. Approval moves them to the permanent scene folder;
rejection removes the staged file and invalidates its generation cache entry.

### Full media-to-gate regeneration

For a new video, create a new project and run the complete production sequence from an editorially
prepared Markdown script:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\regenerate-short-production.ps1 `
  -ChannelId c9716dbc-c7c0-483e-ac32-5901e2c3ec53 `
  -WorkingTitle "Why AI Agents Fail in Production" `
  -Topic "Why AI agents fail outside controlled demonstrations" `
  -ScriptFile ".\inputs\why-ai-agents-fail.md" `
  -ReferenceProjectId e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f `
  -Quality 1080p `
  -VisionModel qwen3-vl:4b `
  -ReferenceAssetId dcccf9b4-2644-4a77-8350-f4194e583a03 `
  -VoiceReferenceAudio "C:\AI-Models\Chatterbox\voices\shorts-narrator.wav"
```

Fresh-project mode creates the project, stores the imported script as a pending content version,
requires script approval, generates and requires approval of a new scene plan, and only then starts
media generation. The script file must already be source-grounded and ready for editorial review;
the runner does not invent research from a title. If `-ReferenceProjectId` is supplied, the runner
uses the newest approved image reference from that earlier project when one is available. The run
also keeps a `review-package` folder under `data\reports\production-runs\{project_id}\{run_id}\`
with the imported script and resolved reference context for later acceptance or change review.

Use existing-project mode only when creating revisions for the same video:

```powershell
powershell -ExecutionPolicy Bypass `
  -File .\scripts\regenerate-short-production.ps1 `
  -ProjectId $PROJECT_ID `
  -Quality 1080p
```

The script generates a new time-based seed unless `-Seed` is supplied. Use an explicit seed when a
run must be reproducible. It displays overall, provider, scene, image-evaluation, narration-alignment,
and rendering progress. Important outputs still pause for a numbered human decision:

```text
1. Approve
2. Reject and stop
```

Approved assets and renders are preserved as historical revisions. ComfyUI images and Chatterbox
narrations are first stored under the project's `.pending` directories. Approval atomically moves
them to versioned permanent paths; rejection deletes the staged file and invalidates its cache entry.
A failed Ollama metadata-provider health check no longer stops the whole run; the script falls back
to the fake metadata provider and logs the reason so the project can still be reviewed.
A failed run writes its last known IDs and error to:

```text
data\reports\production-runs\{project_id}\{run_timestamp}.json
data\reports\production-runs\{project_id}\{run_timestamp}.log
```

The script starts the dashboard at `http://127.0.0.1:8000` when it is not already running. It does
not open a browser. Use `-NoDashboard` when another terminal already manages the dashboard, or
`-DashboardPort 8010` to select a different local port.

WhisperX paths are restored automatically from `C:\AI-Models\WhisperX` when session environment
variables are absent. Device mode defaults to `auto`: CUDA is used when the isolated runtime reports
it available; otherwise the runner uses the verified CPU/int8 alignment fallback. Override this only
when needed with `-WhisperXDevice cuda|cpu` and `-WhisperXComputeType`.

Useful options:

```powershell
# Use 2160x3840 image generation. The final timeline currently remains 1080x1920.
-Quality 4k

# Skip Ollama image scoring but retain required human image review.
-SkipImageEvaluation

# Stop after the approved video render.
-SkipPackaging

# Create packaging but do not run the publishing gate.
-SkipSafetyGate

# Reproduce generation settings from an earlier run.
-Seed 123456
```

The command does not publish to YouTube or bypass human approvals. A project represents one video;
retries for that video remain immutable revisions inside the project. Create another project when
starting another video, not merely because one generation attempt needs correction.

## 11. Generate And Approve A Timeline

Generate a vertical faceless timeline:

```powershell
$TIMELINE_ID = & $PYTHON -m ai_media_os.cli generate-timeline `
  --project-id $PROJECT_ID `
  --video-format short_vertical `
  --style-profile faceless_editorial
```

Validate it:

```powershell
& $PYTHON -m ai_media_os.cli validate-timeline --timeline-version-id $TIMELINE_ID
```

Create the timeline approval request. Despite its historical name, `approve-timeline` creates a
pending request; it does not approve automatically:

```powershell
$APPROVAL_ID = & $PYTHON -m ai_media_os.cli approve-timeline `
  --timeline-version-id $TIMELINE_ID

& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID
```

## 12. Render And Review The Video

After timeline approval:

```powershell
$RENDER_ID = & $PYTHON -m ai_media_os.cli render-timeline `
  --timeline-version-id $TIMELINE_ID

Write-Host "Render ID: $RENDER_ID"
```

List and verify renders:

```powershell
& $PYTHON -m ai_media_os.cli list-renders --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli verify-render --render-id $RENDER_ID
```

Review the render with the numbered menu:

```powershell
& $PYTHON -m ai_media_os.cli review-render $RENDER_ID
```

## 13. Generate And Approve Metadata

Metadata generation should use the exact approved render:

```powershell
$METADATA_ID = & $PYTHON -m ai_media_os.cli generate-metadata `
  --project-id $PROJECT_ID `
  --render-id $RENDER_ID

& $PYTHON -m ai_media_os.cli list-metadata --project-id $PROJECT_ID
```

Create and review its approval request:

```powershell
& $PYTHON -m ai_media_os.cli review-metadata $METADATA_ID

powershell -ExecutionPolicy Bypass `
  -File .\scripts\review-latest-approval.ps1 `
  -ProjectId $PROJECT_ID `
  -Type metadata
```

## 14. Generate And Review A Thumbnail

Generate the concept after metadata approval:

```powershell
$CONCEPT_ID = & $PYTHON -m ai_media_os.cli generate-thumbnail-concept `
  --project-id $PROJECT_ID `
  --metadata-version-id $METADATA_ID
```

Request and decide concept approval:

```powershell
$APPROVAL_ID = & $PYTHON -m ai_media_os.cli request-approval `
  --project-id $PROJECT_ID `
  --type thumbnail `
  --content-version-id $CONCEPT_ID

& $PYTHON -m ai_media_os.cli review-approval $APPROVAL_ID
```

Generate, list, verify, and review the thumbnail asset:

```powershell
$THUMBNAIL_ID = & $PYTHON -m ai_media_os.cli generate-thumbnail `
  --project-id $PROJECT_ID `
  --metadata-version-id $METADATA_ID `
  --concept-version-id $CONCEPT_ID

& $PYTHON -m ai_media_os.cli list-thumbnails --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli verify-thumbnail-file $THUMBNAIL_ID
& $PYTHON -m ai_media_os.cli review-thumbnail $THUMBNAIL_ID
```

## 15. Run Safety Checks And Publishing Gate

```powershell
& $PYTHON -m ai_media_os.cli check-asset-rights --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli check-claims --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli check-script-safety --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli check-metadata-safety --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli check-thumbnail-safety --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli check-reused-content --project-id $PROJECT_ID
& $PYTHON -m ai_media_os.cli decide-ai-disclosure --project-id $PROJECT_ID

& $PYTHON -m ai_media_os.cli run-publishing-gate `
  --project-id $PROJECT_ID `
  --render-id $RENDER_ID `
  --metadata-version-id $METADATA_ID `
  --thumbnail-asset-id $THUMBNAIL_ID

& $PYTHON -m ai_media_os.cli show-safety-report --project-id $PROJECT_ID
```

The publishing gate does not upload or publish anything.

## 16. Start The Local Dashboard

```powershell
& $PYTHON -m ai_media_os.cli dashboard --host 127.0.0.1 --port 8000
```

Open manually:

```text
http://127.0.0.1:8000
```

Do not expose this localhost dashboard directly to the public internet. Remote approval architecture
is documented in `docs/architecture/remote-approval-access.md`.

## 17. Important Local Paths

Repository:

```text
C:\Users\gspra\OneDrive\Desktop\Dhanush\Ai-Media-Os
```

Database:

```text
C:\Users\gspra\OneDrive\Desktop\Dhanush\Ai-Media-Os\data\database\ai_media_os.db
```

Current project root:

```text
C:\Users\gspra\OneDrive\Desktop\Dhanush\Ai-Media-Os\data\projects\e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f
```

Project folders:

```text
data\projects\{project_id}\images\       Approved scene images
data\projects\{project_id}\images\.pending\  Images waiting for review
data\projects\{project_id}\audio\        Narration audio
data\projects\{project_id}\subtitles\    Generated ASS/SRT subtitle files
data\projects\{project_id}\thumbnails\   Thumbnail PNG files
data\projects\{project_id}\renders\      MP4 renders
data\projects\{project_id}\reports\      Project reports when present
data\reports\image-evaluations\           Ollama image evaluation JSON
data\cache\                                Reusable generated-output cache
data\logs\                                 Local application logs
```

Current reference narration:

```text
C:\AI-Models\Chatterbox\voices\shorts-narrator.wav
```

Current Chatterbox model directory:

```text
C:\AI-Models\Chatterbox\multilingual-v3
```

FFmpeg:

```text
C:\AI-Tools\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe
C:\AI-Tools\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffprobe.exe
```

Current generated narration example:

```text
data\projects\e81f19f0-d20e-4e2a-a5db-bff5c4a98f9f\audio\scene_001\narration_v004.wav
```

## 18. Full Verification

```powershell
& $PYTHON -m pytest
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\mypy.exe src
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe downgrade -1
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\alembic.exe check
git diff --check
```

## 19. Common Errors

### PowerShell says the `<` operator is reserved

Cause: an example placeholder was entered literally.

Fix:

```powershell
$SCENE_ID = "real-uuid-here"
```

Then use `$SCENE_ID`, without angle brackets.

### No pending approval was found

Check all approval states:

```powershell
& $PYTHON -m ai_media_os.cli list-approvals --project-id $PROJECT_ID
```

The request may already be approved, rejected, or superseded, or an approval request may not have
been created yet.

### Timeline validation reports an unapproved asset

An approved image or narration was replaced by a newer revision. Generate a new timeline from the
current active approved assets, validate it, and create a new approval request. Do not reactivate an
old asset through direct SQL.

### The laptop is off

Local generation, dashboard access, Telegram polling, tunnel access, and Netlify-to-local approval
requests are unavailable while the laptop or required local process is offline. No decision should
be treated as approved during an outage.
