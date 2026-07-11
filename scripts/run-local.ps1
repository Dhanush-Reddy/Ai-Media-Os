[CmdletBinding()]
param(
    [ValidateSet("fake", "ollama")]
    [string]$Provider = "fake",

    [string]$Model = "qwen3:8b",

    [switch]$Setup,

    [switch]$BootstrapProject,

    [switch]$NoDashboard,

    [string]$HostAddress = "127.0.0.1",

    [ValidateRange(1, 65535)]
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$venvDirectory = Join-Path $repositoryRoot ".venv"
$python = Join-Path $venvDirectory "Scripts\python.exe"

Push-Location $repositoryRoot
try {
    if ($Setup -and -not (Test-Path -LiteralPath $python)) {
        $pythonLauncher = Get-Command py -ErrorAction SilentlyContinue
        if ($null -eq $pythonLauncher) {
            throw "Python launcher 'py' was not found. Install Python 3.12 first."
        }
        Write-Host "Creating Python 3.12 virtual environment..."
        & py -3.12 -m venv $venvDirectory
        if ($LASTEXITCODE -ne 0) {
            throw "Virtual environment creation failed."
        }
    }

    if (-not (Test-Path -LiteralPath $python)) {
        throw "Virtual environment not found. Run this script again with -Setup."
    }

    if ($Setup) {
        Write-Host "Installing AI Media OS and development dependencies..."
        & $python -m pip install -e ".[dev]"
        if ($LASTEXITCODE -ne 0) {
            throw "Project installation failed."
        }
    }

    Write-Host "Applying database migrations..."
    & $python -m alembic upgrade head
    if ($LASTEXITCODE -ne 0) {
        throw "Database migration failed."
    }

    $env:AI_MEDIA_OS_TEXT_PROVIDER_DEFAULT = $Provider
    if ($Provider -eq "ollama") {
        $env:AI_MEDIA_OS_OLLAMA_DEFAULT_MODEL = $Model
        if ($null -eq (Get-Command ollama -ErrorAction SilentlyContinue)) {
            throw "Ollama is not installed. Install it, run 'ollama pull $Model', then 'ollama serve'."
        }
    }

    Write-Host "Checking text provider '$Provider'..."
    & $python -m ai_media_os.cli check-llm-provider --provider $Provider --model $Model
    if ($LASTEXITCODE -ne 0) {
        throw "Text provider check failed. For Ollama, confirm the server and model are available."
    }

    if ($BootstrapProject) {
        $channelSlug = "ai-future"
        $channelName = "AI & Future"
        $workingTitle = "AI Weekly Update"

        $channelId = $null
        $channelRows = & $python -m ai_media_os.cli list-channels
        foreach ($row in $channelRows) {
            $columns = $row -split "`t"
            if ($columns.Count -ge 2 -and $columns[1] -eq $channelSlug) {
                $channelId = $columns[0]
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($channelId)) {
            $channelId = (& $python -m ai_media_os.cli create-channel `
                --name $channelName `
                --slug $channelSlug `
                --niche "AI" `
                --language "en" | Select-Object -Last 1).Trim()
        }

        $projectId = $null
        $projectRows = & $python -m ai_media_os.cli list-projects --channel-id $channelId
        foreach ($row in $projectRows) {
            $columns = $row -split "`t"
            if ($columns.Count -ge 4 -and $columns[3] -eq $workingTitle) {
                $projectId = $columns[0]
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($projectId)) {
            $projectId = (& $python -m ai_media_os.cli create-project `
                --channel-id $channelId `
                --working-title $workingTitle `
                --topic "Recent changes in artificial intelligence" `
                --target-duration-seconds 420 | Select-Object -Last 1).Trim()
        }

        Write-Host "Channel ID: $channelId"
        Write-Host "Project ID: $projectId"
    }

    if ($NoDashboard) {
        Write-Host "Local checks completed. Dashboard startup was skipped."
        return
    }

    Write-Host "Starting AI Media OS at http://${HostAddress}:$Port"
    Write-Host "Press Ctrl+C to stop."
    & $python -m ai_media_os.cli dashboard --host $HostAddress --port $Port
}
finally {
    Pop-Location
}
