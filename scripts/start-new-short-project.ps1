[CmdletBinding()]
param(
    [string]$ChannelId,
    [string]$WorkingTitle,
    [string]$Topic,
    [string]$ScriptFile,
    [string]$ReferenceProjectId,
    [string]$ResumeProjectId,
    [ValidateSet("1080p", "4k")]
    [string]$Quality = "1080p",
    [switch]$LayeredCharacters,
    [switch]$NoDashboard
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Python = Join-Path $RepositoryRoot ".venv\Scripts\python.exe"
$ProductionRunner = Join-Path $PSScriptRoot "regenerate-short-production.ps1"
$DefaultTestingScript = Join-Path $RepositoryRoot `
    "inputs\video-scripts\testing\new-video-script.md"

if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "Virtual environment Python was not found: $Python"
}
if (-not (Test-Path -LiteralPath $ProductionRunner -PathType Leaf)) {
    throw "Production runner was not found: $ProductionRunner"
}

Push-Location $RepositoryRoot
try {
    if ($ResumeProjectId) {
        $ResolvedResumeProjectId = $ResumeProjectId.Trim()
        $ResumeParameters = @{
            ProjectId = $ResolvedResumeProjectId
            Quality = $Quality
            MetadataProvider = "fake"
            SkipImageEvaluation = $true
            SkipNarrationAlignment = $true
            LayeredCharacters = $LayeredCharacters
        }
        $existingNarrationRows = @(
            & $Python -m ai_media_os.cli list-narration-assets `
                --project-id $ResolvedResumeProjectId
        )
        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect existing narration assets for the resumed project."
        }
        if ($existingNarrationRows | Where-Object { [string]$_ -match '^[0-9a-fA-F-]{36}\t' }) {
            $ResumeParameters.ReusePendingNarration = $true
        }
        if ($NoDashboard) {
            $ResumeParameters.NoDashboard = $true
        }
        Write-Host "Resuming project $ResumeProjectId with its pending narration assets..."
        & $ProductionRunner @ResumeParameters
        return
    }

    if (-not $ChannelId) {
        $ChannelOutput = @(& $Python -m ai_media_os.cli list-channels)
        if ($LASTEXITCODE -ne 0) {
            throw "Could not list channels."
        }
        $LatestChannelRow = $ChannelOutput | Where-Object {
            [string]$_ -match 'LATEST\s*$'
        } | Select-Object -Last 1
        if ($LatestChannelRow -and [string]$LatestChannelRow -match '^([0-9a-fA-F-]{36})') {
            $ChannelId = $Matches[1]
            Write-Host "Using the configured AI & Future channel."
        }
        else {
            throw "No latest channel is configured. Create the AI & Future channel once before running production."
        }
    }
    if (-not $WorkingTitle) {
        $WorkingTitle = Read-Host "Enter working title"
    }
    if (-not $Topic) {
        $Topic = Read-Host "Enter topic (press Enter to use working title)"
        if (-not $Topic) {
            $Topic = $WorkingTitle
        }
    }
    if (-not $ScriptFile) {
        $ScriptFile = Read-Host "Enter Markdown script path (press Enter for testing script)"
        if (-not $ScriptFile) {
            $ScriptFile = $DefaultTestingScript
        }
    }
    if (-not $ReferenceProjectId) {
        $ReferenceProjectId = Read-Host "Optional old project ID for visual reference (press Enter to skip)"
    }

    if (-not $ChannelId.Trim()) { throw "Channel ID is required." }
    if (-not $WorkingTitle.Trim()) { throw "Working title is required." }
    if (-not $Topic.Trim()) { throw "Topic is required." }
    if (-not $ScriptFile.Trim()) { throw "Markdown script path is required." }

    $ResolvedScriptFile = (Resolve-Path -LiteralPath $ScriptFile -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $ResolvedScriptFile -PathType Leaf)) {
        throw "Markdown script file was not found: $ResolvedScriptFile"
    }

    $RunnerParameters = @{
        ChannelId = $ChannelId.Trim()
        WorkingTitle = $WorkingTitle.Trim()
        Topic = $Topic.Trim()
        ScriptFile = $ResolvedScriptFile
        Quality = $Quality
        MetadataProvider = "fake"
        SkipImageEvaluation = $true
        SkipNarrationAlignment = $true
        LayeredCharacters = $LayeredCharacters
    }
    if ($ReferenceProjectId.Trim()) {
        $RunnerParameters.ReferenceProjectId = $ReferenceProjectId.Trim()
    }
    if ($NoDashboard) {
        $RunnerParameters.NoDashboard = $true
    }

    Write-Host ""
    $ProjectRunName = (Get-Date).ToString("yyyy-MM-dd_HH-mm-ss-fff")
    Write-Host "Project run: $ProjectRunName"
    Write-Host "Starting a new reviewable project with duration-based timing (no WhisperX)..."
    & $ProductionRunner @RunnerParameters
    if ($LASTEXITCODE -ne 0) {
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
