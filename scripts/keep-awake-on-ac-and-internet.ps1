param(
    [int]$CheckIntervalSeconds = 30,
    [int]$ProbeTimeoutSeconds = 3,
    [string[]]$ProbeUris = @(
        'https://www.msftconnecttest.com/connecttest.txt',
        'https://www.google.com/generate_204'
    )
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ([System.Environment]::OSVersion.Platform -ne [System.PlatformID]::Win32NT) {
    throw 'This script is intended for Windows only.'
}

Add-Type -AssemblyName System.Windows.Forms

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class SleepControl
{
    [DllImport("kernel32.dll")]
    public static extern uint SetThreadExecutionState(uint esFlags);
}
"@

$script:ES_CONTINUOUS = [uint32][int64]2147483648
$script:ES_SYSTEM_REQUIRED = [uint32]0x00000001
$script:ES_DISPLAY_REQUIRED = [uint32]0x00000002

function Test-OnAcPower {
    try {
        $powerLineStatus = [System.Windows.Forms.SystemInformation]::PowerStatus.PowerLineStatus
        if ($powerLineStatus -eq [System.Windows.Forms.PowerLineStatus]::Online) {
            return $true
        }

        if ($powerLineStatus -eq [System.Windows.Forms.PowerLineStatus]::Offline) {
            return $false
        }
    } catch {
        # Fall back to the battery CIM class if the Windows Forms API is unavailable.
    }

    try {
        $battery = Get-CimInstance -ClassName Win32_Battery -ErrorAction Stop | Select-Object -First 1
        if ($null -eq $battery) {
            return $false
        }

        return $battery.BatteryStatus -in 2, 6, 7, 8, 9, 11
    } catch {
        return $false
    }
}

function Test-InternetConnection {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Uris,

        [Parameter(Mandatory = $true)]
        [int]$TimeoutSeconds
    )

    foreach ($uri in $Uris) {
        try {
            $response = Invoke-WebRequest -Uri $uri -Method Get -TimeoutSec $TimeoutSeconds -MaximumRedirection 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return $true
            }
        } catch {
            continue
        }
    }

    return $false
}

function Set-AwakeState {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Enable
    )

    if ($Enable) {
        [void][SleepControl]::SetThreadExecutionState(
            $script:ES_CONTINUOUS -bor $script:ES_SYSTEM_REQUIRED -bor $script:ES_DISPLAY_REQUIRED
        )
        return
    }

    [void][SleepControl]::SetThreadExecutionState($script:ES_CONTINUOUS)
}

function Write-StatusLine {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$OnAcPower,

        [Parameter(Mandatory = $true)]
        [bool]$InternetAvailable,

        [Parameter(Mandatory = $true)]
        [bool]$AwakeEnabled
    )

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Write-Host "[$timestamp] AC=$OnAcPower Internet=$InternetAvailable Awake=$AwakeEnabled"
}

$awakeEnabled = $false

try {
    while ($true) {
        $onAcPower = Test-OnAcPower
        $internetAvailable = $false

        if ($onAcPower) {
            $internetAvailable = Test-InternetConnection -Uris $ProbeUris -TimeoutSeconds $ProbeTimeoutSeconds
        }

        $shouldStayAwake = $onAcPower -and $internetAvailable

        if ($shouldStayAwake) {
            if (-not $awakeEnabled) {
                Set-AwakeState -Enable $true
                $awakeEnabled = $true
                Write-StatusLine -OnAcPower $onAcPower -InternetAvailable $internetAvailable -AwakeEnabled $awakeEnabled
            } else {
                # Refresh the execution-state request so the process continues to hold the wake lock.
                Set-AwakeState -Enable $true
            }
        } elseif ($awakeEnabled) {
            Set-AwakeState -Enable $false
            $awakeEnabled = $false
            Write-StatusLine -OnAcPower $onAcPower -InternetAvailable $internetAvailable -AwakeEnabled $awakeEnabled
        }

        Start-Sleep -Seconds $CheckIntervalSeconds
    }
} finally {
    if ($awakeEnabled) {
        Set-AwakeState -Enable $false
    }
}
