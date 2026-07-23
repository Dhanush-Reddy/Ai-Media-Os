[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [ValidateSet("1080p", "4k")]
    [string]$Quality = "1080p",

    [string]$VisionModel = "qwen3-vl:4b",
    [string]$ReferenceAssetId,
    [string]$Checkpoint = "z_image_turbo_bf16.safetensors",
    [string]$WorkflowPath = "workflows/comfyui/z_image_turbo_v001.json",
    [int]$Seed = 42,
    [int]$DashboardPort = 8000,
    [switch]$RegenerateImages,
    [switch]$SkipImageEvaluation,
    [switch]$DurationBasedTiming,
    [switch]$LayeredCharacters
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$ReportDirectory = Join-Path $RepositoryRoot "data\reports\image-evaluations"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Virtual environment Python was not found: $Python"
}

New-Item -ItemType Directory -Force -Path $ReportDirectory | Out-Null

function Invoke-AiMediaCli {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [switch]$ShowImageProgress
    )

    $output = @(
        & $Python -m ai_media_os.cli @Arguments | ForEach-Object {
            $line = [string]$_
            if ($ShowImageProgress -and $line -match '^PROGRESS_IMAGE\t(\d+)\t(\d+)\t(\d+)\t([^\t]+)\t(.+)$') {
                $current = [int]$Matches[1]
                $total = [int]$Matches[2]
                $sceneNumber = [int]$Matches[3]
                $percent = [Math]::Floor(($current / $total) * 100)
                Write-Progress `
                    -Activity "Generating scene images" `
                    -Status "Scene $sceneNumber completed ($current of $total)" `
                    -PercentComplete $percent
                $resolution = $Matches[5].ToUpperInvariant()
                Write-Host "[$current/$total] Scene $sceneNumber $resolution`: $($Matches[4])"
            }
            $line
        }
    )
    if ($ShowImageProgress) {
        Write-Progress -Activity "Generating scene images" -Completed
    }
    if ($LASTEXITCODE -ne 0) {
        throw "AI Media OS command failed ($LASTEXITCODE): $($Arguments -join ' ')"
    }
    return @($output)
}

function Select-Identifier {
    param([Parameter(Mandatory = $true)][object[]]$Output)

    $identifiers = @(
        $Output |
            ForEach-Object { [string]$_ } |
            Where-Object { $_ -match '^[0-9a-fA-F-]{36}$' }
    )
    if ($identifiers.Count -eq 0) {
        throw "The command did not return an identifier. Output: $($Output -join ' | ')"
    }
    return $identifiers[-1]
}

function Invoke-AiMediaCliWithActivity {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Activity,
        [Parameter(Mandatory = $true)][string]$Status
    )

    try {
        Write-Progress -Activity $Activity -Status $Status -PercentComplete 1
        $output = [System.Collections.Generic.List[string]]::new()
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $Python -m ai_media_os.cli @Arguments 2>&1 | ForEach-Object {
                $line = [string]$_
                $output.Add($line)
                Write-Host $line
            }
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($null -eq $exitCode) {
            throw "AI Media OS command did not return an exit code: $($Arguments -join ' ')"
        }
        return [pscustomobject]@{
            ExitCode = $exitCode
            Output = @($output)
        }
    }
    finally {
        Write-Progress -Activity $Activity -Completed
    }
}

function Confirm-Approval {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Identifier
    )

    Write-Host "Review $Label $Identifier"
    Write-Host "  1. Approve"
    Write-Host "  2. Reject"
    while ($true) {
        $decision = Read-Host "Choose 1 or 2"
        if ($decision -eq "1") {
            return $true
        }
        if ($decision -eq "2") {
            return $false
        }
        Write-Host "Enter 1 or 2." -ForegroundColor Yellow
    }
}

$Width = 1080
$Height = 1920
$GenerationTimeout = 900
if ($Quality -eq "4k") {
    $Width = 2160
    $Height = 3840
    $GenerationTimeout = 1200
}

Push-Location $RepositoryRoot
try {
    if (-not $SkipImageEvaluation) {
        Write-Host "Checking local Ollama vision model..."
        Invoke-AiMediaCli -Arguments @(
            "check-image-evaluator", "--model", $VisionModel
        ) | ForEach-Object { Write-Host $_ }
    }

    Write-Host "Processing scene visuals sequentially at ${Width}x${Height}..."
    if ($RegenerateImages) {
        Write-Host "Creating new image revisions with seed $Seed; approved history is preserved."
    } else {
        Write-Host "Matching verified assets are reused; only missing or changed scenes are generated."
    }
    $imageArguments = @(
        "generate-project-images",
        "--project-id", $ProjectId,
        "--provider", "comfyui",
        "--model", $Checkpoint,
        "--workflow-path", $WorkflowPath,
        "--width", [string]$Width,
        "--height", [string]$Height,
        "--steps", "8",
        "--cfg", "1.0",
        "--sampler", "res_multistep",
        "--scheduler", "simple",
        "--timeout-seconds", [string]$GenerationTimeout,
        "--seed", [string]$Seed,
        "--text-free",
        "--visual-style", "faceless_editorial",
        "--stage-for-review"
    )
    if (-not $RegenerateImages) {
        $imageArguments += "--reuse-existing"
    }
    $generationOutput = Invoke-AiMediaCli -ShowImageProgress -Arguments $imageArguments
    $imageAssetIds = @(
        $generationOutput |
            ForEach-Object { [string]$_ } |
            Where-Object { $_ -match '^[0-9a-fA-F-]{36}$' }
    )
    if ($imageAssetIds.Count -eq 0) {
        throw "No image asset IDs were returned. Output: $($generationOutput -join ' | ')"
    }
    $approvedImageAssetIds = @(
        Invoke-AiMediaCli -Arguments @("list-assets", "--project-id", $ProjectId) |
            ForEach-Object {
                $columns = ([string]$_) -split "`t"
                if (
                    $columns.Count -ge 5 -and
                    $columns[2] -eq "scene_visual" -and
                    $columns[3] -eq "approved" -and
                    $columns[4] -eq "approved"
                ) {
                    $columns[0]
                }
            }
    )

    $evaluationIndex = 0
    foreach ($initialAssetId in $imageAssetIds) {
        $evaluationIndex += 1
        $assetId = $initialAssetId
        if ($approvedImageAssetIds -contains $assetId) {
            Write-Host "[$evaluationIndex/$($imageAssetIds.Count)] Visual $assetId is already approved; skipping review."
            continue
        }
        $revisionAttempt = 0
        $evaluationPercent = [Math]::Floor(($evaluationIndex / $imageAssetIds.Count) * 100)
        while ($true) {
            Write-Progress `
                -Activity "Evaluating and reviewing scene images" `
                -Status "Image $evaluationIndex of $($imageAssetIds.Count), revision $($revisionAttempt + 1)" `
                -PercentComplete $evaluationPercent
            if (-not $SkipImageEvaluation) {
                $reportPath = Join-Path $ReportDirectory "$assetId.json"
                $evaluationArguments = @(
                    "evaluate-image",
                    "--asset-id", $assetId,
                    "--model", $VisionModel,
                    "--minimum-width", [string]$Width,
                    "--minimum-height", [string]$Height,
                    "--output", $reportPath
                )
                if ($ReferenceAssetId) {
                    $evaluationArguments += @("--reference-asset-id", $ReferenceAssetId)
                }

                # A report must belong to this invocation; never accept a stale prior result.
                Remove-Item -LiteralPath $reportPath -Force -ErrorAction SilentlyContinue
                Write-Host "Evaluating visual $assetId with Ollama..."
                $evaluationResult = Invoke-AiMediaCliWithActivity `
                    -Arguments $evaluationArguments `
                    -Activity "Ollama image evaluation" `
                    -Status "Image $evaluationIndex of $($imageAssetIds.Count)"
                $evaluationExitCode = $evaluationResult.ExitCode
                if (
                    $null -ne $evaluationExitCode `
                    -and $evaluationExitCode -ne 0 `
                    -and $evaluationExitCode -ne 2
                ) {
                    throw "Ollama evaluation could not run for asset $assetId (exit $evaluationExitCode)."
                }
                if (-not (Test-Path -LiteralPath $reportPath -PathType Leaf)) {
                    $displayExitCode = if ($null -eq $evaluationExitCode) { "unknown" } else {
                        [string]$evaluationExitCode
                    }
                    throw "Ollama evaluation failed (exit $displayExitCode); report was not written: $reportPath"
                }
                $report = Get-Content -LiteralPath $reportPath -Raw | ConvertFrom-Json
                Write-Host (
                    "Decision={0}; relevance={1}; sharpness={2}; composition={3}; artifact-risk={4}" -f
                    $report.decision,
                    $report.vision.scene_relevance_score,
                    $report.vision.perceived_sharpness_score,
                    $report.vision.composition_score,
                    $report.vision.artifact_risk_score
                )
                if ($evaluationExitCode -eq 2 -or $report.decision -eq "FAIL") {
                    throw "Visual $assetId failed evaluation. Review $reportPath and regenerate it."
                }
            } else {
                Write-Host "Ollama evaluation skipped for visual $assetId. Human review is still required."
            }

            Write-Host "Preview URL: http://127.0.0.1:$DashboardPort/assets/$assetId/preview"
            $visualApproved = Confirm-Approval -Label "visual" -Identifier $assetId
            if ($visualApproved) {
                Invoke-AiMediaCli -Arguments @(
                    "review-asset", $assetId, "--status", "approved"
                ) | ForEach-Object { Write-Host $_ }
                break
            }

            do {
                $revisionFeedback = Read-Host "Why was this image rejected? Type STOP to end the run"
            } while (-not $revisionFeedback.Trim())
            Invoke-AiMediaCli -Arguments @(
                "review-asset", $assetId, "--status", "rejected",
                "--feedback", $revisionFeedback
            ) | ForEach-Object { Write-Host $_ }
            if ($revisionFeedback.Trim().ToUpperInvariant() -eq "STOP") {
                throw "Visual review was stopped by the user."
            }

            $revisionAttempt += 1
            $revisionSeed = $Seed + ($evaluationIndex - 1) + ($revisionAttempt * 10000)
            Write-Host "Regenerating only this scene from feedback with seed $revisionSeed..."
            $revisionOutput = Invoke-AiMediaCli -Arguments @(
                "regenerate-image-revision",
                "--asset-id", $assetId,
                "--feedback", $revisionFeedback,
                "--provider", "comfyui",
                "--model", $Checkpoint,
                "--workflow-path", $WorkflowPath,
                "--width", [string]$Width,
                "--height", [string]$Height,
                "--steps", "8",
                "--cfg", "1.0",
                "--sampler", "res_multistep",
                "--scheduler", "simple",
                "--timeout-seconds", [string]$GenerationTimeout,
                "--seed", [string]$revisionSeed,
                "--text-free",
                "--visual-style", "faceless_editorial",
                "--stage-for-review"
            )
            $assetId = Select-Identifier -Output $revisionOutput
            Write-Host "Created revised visual: $assetId"
        }
    }
    Write-Progress -Activity "Evaluating and reviewing scene images" -Completed

    Write-Host "Generating the 1080x1920 short production timeline..."
    $UseLayeredCharacterPack = $false
    if ($LayeredCharacters) {
        $CharacterPackRoot = Join-Path $RepositoryRoot "data\reports\layered-animation-demo\assets"
        Write-Host "Registering the approved layered host, support character, and story effect..."
        $layerPackOutput = Invoke-AiMediaCli -Arguments @(
            "ensure-layered-character-pack",
            "--project-id", $ProjectId,
            "--pack-root", $CharacterPackRoot
        )
        $layerPackOutput | ForEach-Object { Write-Host $_ }
        $UseLayeredCharacterPack = @(
            $layerPackOutput | Where-Object { [string]$_ -match '^[0-9a-fA-F-]{36}\t' }
        ).Count -gt 0
        if (-not $UseLayeredCharacterPack) {
            Write-Host "Using topic-aware scene art without the incompatible technology cast."
        }
    }
    $timelineArguments = @(
        "generate-timeline",
        "--project-id", $ProjectId,
        "--video-format", "short_vertical",
        "--style-profile", "reference_minimal_character_motion_v1",
        "--engagement-audio"
    )
    if ($DurationBasedTiming) { $timelineArguments += "--duration-based-timing" }
    if ($UseLayeredCharacterPack) { $timelineArguments += "--layered-characters" }
    $timelineOutput = Invoke-AiMediaCli -Arguments $timelineArguments
    $timelineId = Select-Identifier -Output $timelineOutput
    Invoke-AiMediaCli -Arguments @(
        "validate-timeline", "--timeline-version-id", $timelineId
    ) | ForEach-Object { Write-Host $_ }

    $approvalOutput = Invoke-AiMediaCli -Arguments @(
        "approve-timeline", "--timeline-version-id", $timelineId
    )
    $approvalId = Select-Identifier -Output $approvalOutput
    if (-not (Confirm-Approval -Label "timeline" -Identifier $timelineId)) {
        throw "Production stopped because the timeline was rejected."
    }
    Invoke-AiMediaCli -Arguments @(
        "approve", $approvalId, "--feedback", "Approved during local short production run"
    ) | ForEach-Object { Write-Host $_ }

    Write-Host "Rendering the approved short timeline..."
    $renderOutput = Invoke-AiMediaCli -Arguments @(
        "render-timeline", "--timeline-version-id", $timelineId
    )
    $renderId = Select-Identifier -Output $renderOutput
    Invoke-AiMediaCli -Arguments @(
        "verify-render", "--render-id", $renderId
    ) | ForEach-Object { Write-Host $_ }

    Write-Host "Render URL: http://127.0.0.1:$DashboardPort/renders/$renderId/preview"
    if (-not (Confirm-Approval -Label "render" -Identifier $renderId)) {
        throw "Production stopped because the render was rejected."
    }
    Invoke-AiMediaCli -Arguments @(
        "review-render", $renderId, "--status", "approved"
    ) | ForEach-Object { Write-Host $_ }

    Write-Host "Production complete. Render ID: $renderId"
    Invoke-AiMediaCli -Arguments @(
        "list-renders", "--project-id", $ProjectId
    ) | ForEach-Object { Write-Host $_ }
}
finally {
    Pop-Location
}
