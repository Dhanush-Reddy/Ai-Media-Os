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
    [switch]$NoDashboard
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$launcher = Join-Path $PSScriptRoot "start-new-short-project.ps1"
$parameters = @{
    Quality = $Quality
    LayeredCharacters = $true
}
foreach ($name in @(
    "ChannelId", "WorkingTitle", "Topic", "ScriptFile", "ReferenceProjectId", "ResumeProjectId"
)) {
    $value = Get-Variable -Name $name -ValueOnly
    if ($value) {
        $parameters[$name] = $value
    }
}
if ($NoDashboard) {
    $parameters.NoDashboard = $true
}

Write-Host "Starting layered short production with duration timing and semantic sound design..."
& $launcher @parameters
exit $LASTEXITCODE
