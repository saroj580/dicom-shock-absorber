#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Validates host environment prerequisites for ProRadCS Edge Gateway deployment.

.DESCRIPTION
    Executes pre-installation verification checks according to IEC 62304 / ProRadCS
    engineering governance standards:
      1. Verifies 64-bit Windows Architecture and OS build >= 17763 (Win 10/11/Server 2019+).
      2. Verifies Microsoft Visual C++ 2015-2022 Redistributable (x64) installation.
      3. Verifies archive storage volume capacity (>= 20 GB free space).
      4. Verifies TCP Port 104 (DICOM C-STORE) and Port 8080 (Web Dashboard) availability.

.PARAMETER TargetDrive
    Drive letter hosting D:\DICOM_Archive storage. Default: 'D'.
    Falls back to system drive if specified drive does not exist.

.PARAMETER MinDiskSpaceGB
    Minimum required free space in gigabytes. Default: 20.

.PARAMETER DicomPort
    TCP port for incoming C-STORE associations. Default: 104.

.PARAMETER WebPort
    TCP port for local Web Dashboard REST API. Default: 8080.

.PARAMETER PassThru
    Outputs a structured PSCustomObject containing check results.

.OUTPUTS
    Exit Code 0  : Verification Passed (All prerequisites met).
    Exit Code 10 : Prerequisite Missing (OS version, VC++ Redistributable, Disk Space).
    Exit Code 20 : Port Conflict (Port 104 or 8080 already bound).
    Exit Code 30 : Security / Permission Error.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidatePattern('^[a-zA-Z]$')]
    [string]$TargetDrive = "D",

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 10000)]
    [int]$MinDiskSpaceGB = 20,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$DicomPort = 104,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$WebPort = 8080,

    [Parameter(Mandatory = $false)]
    [switch]$PassThru
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_PORT_CONFLICT = 20
$EXIT_SECURITY_ERROR = 30

$checksPassed = $true
$portConflict = $false
$results = [ordered]@{}

Write-Host "  ProRadCS Enterprise DICOM Gateway - Host Prerequisite Verification  " -ForegroundColor Cyan
Write-Host "  Specification: IEC 62304 Class B | Target Account: PacsServiceWorker " -ForegroundColor Cyan


Write-Host "[1/4] Checking Operating System & Architecture..." -NoNewline
try {
    $is64Bit = [System.Environment]::Is64BitOperatingSystem
    $osVersion = [System.Environment]::OSVersion.Version
    $buildNumber = $osVersion.Build

    # Required: 64-bit Windows, Build >= 17763 (Windows 10 1809 / Server 2019 or later)
    if (-not $is64Bit) {
        Write-Host " [FAIL]" -ForegroundColor Red
        Write-Host "      Error: ProRadCS requires a 64-bit operating system." -ForegroundColor Red
        $checksPassed = $false
        $results["OS_Architecture"] = "32-bit (Unsupported)"
    }
    elseif ($buildNumber -lt 17763) {
        Write-Host " [FAIL]" -ForegroundColor Red
        Write-Host "      Error: OS Build $buildNumber is below minimum requirement 17763 (Win 10 1809 / Server 2019)." -ForegroundColor Red
        $checksPassed = $false
        $results["OS_Build"] = "$buildNumber (Unsupported, requires >= 17763)"
    }
    else {
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      OS: Windows Build $buildNumber (64-bit architecture confirmed)." -ForegroundColor Gray
        $results["OS_Architecture"] = "64-bit"
        $results["OS_Build"] = $buildNumber
    }
}
catch {
    Write-Host " [ERROR]" -ForegroundColor Red
    Write-Host "      Unexpected error evaluating OS version: $_" -ForegroundColor Red
    exit $EXIT_SECURITY_ERROR
}

# -----------------------------------------------------------------------------
# 2. Microsoft Visual C++ 2015-2022 Redistributable (x64) Verification
# -----------------------------------------------------------------------------
Write-Host "[2/4] Checking Visual C++ 2015-2022 Redistributable (x64)..." -NoNewline
$vcRedistInstalled = $false
$vcVersion = "Not Found"

$vcRegPaths = @(
    "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
)

foreach ($path in $vcRegPaths) {
    if (Test-Path $path) {
        $regItem = Get-ItemProperty -Path $path -ErrorAction SilentlyContinue
        if ($null -ne $regItem -and $regItem.PSObject.Properties["Installed"] -and $regItem.Installed -eq 1) {
            $vcRedistInstalled = $true
            if ($regItem.PSObject.Properties["Version"]) {
                $vcVersion = $regItem.Version
            }
            break
        }
    }
}

# Fallback: check Installer dependencies registry
if (-not $vcRedistInstalled -and (Test-Path "HKLM:\SOFTWARE\Classes\Installer\Dependencies")) {
    $depKeys = Get-ChildItem "HKLM:\SOFTWARE\Classes\Installer\Dependencies" -ErrorAction SilentlyContinue
    foreach ($k in $depKeys) {
        if ($k.PSChildName -like "*VC,redist.x64*") {
            $vcRedistInstalled = $true
            $vcVersion = $k.PSChildName
            break
        }
    }
}

if ($vcRedistInstalled) {
    Write-Host " [PASS]" -ForegroundColor Green
    Write-Host "      Visual C++ Runtime: $vcVersion detected." -ForegroundColor Gray
    $results["VCRedist_x64"] = $vcVersion
}
else {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "      Error: Microsoft Visual C++ 2015-2022 Redistributable (x64) is not installed." -ForegroundColor Red
    Write-Host "      Required for pylibjpeg-openjpeg lossless transcoding binaries." -ForegroundColor Red
    $checksPassed = $false
    $results["VCRedist_x64"] = "Missing"
}

# -----------------------------------------------------------------------------
# 3. Disk Space Verification on Archive Storage Drive
# -----------------------------------------------------------------------------
Write-Host "[3/4] Checking Archive Storage Capacity ($($TargetDrive.ToUpper()):\)..." -NoNewline
$driveInfo = Get-PSDrive -Name $TargetDrive -PSProvider FileSystem -ErrorAction SilentlyContinue

if ($null -eq $driveInfo) {
    # If target drive does not exist, check system drive as fallback
    $sysDriveName = $env:SystemDrive.TrimEnd(':')
    Write-Host " [WARN]" -ForegroundColor Yellow
    Write-Host "      Target drive '$($TargetDrive):' not mounted. Checking SystemDrive '$($sysDriveName):'..." -ForegroundColor Yellow
    $driveInfo = Get-PSDrive -Name $sysDriveName -PSProvider FileSystem -ErrorAction SilentlyContinue
}

if ($null -ne $driveInfo) {
    $freeBytes = $driveInfo.Free
    $freeGB = [math]::Round($freeBytes / 1GB, 2)

    if ($freeGB -ge $MinDiskSpaceGB) {
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      Drive $($driveInfo.Name):\ has $freeGB GB free space (Minimum: $MinDiskSpaceGB GB)." -ForegroundColor Gray
        $results["DiskSpace_FreeGB"] = $freeGB
        $results["DiskSpace_Drive"] = $driveInfo.Name
    }
    else {
        Write-Host " [FAIL]" -ForegroundColor Red
        Write-Host "      Error: Drive $($driveInfo.Name):\ has only $freeGB GB free (Required: >= $MinDiskSpaceGB GB)." -ForegroundColor Red
        $checksPassed = $false
        $results["DiskSpace_FreeGB"] = $freeGB
        $results["DiskSpace_Drive"] = $driveInfo.Name
    }
}
else {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "      Error: Unable to locate a valid filesystem volume to verify storage capacity." -ForegroundColor Red
    $checksPassed = $false
    $results["DiskSpace"] = "Drive Unavailable"
}

# -----------------------------------------------------------------------------
# 4. Network Port Availability (Ports 104 and 8080)
# -----------------------------------------------------------------------------
Write-Host "[4/4] Checking Port Availability (DICOM: $DicomPort, Web: $WebPort)..." -NoNewline
$activeListeners = [System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()
$activePorts = $activeListeners | ForEach-Object { $_.Port }

$dicomPortBusy = $activePorts -contains $DicomPort
$webPortBusy = $activePorts -contains $WebPort

if ($dicomPortBusy -or $webPortBusy) {
    Write-Host " [FAIL]" -ForegroundColor Red
    if ($dicomPortBusy) {
        Write-Host "      Error: Port $DicomPort (DICOM C-STORE) is already bound by another process." -ForegroundColor Red
        $results["Port_$DicomPort"] = "CONFLICT"
    }
    if ($webPortBusy) {
        Write-Host "      Error: Port $WebPort (Web Dashboard) is already bound by another process." -ForegroundColor Red
        $results["Port_$WebPort"] = "CONFLICT"
    }
    $portConflict = $true
}
else {
    Write-Host " [PASS]" -ForegroundColor Green
    Write-Host "      Port $DicomPort (DICOM) and Port $WebPort (HTTP) are free and available." -ForegroundColor Gray
    $results["Port_$DicomPort"] = "AVAILABLE"
    $results["Port_$WebPort"] = "AVAILABLE"
}

# -----------------------------------------------------------------------------
# Final Outcome Determination
# -----------------------------------------------------------------------------
Write-Host "----------------------------------------------------------------------" -ForegroundColor Cyan

if ($PassThru) {
    [PSCustomObject]$results
}

if ($portConflict) {
    Write-Host "Pre-installation checks failed: Port Conflict detected." -ForegroundColor Red
    exit $EXIT_PORT_CONFLICT
}

if (-not $checksPassed) {
    Write-Host "Pre-installation checks failed: Missing prerequisites." -ForegroundColor Red
    exit $EXIT_PREREQ_MISSING
}

Write-Host "All host prerequisites successfully verified. System ready for installation." -ForegroundColor Green
exit $EXIT_SUCCESS
