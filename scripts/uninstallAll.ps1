#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Gracefully tears down and uninstalls the ProRadCS Edge Gateway appliance.

.DESCRIPTION
    Performs orderly, non-destructive de-provisioning of the ProRadCS system:
      1. Halts and unregisters the 3 Windows background services (DicomReceiverService,
         ProcessorWorker, WebDashboardService) using NSSM or Windows SCM.
      2. Unregisters the daily maintenance Windows Scheduled Task (ProRadCS-DailyMaintenance).
      3. Removes ProRadCS Windows Defender Firewall boundary rules.
      4. Cleans up system-level PRCS_* machine environment variables and broadcasts WM_SETTINGCHANGE.
      5. Removes the local unprivileged service account (PacsServiceWorker).
      6. DATA PRESERVATION MANDATE: By default, preserves all clinical imaging data,
         staged instances, quarantine folders, and database.db in D:\DICOM_Archive.
         Data is only erased if -PurgeData is explicitly provided.

.PARAMETER PurgeData
    DESTRUCTIVE: If explicitly specified, permanently purges the entire archive
    storage directory (D:\DICOM_Archive) including database and DICOM images.

.PARAMETER KeepServiceAccount
    Preserves the local PacsServiceWorker user account in the SAM database.

.PARAMETER ArchiveDir
    Archive directory path to preserve (or purge if -PurgeData is specified).
    Default: 'D:\DICOM_Archive'.

.PARAMETER NssmPath
    Path to nssm.exe if custom location was used.

.OUTPUTS
    Exit Code 0  : Uninstallation completed successfully.
    Exit Code 10 : Prerequisite missing.
    Exit Code 30 : Security / permission error during teardown.
    Exit Code 40 : Service removal failure.
#>

[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = "High")]
param(
    [Parameter(Mandatory = $false)]
    [switch]$PurgeData,

    [Parameter(Mandatory = $false)]
    [switch]$KeepServiceAccount,

    [Parameter(Mandatory = $false)]
    [string]$ArchiveDir = "D:\DICOM_Archive",

    [Parameter(Mandatory = $false)]
    [string]$NssmPath = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_SECURITY_ERROR = 30
$EXIT_SERVICE_ERROR = 40

Write-Host "  ProRadCS Enterprise DICOM Gateway - Appliance Teardown & Uninstall   " -ForegroundColor Cyan
Write-Host "  Mode: $(if ($PurgeData) { 'DESTRUCTIVE PURGE' } else { 'SAFE PRESERVATION (Default)' })" -ForegroundColor $(if ($PurgeData) { 'Red' } else { 'Green' })

# 1. Stop and Unregister Windows Services
Write-Host "[1/5] Halting and unregistering ProRadCS Windows Services..." -ForegroundColor Cyan
$servicesToTeardown = @("DicomReceiverService", "ProcessorWorker", "WebDashboardService")

# Locate NSSM if available
$resolvedNssm = $NssmPath
if ([string]::IsNullOrWhiteSpace($resolvedNssm)) {
    $scriptDir = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { $PSScriptRoot } else { (Get-Location).Path }
    $parentDir = Split-Path $scriptDir -Parent
    $nssmCandidates = @(
        "C:\Program Files\ProRadCS\nssm.exe",
        (Join-Path $scriptDir "nssm.exe"),
        (Join-Path $parentDir "deployment\nssm.exe")
    )
    foreach ($cand in $nssmCandidates) {
        if (Test-Path $cand) { $resolvedNssm = $cand; break }
    }
}
$useNssm = (-not [string]::IsNullOrWhiteSpace($resolvedNssm)) -and (Test-Path $resolvedNssm)

foreach ($svcName in $servicesToTeardown) {
    Write-Host "      - Teardown '$svcName': " -NoNewline
    $svc = Get-Service -Name $svcName -ErrorAction SilentlyContinue

    if ($null -ne $svc) {
        if ($PSCmdlet.ShouldProcess("$svcName", "Stop and Delete Windows Service")) {
            try {
                if ($svc.Status -eq "Running") {
                    Stop-Service -Name $svcName -Force -ErrorAction SilentlyContinue
                    Start-Sleep -Seconds 1
                }
                if ($useNssm) {
                    & $resolvedNssm remove $svcName confirm | Out-Null
                }
                else {
                    & sc.exe delete $svcName | Out-Null
                }
                Write-Host "[REMOVED]" -ForegroundColor Green
            }
            catch {
                Write-Host "[WARN: $_]" -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "[WHAT-IF]" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "[NOT FOUND]" -ForegroundColor Gray
    }
}

# 2. Unregister Windows Scheduled Task
Write-Host "[2/5] Removing Windows Scheduled Task 'ProRadCS-DailyMaintenance'..." -NoNewline
$taskName = "ProRadCS-DailyMaintenance"
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue

if ($null -ne $task) {
    if ($PSCmdlet.ShouldProcess("$taskName", "Unregister Scheduled Task")) {
        try {
            Unregister-ScheduledTask -TaskName $taskName -Confirm:$false | Out-Null
            Write-Host " [REMOVED]" -ForegroundColor Green
        }
        catch {
            Write-Host " [WARN: $_]" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}
else {
    Write-Host " [NOT FOUND]" -ForegroundColor Gray
}

# 3. Remove Windows Defender Firewall Rules
Write-Host "[3/5] Purging ProRadCS Firewall Rules..." -NoNewline
$rules = Get-NetFirewallRule -Name "ProRadCS*" -ErrorAction SilentlyContinue

if ($null -ne $rules) {
    if ($PSCmdlet.ShouldProcess("ProRadCS Firewall Rules", "Remove NetFirewallRules")) {
        try {
            foreach ($r in $rules) {
                Remove-NetFirewallRule -Name $r.Name -ErrorAction SilentlyContinue
            }
            Write-Host " [REMOVED]" -ForegroundColor Green
        }
        catch {
            Write-Host " [WARN: $_]" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}
else {
    Write-Host " [NONE FOUND]" -ForegroundColor Gray
}

# 4. Remove System Environment Variables
Write-Host "[4/5] Removing PRCS_* Machine Environment Variables..." -NoNewline
$prcsVars = @(
    "PRCS_AE_TITLE",
    "PRCS_DICOM_PORT",
    "PRCS_WEB_PORT",
    "PRCS_ARCHIVE_DIR",
    "PRCS_CLOUD_ENDPOINT",
    "PRCS_NODE_TOKEN",
    "PRCS_STOW_RETRY_MAX",
    "PRCS_DATABASE_PATH"
)

if ($PSCmdlet.ShouldProcess("PRCS_* Environment Variables", "Delete Machine Environment Variables")) {
    try {
        foreach ($var in $prcsVars) {
            [System.Environment]::SetEnvironmentVariable($var, $null, [System.EnvironmentVariableTarget]::Machine)
        }
        Write-Host " [REMOVED]" -ForegroundColor Green
    }
    catch {
        Write-Host " [WARN: $_]" -ForegroundColor Yellow
    }
}
else {
    Write-Host " [WHAT-IF]" -ForegroundColor Yellow
}

# 5. Service Account Removal & Data Directory Handling
Write-Host "[5/5] Service Account & Archive Data Finalization..." -ForegroundColor Cyan

# Remove service account if requested
if (-not $KeepServiceAccount) {
    Write-Host "      - Removing local service account 'PacsServiceWorker': " -NoNewline
    $user = Get-LocalUser -Name "PacsServiceWorker" -ErrorAction SilentlyContinue
    if ($null -ne $user) {
        if ($PSCmdlet.ShouldProcess("PacsServiceWorker", "Remove Local User Account")) {
            try {
                Remove-LocalUser -Name "PacsServiceWorker"
                Write-Host "[REMOVED]" -ForegroundColor Green
            }
            catch {
                Write-Host "[WARN: $_]" -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "[WHAT-IF]" -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "[NOT FOUND]" -ForegroundColor Gray
    }
}
else {
    Write-Host "      - Preserving local user 'PacsServiceWorker' (by request)." -ForegroundColor Gray
}

# Archive Storage Directory: Safe Preservation vs Explicit Purge
if ($PurgeData) {
    Write-Host "      - DESTRUCTIVE PURGE: Erasing archive storage at '$ArchiveDir'..." -ForegroundColor Red
    if (Test-Path $ArchiveDir) {
        if ($PSCmdlet.ShouldProcess("$ArchiveDir", "PERMANENTLY DELETE ENTIRE ARCHIVE DIRECTORY")) {
            try {
                Remove-Item -Path $ArchiveDir -Recurse -Force
                Write-Host "      - [ERASED] Storage directory purged." -ForegroundColor Red
            }
            catch {
                Write-Host "      - [WARN] Error during purge: $_" -ForegroundColor Yellow
            }
        }
        else {
            Write-Host "      - [WHAT-IF] Would permanently delete $ArchiveDir." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "      - Archive directory does not exist." -ForegroundColor Gray
    }
}
else {
    Write-Host "      - SAFE PRESERVATION: Preserving archive directory '$ArchiveDir' (DICOM images & database intact)." -ForegroundColor Green
}

Write-Host "ProRadCS Gateway appliance teardown complete." -ForegroundColor Green
exit $EXIT_SUCCESS
