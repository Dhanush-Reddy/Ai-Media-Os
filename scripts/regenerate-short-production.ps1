[CmdletBinding(DefaultParameterSetName = "NewProject")]
param(
    [Parameter(Mandatory = $true, ParameterSetName = "ExistingProject")]
    [string]$ProjectId,

    [Parameter(Mandatory = $true, ParameterSetName = "NewProject")]
    [string]$ChannelId,

    [Parameter(Mandatory = $true, ParameterSetName = "NewProject")]
    [string]$WorkingTitle,

    [Parameter(Mandatory = $true, ParameterSetName = "NewProject")]
    [string]$Topic,

    [Parameter(Mandatory = $true, ParameterSetName = "NewProject")]
    [string]$ScriptFile,

    [Parameter(ParameterSetName = "NewProject")]
    [string]$Description,

    [Parameter(ParameterSetName = "NewProject")]
    [int]$TargetDurationSeconds = 45,

    [ValidateSet("1080p", "4k")]
    [string]$Quality = "1080p",

    [string]$VisionModel = "qwen3-vl:4b",
    [string]$ReferenceAssetId,
    [string]$ImageCheckpoint = "z_image_turbo_bf16.safetensors",
    [string]$ImageWorkflowPath = "workflows/comfyui/z_image_turbo_v001.json",
    [string]$VoiceReferenceAudio = "C:\AI-Models\Chatterbox\voices\shorts-narrator.wav",
    [string]$VoiceName = "shorts-narrator",
    [string]$Language = "en",
    [string]$WhisperXPythonPath = $env:AI_MEDIA_OS_WHISPERX_PYTHON_PATH,
    [string]$WhisperXModelPath = $env:AI_MEDIA_OS_WHISPERX_MODEL_PATH,
    [ValidateSet("auto", "cuda", "cpu")]
    [string]$WhisperXDevice = "auto",
    [string]$WhisperXComputeType,
    [double]$Exaggeration = 0.6,
    [double]$CfgWeight = 0.4,
    [ValidateSet("fake", "ollama")]
    [string]$MetadataProvider = "ollama",
    [string]$TextModel,
    [int]$Seed = 0,
    [string]$ReferenceProjectId,
    [switch]$ReusePendingNarration,
    [switch]$SkipNarrationAlignment,
    [switch]$LayeredCharacters,
    [int]$DashboardPort = 8000,
    [switch]$NoDashboard,
    [switch]$SkipImageEvaluation,
    [switch]$SkipPackaging,
    [switch]$SkipSafetyGate
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$RunId = (Get-Date).ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
$IsNewProject = $PSCmdlet.ParameterSetName -eq "NewProject"
$Stage = 0

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Virtual environment Python was not found: $Python"
}
if (-not (Test-Path -LiteralPath $VoiceReferenceAudio -PathType Leaf)) {
    throw "Chatterbox reference audio was not found: $VoiceReferenceAudio"
}
if (-not $SkipNarrationAlignment) {
    if (-not $WhisperXPythonPath) {
        $WhisperXPythonPath = "C:\AI-Models\WhisperX\venv\Scripts\python.exe"
    }
    if (-not $WhisperXModelPath) {
        $WhisperXModelPath = "C:\AI-Models\WhisperX\models\wav2vec2-en"
    }
    if (-not (Test-Path -LiteralPath $WhisperXPythonPath -PathType Leaf)) {
        throw "WhisperX Python was not found: $WhisperXPythonPath"
    }
    if (-not (Test-Path -LiteralPath $WhisperXModelPath -PathType Container)) {
        throw "WhisperX model directory was not found: $WhisperXModelPath"
    }
    $env:AI_MEDIA_OS_WHISPERX_PYTHON_PATH = (Resolve-Path $WhisperXPythonPath).Path
    $env:AI_MEDIA_OS_WHISPERX_MODEL_PATH = (Resolve-Path $WhisperXModelPath).Path
    $whisperWorker = Join-Path $RepositoryRoot `
        "src\ai_media_os\providers\whisperx_alignment_worker.py"
    if ($WhisperXDevice -eq "auto") {
        $workerHealthOutput = @(& $env:AI_MEDIA_OS_WHISPERX_PYTHON_PATH $whisperWorker --health)
        if ($LASTEXITCODE -ne 0) {
            throw "WhisperX isolated runtime health probe failed: $($workerHealthOutput -join ' | ')"
        }
        try {
            $workerHealth = $workerHealthOutput -join "`n" | ConvertFrom-Json
        }
        catch {
            throw "WhisperX isolated runtime returned an invalid health response."
        }
        $WhisperXDevice = if ($workerHealth.cuda_available -eq $true) { "cuda" } else { "cpu" }
    }
    if (-not $WhisperXComputeType) {
        $WhisperXComputeType = if ($WhisperXDevice -eq "cuda") { "float16" } else { "int8" }
    }
    $env:AI_MEDIA_OS_WHISPERX_DEVICE = $WhisperXDevice
    $env:AI_MEDIA_OS_WHISPERX_COMPUTE_TYPE = $WhisperXComputeType
}

if ($IsNewProject) {
    if (-not (Test-Path -LiteralPath $ScriptFile -PathType Leaf)) {
        throw "The new project's Markdown script file was not found: $ScriptFile"
    }
    $createProjectArguments = @(
        "-m", "ai_media_os.cli", "create-project",
        "--channel-id", $ChannelId, "--working-title", $WorkingTitle,
        "--topic", $Topic, "--target-duration-seconds", [string]$TargetDurationSeconds
    )
    if ($Description) { $createProjectArguments += @("--description", $Description) }
    $projectOutput = @(& $Python @createProjectArguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw "New project creation failed: $($projectOutput -join ' | ')"
    }
    $projectIdLine = $projectOutput | Where-Object {
        [string]$_ -match '^[0-9a-fA-F-]{36}$'
    } | Select-Object -Last 1
    if (-not $projectIdLine) {
        throw "New project creation did not return a project ID."
    }
    $ProjectId = [string]$projectIdLine
}

$RunRoot = Join-Path $RepositoryRoot "data\reports\production-runs\$ProjectId"
$ReviewPackageRoot = Join-Path $RunRoot "review-package"
$RunLog = Join-Path $RunRoot "$RunId.log"
$SummaryPath = Join-Path $RunRoot "$RunId.json"
$BaseStages = if ($SkipPackaging) { 6 } elseif ($SkipSafetyGate) { 9 } else { 10 }
$TotalStages = $BaseStages + $(if ($IsNewProject) { 2 } else { 0 }) `
    - $(if ($SkipNarrationAlignment) { 1 } else { 0 })
New-Item -ItemType Directory -Force -Path $RunRoot, $ReviewPackageRoot | Out-Null

if ($Seed -eq 0) {
    $Seed = [int]([DateTimeOffset]::UtcNow.ToUnixTimeSeconds() % 2000000000)
}

$Summary = [ordered]@{
    schema_version = "1.0"
    run_id = $RunId
    project_id = $ProjectId
    new_project = $IsNewProject
    working_title = $(if ($IsNewProject) { $WorkingTitle } else { $null })
    seed = $Seed
    started_at_utc = [DateTime]::UtcNow.ToString("o")
    completed_at_utc = $null
    status = "running"
    narration_asset_ids = @()
    alignment_version_ids = @()
    narration_timing = $(if ($SkipNarrationAlignment) { "duration_based" } else { "whisperx" })
    render_id = $null
    metadata_version_id = $null
    thumbnail_concept_version_id = $null
    thumbnail_asset_id = $null
    publishing_gate_status = $null
    dashboard_url = "http://127.0.0.1:$DashboardPort"
    dashboard_process_id = $null
    review_package_root = $ReviewPackageRoot
    reference_asset_id = $ReferenceAssetId
    reference_project_id = $ReferenceProjectId
    error = $null
}

function Save-RunSummary {
    $temporary = "$SummaryPath.tmp"
    $Summary | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $temporary -Encoding UTF8
    Move-Item -LiteralPath $temporary -Destination $SummaryPath -Force
}

function Add-RunLogLine {
    param([AllowEmptyString()][string]$Message)

    $payload = $Message + [Environment]::NewLine
    foreach ($attempt in 1..5) {
        try {
            [System.IO.File]::AppendAllText(
                $RunLog,
                $payload,
                [System.Text.UTF8Encoding]::new($false)
            )
            return
        }
        catch [System.IO.IOException] {
            if ($attempt -eq 5) {
                Write-Warning "Could not append to run log after 5 attempts: $($_.Exception.Message)"
                return
            }
            Start-Sleep -Milliseconds (100 * $attempt)
        }
        catch [System.UnauthorizedAccessException] {
            Write-Warning "Could not append to run log: $($_.Exception.Message)"
            return
        }
    }
}

function Write-RunMessage {
    param([Parameter(Mandatory = $true)][string]$Message)

    $timestamped = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $Message
    Write-Host $timestamped
    Add-RunLogLine -Message $timestamped
}

function Set-ProductionStage {
    param([Parameter(Mandatory = $true)][string]$Name)

    $script:Stage += 1
    $percent = [Math]::Floor((($script:Stage - 1) / $TotalStages) * 100)
    Write-Progress -Id 1 -Activity "AI Media OS full short regeneration" `
        -Status "Stage $script:Stage of $TotalStages`: $Name" -PercentComplete $percent
    Write-RunMessage "STAGE $script:Stage/$TotalStages - $Name"
}

function Test-LocalDashboard {
    try {
        $response = Invoke-WebRequest -Uri $Summary.dashboard_url -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200 -and $response.Content -match "AI Media OS"
    }
    catch {
        return $false
    }
}

function Start-LocalDashboard {
    if ($NoDashboard) { return }
    if (Test-LocalDashboard) {
        Write-RunMessage "Dashboard already running: $($Summary.dashboard_url)"
        return
    }

    $dashboardStdout = Join-Path $RunRoot "$RunId-dashboard.out.log"
    $dashboardStderr = Join-Path $RunRoot "$RunId-dashboard.err.log"
    $process = Start-Process -FilePath $Python -ArgumentList @(
        "-m", "ai_media_os.cli", "dashboard",
        "--host", "127.0.0.1", "--port", [string]$DashboardPort
    ) -PassThru -WindowStyle Hidden `
        -RedirectStandardOutput $dashboardStdout -RedirectStandardError $dashboardStderr
    $Summary.dashboard_process_id = $process.Id
    Save-RunSummary
    foreach ($attempt in 1..30) {
        if (Test-LocalDashboard) {
            Write-RunMessage "Dashboard started: $($Summary.dashboard_url)"
            return
        }
        if ($process.HasExited) {
            $errorOutput = if (Test-Path -LiteralPath $dashboardStderr) {
                Get-Content -LiteralPath $dashboardStderr -Raw
            } else { "No dashboard error output was written." }
            throw "Dashboard failed to start: $errorOutput"
        }
        Start-Sleep -Milliseconds 500
    }
    throw "Dashboard did not become ready at $($Summary.dashboard_url)."
}

function Invoke-AiMediaCli {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $output = @(& $Python -m ai_media_os.cli @Arguments 2>&1)
    $exitCode = $LASTEXITCODE
    $output | ForEach-Object {
        Write-Host $_
        Add-RunLogLine -Message ([string]$_)
    }
    if ($exitCode -ne 0) {
        throw "AI Media OS command failed ($exitCode): $($Arguments -join ' ')"
    }
    return @($output | ForEach-Object { [string]$_ })
}

function Invoke-AiMediaCliLong {
    param(
        [Parameter(Mandatory = $true)][string[]]$Arguments,
        [Parameter(Mandatory = $true)][string]$Activity,
        [int]$EstimatedSeconds = 120,
        [int[]]$AcceptedExitCodes = @(0)
    )

    $startedAt = Get-Date
    try {
        Write-Progress -Id 2 -ParentId 1 -Activity $Activity `
            -Status "Running local provider command..." -PercentComplete 1
        $output = [System.Collections.Generic.List[string]]::new()
        $previousErrorActionPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = "Continue"
            & $Python -m ai_media_os.cli @Arguments 2>&1 | ForEach-Object {
                $line = [string]$_
                $output.Add($line)
                Write-Host $line
                Add-RunLogLine -Message $line
            }
            $exitCode = $LASTEXITCODE
        }
        finally {
            $ErrorActionPreference = $previousErrorActionPreference
        }
        if ($null -eq $exitCode) {
            throw "AI Media OS command did not return an exit code: $($Arguments -join ' ')"
        }
        if ($AcceptedExitCodes -notcontains $exitCode) {
            throw "AI Media OS command failed ($exitCode): $($Arguments -join ' ')"
        }
        $elapsed = [int]((Get-Date) - $startedAt).TotalSeconds
        Write-RunMessage "$Activity completed in ${elapsed}s."
        return @($output)
    }
    finally {
        Write-Progress -Id 2 -ParentId 1 -Activity $Activity -Completed
    }
}

function Select-Identifiers {
    param([Parameter(Mandatory = $true)][object[]]$Output)

    return @(
        $Output | ForEach-Object {
            if ([string]$_ -match '^([0-9a-fA-F-]{36})(?:\t|$)') { $Matches[1] }
        }
    )
}

function Select-Identifier {
    param([Parameter(Mandatory = $true)][object[]]$Output)

    $identifiers = @(Select-Identifiers -Output $Output)
    if ($identifiers.Count -eq 0) {
        throw "The command did not return an identifier. Output: $($Output -join ' | ')"
    }
    return $identifiers[-1]
}

function Resolve-ReferenceAssetId {
    param(
        [string]$ReferenceAssetId,
        [string]$ReferenceProjectId
    )

    if ($ReferenceAssetId) {
        return $ReferenceAssetId
    }
    if (-not $ReferenceProjectId) {
        return $null
    }

    $rows = Invoke-AiMediaCli -Arguments @("list-assets", "--project-id", $ReferenceProjectId)
    $approvedImages = @()
    foreach ($row in $rows) {
        $columns = $row -split "`t"
        if ($columns.Count -lt 5) { continue }
        if (
            $columns[2] -in @("scene_visual", "reference") -and
            $columns[3] -eq "approved" -and
            $columns[4] -eq "approved"
        ) {
            $approvedImages += $columns[0]
        }
    }

    if ($approvedImages.Count -eq 0) {
        throw "No approved reference image was found in project $ReferenceProjectId."
    }

    return $approvedImages[-1]
}

function Find-ReusableNarrationAssets {
    param([Parameter(Mandatory = $true)][string]$VideoProjectId)

    $rows = @(Invoke-AiMediaCli -Arguments @("list-assets", "--project-id", $VideoProjectId))
    return @(
        $rows | ForEach-Object {
            $columns = ([string]$_) -split "`t"
            if (
                $columns.Count -ge 5 -and
                $columns[2] -eq "scene_narration" -and
                $columns[3] -in @("generated", "approved") -and
                $columns[4] -in @("pending_review", "approved")
            ) {
                [pscustomobject]@{
                    AssetId = $columns[0]
                    SceneNumber = [int]$columns[1]
                    ReviewStatus = $columns[4]
                }
            }
        } | Sort-Object SceneNumber
    )
}

function Read-ReviewDecision {
    param(
        [Parameter(Mandatory = $true)][string]$Kind,
        [Parameter(Mandatory = $true)][string]$Identifier,
        [string]$PreviewUrl
    )

    Write-Host ""
    Write-Host "Review $Kind $Identifier"
    if ($PreviewUrl) { Write-Host "Preview: $PreviewUrl" }
    Write-Host "  1. Approve"
    Write-Host "  2. Reject and stop"
    while ($true) {
        $decision = Read-Host "Choose 1 or 2"
        if ($decision -in @("1", "2")) { return $decision }
        Write-Host "Enter 1 or 2." -ForegroundColor Yellow
    }
}

function Find-PendingApproval {
    param(
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][string]$ContentVersionId
    )

    $rows = Invoke-AiMediaCli -Arguments @(
        "list-approvals", "--project-id", $ProjectId,
        "--type", $Type, "--status", "pending"
    )
    foreach ($row in $rows) {
        $columns = $row -split "`t"
        if ($columns.Count -ge 4 -and $columns[3] -eq $ContentVersionId) {
            return $columns[0]
        }
    }
    throw "Pending $Type approval was not found for $ContentVersionId."
}

function Request-And-DecideApproval {
    param(
        [Parameter(Mandatory = $true)][string]$Type,
        [Parameter(Mandatory = $true)][string]$ContentVersionId,
        [Parameter(Mandatory = $true)][string]$Kind
    )

    Invoke-AiMediaCli -Arguments @(
        "request-approval", "--project-id", $ProjectId,
        "--type", $Type, "--content-version-id", $ContentVersionId
    ) | Out-Null
    $approvalId = Find-PendingApproval -Type $Type -ContentVersionId $ContentVersionId
    $decision = Read-ReviewDecision -Kind $Kind -Identifier $ContentVersionId
    Invoke-AiMediaCli -Arguments @(
        "review-approval", $approvalId, "--decision", $decision,
        "--feedback", "Reviewed during full short regeneration run $RunId"
    ) | Out-Null
    if ($decision -eq "2") { throw "$Kind was rejected. Production stopped." }
}

$ResolvedReferenceAssetId = Resolve-ReferenceAssetId `
    -ReferenceAssetId $ReferenceAssetId `
    -ReferenceProjectId $ReferenceProjectId
if ($ResolvedReferenceAssetId) {
    $Summary.reference_asset_id = $ResolvedReferenceAssetId
}
if ($IsNewProject) {
    Copy-Item -LiteralPath $ScriptFile -Destination (Join-Path $ReviewPackageRoot "source-script.md") -Force
}
if ($ReferenceProjectId -and -not $ReferenceAssetId) {
    Write-RunMessage "Resolved reference asset $ResolvedReferenceAssetId from project $ReferenceProjectId"
}
if ($ResolvedReferenceAssetId -or $ReferenceProjectId) {
    $referenceContextPath = Join-Path $ReviewPackageRoot "reference-context.json"
    [ordered]@{
        reference_asset_id = $ResolvedReferenceAssetId
        reference_project_id = $ReferenceProjectId
        reference_source = $(if ($ReferenceAssetId) { "explicit_asset" } elseif ($ReferenceProjectId) { "project" } else { $null })
    } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $referenceContextPath -Encoding UTF8
}
Save-RunSummary

Push-Location $RepositoryRoot
try {
    Save-RunSummary
    Write-RunMessage "Run ID: $RunId"
    Write-RunMessage "Project: $ProjectId"
    Write-RunMessage "Generation seed: $Seed"

    Set-ProductionStage "Provider health checks"
    Start-LocalDashboard
    Invoke-AiMediaCli -Arguments @(
        "check-voice-provider", "--provider", "chatterbox",
        "--voice", $VoiceName, "--reference-audio", $VoiceReferenceAudio
    ) | Out-Null
    if (-not $SkipNarrationAlignment) {
        Invoke-AiMediaCli -Arguments @(
            "check-alignment-provider", "--provider", "whisperx"
        ) | Out-Null
    }
    Invoke-AiMediaCli -Arguments @(
        "check-image-provider", "--provider", "comfyui", "--model", $ImageCheckpoint
    ) | Out-Null
    if (-not $SkipImageEvaluation) {
        Invoke-AiMediaCli -Arguments @(
            "check-image-evaluator", "--model", $VisionModel
        ) | Out-Null
    }
    if (-not $SkipPackaging -and $MetadataProvider -eq "ollama") {
        $llmHealthArguments = @("check-llm-provider", "--provider", "ollama")
        if ($TextModel) { $llmHealthArguments += @("--model", $TextModel) }
        try {
            Invoke-AiMediaCli -Arguments $llmHealthArguments | Out-Null
        }
        catch {
            Write-RunMessage "Ollama metadata provider was unavailable; falling back to the fake metadata provider."
            $MetadataProvider = "fake"
            $TextModel = $null
        }
    }

    if ($IsNewProject) {
        Set-ProductionStage "Import and approve the new project script"
        $scriptContent = Get-Content -LiteralPath $ScriptFile -Raw
        if (-not $scriptContent.Trim()) { throw "The supplied script file is empty." }
        $scriptOutput = Invoke-AiMediaCli -Arguments @(
            "create-content-version", "--project-id", $ProjectId,
            "--type", "script", "--format", "markdown", "--content", $scriptContent
        )
        $scriptVersionId = Select-Identifier -Output $scriptOutput
        Request-And-DecideApproval -Type "script" -ContentVersionId $scriptVersionId `
            -Kind "script"

        Set-ProductionStage "Generate and approve a new scene plan"
        $scenePlanArguments = @(
            "generate-scene-plan", "--project-id", $ProjectId,
            "--script-version-id", $scriptVersionId,
            "--provider", $MetadataProvider
        )
        if ($TextModel) { $scenePlanArguments += @("--model", $TextModel) }
        $scenePlanOutput = Invoke-AiMediaCliLong -Arguments $scenePlanArguments `
            -Activity "Generating scene plan" -EstimatedSeconds 120
        $scenePlanVersionId = Select-Identifier -Output $scenePlanOutput
        $scenePlanApprovalId = Find-PendingApproval -Type "scene_plan" `
            -ContentVersionId $scenePlanVersionId
        $scenePlanDecision = Read-ReviewDecision -Kind "scene plan" `
            -Identifier $scenePlanVersionId
        Invoke-AiMediaCli -Arguments @(
            "review-approval", $scenePlanApprovalId, "--decision", $scenePlanDecision
        ) | Out-Null
        if ($scenePlanDecision -eq "2") {
            throw "Scene plan was rejected. Production stopped."
        }
    }
    else {
        $scenePlanRows = @(Invoke-AiMediaCli -Arguments @(
            "list-content-versions", "--project-id", $ProjectId, "--type", "scene_plan"
        ))
        $pendingScenePlanRow = $scenePlanRows | Where-Object {
            [string]$_ -match '^[0-9a-fA-F-]{36}\tv\d+\tpending_approval$'
        } | Select-Object -Last 1
        if ($pendingScenePlanRow -and [string]$pendingScenePlanRow -match '^([0-9a-fA-F-]{36})') {
            $scenePlanVersionId = $Matches[1]
            Set-ProductionStage "Review the pending scene plan"
            $scenePlanApprovalId = Find-PendingApproval -Type "scene_plan" `
                -ContentVersionId $scenePlanVersionId
            $scenePlanDecision = Read-ReviewDecision -Kind "scene plan" `
                -Identifier $scenePlanVersionId
            Invoke-AiMediaCli -Arguments @(
                "review-approval", $scenePlanApprovalId, "--decision", $scenePlanDecision
            ) | Out-Null
            if ($scenePlanDecision -eq "2") {
                throw "Scene plan was rejected. Production stopped."
            }
        }
    }

    Set-ProductionStage "Plan scene assets"
    Invoke-AiMediaCli -Arguments @(
        "plan-scene-assets", "--project-id", $ProjectId
    ) | Out-Null

    if ($ReusePendingNarration) {
        Set-ProductionStage "Complete missing Chatterbox narration"
    }
    else {
        Set-ProductionStage "Generate Chatterbox narration revisions"
    }
    $narrationArguments = @(
        "generate-project-narration", "--project-id", $ProjectId,
        "--provider", "chatterbox", "--reference-audio", $VoiceReferenceAudio,
        "--voice", $VoiceName, "--language", $Language,
        "--exaggeration", [string]$Exaggeration,
        "--cfg-weight", [string]$CfgWeight, "--seed", [string]$Seed,
        "--stage-for-review"
    )
    if ($ReusePendingNarration) { $narrationArguments += "--reuse-existing" }
    $narrationOutput = Invoke-AiMediaCliLong -Arguments $narrationArguments `
        -Activity "Generating Chatterbox narration" -EstimatedSeconds 300
    $narrationIds = @(Select-Identifiers -Output $narrationOutput)
    $reusableNarrations = @(Find-ReusableNarrationAssets -VideoProjectId $ProjectId)
    $approvedNarrationIds = @(
        $reusableNarrations | Where-Object { $_.ReviewStatus -eq "approved" } |
            Select-Object -ExpandProperty AssetId
    )
    if ($narrationIds.Count -eq 0) { throw "No narration asset IDs were returned." }
    $Summary.narration_asset_ids = $narrationIds
    Save-RunSummary

    Set-ProductionStage "Verify and review narration"
    $narrationIndex = 0
    foreach ($assetId in $narrationIds) {
        $narrationIndex += 1
        $percent = [Math]::Floor(($narrationIndex / $narrationIds.Count) * 100)
        Write-Progress -Id 2 -ParentId 1 -Activity "Review narration" `
            -Status "$narrationIndex of $($narrationIds.Count)" -PercentComplete $percent
        $audioVerification = @(Invoke-AiMediaCli -Arguments @(
            "verify-audio-asset", $assetId
        ))
        if ($audioVerification[-1] -ne "OK") {
            throw "Narration $assetId failed file verification: $($audioVerification -join ' | ')"
        }
        if ($approvedNarrationIds -contains $assetId) {
            Write-RunMessage "Narration $assetId is already approved; skipping review."
            continue
        }
        $decision = Read-ReviewDecision -Kind "narration" -Identifier $assetId `
            -PreviewUrl "$($Summary.dashboard_url)/assets/$assetId/preview"
        Invoke-AiMediaCli -Arguments @(
            "review-asset", $assetId, "--status", $decision
        ) | Out-Null
        if ($decision -eq "2") { throw "Narration $assetId was rejected. Production stopped." }
    }
    Write-Progress -Id 2 -ParentId 1 -Activity "Review narration" -Completed

    $alignmentIds = @()
    if ($SkipNarrationAlignment) {
        Write-RunMessage "WhisperX skipped. Using narration duration for captions and visual beats."
    }
    else {
        Set-ProductionStage "WhisperX narration alignment"
        $alignmentIndex = 0
        foreach ($assetId in $narrationIds) {
            $alignmentIndex += 1
            $alignmentOutput = Invoke-AiMediaCliLong -Arguments @(
                "align-narration", $assetId, "--provider", "whisperx",
                "--language", $Language, "--frame-rate", "30"
            ) -Activity "Aligning narration $alignmentIndex of $($narrationIds.Count)" `
                -EstimatedSeconds 180 -AcceptedExitCodes @(0, 2)
            $alignmentId = Select-Identifier -Output $alignmentOutput
            $alignmentIds += $alignmentId
            if ($alignmentOutput | Where-Object { [string]$_ -match '\t(?:warn|block)\t' }) {
                $Summary.alignment_version_ids = $alignmentIds
                Save-RunSummary
                throw "Narration alignment $alignmentId requires correction; its diagnostic version was preserved."
            }
        }
    }
    $Summary.alignment_version_ids = $alignmentIds
    Save-RunSummary

    Set-ProductionStage "Generate, evaluate, and approve scene images"
    $shortArguments = @(
        "-ExecutionPolicy", "Bypass", "-File", (Join-Path $PSScriptRoot "run-short-production.ps1"),
        "-ProjectId", $ProjectId, "-Quality", $Quality,
        "-VisionModel", $VisionModel, "-Checkpoint", $ImageCheckpoint,
        "-WorkflowPath", $ImageWorkflowPath, "-Seed", [string]$Seed,
        "-DashboardPort", [string]$DashboardPort
    )
    if ($IsNewProject) { $shortArguments += "-RegenerateImages" }
    if ($ReferenceAssetId) { $shortArguments += @("-ReferenceAssetId", $ReferenceAssetId) }
    if ($SkipImageEvaluation) { $shortArguments += "-SkipImageEvaluation" }
    if ($SkipNarrationAlignment) { $shortArguments += "-DurationBasedTiming" }
    if ($LayeredCharacters) { $shortArguments += "-LayeredCharacters" }
    $shortOutput = [System.Collections.Generic.List[string]]::new()
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & powershell.exe @shortArguments 2>&1 | ForEach-Object {
            $line = [string]$_
            $shortOutput.Add($line)
            Write-Host $line
            Add-RunLogLine -Message $line
        }
        $shortExitCode = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
    if ($shortExitCode -ne 0) { throw "Short image/timeline/render runner failed ($shortExitCode)." }
    $renderLine = $shortOutput | Where-Object { [string]$_ -match 'Render ID:\s*([0-9a-fA-F-]{36})' } | Select-Object -Last 1
    if (-not $renderLine -or [string]$renderLine -notmatch 'Render ID:\s*([0-9a-fA-F-]{36})') {
        throw "The short runner completed without returning a render ID."
    }
    $renderId = $Matches[1]
    $Summary.render_id = $renderId
    Save-RunSummary

    if (-not $SkipPackaging) {
        Set-ProductionStage "Generate and approve metadata"
        $metadataArguments = @(
            "generate-metadata", "--project-id", $ProjectId,
            "--render-id", $renderId, "--provider", $MetadataProvider
        )
        if ($TextModel) { $metadataArguments += @("--model", $TextModel) }
        $metadataOutput = Invoke-AiMediaCliLong -Arguments $metadataArguments `
            -Activity "Generating video metadata" -EstimatedSeconds 90
        $metadataId = Select-Identifier -Output $metadataOutput
        $Summary.metadata_version_id = $metadataId
        Save-RunSummary
        Invoke-AiMediaCli -Arguments @("review-metadata", $metadataId) | Out-Null
        $metadataApprovalId = Find-PendingApproval -Type "metadata" `
            -ContentVersionId $metadataId
        $metadataDecision = Read-ReviewDecision -Kind "metadata" -Identifier $metadataId
        Invoke-AiMediaCli -Arguments @(
            "review-approval", $metadataApprovalId, "--decision", $metadataDecision
        ) | Out-Null
        if ($metadataDecision -eq "2") { throw "Metadata was rejected. Production stopped." }

        Set-ProductionStage "Generate and approve thumbnail concept"
        $conceptArguments = @(
            "generate-thumbnail-concept", "--project-id", $ProjectId,
            "--metadata-version-id", $metadataId, "--provider", $MetadataProvider
        )
        if ($TextModel) { $conceptArguments += @("--model", $TextModel) }
        $conceptOutput = Invoke-AiMediaCliLong -Arguments $conceptArguments `
            -Activity "Generating thumbnail concept" -EstimatedSeconds 90
        $conceptId = Select-Identifier -Output $conceptOutput
        $Summary.thumbnail_concept_version_id = $conceptId
        Save-RunSummary
        Request-And-DecideApproval -Type "thumbnail" -ContentVersionId $conceptId `
            -Kind "thumbnail concept"

        Set-ProductionStage "Generate, verify, and review thumbnail"
        $thumbnailOutput = Invoke-AiMediaCli -Arguments @(
            "generate-thumbnail", "--project-id", $ProjectId,
            "--metadata-version-id", $metadataId,
            "--concept-version-id", $conceptId, "--seed", [string]$Seed
        )
        $thumbnailId = Select-Identifier -Output $thumbnailOutput
        $Summary.thumbnail_asset_id = $thumbnailId
        Save-RunSummary
        Invoke-AiMediaCli -Arguments @("verify-thumbnail-file", $thumbnailId) | Out-Null
        $thumbnailDecision = Read-ReviewDecision -Kind "thumbnail" -Identifier $thumbnailId `
            -PreviewUrl "$($Summary.dashboard_url)/assets/$thumbnailId/preview"
        Invoke-AiMediaCli -Arguments @(
            "review-thumbnail", $thumbnailId, "--status", $thumbnailDecision
        ) | Out-Null
        if ($thumbnailDecision -eq "2") { throw "Thumbnail was rejected. Production stopped." }

        if (-not $SkipSafetyGate) {
            Set-ProductionStage "Safety checks and publishing gate"
            foreach ($command in @(
                "check-asset-rights", "check-claims", "check-script-safety",
                "check-metadata-safety", "check-thumbnail-safety",
                "check-reused-content", "decide-ai-disclosure"
            )) {
                Invoke-AiMediaCli -Arguments @($command, "--project-id", $ProjectId) | Out-Null
            }
            $gateOutput = @(Invoke-AiMediaCli -Arguments @(
                "run-publishing-gate", "--project-id", $ProjectId,
                "--render-id", $renderId, "--metadata-version-id", $metadataId,
                "--thumbnail-asset-id", $thumbnailId
            ))
            $Summary.publishing_gate_status = $gateOutput[-1]
            Invoke-AiMediaCli -Arguments @(
                "show-safety-report", "--project-id", $ProjectId
            ) | Out-Null
        }
    }

    $Summary.status = "completed"
    $Summary.completed_at_utc = [DateTime]::UtcNow.ToString("o")
    Save-RunSummary
    Write-Progress -Id 1 -Activity "AI Media OS full short regeneration" -Completed
    Write-Host ""
    Write-Host "Production regeneration completed." -ForegroundColor Green
    Write-Host "Render ID: $($Summary.render_id)"
    Write-Host "Metadata ID: $($Summary.metadata_version_id)"
    Write-Host "Thumbnail ID: $($Summary.thumbnail_asset_id)"
    Write-Host "Publishing gate: $($Summary.publishing_gate_status)"
    Write-Host "Run summary: $SummaryPath"
    Write-Host "Run log: $RunLog"
}
catch {
    $Summary.status = "failed"
    $Summary.completed_at_utc = [DateTime]::UtcNow.ToString("o")
    $Summary.error = $_.Exception.Message
    Save-RunSummary
    Write-Progress -Id 1 -Activity "AI Media OS full short regeneration" -Completed
    Write-Host "Run failed. Existing approved versions were preserved." -ForegroundColor Red
    Write-Host "Run summary: $SummaryPath"
    throw
}
finally {
    Pop-Location
}
