
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Sets system-level PRCS_* machine environment variables.

.DESCRIPTION
    Injects persistent system environment variables into the Windows registry
    ([EnvironmentVariableTarget]::Machine). All ProRadCS background daemons
    read their configuration from these variables at startup to eliminate
    unencrypted on-disk .env file risks.
    Broadcasts WM_SETTINGCHANGE to notify running processes of configuration updates.

.PARAMETER AeTitle
    Local DICOM Application Entity Title. Default: 'PRCS_EDGE_01'.

.PARAMETER DicomPort
    Listening TCP port for incoming C-STORE associations. Default: 104.

.PARAMETER WebPort
    HTTP port for local telemetry and REST API. Default: 8080.

.PARAMETER ArchiveDir
    Root path for archive filesystem buffer. Default: 'D:\DICOM_Archive'.

.PARAMETER CloudEndpoint
    Upstream Cloud VNA DICOMweb STOW-RS URL. Default: 'https://vna.hospital.org/stow'.

.PARAMETER NodeToken
    Bearer authentication token / API key for upstream cloud relay. Default: ''.

.PARAMETER MaxRetries
    Maximum upload retry attempts before marking FAILED. Default: 5.

.PARAMETER DatabasePath
    File path to local SQLite database. Default: 'D:\DICOM_Archive\database.db'.

.PARAMETER PassThru
    Outputs a PSCustomObject containing all active machine variables.

.OUTPUTS
    Exit Code 0  : Variables successfully written and verified.
    Exit Code 10 : Prerequisite / parameter error.
    Exit Code 30 : Security / Registry permission error.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$AeTitle = "PRCS_EDGE_01",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$DicomPort = 104,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$WebPort = 8080,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$ArchiveDir = "D:\DICOM_Archive",

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$CloudEndpoint = "https://vna.hospital.org/stow",

    [Parameter(Mandatory = $false)]
    [string]$NodeToken = "",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 100)]
    [int]$MaxRetries = 5,

    [Parameter(Mandatory = $false)]
    [ValidateNotNullOrEmpty()]
    [string]$DatabasePath = "D:\DICOM_Archive\database.db",

    [Parameter(Mandatory = $false)]
    [switch]$PassThru
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_SECURITY_ERROR = 30


Write-Host "  ProRadCS Enterprise DICOM Gateway - System Environment Configuration " -ForegroundColor Cyan
Write-Host "  Target Scope: [EnvironmentVariableTarget]::Machine                   " -ForegroundColor Cyan

# 1. Variable Map Definition
$variableMap = [ordered]@{
    "PRCS_AE_TITLE"       = $AeTitle
    "PRCS_DICOM_PORT"     = $DicomPort.ToString()
    "PRCS_WEB_PORT"       = $WebPort.ToString()
    "PRCS_ARCHIVE_DIR"    = $ArchiveDir
    "PRCS_CLOUD_ENDPOINT" = $CloudEndpoint
    "PRCS_NODE_TOKEN"     = $NodeToken
    "PRCS_STOW_RETRY_MAX" = $MaxRetries.ToString()
    "PRCS_DATABASE_PATH"  = $DatabasePath
}

# 2. Set Machine Variables in Registry
$appliedValues = [ordered]@{}

try {
    foreach ($entry in $variableMap.GetEnumerator()) {
        $varName = $entry.Key
        $varValue = $entry.Value
        
        Write-Host "  Applying $varName = '$varValue'..." -NoNewline

        if ($PSCmdlet.ShouldProcess("$varName", "Set Machine Environment Variable")) {
            [System.Environment]::SetEnvironmentVariable(
                $varName,
                $varValue,
                [System.EnvironmentVariableTarget]::Machine
            )
            Write-Host " [OK]" -ForegroundColor Green
            $appliedValues[$varName] = $varValue
        }
        else {
            Write-Host " [WHAT-IF]" -ForegroundColor Yellow
            $appliedValues[$varName] = $varValue
        }
    }
}
catch {
    Write-Host "`n[FAIL] Failed writing system environment variable: $_" -ForegroundColor Red
    exit $EXIT_SECURITY_ERROR
}

# 3. Broadcast WM_SETTINGCHANGE to Windows Subsystem
Write-Host "`nBroadcasting WM_SETTINGCHANGE notification to Windows subsystem..." -NoNewline
try {
    $broadcastCode = @'
using System;
using System.Runtime.InteropServices;

public class Win32Notifier {
    [DllImport("user32.dll", SetLastError = true, CharSet = CharSet.Auto)]
    public static extern IntPtr SendMessageTimeout(
        IntPtr hWnd,
        uint Msg,
        UIntPtr wParam,
        string lParam,
        uint fuFlags,
        uint uTimeout,
        out UIntPtr lpdwResult
    );

    public static void NotifyEnvironmentChange() {
        IntPtr HWND_BROADCAST = new IntPtr(0xffff);
        uint WM_SETTINGCHANGE = 0x001a;
        uint SMTO_ABORTIFHUNG = 0x0002;
        UIntPtr result;
        SendMessageTimeout(HWND_BROADCAST, WM_SETTINGCHANGE, UIntPtr.Zero, "Environment", SMTO_ABORTIFHUNG, 3000, out result);
    }
}
'@

    if (-not ([System.Management.Automation.PSTypeName]'Win32Notifier').Type) {
        Add-Type -TypeDefinition $broadcastCode
    }

    if ($PSCmdlet.ShouldProcess("Environment", "Broadcast WM_SETTINGCHANGE")) {
        [Win32Notifier]::NotifyEnvironmentChange()
        Write-Host " [BROADCAST SENT]" -ForegroundColor Green
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}
catch {
    Write-Host " [WARN: Notification skipped, non-fatal: $_]" -ForegroundColor Yellow
}

# Output & Verification
Write-Host "All machine environment variables successfully registered." -ForegroundColor Green

if ($PassThru) {
    [PSCustomObject]$appliedValues
}

exit $EXIT_SUCCESS
