[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$SourceAudio,

    [string]$SourceVideo,
    [string]$SourceUrl = "https://www.youtube.com/watch?v=2aoLsF3-2gI",
    [string]$Creator = "TechKeyFi",
    [string]$License = "UNKNOWN",
    [switch]$CommercialUseConfirmed
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepositoryRoot = Split-Path -Parent $PSScriptRoot
$Ffmpeg = if ($env:AI_MEDIA_OS_FFMPEG_PATH) {
    $env:AI_MEDIA_OS_FFMPEG_PATH
}
else {
    "C:\AI-Tools\ffmpeg\ffmpeg-8.1.2-essentials_build\bin\ffmpeg.exe"
}

if (-not (Test-Path -LiteralPath $SourceAudio -PathType Leaf)) {
    throw "Source audio was not found: $SourceAudio"
}
if (-not (Test-Path -LiteralPath $Ffmpeg -PathType Leaf)) {
    throw "FFmpeg was not found: $Ffmpeg"
}
if ($CommercialUseConfirmed -and $License -eq "UNKNOWN") {
    throw "A specific license or permission record is required for commercial use."
}

$SafetyState = if ($CommercialUseConfirmed) { "SAFE" } else { "UNKNOWN" }
$Collection = "techkeyfi-2aoLsF3-2gI"
$RelativeRoot = if ($CommercialUseConfirmed) {
    "inputs/sfx-library/approved/$Collection"
}
else {
    "inputs/sfx-library/quarantine/$Collection"
}
$OutputRoot = Join-Path $RepositoryRoot ($RelativeRoot -replace "/", "\")
New-Item -ItemType Directory -Force -Path $OutputRoot | Out-Null

$Definitions = @(
    @{ Number = 1; Name = "whoosh"; Start = 1.25; End = 2.00; Category = "transition"; Tags = @("whoosh", "movement", "scene_open") },
    @{ Number = 2; Name = "gear"; Start = 2.00; End = 3.50; Category = "mechanical"; Tags = @("gear", "machine", "process") },
    @{ Number = 3; Name = "click"; Start = 3.75; End = 4.75; Category = "ui"; Tags = @("click", "selection", "interface") },
    @{ Number = 4; Name = "pop"; Start = 4.75; End = 6.00; Category = "ui"; Tags = @("pop", "appearance", "emphasis") },
    @{ Number = 5; Name = "cash-register"; Start = 6.00; End = 7.25; Category = "money"; Tags = @("money", "cost", "revenue", "price") },
    @{ Number = 6; Name = "aww"; Start = 7.25; End = 9.00; Category = "reaction"; Tags = @("aww", "emotional", "cute") },
    @{ Number = 7; Name = "wrong-answer"; Start = 9.25; End = 11.25; Category = "reaction"; Tags = @("wrong", "failure", "warning") },
    @{ Number = 8; Name = "fire-whoosh"; Start = 11.50; End = 13.25; Category = "transition"; Tags = @("whoosh", "fire", "fast_transition") },
    @{ Number = 9; Name = "game-point"; Start = 13.75; End = 14.50; Category = "ui"; Tags = @("point", "score", "success") },
    @{ Number = 10; Name = "discord-join"; Start = 14.50; End = 15.25; Category = "notification"; Tags = @("discord", "join", "notification"); Blocked = $true },
    @{ Number = 11; Name = "discord-leave"; Start = 15.50; End = 16.50; Category = "notification"; Tags = @("discord", "leave", "notification"); Blocked = $true },
    @{ Number = 12; Name = "iphone-send"; Start = 16.75; End = 17.25; Category = "notification"; Tags = @("phone", "send", "message"); Blocked = $true },
    @{ Number = 13; Name = "iphone-receive"; Start = 17.75; End = 18.50; Category = "notification"; Tags = @("phone", "receive", "message"); Blocked = $true },
    @{ Number = 14; Name = "apple-notification"; Start = 18.75; End = 19.75; Category = "notification"; Tags = @("apple", "notification", "message"); Blocked = $true },
    @{ Number = 15; Name = "anime-wow"; Start = 20.00; End = 23.00; Category = "reaction"; Tags = @("wow", "surprise", "reveal") },
    @{ Number = 16; Name = "bone-crack"; Start = 23.25; End = 24.25; Category = "impact"; Tags = @("crack", "break", "impact") },
    @{ Number = 17; Name = "slap"; Start = 24.50; End = 25.50; Category = "impact"; Tags = @("slap", "hit", "comedy") },
    @{ Number = 18; Name = "camera-shutter"; Start = 25.50; End = 26.25; Category = "camera"; Tags = @("camera", "photo", "snapshot") },
    @{ Number = 19; Name = "whoosh-2"; Start = 26.50; End = 27.25; Category = "transition"; Tags = @("whoosh", "movement", "transition") },
    @{ Number = 20; Name = "paper"; Start = 27.75; End = 29.25; Category = "foley"; Tags = @("paper", "document", "page") },
    @{ Number = 21; Name = "kids-cheer"; Start = 29.75; End = 33.50; Category = "crowd"; Tags = @("kids", "cheer", "celebration", "success") },
    @{ Number = 22; Name = "display-digits"; Start = 33.75; End = 35.75; Category = "technology"; Tags = @("digits", "data", "counter", "technology") },
    @{ Number = 23; Name = "party-horn"; Start = 36.25; End = 37.25; Category = "celebration"; Tags = @("party", "celebration", "success") },
    @{ Number = 24; Name = "glitch-1"; Start = 37.75; End = 39.00; Category = "technology"; Tags = @("glitch", "error", "digital") },
    @{ Number = 25; Name = "anvil"; Start = 39.25; End = 40.50; Category = "impact"; Tags = @("anvil", "metal", "impact") },
    @{ Number = 26; Name = "cinematic-hit"; Start = 40.50; End = 44.75; Category = "impact"; Tags = @("cinematic", "impact", "reveal", "important") },
    @{ Number = 27; Name = "in-and-out"; Start = 45.00; End = 46.25; Category = "transition"; Tags = @("in", "out", "transition", "movement") },
    @{ Number = 28; Name = "sudden-suspense"; Start = 46.50; End = 47.75; Category = "suspense"; Tags = @("suspense", "question", "tension") },
    @{ Number = 29; Name = "boom"; Start = 48.00; End = 49.50; Category = "impact"; Tags = @("boom", "impact", "reveal") },
    @{ Number = 30; Name = "glass-shatter"; Start = 49.75; End = 51.00; Category = "impact"; Tags = @("glass", "shatter", "break") },
    @{ Number = 31; Name = "clock-ticking"; Start = 51.50; End = 53.50; Category = "time"; Tags = @("clock", "time", "deadline", "waiting") },
    @{ Number = 32; Name = "mario-coin"; Start = 53.75; End = 55.00; Category = "game"; Tags = @("coin", "game", "reward"); Blocked = $true },
    @{ Number = 33; Name = "crumpled-paper"; Start = 55.25; End = 57.75; Category = "foley"; Tags = @("paper", "discard", "failure", "revision") },
    @{ Number = 34; Name = "ding"; Start = 57.75; End = 59.00; Category = "ui"; Tags = @("ding", "complete", "success") },
    @{ Number = 35; Name = "glitch-2"; Start = 59.25; End = 61.75; Category = "technology"; Tags = @("glitch", "error", "digital", "failure") }
)

$Clips = @()
foreach ($Definition in $Definitions) {
    $FileName = "sfx-{0:d2}-{1}.wav" -f $Definition.Number, $Definition.Name
    $OutputPath = Join-Path $OutputRoot $FileName
    $Duration = [double]$Definition.End - [double]$Definition.Start
    & $Ffmpeg -y -hide_banner -loglevel error `
        -ss ([string]$Definition.Start) -t ([string]$Duration) -i $SourceAudio `
        -af "silenceremove=start_periods=1:start_silence=0.015:start_threshold=-42dB,areverse,silenceremove=start_periods=1:start_silence=0.015:start_threshold=-42dB,areverse,loudnorm=I=-18:TP=-2:LRA=11" `
        -ar 48000 -ac 2 -c:a pcm_s16le $OutputPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath -PathType Leaf)) {
        throw "Failed to extract sound $($Definition.Number): $($Definition.Name)"
    }
    $Hash = (Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256).Hash.ToLowerInvariant()
    $ClipBlocked = $Definition.ContainsKey("Blocked") -and $Definition.Blocked -eq $true
    $ClipSafetyState = if ($ClipBlocked) { "BLOCKED" } else { $SafetyState }
    $Clips += [ordered]@{
        id = "sfx-{0:d2}-{1}" -f $Definition.Number, $Definition.Name
        label = $Definition.Name
        category = $Definition.Category
        tags = $Definition.Tags
        source_start_seconds = $Definition.Start
        source_end_seconds = $Definition.End
        file_path = "$RelativeRoot/$FileName"
        sha256 = $Hash
        safety_state = $ClipSafetyState
        auto_usable = $CommercialUseConfirmed.IsPresent -and -not $ClipBlocked
    }
    Write-Host "[$($Definition.Number)/$($Definitions.Count)] $($Definition.Name)"
}

$Catalog = [ordered]@{
    schema_version = "1.0"
    collection = $Collection
    created_at_utc = [DateTime]::UtcNow.ToString("o")
    source = [ordered]@{
        url = $SourceUrl
        creator = $Creator
        audio_file = $SourceAudio
        video_file = $SourceVideo
        license = $License
        commercial_use_confirmed = $CommercialUseConfirmed.IsPresent
        safety_state = $SafetyState
    }
    clip_count = $Clips.Count
    clips = $Clips
}
$CatalogPath = Join-Path $OutputRoot "catalog.json"
$Catalog | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $CatalogPath -Encoding UTF8
Write-Host "Catalog: $CatalogPath"
Write-Host "Safety state: $SafetyState"
