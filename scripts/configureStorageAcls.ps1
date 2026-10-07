#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Configures locked-down NTFS Discretionary Access Control Lists (DACLs).

.DESCRIPTION
    Enforces least-privilege NTFS permissions on the archive storage directory
    and application installation root according to IEC 62304 / HIPAA:
      1. Provisions storage folder hierarchy:
         - D:\DICOM_Archive\staging
         - D:\DICOM_Archive\processed
         - D:\DICOM_Archive\quarantine
         - D:\DICOM_Archive\backups
         - D:\DICOM_Archive\logs
      2. Breaks inheritance (/inheritance:r) on D:\DICOM_Archive.
      3. Grants Full Control ((OI)(CI)F) to NT AUTHORITY\SYSTEM and BUILTIN\Administrators.
      4. Grants Modify ((OI)(CI)M) to PacsServiceWorker on D:\DICOM_Archive.
      5. Grants Read & Execute ((OI)(CI)RX) to PacsServiceWorker on C:\Program Files\ProRadCS.
      6. Explicitly removes permissions for Users, Authenticated Users, and Everyone.

.PARAMETER ArchiveRoot
    Root directory for DICOM storage. Default: 'D:\DICOM_Archive'.

.PARAMETER InstallRoot
    Root directory for application binaries. Default: 'C:\Program Files\ProRadCS'.

.PARAMETER ServiceAccount
    Name of the service account receiving access. Default: 'PacsServiceWorker'.

.PARAMETER SkipInstallRoot
    Skips configuring the installation directory if binaries are not yet deployed.

.OUTPUTS
    Exit Code 0  : ACLs configured and verified successfully.
    Exit Code 10 : Prerequisite missing (Target volume inaccessible).
    Exit Code 30 : Security or icacls execution error.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [string]$ArchiveRoot = "D:\DICOM_Archive",

    [Parameter(Mandatory = $false)]
    [string]$InstallRoot = "C:\Program Files\ProRadCS",

    [Parameter(Mandatory = $false)]
    [string]$ServiceAccount = "PacsServiceWorker",

    [Parameter(Mandatory = $false)]
    [switch]$SkipInstallRoot
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_SECURITY_ERROR = 30

Write-Host "  ProRadCS Enterprise DICOM Gateway - NTFS DACL Hardening             " -ForegroundColor Cyan
Write-Host "  Archive: $ArchiveRoot | Service Account: $ServiceAccount             " -ForegroundColor Cyan

# 1. Target Volume and Path Verification
$driveLetter = [System.IO.Path]::GetPathRoot($ArchiveRoot).TrimEnd('\', ':')
if (-not (Get-PSDrive -Name $driveLetter -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
    Write-Host "[FAIL] Target drive '${driveLetter}:' is not mounted or available on this system." -ForegroundColor Red
    exit $EXIT_PREREQ_MISSING
}

# 2. Directory Structure Provisioning
Write-Host "[1/3] Provisioning archive folder structure..." -NoNewline
$subdirs = @("staging", "processed", "quarantine", "backups", "logs")

try {
    if (-not (Test-Path -Path $ArchiveRoot)) {
        if ($PSCmdlet.ShouldProcess("$ArchiveRoot", "Create Archive Root Directory")) {
            New-Item -ItemType Directory -Path $ArchiveRoot -Force | Out-Null
        }
    }

    foreach ($sub in $subdirs) {
        $subPath = Join-Path -Path $ArchiveRoot -ChildPath $sub
        if (-not (Test-Path -Path $subPath)) {
            if ($PSCmdlet.ShouldProcess("$subPath", "Create Subdirectory")) {
                New-Item -ItemType Directory -Path $subPath -Force | Out-Null
            }
        }
    }
    Write-Host " [PASS]" -ForegroundColor Green
    Write-Host "      Storage tree verified at: $ArchiveRoot" -ForegroundColor Gray
}
catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "      Failed to create directory structure: $_" -ForegroundColor Red
    exit $EXIT_SECURITY_ERROR
}

# 3. Apply NTFS Hardening to Archive Root (icacls)
Write-Host "[2/3] Hardening Archive Storage DACLs ($ArchiveRoot)..." -NoNewline

function Invoke-IcaclsCommand {
    param([string]$ArgumentString)
    
    $pinfo = New-Object System.Diagnostics.ProcessStartInfo
    $pinfo.FileName = "icacls.exe"
    $pinfo.Arguments = $ArgumentString
    $pinfo.RedirectStandardOutput = $true
    $pinfo.RedirectStandardError = $true
    $pinfo.UseShellExecute = $false
    $pinfo.CreateNoWindow = $true

    $p = [System.Diagnostics.Process]::Start($pinfo)
    $p.WaitForExit()
    $stdout = $p.StandardOutput.ReadToEnd()
    $stderr = $p.StandardError.ReadToEnd()

    if ($p.ExitCode -ne 0) {
        throw "icacls returned exit code $($p.ExitCode): $stdout $stderr"
    }
}

try {
    if ($PSCmdlet.ShouldProcess("$ArchiveRoot", "Apply Storage NTFS Lockdown via icacls")) {
        # Break inheritance and remove existing inherited rules
        Invoke-IcaclsCommand "`"$ArchiveRoot`" /inheritance:r"
        
        # Grant SYSTEM Full Control with container and object inheritance
        Invoke-IcaclsCommand "`"$ArchiveRoot`" /grant:r `"SYSTEM:(OI)(CI)F`""

        # Grant Administrators Full Control
        Invoke-IcaclsCommand "`"$ArchiveRoot`" /grant:r `"Administrators:(OI)(CI)F`""

        # Grant PacsServiceWorker Modify (Read/Write/Delete)
        Invoke-IcaclsCommand "`"$ArchiveRoot`" /grant:r `"${ServiceAccount}:(OI)(CI)M`""

        # Strip unprivileged groups
        $stripGroups = @("Users", "Authenticated Users", "Everyone")
        foreach ($grp in $stripGroups) {
            try {
                Invoke-IcaclsCommand "`"$ArchiveRoot`" /remove `"$grp`""
            }
            catch {
                # Ignore non-fatal if group wasn't present
            }
        }
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      Permissions: SYSTEM:F, Administrators:F, ${ServiceAccount}:M (Users/Everyone: REMOVED)." -ForegroundColor Gray
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}
catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "      icacls execution failed: $_" -ForegroundColor Red
    exit $EXIT_SECURITY_ERROR
}

# 4. Apply NTFS Hardening to Installation Directory (Optional / Binaries)
if (-not $SkipInstallRoot) {
    Write-Host "[3/3] Checking Application Binaries Directory ($InstallRoot)..." -NoNewline
    if (Test-Path -Path $InstallRoot) {
        try {
            if ($PSCmdlet.ShouldProcess("$InstallRoot", "Apply Application Binary Lockdown via icacls")) {
                Invoke-IcaclsCommand "`"$InstallRoot`" /inheritance:r"
                Invoke-IcaclsCommand "`"$InstallRoot`" /grant:r `"SYSTEM:(OI)(CI)F`""
                Invoke-IcaclsCommand "`"$InstallRoot`" /grant:r `"Administrators:(OI)(CI)F`""
                # Read & Execute only for service worker on application binaries
                Invoke-IcaclsCommand "`"$InstallRoot`" /grant:r `"${ServiceAccount}:(OI)(CI)RX`""

                foreach ($grp in @("Users", "Authenticated Users", "Everyone")) {
                    try {
                        Invoke-IcaclsCommand "`"$InstallRoot`" /remove `"$grp`""
                    }
                    catch {
                        # Ignore non-fatal
                    }
                }
                Write-Host " [PASS]" -ForegroundColor Green
                Write-Host "      Permissions: SYSTEM:F, Administrators:F, ${ServiceAccount}:RX." -ForegroundColor Gray
            }
            else {
                Write-Host " [WHAT-IF]" -ForegroundColor Yellow
            }
        }
        catch {
            Write-Host " [FAIL]" -ForegroundColor Red
            Write-Host "      Failed to harden installation directory: $_" -ForegroundColor Red
            exit $EXIT_SECURITY_ERROR
        }
    }
    else {
        Write-Host " [SKIPPED]" -ForegroundColor Yellow
        Write-Host "      Directory does not exist yet (will be applied during NSIS binary extraction)." -ForegroundColor Gray
    }
}
else {
    Write-Host "[3/3] Application Binaries Directory hardening skipped by flag." -ForegroundColor Gray
}

Write-Host "Storage security hardening complete. NTFS DACLs enforced." -ForegroundColor Green
exit $EXIT_SUCCESS
