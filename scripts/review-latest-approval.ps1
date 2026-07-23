[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectId,

    [ValidateSet(
        "research",
        "script",
        "scene_plan",
        "metadata",
        "thumbnail",
        "publishing",
        "production_timeline"
    )]
    [string]$Type,

    [string]$ApprovalId,

    [switch]$ListOnly,

    [ValidateSet("1", "2", "3", "approved", "rejected", "changes_requested")]
    [string]$Decision,

    [string]$Feedback
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $repositoryRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Virtual-environment Python was not found: $python"
}

Push-Location $repositoryRoot
try {
    if (-not $ApprovalId) {
        $listArguments = @(
            "-m",
            "ai_media_os.cli",
            "list-approvals",
            "--project-id",
            $ProjectId,
            "--status",
            "pending"
        )
        if ($Type) {
            $listArguments += @("--type", $Type)
        }

        $rows = @(& $python @listArguments | Where-Object { $_.Trim() })
        if ($LASTEXITCODE -ne 0) {
            throw "Could not list approval requests (exit $LASTEXITCODE)."
        }
        if ($rows.Count -eq 0) {
            $filter = if ($Type) { " of type '$Type'" } else { "" }
            throw "No pending approval requests$filter were found for project $ProjectId."
        }

        Write-Host "Pending approvals (newest first):" -ForegroundColor Cyan
        Write-Host "APPROVAL_ID`tTYPE`tSTATUS`tCONTENT_VERSION_ID"
        $rows | ForEach-Object { Write-Host $_ }
        $ApprovalId = ($rows[0] -split "`t")[0]
        Write-Host "`nSelected newest approval: $ApprovalId" -ForegroundColor Yellow
    }

    if ($ListOnly) {
        return
    }

    $reviewArguments = @(
        "-m",
        "ai_media_os.cli",
        "review-approval",
        $ApprovalId
    )
    if ($Decision) {
        $reviewArguments += @("--decision", $Decision)
    }
    if ($Feedback) {
        $reviewArguments += @("--feedback", $Feedback)
    }

    & $python @reviewArguments
    if ($LASTEXITCODE -ne 0) {
        throw "Approval review failed (exit $LASTEXITCODE)."
    }
}
finally {
    Pop-Location
}
