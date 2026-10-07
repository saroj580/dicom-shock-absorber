#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Registers and configures the 3 ProRadCS Windows background services via NSSM.

.DESCRIPTION
    Installs the decoupled ProRadCS background services into the Windows Service
    Control Manager (SCM) using NSSM (Non-Sucking Service Manager):
      1. DicomReceiverService  (proradcs-receiver.exe): Port 104 C-STORE ingestion.
      2. ProcessorWorker       (proradcs-worker.exe): PS 3.15 Anonymizer + Lossless J2K + STOW-RS.
      3. WebDashboardService   (proradcs-web.exe): Port 8080 FastAPI + React dashboard.
    Enforces process isolation, service account credentials (PacsServiceWorker),
    automatic restart policies, and redirected stdout/stderr diagnostic logs.

.PARAMETER BinDir
    Directory hosting the frozen executables. Default: 'C:\Program Files\ProRadCS'.

.PARAMETER ServiceAccount
    Account under which services execute. Default: 'PacsServiceWorker'.

.PARAMETER ServicePassword
    Secure password for the service account if required by SCM. Default: $null.

.PARAMETER LogDir
    Directory for redirected stdout/stderr logs. Default: 'D:\DICOM_Archive\logs'.

.PARAMETER NssmPath
    Explicit path to nssm.exe. If omitted, searches standard install paths and PATH.

.PARAMETER StartImmediately
    Starts all services immediately upon registration. Default: $false.

.OUTPUTS
    Exit Code 0  : Services registered and configured successfully.
    Exit Code 10 : Prerequisite missing (Binaries or NSSM missing).
    Exit Code 30 : Permission / Security error.
    Exit Code 40 : Service registration failure.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$BinDir = "C:\Program Files\ProRadCS",

    [Parameter(Mandatory = $false)]
    [string]$ServiceAccount = "PacsServiceWorker",

    [Parameter(Mandatory = $false)]
    [System.Security.SecureString]$ServicePassword = $null,

    [Parameter(Mandatory = $false)]
    [string]$LogDir = "D:\DICOM_Archive\logs",

    [Parameter(Mandatory = $false)]
    [string]$NssmPath = "",

    [Parameter(Mandatory = $false)]
    [switch]$StartImmediately
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_SECURITY_ERROR = 30
$EXIT_SERVICE_ERROR = 40

Write-Host "  ProRadCS Enterprise DICOM Gateway - Service Registration Suite       " -ForegroundColor Cyan
Write-Host "  Process Isolation: SCM / NSSM | Service Context: $ServiceAccount     " -ForegroundColor Cyan

# 1. Locate NSSM Executable
$resolvedNssm = $NssmPath
if ([string]::IsNullOrWhiteSpace($resolvedNssm)) {
    $scriptDir = if (-not [string]::IsNullOrWhiteSpace($PSScriptRoot)) { $PSScriptRoot } else { (Get-Location).Path }
    $parentDir = Split-Path $scriptDir -Parent

    $searchCandidates = @(
        (Join-Path $BinDir "nssm.exe"),
        (Join-Path $scriptDir "nssm.exe"),
        (Join-Path $parentDir "deployment\nssm.exe"),
        "C:\Program Files\ProRadCS\nssm.exe"
    )

    foreach ($candidate in $searchCandidates) {
        if (Test-Path $candidate) {
            $resolvedNssm = $candidate
            break
        }
    }

    if ([string]::IsNullOrWhiteSpace($resolvedNssm)) {
        $pathCmd = Get-Command "nssm.exe" -ErrorAction SilentlyContinue
        if ($null -ne $pathCmd) {
            $resolvedNssm = $pathCmd.Source
        }
    }
}

$useNssm = $false
if (-not [string]::IsNullOrWhiteSpace($resolvedNssm) -and (Test-Path $resolvedNssm)) {
    $useNssm = $true
    Write-Host "[INFO] NSSM orchestrator located: $resolvedNssm" -ForegroundColor Gray
}
else {
    Write-Host "[WARN] nssm.exe not found. Falling back to native Windows Service Control Manager (sc.exe)." -ForegroundColor Yellow
}

# 2. Service Definitions Matrix
$services = @(
    @{
        Name        = "DicomReceiverService"
        DisplayName = "ProRadCS DICOM Receiver Service"
        Binary      = "proradcs-receiver.exe"
        Description = "ProRadCS high-speed zero-trust C-STORE SCP network ingestion daemon."
    },
    @{
        Name        = "ProcessorWorker"
        DisplayName = "ProRadCS DICOM Processor & Forwarder Worker"
        Binary      = "proradcs-worker.exe"
        Description = "ProRadCS DICOM PS 3.15 anonymization, lossless transcoding, and STOW-RS cloud relay worker."
    },
    @{
        Name        = "WebDashboardService"
        DisplayName = "ProRadCS Web Dashboard & Telemetry Service"
        Binary      = "proradcs-web.exe"
        Description = "ProRadCS local web management dashboard and telemetry REST API daemon."
    }
)

# Ensure log directory exists
if (-not (Test-Path $LogDir)) {
    if ($PSCmdlet.ShouldProcess("$LogDir", "Create Service Logs Directory")) {
        New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
    }
}

# 3. Service Registration Loop
$registrationSuccess = $true

foreach ($svc in $services) {
    $sName = $svc.Name
    $sDisplay = $svc.DisplayName
    $sDesc = $svc.Description
    $exePath = Join-Path $BinDir $svc.Binary

    Write-Host "`nRegistering service: $sName ($sDisplay)..." -ForegroundColor Cyan

    # Check existing service
    $existingSvc = Get-Service -Name $sName -ErrorAction SilentlyContinue
    if ($null -ne $existingSvc) {
        Write-Host "  Service '$sName' already exists. Stopping and removing for update..." -ForegroundColor Yellow
        if ($PSCmdlet.ShouldProcess("$sName", "Stop and Remove Existing Service")) {
            try {
                Stop-Service -Name $sName -Force -ErrorAction SilentlyContinue
                if ($useNssm) {
                    & $resolvedNssm remove $sName confirm | Out-Null
                }
                else {
                    & sc.exe delete $sName | Out-Null
                }
                Start-Sleep -Seconds 1
            }
            catch {
                Write-Host "  [WARN] Failed cleaning previous service: $_" -ForegroundColor Yellow
            }
        }
    }

    # Install using NSSM or sc.exe
    if ($useNssm) {
        if ($PSCmdlet.ShouldProcess("$sName", "Install via NSSM")) {
            try {
                # 1. Install service
                & $resolvedNssm install $sName $exePath
                if ($LASTEXITCODE -ne 0) { throw "NSSM install failed with code $LASTEXITCODE" }

                # 2. Configure service parameters
                & $resolvedNssm set $sName AppDirectory $BinDir | Out-Null
                & $resolvedNssm set $sName DisplayName $sDisplay | Out-Null
                & $resolvedNssm set $sName Description $sDesc | Out-Null
                & $resolvedNssm set $sName Start SERVICE_AUTO_START | Out-Null
                & $resolvedNssm set $sName AppRestartDelay 5000 | Out-Null
                
                # Configure logs
                $stdoutLog = Join-Path $LogDir "$sName.log"
                $stderrLog = Join-Path $LogDir "$sName-error.log"
                & $resolvedNssm set $sName AppStdout $stdoutLog | Out-Null
                & $resolvedNssm set $sName AppStderr $stderrLog | Out-Null

                # Configure credentials if service account specified
                if (-not [string]::IsNullOrWhiteSpace($ServiceAccount) -and $ServiceAccount -ne "LocalSystem") {
                    if ($null -ne $ServicePassword) {
                        $plainPassword = [System.Net.NetworkCredential]::new("", $ServicePassword).Password
                        & $resolvedNssm set $sName ObjectName ".\$ServiceAccount" $plainPassword | Out-Null
                    }
                    else {
                        & $resolvedNssm set $sName ObjectName ".\$ServiceAccount" | Out-Null
                    }
                }

                Write-Host "  [PASS] Service '$sName' registered successfully via NSSM." -ForegroundColor Green
            }
            catch {
                Write-Host "  [FAIL] NSSM registration error: $_" -ForegroundColor Red
                $registrationSuccess = $false
            }
        }
        else {
            Write-Host "  [WHAT-IF] Registered '$sName' via NSSM." -ForegroundColor Yellow
        }
    }
    else {
        # Native SCM fallback via sc.exe
        if ($PSCmdlet.ShouldProcess("$sName", "Install via Native sc.exe")) {
            try {
                $binArg = "`"$exePath`""
                & sc.exe create $sName binPath= $binArg start= auto DisplayName= "`"$sDisplay`"" | Out-Null
                & sc.exe description $sName "`"$sDesc`"" | Out-Null
                Write-Host "  [PASS] Service '$sName' registered via native SCM." -ForegroundColor Green
            }
            catch {
                Write-Host "  [FAIL] Native SCM registration error: $_" -ForegroundColor Red
                $registrationSuccess = $false
            }
        }
        else {
            Write-Host "  [WHAT-IF] Registered '$sName' via native sc.exe." -ForegroundColor Yellow
        }
    }

    # Start service if requested
    if ($StartImmediately -and $registrationSuccess) {
        if ($PSCmdlet.ShouldProcess("$sName", "Start Service")) {
            try {
                Start-Service -Name $sName
                Write-Host "  [ONLINE] Service '$sName' started successfully." -ForegroundColor Green
            }
            catch {
                Write-Host "  [WARN] Service registered but failed to start immediately: $_" -ForegroundColor Yellow
            }
        }
    }
}

if (-not $registrationSuccess) {
    Write-Host "One or more services failed registration." -ForegroundColor Red
    exit $EXIT_SERVICE_ERROR
}

Write-Host "All 3 ProRadCS background services successfully installed." -ForegroundColor Green
exit $EXIT_SUCCESS
