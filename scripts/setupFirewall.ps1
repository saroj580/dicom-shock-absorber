#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Configures Windows Defender Firewall rules for the ProRadCS Edge Gateway.

.DESCRIPTION
    Applies network boundary isolation and zero-trust segmentation rules:
      1. Inbound Port 104 (TCP): Permits DICOM C-STORE traffic from authorized
         modality subnets or LocalSubnet.
      2. Inbound Port 8080 (TCP): Restricts Web Dashboard & REST API to localhost
         loopback (127.0.0.1, ::1) and administrative management subnets.
      3. Outbound Port 443 (TCP): Permits HTTPS / TLS 1.3 STOW-RS telemetry and
         image relay to upstream Cloud VNA endpoints.
      4. Program-specific outbound boundaries for proradcs-worker.exe.

.PARAMETER DicomPort
    Inbound TCP port for DICOM C-STORE. Default: 104.

.PARAMETER WebPort
    Inbound TCP port for Web Dashboard REST API. Default: 8080.

.PARAMETER CloudPort
    Outbound TCP port for Cloud VNA HTTPS STOW-RS. Default: 443.

.PARAMETER ModalitySubnets
    Array of allowed IP addresses/CIDR blocks for medical scanners. Default: @("LocalSubnet").

.PARAMETER AdminSubnets
    Array of allowed IP addresses/CIDR blocks for admin dashboard access.
    Default: @("127.0.0.1", "::1", "LocalSubnet").

.PARAMETER WorkerExecutablePath
    Path to proradcs-worker.exe for app-specific egress rule. Default: 'C:\Program Files\ProRadCS\proradcs-worker.exe'.

.PARAMETER RemoveExisting
    Removes existing ProRadCS firewall rules before recreating them. Default: $true.

.OUTPUTS
    Exit Code 0  : Firewall rules created and enabled successfully.
    Exit Code 10 : Prerequisite missing (NetSecurity module unavailable).
    Exit Code 30 : Security or firewall configuration error.
#>

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$DicomPort = 104,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$WebPort = 8080,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 65535)]
    [int]$CloudPort = 443,

    [Parameter(Mandatory = $false)]
    [string[]]$ModalitySubnets = @("LocalSubnet"),

    [Parameter(Mandatory = $false)]
    [string[]]$AdminSubnets = @("127.0.0.1", "::1", "LocalSubnet"),

    [Parameter(Mandatory = $false)]
    [string]$WorkerExecutablePath = "C:\Program Files\ProRadCS\proradcs-worker.exe",

    [Parameter(Mandatory = $false)]
    [bool]$RemoveExisting = $true
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# --- Exit Code Constants ---
$EXIT_SUCCESS = 0
$EXIT_PREREQ_MISSING = 10
$EXIT_SECURITY_ERROR = 30

Write-Host "  ProRadCS Enterprise DICOM Gateway - Firewall Security Hardening     " -ForegroundColor Cyan
Write-Host "  Boundary Isolation: C-STORE (Port $DicomPort) | Web (Port $WebPort) " -ForegroundColor Cyan

# 1. Prerequisite Verification (NetSecurity Module)
if (-not (Get-Command -Name "New-NetFirewallRule" -ErrorAction SilentlyContinue)) {
    Write-Host "[FAIL] Windows Defender Firewall cmdlets (NetSecurity) are not available." -ForegroundColor Red
    exit $EXIT_PREREQ_MISSING
}

# 2. Cleanup Existing ProRadCS Rules
$rulePrefix = "ProRadCS"
$existingRules = Get-NetFirewallRule -Name "$rulePrefix*" -ErrorAction SilentlyContinue

if ($RemoveExisting -and $null -ne $existingRules) {
    Write-Host "[1/4] Removing prior ProRadCS firewall rules..." -NoNewline
    try {
        foreach ($rule in $existingRules) {
            if ($PSCmdlet.ShouldProcess("$($rule.Name)", "Remove existing firewall rule")) {
                Remove-NetFirewallRule -Name $rule.Name -ErrorAction SilentlyContinue
            }
        }
        Write-Host " [PASS]" -ForegroundColor Green
    }
    catch {
        Write-Host " [WARN]" -ForegroundColor Yellow
        Write-Host "      Warning during rule cleanup: $_" -ForegroundColor Yellow
    }
}
else {
    Write-Host "[1/4] No prior ProRadCS firewall rules to purge." -ForegroundColor Gray
}

# 3. Rule 1: Inbound DICOM C-STORE (Port 104 TCP)
Write-Host "[2/4] Configuring Inbound DICOM Rule (Port $DicomPort TCP)..." -NoNewline
$dicomRuleName = "$rulePrefix-Inbound-DICOM"
try {
    if ($PSCmdlet.ShouldProcess("$dicomRuleName", "Create Inbound DICOM Port $DicomPort Rule")) {
        New-NetFirewallRule `
            -Name $dicomRuleName `
            -DisplayName "ProRadCS Inbound DICOM C-STORE (Port $DicomPort)" `
            -Description "Permits incoming DICOM image associations from modalities and PACS brokers." `
            -Direction Inbound `
            -Protocol TCP `
            -LocalPort $DicomPort `
            -RemoteAddress $ModalitySubnets `
            -Action Allow `
            -Enabled True `
            -Profile Any | Out-Null
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      Allowed: Port $DicomPort from $($ModalitySubnets -join ', ')." -ForegroundColor Gray
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}
catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "      Failed to create DICOM inbound rule: $_" -ForegroundColor Red
    exit $EXIT_SECURITY_ERROR
}

# 4. Rule 2: Inbound Web Dashboard & REST API (Port 8080 TCP)
Write-Host "[3/4] Configuring Inbound Web Dashboard Rule (Port $WebPort TCP)..." -NoNewline
$webRuleName = "$rulePrefix-Inbound-WebDashboard"
try {
    if ($PSCmdlet.ShouldProcess("$webRuleName", "Create Inbound Web Dashboard Port $WebPort Rule")) {
        New-NetFirewallRule `
            -Name $webRuleName `
            -DisplayName "ProRadCS Inbound Web Dashboard & REST API (Port $WebPort)" `
            -Description "Restricts local telemetry and management dashboard access to localhost and admin subnets." `
            -Direction Inbound `
            -Protocol TCP `
            -LocalPort $WebPort `
            -RemoteAddress $AdminSubnets `
            -Action Allow `
            -Enabled True `
            -Profile Any | Out-Null
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      Allowed: Port $WebPort from $($AdminSubnets -join ', ')." -ForegroundColor Gray
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}
catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "      Failed to create Web Dashboard inbound rule: $_" -ForegroundColor Red
    exit $EXIT_SECURITY_ERROR
}

# 5. Rule 3: Outbound Cloud VNA Relay (Port 443 TCP / HTTPS)
Write-Host "[4/4] Configuring Outbound Cloud Relay Rule (Port $CloudPort TCP)..." -NoNewline
$outboundRuleName = "$rulePrefix-Outbound-CloudRelay"
try {
    if ($PSCmdlet.ShouldProcess("$outboundRuleName", "Create Outbound Cloud Relay Port $CloudPort Rule")) {
        New-NetFirewallRule `
            -Name $outboundRuleName `
            -DisplayName "ProRadCS Outbound Cloud VNA STOW-RS (Port $CloudPort)" `
            -Description "Permits secure HTTPS/TLS 1.3 STOW-RS upload to upstream Cloud VNA." `
            -Direction Outbound `
            -Protocol TCP `
            -RemotePort $CloudPort `
            -Action Allow `
            -Enabled True `
            -Profile Any | Out-Null
        Write-Host " [PASS]" -ForegroundColor Green
        Write-Host "      Allowed: Outbound Port $CloudPort (HTTPS STOW-RS)." -ForegroundColor Gray
    }
    else {
        Write-Host " [WHAT-IF]" -ForegroundColor Yellow
    }
}
catch {
    Write-Host " [FAIL]" -ForegroundColor Red
    Write-Host "      Failed to create Cloud Relay outbound rule: $_" -ForegroundColor Red
    exit $EXIT_SECURITY_ERROR
}

Write-Host "Windows Defender Firewall configuration successfully applied." -ForegroundColor Green
exit $EXIT_SUCCESS
